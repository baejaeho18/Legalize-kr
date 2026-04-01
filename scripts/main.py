#!/usr/bin/env python3
"""
legalize-kr 메인 스크립트 (main.py)
───────────────────────────────────
모든 한국 법률을 Git 저장소에 마크다운으로 기록한다.

사용법:
  # 전체 법률 초기 구축 (최초 1회)
  python main.py --init

  # 최근 변경된 법령만 업데이트 (일일 실행)
  python main.py --update

  # 특정 법령만 처리
  python main.py --law "개인정보 보호법"

  # 특정 법령의 전체 연혁 재구축
  python main.py --history --law "개인정보 보호법"

  # 판례 수집
  python main.py --cases --law "개인정보 보호법"

  # 영문 법령 수집
  python main.py --english --limit 10

  # 상호참조 그래프 생성
  python main.py --crossref

  # RSS 피드 생성
  python main.py --feed

  # 검색 인덱스 생성
  python main.py --index
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 스크립트 디렉토리를 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LAWS_DIR, LAWS_EN_DIR, LOG_LEVEL, GITHUB_REPO_URL
from fetcher import fetch_all_laws, fetch_law_detail, fetch_law_history, fetch_law_list, LawSummary
from converter import law_to_markdown, generate_filename, generate_commit_message, get_commit_date
from committer import GitCommitter
from assembly import build_assembly_metadata

# ──────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("legalize-kr")


# ──────────────────────────────────────────────
# 커밋 author 추출 헬퍼
# ──────────────────────────────────────────────
def _extract_author(assembly_meta: dict, detail) -> tuple[str, str]:
    """
    assembly_meta에서 대표발의 의원명을 추출하여 Git author 정보를 반환한다.

    반환: (author_name, author_email)
      - 의원발의 법안 → ("홍길동", "홍길동@legislator.kr")
      - 정부제출 법안 → ("행정안전부", "행정안전부@government.kr")
      - 정보 없음     → ("legalize-kr", "legalize-kr@github.com")

    git blame 시 각 법령 라인에 발의 의원명이 표시된다.
    """
    DEFAULT = ("legalize-kr", "legalize-kr@github.com")

    if not assembly_meta:
        # assembly_meta 없는 경우: 소관부처명이 있으면 사용
        if hasattr(detail, "ministry") and detail.ministry:
            return (detail.ministry, f"{detail.ministry}@government.kr")
        return DEFAULT

    # 1순위: legislators 리스트에서 대표발의자
    legislators = assembly_meta.get("legislators", [])
    for leg in legislators:
        if leg.get("role") == "대표발의" and leg.get("name"):
            name = leg["name"]
            return (name, f"{name}@legislator.kr")

    # 2순위: rst_proposer 필드 (API에서 직접 제공)
    rst = assembly_meta.get("rst_proposer", "").strip()
    if rst:
        return (rst, f"{rst}@legislator.kr")

    # 3순위: proposer 필드에서 이름 추출 ("홍길동의원 등 12인" → "홍길동")
    proposer = assembly_meta.get("proposer", "")
    if proposer:
        # "홍길동의원 등 12인", "정부" 등 다양한 형태
        if "정부" in proposer:
            if hasattr(detail, "ministry") and detail.ministry:
                return (detail.ministry, f"{detail.ministry}@government.kr")
            return ("정부", "정부@government.kr")
        # "홍길동의원 등 12인" → "홍길동"
        name = proposer.split("의원")[0].split("위원장")[0].strip()
        if name and len(name) <= 10:
            return (name, f"{name}@legislator.kr")

    return DEFAULT


def _build_vote_commit_message(law_name: str, vote_meta: dict) -> str:
    """
    표결 메타데이터 커밋 메시지를 생성한다.

    요약 + 정당별 소계 + 의원별 전체 투표 테이블을 포함한다.
    형식:
      meta: 표결 갱신 — {법령명}

      [표결 결과]
      일시: 2024-01-15
      결과: 가결 (찬성 240 / 반대 35 / 기권 10 / 불참 14)

      [정당별]
      더불어민주당: 찬성 120, 반대 5, 기권 2, 불참 3
      국민의힘: 찬성 100, 반대 28, 기권 7, 불참 10
      ...

      [의원별 표결 (300명)]
      이름 (정당): 투표
      ...
    """
    subject = f"meta: 표결 갱신 — {law_name}"

    lines = []
    lines.append("[표결 결과]")
    if vote_meta.get("vote_date"):
        lines.append(f"일시: {vote_meta['vote_date']}")
    result = vote_meta.get("result", "")
    yes = vote_meta.get("yes", 0)
    no = vote_meta.get("no", 0)
    abstain = vote_meta.get("abstain", 0)
    absent = vote_meta.get("absent", 0)
    lines.append(f"결과: {result} (찬성 {yes} / 반대 {no} / 기권 {abstain} / 불참 {absent})")

    # 정당별 소계
    party_summary = vote_meta.get("party_summary", {})
    if party_summary:
        lines.append("")
        lines.append("[정당별]")
        for party, counts in sorted(party_summary.items(), key=lambda x: -sum(x[1].values())):
            parts = []
            for k in ["찬성", "반대", "기권", "불참"]:
                v = counts.get(k, 0)
                if v:
                    parts.append(f"{k} {v}")
            lines.append(f"{party}: {', '.join(parts)}")

    # 의원별 전체 테이블
    member_votes = vote_meta.get("member_votes", [])
    if member_votes:
        lines.append("")
        lines.append(f"[의원별 표결 ({len(member_votes)}명)]")
        # 정당별로 그룹핑, 각 정당 내에서 이름순
        by_party = {}
        for mv in member_votes:
            party = mv.get("party", "무소속")
            if party not in by_party:
                by_party[party] = []
            by_party[party].append(mv)

        for party in sorted(by_party.keys()):
            members = sorted(by_party[party], key=lambda x: x.get("name", ""))
            for mv in members:
                lines.append(f"{mv['name']} ({party}): {mv.get('vote', '?')}")

    body = "\n".join(lines)
    return f"{subject}\n\n{body}"


# ──────────────────────────────────────────────
# 핵심 처리 로직
# ──────────────────────────────────────────────
def process_single_law(
    law: LawSummary,
    committer: GitCommitter,
    include_assembly: bool = True,
    include_votes: bool = False,
    include_cases: bool = False,
    include_crossref: bool = False,
    force: bool = False,
) -> bool:
    """
    단일 법령을 마크다운으로 변환하고 커밋한다.

    커밋 분리 원칙:
      1) 법령 .md 커밋 → korea/ 디렉토리, 공포일자 기준 날짜
      2) 메타데이터 커밋 → metadata/ 디렉토리, "meta:" 접두사, 현재 시각
      → git log -- korea/*.md 는 순수 법 개정 이력만 표시
    """
    # 법령 상세 조회
    detail = fetch_law_detail(law.serial_no)
    if not detail:
        logger.warning(f"법령 상세 조회 실패: {law.name} (serial={law.serial_no})")
        return False

    # 파일 경로 결정
    filename = generate_filename(detail)
    file_path = f"{LAWS_DIR}/{filename}"

    # 이미 처리된 법령인지 확인
    if not force:
        latest_date = committer.get_latest_commit_date(file_path)
        if latest_date and detail.promul_date:
            from converter import _format_date
            if _format_date(detail.promul_date) <= latest_date[:10]:
                logger.debug(f"이미 최신: {law.name}")
                return False

    # ── 1단계: 국회 메타데이터 조회 (frontmatter에 포함, 법령 커밋에 함께 기록) ──
    assembly_meta = None
    if include_assembly and detail.revision_type in ["제정", "일부개정", "전부개정"]:
        try:
            assembly_meta = build_assembly_metadata(detail.name)
        except Exception as e:
            logger.warning(f"국회 메타데이터 조회 실패: {e}")

    # ── 2단계: 법령 .md 생성 및 커밋 (순수 법령 데이터만) ──
    markdown = law_to_markdown(
        detail,
        assembly_meta=assembly_meta,
    )

    commit_msg = generate_commit_message(detail, assembly_meta)
    commit_date = get_commit_date(detail)

    # Git author = 대표발의 의원 (git blame에 표시)
    author_name, author_email = _extract_author(assembly_meta, detail)

    # 폐지된 법령 처리
    if detail.revision_type in ["폐지", "폐지제정", "타법폐지", "일괄폐지"]:
        if detail.revision_type in ("폐지", "타법폐지"):
            return committer.delete_law(file_path, commit_msg, commit_date)

    law_committed = committer.commit_law(
        file_path=file_path,
        content=markdown,
        commit_message=commit_msg,
        commit_date=commit_date,
        author_name=author_name,
        author_email=author_email,
    )

    # ── 3단계: 부가 메타데이터를 별도 커밋으로 저장 ──

    # 표결 정보 → metadata/votes/{법령명}.json
    if include_votes and assembly_meta and assembly_meta.get("bill_no"):
        try:
            from vote import build_vote_metadata
            vote_meta = build_vote_metadata(
                bill_no=assembly_meta["bill_no"],
                include_member_votes=True,
            )
            if vote_meta:
                vote_commit_msg = _build_vote_commit_message(detail.name, vote_meta)
                committer.commit_metadata(
                    law_name=detail.name,
                    meta_type="votes",
                    data=vote_meta,
                    commit_message=vote_commit_msg,
                )
        except Exception as e:
            logger.warning(f"표결 정보 조회 실패: {e}")

    # 판례 참조 → metadata/cases/{법령명}.json
    if include_cases:
        try:
            from courtcase import build_case_metadata
            case_meta = build_case_metadata(detail.name, max_cases=10)
            if case_meta and case_meta.get("cases"):
                committer.commit_metadata(
                    law_name=detail.name,
                    meta_type="cases",
                    data=case_meta,
                )
        except Exception as e:
            logger.warning(f"판례 조회 실패: {e}")

    # 상호참조 → metadata/crossrefs/{법령명}.json
    if include_crossref:
        try:
            from crossref import find_subordinate_laws, extract_references_from_text
            subs = find_subordinate_laws(detail.name)
            temp_md = law_to_markdown(detail)
            refs = extract_references_from_text(detail.name, temp_md)
            crossref_data = {
                "subordinates": [
                    {"name": s.name, "law_id": s.law_id, "relationship": s.relationship}
                    for s in subs
                ],
                "outgoing_refs": [
                    {"target_law": r.target_law, "source_article": r.source_article,
                     "target_article": r.target_article, "type": r.ref_type}
                    for r in refs if r.target_law
                ],
            }
            if crossref_data["subordinates"] or crossref_data["outgoing_refs"]:
                committer.commit_metadata(
                    law_name=detail.name,
                    meta_type="crossrefs",
                    data=crossref_data,
                )
        except Exception as e:
            logger.warning(f"상호참조 분석 실패: {e}")

    return law_committed


def process_law_history(
    law_name: str,
    committer: GitCommitter,
    include_assembly: bool = True,
    include_votes: bool = False,
) -> int:
    """
    특정 법령의 전체 연혁을 시간순으로 커밋한다.
    """
    logger.info(f"=== 법령 연혁 재구축: {law_name} ===")

    laws, _ = fetch_law_list(query=law_name, display=5)
    if not laws:
        logger.error(f"법령을 찾을 수 없음: {law_name}")
        return 0

    target = laws[0]
    logger.info(f"대상 법령: {target.name} (ID={target.law_id})")

    history = fetch_law_history(target.law_id)
    if not history:
        logger.warning("연혁 정보 없음")
        return 0

    count = 0
    for version in history:
        try:
            success = process_single_law(
                version, committer,
                include_assembly=include_assembly,
                include_votes=include_votes,
                force=True,
            )
            if success:
                count += 1
        except Exception as e:
            logger.error(f"버전 처리 실패 ({version.promul_date}): {e}")

    logger.info(f"=== 연혁 {count}건 커밋 완료 ===")
    return count


def init_full_build(
    committer: GitCommitter,
    law_kind: str = "",
    include_assembly: bool = False,
    include_votes: bool = False,
    limit: int = 0,
    sort: str = "lasc",
) -> int:
    """
    전체 현행법령을 수집하여 Git 저장소를 초기 구축한다.
    """
    logger.info("=== 전체 법령 초기 구축 시작 ===")

    laws = fetch_all_laws(law_kind=law_kind, sort=sort)
    if limit:
        laws = laws[:limit]

    total = len(laws)
    count = 0
    errors = 0

    for i, law in enumerate(laws, 1):
        logger.info(f"[{i}/{total}] {law.name}")
        try:
            success = process_single_law(
                law, committer,
                include_assembly=include_assembly,
                include_votes=include_votes,
            )
            if success:
                count += 1
        except Exception as e:
            logger.error(f"처리 실패: {law.name} — {e}")
            errors += 1

    logger.info(f"=== 초기 구축 완료: {count}건 커밋, {errors}건 실패 ===")
    return count


def update_recent(
    committer: GitCommitter,
    days: int = 7,
    include_assembly: bool = True,
    include_votes: bool = False,
) -> int:
    """
    최근 N일 내 공포된 법령만 업데이트한다.
    """
    today = datetime.now()
    date_from = (today - timedelta(days=days)).strftime("%Y%m%d")
    date_to = today.strftime("%Y%m%d")

    logger.info(f"=== 최근 변경 업데이트: {date_from} ~ {date_to} ===")

    all_updated = []
    page = 1
    while True:
        laws, total = fetch_law_list(
            page=page,
            promul_date_from=date_from,
            promul_date_to=date_to,
        )
        all_updated.extend(laws)
        if len(all_updated) >= total or not laws:
            break
        page += 1

    if not all_updated:
        logger.info("업데이트할 법령 없음")
        return 0

    count = 0
    for law in all_updated:
        try:
            success = process_single_law(
                law, committer,
                include_assembly=include_assembly,
                include_votes=include_votes,
            )
            if success:
                count += 1
        except Exception as e:
            logger.error(f"업데이트 실패: {law.name} — {e}")

    logger.info(f"=== 업데이트 완료: {count}건 ===")
    return count


# ──────────────────────────────────────────────
# 판례 수집
# ──────────────────────────────────────────────
def collect_cases(
    law_name: str,
    committer: GitCommitter,
    max_cases: int = 20,
) -> int:
    """특정 법률에 대한 판례를 수집하고 별도 커밋으로 저장한다."""
    from courtcase import build_case_metadata

    logger.info(f"=== 판례 수집: {law_name} ===")

    meta = build_case_metadata(law_name, max_cases=max_cases)
    if not meta or not meta.get("cases"):
        logger.info("관련 판례 없음")
        return 0

    committer.commit_metadata(
        law_name=law_name,
        meta_type="cases",
        data=meta,
    )

    logger.info(f"판례 {len(meta['cases'])}건 커밋 완료")
    return len(meta["cases"])


# ──────────────────────────────────────────────
# 영문 법령 수집
# ──────────────────────────────────────────────
def collect_english(
    committer: GitCommitter,
    limit: int = 0,
    query: str = "",
) -> int:
    """영문 법령을 수집하여 별도 디렉토리에 저장한다."""
    from english import (
        fetch_all_english_laws,
        fetch_english_law_detail,
        english_law_to_markdown,
        generate_english_filename,
    )

    logger.info("=== 영문 법령 수집 시작 ===")

    laws = fetch_all_english_laws(query=query)
    if limit:
        laws = laws[:limit]

    count = 0
    for i, law in enumerate(laws, 1):
        logger.info(f"[{i}/{len(laws)}] {law.name_en or law.name_kr}")
        try:
            detail = fetch_english_law_detail(law.serial_no)
            if not detail:
                continue

            markdown = english_law_to_markdown(detail)
            filename = generate_english_filename(detail)
            file_path = f"{LAWS_EN_DIR}/{filename}"

            success = committer.commit_law(
                file_path=file_path,
                content=markdown,
                commit_message=f"영문: {detail.name_en or detail.name_kr}",
                commit_date=get_commit_date_from_str(detail.promul_date),
            )
            if success:
                count += 1
        except Exception as e:
            logger.error(f"영문 법령 처리 실패: {e}")

    logger.info(f"=== 영문 법령 {count}건 수집 완료 ===")
    return count


# ──────────────────────────────────────────────
# 상호참조 그래프
# ──────────────────────────────────────────────
def build_crossref(repo_path: str) -> dict:
    """상호참조 그래프를 생성하고 저장한다."""
    from crossref import build_reference_graph, save_reference_graph

    logger.info("=== 상호참조 그래프 생성 ===")
    graph = build_reference_graph(repo_path)
    save_reference_graph(graph, repo_path)

    stats = graph.get("stats", {})
    logger.info(
        f"그래프: {stats.get('total_laws', 0)}개 법률, "
        f"{stats.get('total_references', 0)}개 참조"
    )
    return graph


# ──────────────────────────────────────────────
# RSS 피드
# ──────────────────────────────────────────────
def generate_feeds(repo_path: str, base_url: str = "") -> None:
    """RSS/Atom 피드를 생성한다."""
    from rss import extract_entries_from_git, generate_filtered_feeds

    if not base_url:
        base_url = GITHUB_REPO_URL

    logger.info("=== RSS/Atom 피드 생성 ===")
    entries = extract_entries_from_git(repo_path, max_entries=100, base_url=base_url)
    generate_filtered_feeds(entries, repo_path, base_url=base_url)
    logger.info(f"피드 생성 완료 → {repo_path}/feeds/")


# ──────────────────────────────────────────────
# 검색 인덱스
# ──────────────────────────────────────────────
def build_indexes(repo_path: str) -> dict:
    """전체 검색 인덱스를 생성한다."""
    from search_index import generate_all_indexes

    logger.info("=== 검색 인덱스 생성 ===")
    paths = generate_all_indexes(repo_path)
    logger.info(f"인덱스 {len(paths)}개 생성 완료")
    return paths


# ──────────────────────────────────────────────
# 통계 / 보고
# ──────────────────────────────────────────────
def print_stats(committer: GitCommitter, repo_path: str):
    """저장소 통계를 출력한다."""
    laws_path = Path(repo_path) / LAWS_DIR
    en_path = Path(repo_path) / LAWS_EN_DIR
    meta_path = Path(repo_path) / "metadata"

    md_files = list(laws_path.glob("*.md")) if laws_path.exists() else []
    en_files = list(en_path.glob("*.md")) if en_path.exists() else []
    commit_count = committer.get_commit_count()

    print(f"\n{'─' * 50}")
    print(f"  legalize-kr 통계")
    print(f"{'─' * 50}")
    print(f"  법령 파일 수   : {len(md_files)}건")
    print(f"  영문 법령 수   : {len(en_files)}건")
    print(f"  Git 커밋 수    : {commit_count}건")
    print(f"  저장소 경로    : {repo_path}")

    if meta_path.exists():
        meta_files = list(meta_path.glob("*.json"))
        print(f"  메타데이터 파일 : {len(meta_files)}개")

    feeds_path = Path(repo_path) / "feeds"
    if feeds_path.exists():
        feed_files = list(feeds_path.rglob("*.xml"))
        print(f"  RSS 피드       : {len(feed_files)}개")

    print(f"{'─' * 50}\n")


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def get_commit_date_from_str(date_str: str) -> str:
    """YYYYMMDD 문자열에서 커밋 날짜를 생성한다."""
    if date_str and len(date_str) == 8:
        try:
            dt = datetime.strptime(date_str, "%Y%m%d")
            return dt.strftime("%Y-%m-%dT12:00:00+09:00")
        except ValueError:
            pass
    return datetime.now().strftime("%Y-%m-%dT12:00:00+09:00")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="legalize-kr: 한국 법률을 Git으로 추적합니다",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 전체 법률 초기 구축 (법률만, 대통령령 제외)
  python main.py --init --kind 법률

  # 전체 법률 + 국회/표결 메타데이터 포함
  python main.py --init --kind 법률 --assembly --votes

  # 최근 7일간 변경된 법령만 업데이트
  python main.py --update --days 7

  # 특정 법령의 전체 연혁 재구축
  python main.py --history --law "개인정보 보호법"

  # 판례 수집
  python main.py --cases --law "개인정보 보호법"

  # 영문 법령 수집
  python main.py --english --limit 10

  # 상호참조 그래프 생성
  python main.py --crossref

  # RSS/Atom 피드 생성
  python main.py --feed

  # 검색 인덱스 생성
  python main.py --index

  # 모든 후처리 (피드 + 인덱스 + 상호참조) 한번에
  python main.py --postprocess

  # 테스트: 5건만 처리
  python main.py --init --limit 5
        """,
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--init", action="store_true",
                        help="전체 현행법령 초기 구축")
    action.add_argument("--update", action="store_true",
                        help="최근 변경된 법령만 업데이트")
    action.add_argument("--history", action="store_true",
                        help="특정 법령의 전체 연혁 재구축")
    action.add_argument("--cases", action="store_true",
                        help="특정 법률 관련 판례 수집")
    action.add_argument("--english", action="store_true",
                        help="영문 법령 수집")
    action.add_argument("--crossref", action="store_true",
                        help="상호참조 그래프 생성")
    action.add_argument("--feed", action="store_true",
                        help="RSS/Atom 피드 생성")
    action.add_argument("--index", action="store_true",
                        help="검색 인덱스 생성")
    action.add_argument("--postprocess", action="store_true",
                        help="후처리 전체 실행 (피드 + 인덱스 + 상호참조)")
    action.add_argument("--stats", action="store_true",
                        help="저장소 통계 출력")

    parser.add_argument("--law", type=str, default="",
                        help="특정 법령명 (검색)")
    parser.add_argument("--kind", type=str, default="",
                        choices=["", "법률", "대통령령", "총리령", "부령"],
                        help="법령 종류 필터")
    parser.add_argument("--days", type=int, default=7,
                        help="업데이트 시 검색할 일수 (기본: 7)")
    parser.add_argument("--assembly", action="store_true",
                        help="국회 메타데이터 포함 (발의의원 등)")
    parser.add_argument("--votes", action="store_true",
                        help="본회의 표결 정보 포함")
    parser.add_argument("--limit", type=int, default=0,
                        help="처리할 최대 법령 수 (테스트용)")
    parser.add_argument("--sort", type=str, default="lasc",
                        choices=["lasc", "ldes", "dasc", "ddes", "efasc", "efdes"],
                        help="정렬 (lasc=법령명↑, ddes=공포일↓최신순, dasc=공포일↑오래된순)")
    parser.add_argument("--max-cases", type=int, default=20,
                        help="판례 최대 수집 건수 (기본: 20)")
    parser.add_argument("--repo", type=str, default=".",
                        help="Git 저장소 경로 (기본: 현재 디렉토리)")
    parser.add_argument("--base-url", type=str, default="",
                        help="GitHub 저장소 URL (RSS 피드용)")

    args = parser.parse_args()
    repo_path = os.path.abspath(args.repo)
    committer = GitCommitter(repo_path)

    if args.stats:
        print_stats(committer, repo_path)
        return

    if args.init:
        count = init_full_build(
            committer,
            law_kind=args.kind,
            include_assembly=args.assembly,
            include_votes=args.votes,
            limit=args.limit,
            sort=args.sort,
        )
        print_stats(committer, repo_path)
        print(f"초기 구축 완료: {count}건 커밋")

    elif args.update:
        count = update_recent(
            committer,
            days=args.days,
            include_assembly=args.assembly,
            include_votes=args.votes,
        )
        print(f"업데이트 완료: {count}건 커밋")

    elif args.history:
        if not args.law:
            parser.error("--history는 --law 옵션이 필요합니다")
        count = process_law_history(
            args.law, committer,
            include_assembly=args.assembly,
            include_votes=args.votes,
        )
        print(f"연혁 재구축 완료: {count}건 커밋")

    elif args.cases:
        if not args.law:
            parser.error("--cases는 --law 옵션이 필요합니다")
        count = collect_cases(args.law, committer, max_cases=args.max_cases)
        print(f"판례 수집 완료: {count}건")

    elif args.english:
        count = collect_english(committer, limit=args.limit, query=args.law)
        print(f"영문 법령 수집 완료: {count}건")

    elif args.crossref:
        graph = build_crossref(repo_path)
        stats = graph.get("stats", {})
        print(
            f"상호참조 그래프 생성 완료: "
            f"{stats.get('total_laws', 0)}개 법률, "
            f"{stats.get('total_references', 0)}개 참조"
        )

    elif args.feed:
        generate_feeds(repo_path, base_url=args.base_url)
        print("RSS/Atom 피드 생성 완료")

    elif args.index:
        paths = build_indexes(repo_path)
        print(f"검색 인덱스 생성 완료: {len(paths)}개 파일")

    elif args.postprocess:
        print("=== 후처리 시작 ===")
        build_crossref(repo_path)
        generate_feeds(repo_path, base_url=args.base_url)
        build_indexes(repo_path)
        print("=== 후처리 완료 ===")


if __name__ == "__main__":
    main()
