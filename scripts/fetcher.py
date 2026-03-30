"""
법령 수집기 (fetcher.py)
────────────────────────
국가법령정보 공동활용 API에서 법령 목록과 상세 조문을 가져온다.

API 문서: https://open.law.go.kr/LSO/openApi/guideResult.do
"""
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import (
    LAW_API_OC,
    LAW_SEARCH_URL,
    LAW_SERVICE_URL,
    PAGE_SIZE,
    REQUEST_DELAY,
    REVISION_TYPES,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────
@dataclass
class LawSummary:
    """법령 검색 결과 요약 정보"""
    law_id: int                    # 법령ID
    serial_no: int                 # 법령일련번호
    name: str                      # 법령명한글
    short_name: str = ""           # 법령약칭명
    promul_date: str = ""          # 공포일자 (YYYYMMDD)
    promul_no: str = ""            # 공포번호
    enforce_date: str = ""         # 시행일자
    revision_type: str = ""        # 제개정구분명
    ministry: str = ""             # 소관부처명
    law_type: str = ""             # 법령구분명 (법률/대통령령/총리령/부령)
    detail_link: str = ""          # 법령상세링크
    is_current: bool = True        # 현행여부


@dataclass
class LawArticle:
    """법령 조문"""
    number: str = ""               # 조문번호 (제1조)
    title: str = ""                # 조문제목
    content: str = ""              # 조문내용
    paragraphs: list = field(default_factory=list)  # 항 목록


@dataclass
class LawDetail:
    """법령 상세 정보"""
    law_id: int = 0
    serial_no: int = 0
    name: str = ""
    promul_date: str = ""
    promul_no: str = ""
    enforce_date: str = ""
    revision_type: str = ""
    ministry: str = ""
    law_type: str = ""
    preamble: str = ""             # 전문(前文)
    articles: list = field(default_factory=list)     # 조문 리스트
    addenda: list = field(default_factory=list)       # 부칙
    chapter_structure: list = field(default_factory=list)  # 편/장/절 구조


# ──────────────────────────────────────────────
# 법령 목록 조회
# ──────────────────────────────────────────────
def fetch_law_list(
    query: str = "",
    page: int = 1,
    display: int = PAGE_SIZE,
    sort: str = "lasc",
    law_kind: str = "",
    revision_code: str = "",
    promul_date_from: str = "",
    promul_date_to: str = "",
) -> tuple[list[LawSummary], int]:
    """
    현행법령 목록을 조회한다.

    sort 옵션:
        lasc  = 법령명 가나다 오름차순 (기본값)
        ldesc = 법령명 가나다 내림차순
        pasc  = 공포일자 오름차순 (오래된 순)
        pdesc = 공포일자 내림차순 (최신 순)
        efasc = 시행일자 오름차순
        efdesc = 시행일자 내림차순

    Returns:
        (법령 요약 리스트, 전체 건수)
    """
    params = {
        "OC": LAW_API_OC,
        "target": "law",
        "type": "XML",
        "page": page,
        "display": display,
        "sort": sort,
    }
    if query:
        params["query"] = query
    if law_kind:
        params["knd"] = law_kind
    if revision_code:
        params["rrClsCd"] = revision_code
    if promul_date_from and promul_date_to:
        params["ancYd"] = f"{promul_date_from}~{promul_date_to}"

    logger.info(f"법령 목록 조회: page={page}, query='{query}'")

    try:
        resp = requests.get(LAW_SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"API 요청 실패: {e}")
        return [], 0

    time.sleep(REQUEST_DELAY)

    root = ET.fromstring(resp.content)
    total_count = int(root.findtext("totalCnt", "0"))

    laws = []
    for item in root.iter("law"):
        law = LawSummary(
            law_id=int(item.findtext("법령ID", "0")),
            serial_no=int(item.findtext("법령일련번호", "0")),
            name=_clean(item.findtext("법령명한글", "")),
            short_name=_clean(item.findtext("법령약칭명", "")),
            promul_date=item.findtext("공포일자", ""),
            promul_no=item.findtext("공포번호", ""),
            enforce_date=item.findtext("시행일자", ""),
            revision_type=_clean(item.findtext("제개정구분명", "")),
            ministry=_clean(item.findtext("소관부처명", "")),
            law_type=_clean(item.findtext("법령구분명", "")),
            detail_link=item.findtext("법령상세링크", ""),
        )
        laws.append(law)

    logger.info(f"  → {len(laws)}건 조회 (전체 {total_count}건)")
    return laws, total_count


def fetch_all_laws(law_kind: str = "", query: str = "", sort: str = "lasc") -> list[LawSummary]:
    """모든 페이지를 순회하여 전체 법령 목록을 가져온다."""
    all_laws = []
    page = 1

    laws, total = fetch_law_list(query=query, page=page, law_kind=law_kind, sort=sort)
    all_laws.extend(laws)

    while len(all_laws) < total:
        page += 1
        laws, _ = fetch_law_list(query=query, page=page, law_kind=law_kind, sort=sort)
        if not laws:
            break
        all_laws.extend(laws)

    logger.info(f"전체 법령 {len(all_laws)}건 수집 완료")
    return all_laws


# ──────────────────────────────────────────────
# 법령 상세 조회
# ──────────────────────────────────────────────
def fetch_law_detail(serial_no: int) -> Optional[LawDetail]:
    """
    법령일련번호로 법령 상세(조문 전체)를 가져온다.
    """
    params = {
        "OC": LAW_API_OC,
        "target": "law",
        "type": "XML",
        "MST": serial_no,
    }

    logger.info(f"법령 상세 조회: MST={serial_no}")

    try:
        resp = requests.get(LAW_SERVICE_URL, params=params, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"법령 상세 API 요청 실패: {e}")
        return None

    time.sleep(REQUEST_DELAY)

    root = ET.fromstring(resp.content)
    base = root.find("기본정보") or root

    detail = LawDetail(
        law_id=int(base.findtext("법령ID", "0")),
        serial_no=serial_no,
        name=_clean(base.findtext("법령명_한글", base.findtext("법령명한글", ""))),
        promul_date=base.findtext("공포일자", ""),
        promul_no=base.findtext("공포번호", ""),
        enforce_date=base.findtext("시행일자", ""),
        revision_type=_clean(base.findtext("제개정구분명", "")),
        ministry=_clean(base.findtext("소관부처명", base.findtext("소관부처", ""))),
        law_type=_clean(base.findtext("법령구분명", base.findtext("법종구분", ""))),
        preamble=_clean(base.findtext("전문", "")),
    )

    # 조문 파싱
    for article_el in root.iter("조문단위"):
        article = LawArticle(
            number=_clean(article_el.findtext("조문번호", "")),
            title=_clean(article_el.findtext("조문제목", "")),
            content=_clean(article_el.findtext("조문내용", "")),
        )

        # 항 파싱
        for para_el in article_el.iter("항"):
            para_content = _clean(para_el.findtext("항내용", ""))
            if para_content:
                article.paragraphs.append(para_content)

        detail.articles.append(article)

    # 부칙 파싱
    for addendum_el in root.iter("부칙단위"):
        addendum_content = _clean(addendum_el.findtext("부칙내용", ""))
        if addendum_content:
            detail.addenda.append(addendum_content)

    # 편/장/절 구조 파싱
    for chap_el in root.iter("편장절관"):
        chap_info = {
            "type": _clean(chap_el.findtext("편장절구분", "")),
            "number": _clean(chap_el.findtext("편장절번호", "")),
            "title": _clean(chap_el.findtext("편장절명", "")),
            "key": _clean(chap_el.findtext("편장절키", "")),
        }
        if chap_info["title"]:
            detail.chapter_structure.append(chap_info)

    logger.info(f"  → '{detail.name}': {len(detail.articles)}개 조문")
    return detail


# ──────────────────────────────────────────────
# 법령 연혁 조회
# ──────────────────────────────────────────────
def fetch_law_history(law_id: int) -> list[LawSummary]:
    """
    법령ID로 해당 법령의 연혁(모든 개정 버전)을 가져온다.
    """
    params = {
        "OC": LAW_API_OC,
        "target": "law",
        "type": "XML",
        "ID": law_id,
        "display": 200,
    }

    logger.info(f"법령 연혁 조회: law_id={law_id}")

    try:
        resp = requests.get(LAW_SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"연혁 API 요청 실패: {e}")
        return []

    time.sleep(REQUEST_DELAY)

    root = ET.fromstring(resp.content)
    history = []
    for item in root.iter("law"):
        law = LawSummary(
            law_id=int(item.findtext("법령ID", "0")),
            serial_no=int(item.findtext("법령일련번호", "0")),
            name=_clean(item.findtext("법령명한글", "")),
            promul_date=item.findtext("공포일자", ""),
            promul_no=item.findtext("공포번호", ""),
            enforce_date=item.findtext("시행일자", ""),
            revision_type=_clean(item.findtext("제개정구분명", "")),
            ministry=_clean(item.findtext("소관부처명", "")),
            law_type=_clean(item.findtext("법령구분명", "")),
            is_current=False,
        )
        history.append(law)

    # 공포일 기준 오름차순 정렬 (오래된 것 → 최신)
    history.sort(key=lambda x: x.promul_date)
    logger.info(f"  → {len(history)}개 연혁 버전")
    return history


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _clean(text: str) -> str:
    """공백 정리"""
    if not text:
        return ""
    return " ".join(text.split()).strip()
