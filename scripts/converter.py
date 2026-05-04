"""
법령 → 마크다운 변환기 (converter.py)
──────────────────────────────────────
법령 상세 데이터를 마크다운 파일로 변환한다.

원칙:
  법령 .md 파일에는 "공식 법령 데이터"만 포함한다.
  - 공포일, 시행일, 소관부처, 제개정구분 (법령 자체 메타데이터)
  - 국회 발의 정보 (의안명, 대표발의자, 소관위원회 등)
  - 법률 조문 원문

  판례, 표결, 상호참조, 하위법령 등 "부가 분석 데이터"는
  metadata/ 디렉토리에 별도 JSON으로 저장하며 별도 커밋된다.
  → git log -- korea/*.md 가 순수 법 개정 이력만 보여주도록.

매핑 규칙:
  편(編)  → # (h1)
  장(章)  → ## (h2)
  절(節)  → ### (h3)
  조(條)  → #### (h4)
  항(項)  → 번호 리스트
  호(號)  → 들여쓰기 리스트
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fetcher import LawDetail


def law_to_markdown(
    detail: LawDetail,
    assembly_meta: Optional[dict] = None,
    english_serial: Optional[int] = None,
) -> str:
    """
    LawDetail 객체를 마크다운 문자열로 변환한다.

    Args:
        detail: 법령 상세 정보
        assembly_meta: 국회 발의 메타데이터 (frontmatter에 포함)
        english_serial: 영문 법령 일련번호 (있으면 링크 추가)

    Note:
        판례, 표결, 상호참조 등 부가 데이터는 여기에 넣지 않는다.
        별도 JSON 파일로 metadata/ 디렉토리에 저장한다.
    """
    lines = []

    # ── YAML frontmatter ──
    lines.append("---")
    lines.append(f"법령명: \"{_escape_yaml(detail.name)}\"")
    if detail.law_type:
        lines.append(f"법령구분: \"{detail.law_type}\"")
    if detail.law_id:
        lines.append(f"법령ID: {detail.law_id}")
    if detail.serial_no:
        lines.append(f"법령일련번호: {detail.serial_no}")
    if detail.promul_date:
        lines.append(f"공포일자: \"{_format_date(detail.promul_date)}\"")
    if detail.promul_no:
        lines.append(f"공포번호: \"{detail.promul_no}\"")
    if detail.enforce_date:
        lines.append(f"시행일자: \"{_format_date(detail.enforce_date)}\"")
    if detail.revision_type:
        lines.append(f"제개정구분: \"{detail.revision_type}\"")
    if detail.ministry:
        lines.append(f"소관부처: \"{detail.ministry}\"")

    # 영문 법령 링크
    if english_serial:
        lines.append(f"영문법령일련번호: {english_serial}")

    # 국회 메타데이터 — 법률 제정/개정의 공식 기록이므로 frontmatter에 유지
    if assembly_meta:
        lines.append("국회정보:")
        if assembly_meta.get("bill_name"):
            lines.append(f"  의안명: \"{_escape_yaml(assembly_meta['bill_name'])}\"")
        if assembly_meta.get("propose_date"):
            lines.append(f"  제안일: \"{assembly_meta['propose_date']}\"")
        if assembly_meta.get("proposer"):
            lines.append(f"  제안자: \"{_escape_yaml(assembly_meta['proposer'])}\"")
        if assembly_meta.get("rst_proposer"):
            lines.append(f"  대표발의자: \"{_escape_yaml(assembly_meta['rst_proposer'])}\"")
        if assembly_meta.get("committee"):
            lines.append(f"  소관위원회: \"{assembly_meta['committee']}\"")
        if assembly_meta.get("proc_result"):
            lines.append(f"  처리결과: \"{assembly_meta['proc_result']}\"")
        if assembly_meta.get("legislators"):
            lines.append(f"  발의의원수: {len(assembly_meta['legislators'])}")
            lines.append("  발의의원:")
            for leg in assembly_meta["legislators"]:
                role_tag = " (대표)" if leg.get("role") == "대표발의" else ""
                party_tag = f" [{leg['party']}]" if leg.get("party") else ""
                lines.append(f"    - \"{leg['name']}{party_tag}{role_tag}\"")

    lines.append("---")
    lines.append("")

    # ── 법령명 타이틀 ──
    lines.append(f"# {detail.name}")
    lines.append("")

    # ── 전문(前文) ──
    if detail.preamble:
        lines.append(detail.preamble)
        lines.append("")

    # ── 편/장/절 구조 + 조문 매핑 ──
    chapter_map = _build_chapter_map(detail.chapter_structure)

    for article in detail.articles:
        # 해당 조문 앞에 새로운 편/장/절 헤딩이 있으면 삽입
        art_key = article.number
        if art_key in chapter_map:
            for chap in chapter_map[art_key]:
                heading_level = _chapter_heading_level(chap["type"])
                lines.append(f"{'#' * heading_level} {chap['number']} {chap['title']}")
                lines.append("")

        # 조문 라벨: "제1조" 또는 "제3조의2"
        if article.number:
            if article.branch_number:
                article_label = f"제{article.number}조의{article.branch_number}"
            else:
                article_label = f"제{article.number}조"
        else:
            article_label = ""

        # 조문 헤딩
        if article_label or article.title:
            if article_label and article.title:
                lines.append(f"#### {article_label} ({article.title})")
            elif article_label:
                lines.append(f"#### {article_label}")
            else:
                lines.append(f"#### {article.title}")
            lines.append("")

        if article.content:
            body = _clean_content(article.content)
            # 본문 시작이 헤딩과 중복되면 (예: "제1조(목적) 이 법은...") 접두사 제거
            if article_label:
                body = re.sub(
                    rf"^{re.escape(article_label)}\s*(\([^)]*\))?\s*",
                    "",
                    body,
                )
            if body:
                lines.append(body)
                lines.append("")

        # 항 출력
        for i, para in enumerate(article.paragraphs, 1):
            cleaned = _clean_content(para)
            if re.match(r"^[①-⑳⑴-⒇]", cleaned):
                lines.append(cleaned)
            else:
                lines.append(f"{_circled_num(i)} {cleaned}")
            lines.append("")

    # ── 부칙 ──
    if detail.addenda:
        lines.append("## 부칙")
        lines.append("")
        for addendum in detail.addenda:
            lines.append(_clean_content(addendum))
            lines.append("")

    return "\n".join(lines)


def classify_law_field(detail: LawDetail) -> str:
    """
    법령을 한국법 분야로 분류한다.
    1) 법령명 키워드 매칭 (FIELD_BY_KEYWORD 순서대로)
    2) 소관부처 매핑 (FIELD_BY_MINISTRY)
    3) "기타"
    """
    from config import FIELD_BY_KEYWORD, FIELD_BY_MINISTRY, FIELD_FALLBACK

    name = detail.name or ""
    for pattern, field in FIELD_BY_KEYWORD:
        if re.search(pattern, name):
            return field

    if detail.ministry and detail.ministry in FIELD_BY_MINISTRY:
        return FIELD_BY_MINISTRY[detail.ministry]

    return FIELD_FALLBACK


def generate_filename(detail: LawDetail) -> str:
    """
    법령 파일 경로 생성. 형식: {분야}/{법령구분}/{법령ID}-{법령명}.md

    law_id(법령ID)는 개정되어도 변하지 않으므로 같은 법령의 모든 개정이
    하나의 파일을 덮어쓴다 → git blame으로 조문별 개정자 추적.

    예시:
      형사법/법률/1692-형법.md
      민사법/법률/1706-민법.md
      행정일반/대통령령/12345-...md
    """
    safe_name = _sanitize_filename(detail.name)
    field = classify_law_field(detail)
    law_type = detail.law_type or "기타"
    return f"{field}/{law_type}/{detail.law_id}-{safe_name}.md"


def generate_commit_message(
    detail: LawDetail,
    assembly_meta: Optional[dict] = None,
) -> str:
    """
    법령 개정 커밋 메시지를 생성한다.

    형식:
      {제개정구분}: {법령명}
      공포일자: YYYY-MM-DD
      소관부처: ...
      [국회 정보]
      대표발의: ...
    """
    subject = f"{detail.revision_type or '갱신'}: {detail.name}"

    body_lines = []
    if detail.promul_date:
        body_lines.append(f"공포일자: {_format_date(detail.promul_date)}")
    if detail.promul_no:
        body_lines.append(f"공포번호: 제{detail.promul_no}호")
    if detail.enforce_date:
        body_lines.append(f"시행일자: {_format_date(detail.enforce_date)}")
    if detail.ministry:
        body_lines.append(f"소관부처: {detail.ministry}")

    if assembly_meta:
        body_lines.append("")
        body_lines.append("[국회 정보]")
        if assembly_meta.get("committee"):
            body_lines.append(f"소관위원회: {assembly_meta['committee']}")
        if assembly_meta.get("proc_result"):
            body_lines.append(f"처리결과: {assembly_meta['proc_result']}")

        # 발의의원 전원 나열
        legislators = assembly_meta.get("legislators", [])
        if legislators:
            lead = [l for l in legislators if l.get("role") == "대표발의"]
            co = [l for l in legislators if l.get("role") != "대표발의"]

            body_lines.append("")
            body_lines.append(f"[발의의원 ({len(legislators)}명)]")
            if lead:
                l = lead[0]
                party = f" ({l['party']})" if l.get("party") else ""
                body_lines.append(f"대표발의: {l['name']}{party}")
            if co:
                names = [
                    f"{l['name']} ({l['party']})" if l.get("party") else l["name"]
                    for l in co
                ]
                body_lines.append(f"공동발의: {', '.join(names)}")
        elif assembly_meta.get("proposer"):
            # legislators 못 가져온 경우 fallback
            body_lines.append(f"제안자: {assembly_meta['proposer']}")

    body = "\n".join(body_lines)
    return f"{subject}\n\n{body}" if body_lines else subject


_KST = timezone(timedelta(hours=9))


def get_commit_date(detail: LawDetail) -> str:
    """
    커밋 날짜를 공포일자 KST 12:00 기준으로 반환한다.

    Windows Git은 1970-01-01 UTC 이전 timestamp를 ISO 양식이든
    raw epoch(@-N) 양식이든 모두 거부한다(OS API 제약).
    그래서 1970 이전 일자는 epoch 0 (1970-01-01 09:00 KST)으로
    통일하고, 정확한 공포일자는 커밋 메시지 body와 마크다운
    frontmatter에 그대로 보존한다.

    git log의 author date는 옛 일자들이 같은 시각으로 보이지만,
    검색은 본문 'commit body 공포일자: YYYY-MM-DD'로 가능.
    """
    if detail.promul_date and len(detail.promul_date) == 8:
        try:
            dt_kst = datetime.strptime(detail.promul_date, "%Y%m%d").replace(
                hour=12, tzinfo=_KST
            )
            epoch = int(dt_kst.timestamp())
            if epoch < 0:
                # Windows Git 호환 — 1970-01-01 09:00 KST = epoch 0
                return "1970-01-01T09:00:00+09:00"
            return dt_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00")
        except (ValueError, OverflowError):
            pass
    return datetime.now(_KST).strftime("%Y-%m-%dT12:00:00+09:00")


# ──────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────
def _build_chapter_map(chapters: list) -> dict:
    mapping = {}
    for ch in chapters:
        key = ch.get("key", "")
        if key:
            if key not in mapping:
                mapping[key] = []
            mapping[key].append(ch)
    return mapping


def _chapter_heading_level(chapter_type: str) -> int:
    levels = {"편": 1, "장": 2, "절": 3, "관": 3}
    return levels.get(chapter_type, 2)


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


def _sanitize_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', "", name)
    safe = safe.replace(" ", "_")
    return safe[:80]


def _circled_num(n: int) -> str:
    if 1 <= n <= 20:
        return chr(0x2460 + n - 1)
    return f"({n})"
