"""
하위법령 연결 + 법률 간 상호참조 모듈 (crossref.py)
─────────────────────────────────────────────────
법률 → 시행령 → 시행규칙 간 계층관계와
법률 본문 내 타 법률 참조를 추적한다.

기능:
  1. 하위법령 연결: 법률 → 대통령령(시행령) → 총리령/부령(시행규칙)
  2. 상호참조 추출: 법률 본문에서 "「○○법」 제○조" 패턴 감지
  3. 위임조항 추적: "대통령령으로 정한다", "부령으로 정한다" 패턴 감지
  4. 참조 그래프 생성: 법률 간 참조 관계를 JSON으로 기록
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

from config import (
    LAW_API_OC,
    LAW_SEARCH_URL,
    LAWS_DIR,
    REQUEST_DELAY,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────
@dataclass
class LawReference:
    """법률 간 참조"""
    source_law: str = ""           # 참조하는 법률명
    source_article: str = ""       # 참조하는 조문 (예: 제5조)
    target_law: str = ""           # 참조되는 법률명
    target_article: str = ""       # 참조되는 조문 (예: 제10조)
    ref_type: str = ""             # 참조 유형: "인용", "위임", "준용"
    context: str = ""              # 참조 문맥 (해당 문장)


@dataclass
class SubordinateLaw:
    """하위법령 정보"""
    law_id: int = 0
    name: str = ""
    law_type: str = ""             # 대통령령/총리령/부령
    promul_date: str = ""
    enforce_date: str = ""
    parent_law_name: str = ""      # 상위 법률명
    relationship: str = ""         # 시행령/시행규칙


@dataclass
class CrossRefReport:
    """상호참조 분석 결과"""
    law_name: str = ""
    subordinates: list = field(default_factory=list)     # list[SubordinateLaw]
    outgoing_refs: list = field(default_factory=list)    # list[LawReference] — 이 법이 참조하는 타 법률
    incoming_refs: list = field(default_factory=list)    # list[LawReference] — 타 법률이 이 법을 참조
    delegation_articles: list = field(default_factory=list)  # 위임 조항 목록


# ──────────────────────────────────────────────
# 하위법령 검색
# ──────────────────────────────────────────────
def find_subordinate_laws(law_name: str) -> list[SubordinateLaw]:
    """
    법률의 하위법령(시행령, 시행규칙)을 검색한다.

    전략:
      1. "{법률명} 시행령"으로 대통령령 검색
      2. "{법률명} 시행규칙"으로 총리령/부령 검색
    """
    subordinates = []

    # 시행령 검색
    for suffix, law_type, rel in [
        ("시행령", "대통령령", "시행령"),
        ("시행규칙", "부령", "시행규칙"),
    ]:
        query = f"{law_name} {suffix}"
        params = {
            "OC": LAW_API_OC,
            "target": "law",
            "type": "XML",
            "query": query,
            "display": 10,
        }

        try:
            resp = requests.get(LAW_SEARCH_URL, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"하위법령 검색 실패: {e}")
            continue

        time.sleep(REQUEST_DELAY)

        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)

        for item in root.iter("law"):
            name = _clean(item.findtext("법령명한글", ""))
            # 정확한 하위법령인지 확인
            if law_name in name and suffix in name:
                sub = SubordinateLaw(
                    law_id=int(item.findtext("법령ID", "0")),
                    name=name,
                    law_type=_clean(item.findtext("법령구분명", law_type)),
                    promul_date=item.findtext("공포일자", ""),
                    enforce_date=item.findtext("시행일자", ""),
                    parent_law_name=law_name,
                    relationship=rel,
                )
                subordinates.append(sub)
                break  # 첫 번째 매칭만

    logger.info(f"'{law_name}' 하위법령 {len(subordinates)}건")
    return subordinates


# ──────────────────────────────────────────────
# 법률 본문에서 상호참조 추출
# ──────────────────────────────────────────────
def extract_references_from_text(
    law_name: str,
    text: str,
) -> list[LawReference]:
    """
    법률 본문 텍스트에서 타 법률 참조를 추출한다.

    인식 패턴:
      - 「개인정보 보호법」 제2조
      - 「형법」 제30조부터 제32조까지
      - 「민법」에 따른
      - 다른 법률에 특별한 규정이 있는 경우
    """
    references = []

    # 현재 조문 번호 추적
    current_article = ""

    for line in text.split("\n"):
        # 현재 조문 번호 업데이트
        art_match = re.match(r"#{1,4}\s*(제\d+조(?:의\d+)?)", line)
        if art_match:
            current_article = art_match.group(1)
            continue

        # 패턴 1: 「법률명」 제N조
        pattern1 = r"「([^」]+)」\s*(?:제(\d+조(?:의\d+)?))?(?:제(\d+항))?"
        for m in re.finditer(pattern1, line):
            target_law = m.group(1)
            target_article = f"제{m.group(2)}" if m.group(2) else ""

            # 자기 자신 참조는 제외
            if target_law == law_name:
                continue

            ref = LawReference(
                source_law=law_name,
                source_article=current_article,
                target_law=target_law,
                target_article=target_article,
                ref_type="인용",
                context=_truncate(line.strip(), 100),
            )
            references.append(ref)

        # 패턴 2: 위임 조항 ("대통령령으로 정한다" 등)
        delegation_patterns = [
            (r"대통령령으로\s+정한다", "대통령령 위임"),
            (r"대통령령으로\s+정하는", "대통령령 위임"),
            (r"총리령으로\s+정한다", "총리령 위임"),
            (r"부령으로\s+정한다", "부령 위임"),
            (r"(?:총리령|부령)(?:또는|·)(?:총리령|부령)으로\s+정한다", "총리령/부령 위임"),
        ]

        for pattern, ref_type in delegation_patterns:
            if re.search(pattern, line):
                ref = LawReference(
                    source_law=law_name,
                    source_article=current_article,
                    target_law="",
                    target_article="",
                    ref_type=ref_type,
                    context=_truncate(line.strip(), 100),
                )
                references.append(ref)

        # 패턴 3: 준용 규정 ("~를 준용한다")
        prep_match = re.search(r"「([^」]+)」[^」]*준용", line)
        if prep_match:
            target_law = prep_match.group(1)
            if target_law != law_name:
                ref = LawReference(
                    source_law=law_name,
                    source_article=current_article,
                    target_law=target_law,
                    ref_type="준용",
                    context=_truncate(line.strip(), 100),
                )
                references.append(ref)

    logger.info(f"'{law_name}': {len(references)}개 참조 추출")
    return references


# ──────────────────────────────────────────────
# 참조 그래프 생성
# ──────────────────────────────────────────────
def build_reference_graph(repo_path: str) -> dict:
    """
    전체 법령 파일을 스캔하여 참조 그래프를 생성한다.

    Returns:
        {
            "nodes": [
                {"id": "개인정보 보호법", "type": "법률", "file": "12345-개인정보_보호법.md"},
                ...
            ],
            "edges": [
                {"source": "개인정보 보호법", "target": "형법", "type": "인용", "articles": ["제70조"]},
                ...
            ],
            "stats": {
                "total_laws": 100,
                "total_references": 500,
                "most_referenced": [("민법", 120), ("형법", 95)],
            }
        }
    """
    laws_path = Path(repo_path) / LAWS_DIR
    if not laws_path.exists():
        logger.warning(f"법령 디렉토리 없음: {laws_path}")
        return {"nodes": [], "edges": [], "stats": {}}

    nodes = []
    edges = []
    ref_count = {}  # 피참조 카운트

    for md_file in sorted(laws_path.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")

        # frontmatter에서 법령명 추출
        law_name = _extract_frontmatter_field(content, "법령명")
        law_type = _extract_frontmatter_field(content, "법령구분")

        if not law_name:
            continue

        nodes.append({
            "id": law_name,
            "type": law_type or "법률",
            "file": md_file.name,
        })

        # 본문에서 참조 추출
        refs = extract_references_from_text(law_name, content)
        for ref in refs:
            if ref.target_law:
                edges.append({
                    "source": law_name,
                    "target": ref.target_law,
                    "type": ref.ref_type,
                    "source_article": ref.source_article,
                    "target_article": ref.target_article,
                })

                # 피참조 카운트
                ref_count[ref.target_law] = ref_count.get(ref.target_law, 0) + 1

    # 통계
    most_referenced = sorted(ref_count.items(), key=lambda x: -x[1])[:20]

    graph = {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_laws": len(nodes),
            "total_references": len(edges),
            "most_referenced": most_referenced,
        },
    }

    logger.info(f"참조 그래프: {len(nodes)}개 법률, {len(edges)}개 참조")
    return graph


def save_reference_graph(graph: dict, repo_path: str) -> str:
    """참조 그래프를 JSON 파일로 저장한다."""
    output_path = Path(repo_path) / "metadata" / "reference_graph.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    logger.info(f"참조 그래프 저장: {output_path}")
    return str(output_path)


# ──────────────────────────────────────────────
# 하위법령 매핑 생성
# ──────────────────────────────────────────────
def build_subordinate_map(repo_path: str) -> dict:
    """
    전체 법률에 대해 하위법령 매핑을 생성한다.

    Returns:
        {
            "개인정보 보호법": {
                "시행령": {"name": "개인정보 보호법 시행령", "law_id": 12346},
                "시행규칙": {"name": "개인정보 보호법 시행규칙", "law_id": 12347},
            },
            ...
        }
    """
    laws_path = Path(repo_path) / LAWS_DIR
    if not laws_path.exists():
        return {}

    mapping = {}

    for md_file in sorted(laws_path.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        law_name = _extract_frontmatter_field(content, "법령명")
        law_type = _extract_frontmatter_field(content, "법령구분")

        if not law_name or law_type != "법률":
            continue

        subs = find_subordinate_laws(law_name)
        if subs:
            mapping[law_name] = {}
            for sub in subs:
                mapping[law_name][sub.relationship] = {
                    "name": sub.name,
                    "law_id": sub.law_id,
                    "law_type": sub.law_type,
                }

    # 저장
    output_path = Path(repo_path) / "metadata" / "subordinate_map.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    logger.info(f"하위법령 매핑 저장: {output_path} ({len(mapping)}건)")
    return mapping


# ──────────────────────────────────────────────
# 위임 조항 분석
# ──────────────────────────────────────────────
def analyze_delegations(law_name: str, text: str) -> list[dict]:
    """
    법률 본문에서 하위법령 위임 조항을 분석한다.

    Returns:
        [
            {
                "article": "제5조",
                "delegation_to": "대통령령",
                "context": "...대통령령으로 정한다."
            },
            ...
        ]
    """
    delegations = []
    current_article = ""

    for line in text.split("\n"):
        art_match = re.match(r"#{1,4}\s*(제\d+조(?:의\d+)?)", line)
        if art_match:
            current_article = art_match.group(1)
            continue

        patterns = [
            (r"대통령령으로\s+(?:정한다|정하는)", "대통령령"),
            (r"총리령으로\s+(?:정한다|정하는)", "총리령"),
            (r"부령으로\s+(?:정한다|정하는)", "부령"),
            (r"시행령으로\s+(?:정한다|정하는)", "시행령"),
        ]

        for pattern, target in patterns:
            if re.search(pattern, line):
                delegations.append({
                    "article": current_article,
                    "delegation_to": target,
                    "context": _truncate(line.strip(), 120),
                })

    return delegations


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _clean(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.split()).strip()


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _extract_frontmatter_field(content: str, field_name: str) -> str:
    """마크다운 frontmatter에서 특정 필드 값을 추출한다."""
    match = re.search(rf'^{field_name}:\s*"?([^"\n]+)"?\s*$', content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return ""
