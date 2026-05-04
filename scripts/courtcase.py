"""
판례 연동 모듈 (courtcase.py)
─────────────────────────────
대법원 종합법률정보 및 국가법령정보 판례 API에서
특정 법조문과 관련된 판례를 수집한다.

데이터 소스:
  1. 국가법령정보 판례 검색 API (law.go.kr/DRF/lawSearch.do?target=prec)
  2. 대법원 종합법률정보 (glaw.scourt.go.kr) — 웹 파싱 fallback

제공 정보:
  - 판례 번호 (예: 2023다12345)
  - 선고일자
  - 법원명 (대법원/고등법원/지방법원)
  - 사건종류 (민사/형사/행정 등)
  - 판시사항 요약
  - 참조 조문 (어떤 법 어떤 조가 인용되었는지)
"""
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import (
    LAW_API_OC,
    LAW_API_BASE,
    REQUEST_DELAY,
)

logger = logging.getLogger(__name__)

# 판례 검색 API URL
PREC_SEARCH_URL = f"{LAW_API_BASE}/lawSearch.do"
PREC_SERVICE_URL = f"{LAW_API_BASE}/lawService.do"


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────
@dataclass
class CourtCase:
    """판례 정보"""
    case_id: int = 0               # 판례일련번호
    case_no: str = ""              # 사건번호 (예: 2023다12345)
    case_name: str = ""            # 사건명
    court_name: str = ""           # 법원명
    court_type: str = ""           # 법원종류 (대법원/고등법원 등)
    case_type: str = ""            # 사건종류 (민사/형사/행정 등)
    judgment_date: str = ""        # 선고일자 (YYYYMMDD)
    judgment_type: str = ""        # 선고/결정 구분
    ruling: str = ""               # 판시사항
    summary: str = ""              # 판결요지
    ref_articles: list = field(default_factory=list)  # 참조조문 목록
    full_text_url: str = ""        # 전문 링크


@dataclass
class CaseReference:
    """법조문에 대한 판례 참조 정보 (마크다운에 삽입할 요약)"""
    case_no: str = ""
    court_name: str = ""
    judgment_date: str = ""
    case_name: str = ""
    summary_short: str = ""        # 50자 요약


# ──────────────────────────────────────────────
# 판례 검색
# ──────────────────────────────────────────────
def search_cases(
    query: str = "",
    page: int = 1,
    display: int = 20,
    law_name: str = "",
) -> tuple[list[CourtCase], int]:
    """
    판례를 검색한다.

    Args:
        query: 검색어 (법령명 또는 키워드)
        page: 페이지 번호
        display: 페이지당 건수
        law_name: 관련 법령명으로 필터

    Returns:
        (판례 리스트, 전체 건수)
    """
    params = {
        "OC": LAW_API_OC,
        "target": "prec",
        "type": "XML",
        "page": page,
        "display": display,
    }
    if query:
        params["query"] = query

    logger.info(f"판례 검색: query='{query}', page={page}")

    try:
        resp = requests.get(PREC_SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"판례 검색 API 실패: {e}")
        return [], 0

    time.sleep(REQUEST_DELAY)

    root = ET.fromstring(resp.content)
    total = int(root.findtext("totalCnt", "0"))

    cases = []
    for item in root.iter("prec"):
        case = CourtCase(
            case_id=int(item.findtext("판례일련번호", "0")),
            case_name=_clean(item.findtext("사건명", "")),
            case_no=_clean(item.findtext("사건번호", "")),
            court_name=_clean(item.findtext("법원명", "")),
            court_type=_clean(item.findtext("법원종류코드", "")),
            case_type=_clean(item.findtext("사건종류명", "")),
            judgment_date=item.findtext("선고일자", ""),
            judgment_type=_clean(item.findtext("선고", "")),
        )
        cases.append(case)

    logger.info(f"  → 판례 {len(cases)}건 (전체 {total}건)")
    return cases, total


# ──────────────────────────────────────────────
# 판례 상세 조회
# ──────────────────────────────────────────────
def fetch_case_detail(case_id: int) -> Optional[CourtCase]:
    """
    판례일련번호로 판례 상세를 조회한다.
    """
    params = {
        "OC": LAW_API_OC,
        "target": "prec",
        "type": "XML",
        "ID": case_id,
    }

    logger.info(f"판례 상세 조회: case_id={case_id}")

    try:
        resp = requests.get(PREC_SERVICE_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"판례 상세 API 실패: {e}")
        return None

    time.sleep(REQUEST_DELAY)

    root = ET.fromstring(resp.content)

    case = CourtCase(
        case_id=case_id,
        case_no=_clean(root.findtext("사건번호", "")),
        case_name=_clean(root.findtext("사건명", "")),
        court_name=_clean(root.findtext("법원명", "")),
        court_type=_clean(root.findtext("법원종류코드", "")),
        case_type=_clean(root.findtext("사건종류명", "")),
        judgment_date=root.findtext("선고일자", ""),
        judgment_type=_clean(root.findtext("선고", "")),
        ruling=_clean(root.findtext("판시사항", "")),
        summary=_clean(root.findtext("판결요지", "")),
    )

    # 참조조문 파싱
    ref_text = root.findtext("참조조문", "")
    if ref_text:
        case.ref_articles = _parse_ref_articles(ref_text)

    # 전문 링크 구성
    case.full_text_url = f"https://www.law.go.kr/판례/{case.case_no}"

    logger.info(f"  → '{case.case_no}': 참조조문 {len(case.ref_articles)}건")
    return case


# ──────────────────────────────────────────────
# 특정 법률에 대한 관련 판례 수집
# ──────────────────────────────────────────────
def fetch_cases_for_law(
    law_name: str,
    max_cases: int = 20,
    article_number: str = "",
) -> list[CourtCase]:
    """
    특정 법률(또는 특정 조문)에 대한 관련 판례를 수집한다.

    Args:
        law_name: 법령명 (예: "개인정보 보호법")
        max_cases: 최대 수집 판례 수
        article_number: 특정 조문 번호 (예: "제2조")

    Returns:
        관련 판례 리스트 (상세 정보 포함)
    """
    # 검색어 구성
    query = law_name
    if article_number:
        query = f"{law_name} {article_number}"

    all_cases = []
    page = 1

    while len(all_cases) < max_cases:
        cases, total = search_cases(query=query, page=page, display=20)
        if not cases:
            break

        for case in cases:
            if len(all_cases) >= max_cases:
                break
            # 상세 조회
            detail = fetch_case_detail(case.case_id)
            if detail:
                all_cases.append(detail)
            else:
                all_cases.append(case)

        if len(all_cases) >= total:
            break
        page += 1

    logger.info(f"'{law_name}' 관련 판례 {len(all_cases)}건 수집")
    return all_cases


# ──────────────────────────────────────────────
# 조문별 판례 매핑
# ──────────────────────────────────────────────
def build_article_case_map(
    law_name: str,
    cases: list[CourtCase],
) -> dict[str, list[CaseReference]]:
    """
    판례의 참조조문을 분석하여 조문별 관련 판례 목록을 만든다.

    Returns:
        {
            "제1조": [CaseReference(...), ...],
            "제2조": [...],
            ...
        }
    """
    article_map: dict[str, list[CaseReference]] = {}

    for case in cases:
        # 참조조문에서 해당 법률의 조문 추출
        relevant_articles = []
        for ref in case.ref_articles:
            if law_name in ref or _is_article_ref(ref):
                articles = _extract_article_numbers(ref)
                relevant_articles.extend(articles)

        # 참조조문이 없으면 사건명에서 추론
        if not relevant_articles:
            relevant_articles = _extract_article_numbers(case.case_name)

        ref = CaseReference(
            case_no=case.case_no,
            court_name=case.court_name,
            judgment_date=_format_date(case.judgment_date),
            case_name=case.case_name,
            summary_short=_truncate(case.ruling or case.summary, 80),
        )

        for art in relevant_articles:
            if art not in article_map:
                article_map[art] = []
            article_map[art].append(ref)

        # 조문 특정이 안 되면 "일반"으로 분류
        if not relevant_articles:
            key = "_general"
            if key not in article_map:
                article_map[key] = []
            article_map[key].append(ref)

    return article_map


def build_case_metadata(law_name: str, max_cases: int = 10) -> dict:
    """
    법령에 대한 판례 메타데이터를 구성한다.

    Returns:
        {
            "total_cases": 15,
            "cases": [
                {
                    "case_no": "2023다12345",
                    "court": "대법원",
                    "date": "2023-06-15",
                    "name": "개인정보 유출 손해배상",
                    "summary": "...",
                    "ref_articles": ["제2조", "제17조"]
                },
                ...
            ],
            "article_map": {
                "제2조": ["2023다12345", "2022다67890"],
                ...
            }
        }
    """
    cases = fetch_cases_for_law(law_name, max_cases=max_cases)
    if not cases:
        return {}

    meta = {
        "total_cases": len(cases),
        "cases": [],
        "article_map": {},
    }

    for case in cases:
        case_entry = {
            "case_no": case.case_no,
            "court": case.court_name,
            "date": _format_date(case.judgment_date),
            "name": case.case_name,
            "summary": _truncate(case.ruling or case.summary, 100),
            "ref_articles": case.ref_articles,
            "url": case.full_text_url,
        }
        meta["cases"].append(case_entry)

    # 조문별 매핑
    article_map = build_article_case_map(law_name, cases)
    meta["article_map"] = {
        art: [ref.case_no for ref in refs]
        for art, refs in article_map.items()
    }

    return meta


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _clean(text: str) -> str:
    if not text:
        return ""
    # HTML 태그 제거
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split()).strip()


def _format_date(date_str: str) -> str:
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _parse_ref_articles(ref_text: str) -> list[str]:
    """참조조문 텍스트를 개별 항목으로 분리"""
    if not ref_text:
        return []
    # " / " 또는 줄바꿈으로 구분
    parts = re.split(r"\s*/\s*|\n|,\s*", ref_text)
    return [p.strip() for p in parts if p.strip()]


def _is_article_ref(text: str) -> bool:
    """조문 참조인지 여부"""
    return bool(re.search(r"제\d+조", text))


def _extract_article_numbers(text: str) -> list[str]:
    """텍스트에서 조문 번호 추출 (예: 제1조, 제2조의2)"""
    pattern = r"제\d+조(?:의\d+)?"
    return re.findall(pattern, text)
