"""
국회 데이터 수집기 (assembly.py)
──────────────────────────────
열린국회정보 API에서 의안 발의 정보, 의원 정보, 표결 결과를 가져온다.

API 포털: https://open.assembly.go.kr/portal/openapi/main.do
"""
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import (
    ASSEMBLY_API_BASE,
    ASSEMBLY_API_KEY,
    ASSEMBLY_BILL_SVC,
    REQUEST_DELAY,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────
@dataclass
class BillInfo:
    """의안 정보"""
    bill_id: str = ""              # 의안ID
    bill_no: str = ""              # 의안번호
    bill_name: str = ""            # 법률안명
    proposer: str = ""             # 제안자
    propose_date: str = ""         # 제안일
    committee: str = ""            # 소관위원회
    proc_result: str = ""          # 처리상태
    detail_link: str = ""          # 상세페이지 링크
    rst_proposer: str = ""         # 대표발의자
    publ_proposer: str = ""        # 공동발의자 수


@dataclass
class Legislator:
    """의원 정보"""
    name: str = ""
    party: str = ""
    member_id: str = ""
    role: str = "공동발의"          # 대표발의 / 공동발의


# ──────────────────────────────────────────────
# 발의법률안 조회
# ──────────────────────────────────────────────
def search_bills(
    bill_name: str = "",
    assembly_age: int = 22,
    page: int = 1,
    page_size: int = 100,
) -> list[BillInfo]:
    """
    국회의원 발의법률안을 검색한다.

    Args:
        bill_name: 법률안명 (부분 검색)
        assembly_age: 대수 (22 = 22대 국회)
        page: 페이지 번호
        page_size: 페이지당 건수
    """
    if not ASSEMBLY_API_KEY:
        logger.warning("ASSEMBLY_API_KEY가 설정되지 않았습니다. 국회 데이터를 건너뜁니다.")
        return []

    url = f"{ASSEMBLY_API_BASE}/{ASSEMBLY_BILL_SVC}"
    params = {
        "KEY": ASSEMBLY_API_KEY,
        "Type": "xml",
        "pIndex": page,
        "pSize": page_size,
        "AGE": assembly_age,
    }
    if bill_name:
        params["BILL_NAME"] = bill_name

    logger.info(f"발의법률안 검색: '{bill_name}', {assembly_age}대, page={page}")

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"국회 API 요청 실패: {e}")
        return []

    time.sleep(REQUEST_DELAY)

    bills = []
    try:
        root = ET.fromstring(resp.content)
        for row in root.iter("row"):
            bill = BillInfo(
                bill_id=_text(row, "BILL_ID"),
                bill_no=_text(row, "BILL_NO"),
                bill_name=_text(row, "BILL_NAME"),
                proposer=_text(row, "PROPOSER"),
                propose_date=_text(row, "PROPOSE_DT"),
                committee=_text(row, "COMMITTEE"),
                proc_result=_text(row, "PROC_RESULT"),
                detail_link=_text(row, "DETAIL_LINK"),
                rst_proposer=_text(row, "RST_PROPOSER"),
                publ_proposer=_text(row, "PUBL_PROPOSER"),
            )
            bills.append(bill)
    except ET.ParseError as e:
        logger.error(f"XML 파싱 실패: {e}")
        return []

    logger.info(f"  → {len(bills)}건 조회")
    return bills


def find_bill_for_law(law_name: str) -> Optional[BillInfo]:
    """
    법령명으로 관련 발의법률안을 찾는다.
    법령명에서 '법' 이전까지를 키워드로 검색한다.
    """
    # '~에 관한 법률' → '~에 관한 법률'로 검색
    search_name = law_name.replace("법률", "").replace("일부개정", "").strip()
    if not search_name:
        return None

    # 최근 3개 대수에서 검색
    for age in [22, 21, 20]:
        bills = search_bills(bill_name=search_name, assembly_age=age)
        if bills:
            # 가장 최근 것 반환
            return bills[0]

    return None


# ──────────────────────────────────────────────
# 발의의원 목록 크롤링
# ──────────────────────────────────────────────
def fetch_proposers(bill_id: str) -> list[Legislator]:
    """
    의안의 발의의원(대표발의자 + 공동발의자) 목록을 가져온다.
    열린국회정보 API로 직접 제공되지 않는 상세 정보는
    의안정보시스템 웹 페이지를 파싱한다.
    """
    url = f"https://likms.assembly.go.kr/bill/coactorListPopup.do?billId={bill_id}"
    legislators = []

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        period_div = soup.find("div", {"id": "periodDiv"})
        if not period_div:
            logger.warning(f"발의의원 정보를 찾을 수 없음: bill_id={bill_id}")
            return []

        for tag in period_div.find_all("a"):
            text = tag.string
            if not text:
                continue
            try:
                name = text.split("(")[0].strip()
                party = text.split("(")[1].split("/")[0].strip() if "(" in text else ""
                member_id = ""
                if tag.has_attr("href"):
                    from urllib.parse import parse_qs, urlparse
                    qs = parse_qs(urlparse(tag["href"]).query)
                    member_id = qs.get("dept_cd", [""])[0]

                legislators.append(Legislator(
                    name=name,
                    party=party,
                    member_id=member_id,
                ))
            except (IndexError, ValueError):
                continue

    except requests.RequestException as e:
        logger.error(f"발의의원 크롤링 실패: {e}")

    time.sleep(REQUEST_DELAY)

    if legislators:
        legislators[0].role = "대표발의"
        logger.info(f"  → 발의의원 {len(legislators)}명 (대표: {legislators[0].name})")

    return legislators


# ──────────────────────────────────────────────
# 메타데이터 구성
# ──────────────────────────────────────────────
def build_assembly_metadata(law_name: str) -> dict:
    """
    법령명에 해당하는 국회 메타데이터를 구성한다.
    반환 예시:
    {
        "bill_name": "개인정보 보호법 일부개정법률안",
        "propose_date": "2024-01-15",
        "proposer": "홍길동의원 등 12인",
        "committee": "행정안전위원회",
        "proc_result": "원안가결",
        "legislators": [
            {"name": "홍길동", "party": "더불어민주당", "role": "대표발의"},
            ...
        ]
    }
    """
    result = {}

    bill = find_bill_for_law(law_name)
    if not bill:
        return result

    result = {
        "bill_id": bill.bill_id,
        "bill_no": bill.bill_no,
        "bill_name": bill.bill_name,
        "propose_date": bill.propose_date,
        "proposer": bill.proposer,
        "committee": bill.committee,
        "proc_result": bill.proc_result,
        "rst_proposer": bill.rst_proposer,
    }

    # 발의의원 상세 (선택적)
    if bill.bill_id:
        proposers = fetch_proposers(bill.bill_id)
        result["legislators"] = [
            {"name": l.name, "party": l.party, "role": l.role}
            for l in proposers
        ]

    return result


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _text(el: ET.Element, tag: str) -> str:
    t = el.findtext(tag, "")
    return t.strip() if t else ""
