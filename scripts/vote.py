"""
본회의 표결 기록 수집기 (vote.py)
────────────────────────────────
열린국회정보 API에서 본회의 표결 정보를 수집한다.

표결 데이터 포함 항목:
  - 의안별 찬성/반대/기권 수
  - 의원별 표결 내역 (찬성/반대/기권/불참)
  - 표결 일시

API 서비스:
  - 국회의원 본회의 표결정보 (pvoterncwbillgatljpazxkubdpn)
"""
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import (
    ASSEMBLY_API_BASE,
    ASSEMBLY_API_KEY,
    VOTE_RESULT_SVC,
    VOTE_MEMBER_SVC,
    REQUEST_DELAY,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────
@dataclass
class VoteResult:
    """의안별 표결 결과"""
    bill_id: str = ""
    bill_no: str = ""
    bill_name: str = ""
    vote_date: str = ""           # 표결일 (YYYY-MM-DD)
    total: int = 0                # 재적의원
    yes: int = 0                  # 찬성
    no: int = 0                   # 반대
    abstain: int = 0              # 기권
    absent: int = 0               # 불참(결석)
    result: str = ""              # 가결/부결


@dataclass
class MemberVote:
    """의원별 표결 내역"""
    member_name: str = ""
    party: str = ""
    vote: str = ""                # 찬성/반대/기권/불참
    member_id: str = ""


@dataclass
class VoteSummary:
    """의안 표결 종합 정보"""
    result: Optional[VoteResult] = None
    member_votes: list = field(default_factory=list)  # list[MemberVote]


# ──────────────────────────────────────────────
# 의안별 표결 결과 조회
# ──────────────────────────────────────────────
def fetch_vote_result(
    bill_no: str = "",
    bill_name: str = "",
    assembly_age: int = 22,
) -> list[VoteResult]:
    """
    본회의 표결 결과를 조회한다.

    Args:
        bill_no: 의안번호
        bill_name: 법률안명 (부분검색)
        assembly_age: 대수
    """
    if not ASSEMBLY_API_KEY:
        logger.warning("ASSEMBLY_API_KEY 미설정 — 표결 데이터 건너뜀")
        return []

    url = f"{ASSEMBLY_API_BASE}/{VOTE_RESULT_SVC}"
    params = {
        "KEY": ASSEMBLY_API_KEY,
        "Type": "xml",
        "pIndex": 1,
        "pSize": 100,
        "AGE": assembly_age,
    }
    if bill_no:
        params["BILL_NO"] = bill_no
    if bill_name:
        params["BILL_NAME"] = bill_name

    logger.info(f"표결 결과 조회: bill_no={bill_no}, name='{bill_name}'")

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"표결 API 요청 실패: {e}")
        return []

    time.sleep(REQUEST_DELAY)

    results = []
    try:
        root = ET.fromstring(resp.content)
        for row in root.iter("row"):
            vr = VoteResult(
                bill_id=_text(row, "BILL_ID"),
                bill_no=_text(row, "BILL_NO"),
                bill_name=_text(row, "BILL_NAME"),
                vote_date=_text(row, "VOTE_DATE"),
                total=_int(row, "MEMBER_TCNT"),
                yes=_int(row, "YES_TCNT"),
                no=_int(row, "NO_TCNT"),
                abstain=_int(row, "BLANK_TCNT"),
                absent=_int(row, "ABSENT_TCNT", alt_tag="NOSIGN_TCNT"),
                result=_text(row, "RESULT"),
            )
            results.append(vr)
    except ET.ParseError as e:
        logger.error(f"표결 XML 파싱 실패: {e}")

    logger.info(f"  → 표결 결과 {len(results)}건")
    return results


# ──────────────────────────────────────────────
# 의원별 표결 내역 조회
# ──────────────────────────────────────────────
def fetch_member_votes(
    bill_no: str,
    assembly_age: int = 22,
) -> list[MemberVote]:
    """
    특정 의안에 대한 의원별 표결 내역을 조회한다.
    """
    if not ASSEMBLY_API_KEY:
        return []

    url = f"{ASSEMBLY_API_BASE}/{VOTE_MEMBER_SVC}"
    params = {
        "KEY": ASSEMBLY_API_KEY,
        "Type": "xml",
        "pIndex": 1,
        "pSize": 300,   # 의원 수 최대
        "AGE": assembly_age,
        "BILL_NO": bill_no,
    }

    logger.info(f"의원별 표결 조회: bill_no={bill_no}")

    all_votes = []
    page = 1

    while True:
        params["pIndex"] = page

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"의원별 표결 API 실패: {e}")
            break

        time.sleep(REQUEST_DELAY)

        try:
            root = ET.fromstring(resp.content)
            rows = list(root.iter("row"))

            if not rows:
                break

            for row in rows:
                mv = MemberVote(
                    member_name=_text(row, "HG_NM"),
                    party=_text(row, "POLY_NM"),
                    vote=_text(row, "RESULT_VOTE_MOD"),
                    member_id=_text(row, "MONA_CD"),
                )
                all_votes.append(mv)

            # 전체 건수 확인
            total_el = root.find(".//list_total_count")
            if total_el is not None:
                total = int(total_el.text or "0")
                if len(all_votes) >= total:
                    break

            page += 1

        except ET.ParseError as e:
            logger.error(f"의원별 표결 XML 파싱 실패: {e}")
            break

    logger.info(f"  → 의원별 표결 {len(all_votes)}건")
    return all_votes


# ──────────────────────────────────────────────
# 종합 표결 정보 구성
# ──────────────────────────────────────────────
def build_vote_metadata(
    bill_no: str = "",
    bill_name: str = "",
    include_member_votes: bool = True,
) -> Optional[dict]:
    """
    의안의 표결 정보를 종합하여 메타데이터 dict로 반환한다.

    Returns:
        {
            "vote_date": "2024-01-15",
            "total": 299,
            "yes": 240,
            "no": 35,
            "abstain": 10,
            "absent": 14,
            "result": "가결",
            "member_votes": [
                {"name": "홍길동", "party": "더불어민주당", "vote": "찬성"},
                ...
            ]
        }
    """
    # 표결 결과 조회
    results = []
    for age in [22, 21, 20]:
        results = fetch_vote_result(
            bill_no=bill_no,
            bill_name=bill_name,
            assembly_age=age,
        )
        if results:
            break

    if not results:
        return None

    vr = results[0]
    meta = {
        "vote_date": vr.vote_date,
        "total": vr.total,
        "yes": vr.yes,
        "no": vr.no,
        "abstain": vr.abstain,
        "absent": vr.absent,
        "result": vr.result,
    }

    # 의원별 표결 (선택)
    if include_member_votes and vr.bill_no:
        member_votes = fetch_member_votes(vr.bill_no)
        if member_votes:
            meta["member_votes"] = [
                {
                    "name": mv.member_name,
                    "party": mv.party,
                    "vote": mv.vote,
                }
                for mv in member_votes
            ]

            # 정당별 표결 요약
            party_summary = {}
            for mv in member_votes:
                if mv.party not in party_summary:
                    party_summary[mv.party] = {"찬성": 0, "반대": 0, "기권": 0, "불참": 0}
                vote_key = mv.vote if mv.vote in party_summary[mv.party] else "불참"
                party_summary[mv.party][vote_key] += 1

            meta["party_summary"] = party_summary

    return meta


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _text(el: ET.Element, tag: str) -> str:
    t = el.findtext(tag, "")
    return t.strip() if t else ""


def _int(el: ET.Element, tag: str, alt_tag: str = "") -> int:
    t = el.findtext(tag, "")
    if not t and alt_tag:
        t = el.findtext(alt_tag, "")
    try:
        return int(t) if t else 0
    except ValueError:
        return 0
