"""
영문 법령 수집기 (english.py)
────────────────────────────
한국법제연구원(KLRI) 영문법령센터에서 영문 법령을 수집한다.

데이터 소스:
  - 국가법령정보 영문법령 API (law.go.kr/DRF/lawSearch.do?target=elaw)
  - 한국법제연구원 영문법령 (elaw.klri.re.kr)

기능:
  - 영문 법령 본문 수집
  - 한글 법령과 1:1 매핑
  - 이중 언어 마크다운 생성 (선택)
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

# 영문 법령 API URL
ELAW_SEARCH_URL = f"{LAW_API_BASE}/lawSearch.do"
ELAW_SERVICE_URL = f"{LAW_API_BASE}/lawService.do"


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────
@dataclass
class EnglishLawSummary:
    """영문 법령 검색 결과"""
    law_id: int = 0
    serial_no: int = 0
    name_kr: str = ""              # 법령명(한글)
    name_en: str = ""              # 법령명(영문)
    promul_date: str = ""
    enforce_date: str = ""
    ministry: str = ""


@dataclass
class EnglishLawArticle:
    """영문 조문"""
    number: str = ""               # Article number
    title: str = ""                # Article title
    content: str = ""              # Article content
    paragraphs: list = field(default_factory=list)


@dataclass
class EnglishLawDetail:
    """영문 법령 상세"""
    law_id: int = 0
    serial_no: int = 0
    name_kr: str = ""
    name_en: str = ""
    promul_date: str = ""
    enforce_date: str = ""
    ministry: str = ""
    articles: list = field(default_factory=list)  # list[EnglishLawArticle]
    addenda: list = field(default_factory=list)


# ──────────────────────────────────────────────
# 영문 법령 검색
# ──────────────────────────────────────────────
def search_english_laws(
    query: str = "",
    page: int = 1,
    display: int = 100,
) -> tuple[list[EnglishLawSummary], int]:
    """
    영문 법령 목록을 검색한다.
    """
    params = {
        "OC": LAW_API_OC,
        "target": "elaw",
        "type": "XML",
        "page": page,
        "display": display,
    }
    if query:
        params["query"] = query

    logger.info(f"영문 법령 검색: query='{query}', page={page}")

    try:
        resp = requests.get(ELAW_SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"영문 법령 검색 API 실패: {e}")
        return [], 0

    time.sleep(REQUEST_DELAY)

    root = ET.fromstring(resp.content)
    total = int(root.findtext("totalCnt", "0"))

    laws = []
    for item in root.iter("elaw"):
        law = EnglishLawSummary(
            law_id=int(item.findtext("법령ID", "0")),
            serial_no=int(item.findtext("법령일련번호", "0")),
            name_kr=_clean(item.findtext("법령명한글", "")),
            name_en=_clean(item.findtext("법령명영문", item.findtext("법령명약칭", ""))),
            promul_date=item.findtext("공포일자", ""),
            enforce_date=item.findtext("시행일자", ""),
            ministry=_clean(item.findtext("소관부처명", "")),
        )
        laws.append(law)

    logger.info(f"  → 영문 법령 {len(laws)}건 (전체 {total}건)")
    return laws, total


def fetch_all_english_laws(query: str = "") -> list[EnglishLawSummary]:
    """모든 영문 법령 목록을 가져온다."""
    all_laws = []
    page = 1

    laws, total = search_english_laws(query=query, page=page)
    all_laws.extend(laws)

    while len(all_laws) < total:
        page += 1
        laws, _ = search_english_laws(query=query, page=page)
        if not laws:
            break
        all_laws.extend(laws)

    logger.info(f"영문 법령 전체 {len(all_laws)}건 수집")
    return all_laws


# ──────────────────────────────────────────────
# 영문 법령 상세 조회
# ──────────────────────────────────────────────
def fetch_english_law_detail(serial_no: int) -> Optional[EnglishLawDetail]:
    """
    영문 법령 상세(조문)를 조회한다.
    """
    params = {
        "OC": LAW_API_OC,
        "target": "elaw",
        "type": "XML",
        "MST": serial_no,
    }

    logger.info(f"영문 법령 상세 조회: MST={serial_no}")

    try:
        resp = requests.get(ELAW_SERVICE_URL, params=params, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"영문 법령 상세 API 실패: {e}")
        return None

    time.sleep(REQUEST_DELAY)

    root = ET.fromstring(resp.content)
    base = root.find("기본정보") or root

    detail = EnglishLawDetail(
        law_id=int(base.findtext("법령ID", "0")),
        serial_no=serial_no,
        name_kr=_clean(base.findtext("법령명_한글", base.findtext("법령명한글", ""))),
        name_en=_clean(base.findtext("법령명_영문", base.findtext("법령명영문", ""))),
        promul_date=base.findtext("공포일자", ""),
        enforce_date=base.findtext("시행일자", ""),
        ministry=_clean(base.findtext("소관부처명", "")),
    )

    # 영문 조문 파싱
    for article_el in root.iter("조문단위"):
        article = EnglishLawArticle(
            number=_clean(article_el.findtext("조문번호", "")),
            title=_clean(article_el.findtext("조문제목", "")),
            content=_clean(article_el.findtext("조문내용", "")),
        )

        for para_el in article_el.iter("항"):
            para_content = _clean(para_el.findtext("항내용", ""))
            if para_content:
                article.paragraphs.append(para_content)

        detail.articles.append(article)

    # 부칙
    for add_el in root.iter("부칙단위"):
        add_content = _clean(add_el.findtext("부칙내용", ""))
        if add_content:
            detail.addenda.append(add_content)

    logger.info(f"  → '{detail.name_en or detail.name_kr}': {len(detail.articles)}개 조문")
    return detail


# ──────────────────────────────────────────────
# 영문 법령 마크다운 변환
# ──────────────────────────────────────────────
def english_law_to_markdown(detail: EnglishLawDetail) -> str:
    """
    영문 법령을 마크다운으로 변환한다.
    """
    lines = []

    # YAML frontmatter
    lines.append("---")
    lines.append(f'law_name_kr: "{_escape_yaml(detail.name_kr)}"')
    lines.append(f'law_name_en: "{_escape_yaml(detail.name_en)}"')
    if detail.law_id:
        lines.append(f"law_id: {detail.law_id}")
    if detail.serial_no:
        lines.append(f"serial_no: {detail.serial_no}")
    if detail.promul_date:
        lines.append(f'promulgation_date: "{_format_date(detail.promul_date)}"')
    if detail.enforce_date:
        lines.append(f'enforcement_date: "{_format_date(detail.enforce_date)}"')
    if detail.ministry:
        lines.append(f'competent_authority: "{detail.ministry}"')
    lines.append('language: "en"')
    lines.append("---")
    lines.append("")

    # Title
    title = detail.name_en or detail.name_kr
    lines.append(f"# {title}")
    lines.append("")

    if detail.name_kr and detail.name_en:
        lines.append(f"*{detail.name_kr}*")
        lines.append("")

    # Articles
    for article in detail.articles:
        if article.number or article.title:
            if article.number and article.title:
                lines.append(f"#### {article.number} ({article.title})")
            elif article.number:
                lines.append(f"#### {article.number}")
            else:
                lines.append(f"#### {article.title}")
            lines.append("")

        if article.content:
            lines.append(_clean_content(article.content))
            lines.append("")

        for para in article.paragraphs:
            lines.append(_clean_content(para))
            lines.append("")

    # Addenda
    if detail.addenda:
        lines.append("## Addenda")
        lines.append("")
        for add in detail.addenda:
            lines.append(_clean_content(add))
            lines.append("")

    return "\n".join(lines)


def generate_english_filename(detail: EnglishLawDetail) -> str:
    """영문 법령 파일명 생성"""
    name = detail.name_en or detail.name_kr
    safe_name = re.sub(r'[<>:"/\\|?*]', "", name)
    safe_name = safe_name.replace(" ", "_")[:80]
    return f"{detail.serial_no}-{safe_name}.md"


# ──────────────────────────────────────────────
# 한-영 매핑
# ──────────────────────────────────────────────
def find_english_version(law_id: int) -> Optional[EnglishLawSummary]:
    """
    한글 법령 ID로 대응하는 영문 법령을 찾는다.
    """
    # 국가법령정보 API에서 법령ID로 영문 버전 검색
    params = {
        "OC": LAW_API_OC,
        "target": "elaw",
        "type": "XML",
        "ID": law_id,
        "display": 5,
    }

    try:
        resp = requests.get(ELAW_SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.debug(f"영문 법령 매핑 실패: {e}")
        return None

    time.sleep(REQUEST_DELAY)

    root = ET.fromstring(resp.content)
    for item in root.iter("elaw"):
        return EnglishLawSummary(
            law_id=int(item.findtext("법령ID", "0")),
            serial_no=int(item.findtext("법령일련번호", "0")),
            name_kr=_clean(item.findtext("법령명한글", "")),
            name_en=_clean(item.findtext("법령명영문", "")),
        )

    return None


def build_bilingual_markdown(
    kr_markdown: str,
    en_detail: EnglishLawDetail,
) -> str:
    """
    한글 마크다운에 영문 조문을 병렬로 추가한다.
    frontmatter에 영문 법령 정보를 추가하고,
    본문 마지막에 영문 전문을 첨부한다.
    """
    # frontmatter에 영문 정보 추가
    if "---" in kr_markdown:
        parts = kr_markdown.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            body = parts[2]

            # 영문 정보 추가
            en_info = f'\n영문법령명: "{_escape_yaml(en_detail.name_en)}"'
            en_info += f"\n영문법령일련번호: {en_detail.serial_no}"
            frontmatter += en_info

            # 영문 전문 섹션 추가
            en_section = "\n\n---\n\n## English Translation\n\n"
            en_section += f"*{en_detail.name_en}*\n\n"

            for article in en_detail.articles:
                if article.number or article.title:
                    heading = article.number
                    if article.title:
                        heading += f" ({article.title})" if heading else article.title
                    en_section += f"#### {heading}\n\n"

                if article.content:
                    en_section += f"{_clean_content(article.content)}\n\n"

                for para in article.paragraphs:
                    en_section += f"{_clean_content(para)}\n\n"

            return f"---{frontmatter}---{body}{en_section}"

    return kr_markdown


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _clean(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.split()).strip()


def _clean_content(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _format_date(date_str: str) -> str:
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def _escape_yaml(text: str) -> str:
    return text.replace('"', '\\"').replace("\n", " ")
