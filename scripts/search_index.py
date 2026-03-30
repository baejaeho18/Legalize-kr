"""
검색 인덱스 생성기 (search_index.py)
────────────────────────────────────
법령 마크다운 파일을 스캔하여 검색 가능한 JSON 인덱스를 생성한다.

기능:
  1. 전문 검색 인덱스 (Full-text search index)
  2. 법령 메타데이터 카탈로그
  3. 조문별 인덱스 (개별 조문 검색)
  4. GitHub Pages 정적 검색 지원 (lunr.js / fuse.js 호환)
  5. 통계 대시보드 데이터
"""
import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import LAWS_DIR

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 법령 카탈로그 생성
# ──────────────────────────────────────────────
def build_catalog(repo_path: str) -> list[dict]:
    """
    전체 법령의 메타데이터 카탈로그를 생성한다.

    Returns:
        [
            {
                "id": "12345",
                "name": "개인정보 보호법",
                "type": "법률",
                "ministry": "개인정보보호위원회",
                "promul_date": "2024-01-15",
                "enforce_date": "2024-07-15",
                "revision_type": "일부개정",
                "article_count": 75,
                "file": "12345-개인정보_보호법.md",
            },
            ...
        ]
    """
    laws_path = Path(repo_path) / LAWS_DIR
    if not laws_path.exists():
        return []

    catalog = []

    for md_file in sorted(laws_path.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        meta = _parse_frontmatter(content)

        if not meta.get("법령명"):
            continue

        # 조문 수 계산
        article_count = len(re.findall(r"^####\s+제\d+조", content, re.MULTILINE))

        entry = {
            "id": str(meta.get("법령ID", "")),
            "serial_no": str(meta.get("법령일련번호", "")),
            "name": meta.get("법령명", ""),
            "type": meta.get("법령구분", ""),
            "ministry": meta.get("소관부처", ""),
            "promul_date": meta.get("공포일자", ""),
            "enforce_date": meta.get("시행일자", ""),
            "revision_type": meta.get("제개정구분", ""),
            "promul_no": meta.get("공포번호", ""),
            "article_count": article_count,
            "file": md_file.name,
        }

        # 국회 정보가 있으면 추가
        if "국회정보" in content:
            entry["has_assembly_info"] = True
            rst = _extract_field(content, "대표발의자")
            if rst:
                entry["rst_proposer"] = rst

        catalog.append(entry)

    logger.info(f"카탈로그 생성: {len(catalog)}건")
    return catalog


# ──────────────────────────────────────────────
# 전문 검색 인덱스 (lunr.js / fuse.js 호환)
# ──────────────────────────────────────────────
def build_search_index(repo_path: str) -> list[dict]:
    """
    전문 검색을 위한 인덱스를 생성한다.
    fuse.js / lunr.js에서 바로 사용 가능한 형식.

    각 항목:
    {
        "id": "12345-개인정보_보호법.md",
        "title": "개인정보 보호법",
        "body": "제1조(목적) 이 법은 개인정보의 처리 및...",  # 본문 요약
        "ministry": "개인정보보호위원회",
        "date": "2024-01-15",
    }
    """
    laws_path = Path(repo_path) / LAWS_DIR
    if not laws_path.exists():
        return []

    index = []

    for md_file in sorted(laws_path.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        meta = _parse_frontmatter(content)

        if not meta.get("법령명"):
            continue

        # 본문 추출 (frontmatter 제거)
        body = _extract_body(content)

        # 본문을 검색용으로 정리 (마크다운 문법 제거, 압축)
        clean_body = _clean_for_search(body)

        entry = {
            "id": md_file.name,
            "title": meta.get("법령명", ""),
            "body": clean_body[:5000],  # 최대 5000자
            "ministry": meta.get("소관부처", ""),
            "date": meta.get("공포일자", ""),
            "type": meta.get("법령구분", ""),
        }
        index.append(entry)

    logger.info(f"검색 인덱스 생성: {len(index)}건")
    return index


# ──────────────────────────────────────────────
# 조문별 인덱스
# ──────────────────────────────────────────────
def build_article_index(repo_path: str) -> list[dict]:
    """
    개별 조문 단위 검색 인덱스를 생성한다.

    각 항목:
    {
        "law_name": "개인정보 보호법",
        "article": "제2조",
        "title": "정의",
        "content": "이 법에서 사용하는 용어의 뜻은...",
        "file": "12345-개인정보_보호법.md",
    }
    """
    laws_path = Path(repo_path) / LAWS_DIR
    if not laws_path.exists():
        return []

    articles = []

    for md_file in sorted(laws_path.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        meta = _parse_frontmatter(content)
        law_name = meta.get("법령명", "")

        if not law_name:
            continue

        # 조문 단위로 분리
        body = _extract_body(content)
        article_blocks = _split_articles(body)

        for block in article_blocks:
            articles.append({
                "law_name": law_name,
                "article": block["number"],
                "title": block["title"],
                "content": block["content"][:2000],
                "file": md_file.name,
            })

    logger.info(f"조문별 인덱스 생성: {len(articles)}건")
    return articles


# ──────────────────────────────────────────────
# 통계 대시보드 데이터
# ──────────────────────────────────────────────
def build_stats(repo_path: str, catalog: Optional[list] = None) -> dict:
    """
    전체 법령 통계 데이터를 생성한다.

    Returns:
        {
            "total_laws": 2000,
            "by_type": {"법률": 1800, "대통령령": 200},
            "by_ministry": {"법무부": 150, ...},
            "by_revision": {"일부개정": 1500, ...},
            "by_year": {"2024": 50, "2023": 80, ...},
            "latest_update": "2024-01-15",
            "generated_at": "2024-01-16T12:00:00",
        }
    """
    if catalog is None:
        catalog = build_catalog(repo_path)

    stats = {
        "total_laws": len(catalog),
        "by_type": dict(Counter(e["type"] for e in catalog if e.get("type"))),
        "by_ministry": dict(Counter(e["ministry"] for e in catalog if e.get("ministry"))),
        "by_revision": dict(Counter(e["revision_type"] for e in catalog if e.get("revision_type"))),
        "by_year": {},
        "total_articles": sum(e.get("article_count", 0) for e in catalog),
        "latest_update": "",
        "generated_at": datetime.now().isoformat(),
    }

    # 연도별 통계
    year_counter = Counter()
    latest_date = ""
    for e in catalog:
        date = e.get("promul_date", "")
        if date and len(date) >= 4:
            year_counter[date[:4]] += 1
            if date > latest_date:
                latest_date = date

    stats["by_year"] = dict(sorted(year_counter.items()))
    stats["latest_update"] = latest_date

    # 가장 많은 조문을 가진 법률 Top 10
    top_by_articles = sorted(catalog, key=lambda x: x.get("article_count", 0), reverse=True)[:10]
    stats["top_by_article_count"] = [
        {"name": e["name"], "count": e["article_count"]}
        for e in top_by_articles
    ]

    return stats


# ──────────────────────────────────────────────
# 전체 인덱스 생성 및 저장
# ──────────────────────────────────────────────
def generate_all_indexes(repo_path: str) -> dict[str, str]:
    """
    모든 인덱스를 생성하고 metadata/ 디렉토리에 저장한다.

    Returns:
        생성된 파일 경로 dict
    """
    output_dir = Path(repo_path) / "metadata"
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    # 1. 카탈로그
    catalog = build_catalog(repo_path)
    catalog_path = output_dir / "catalog.json"
    _save_json(catalog, catalog_path)
    paths["catalog"] = str(catalog_path)

    # 2. 검색 인덱스
    search_idx = build_search_index(repo_path)
    search_path = output_dir / "search_index.json"
    _save_json(search_idx, search_path)
    paths["search_index"] = str(search_path)

    # 3. 조문별 인덱스
    article_idx = build_article_index(repo_path)
    article_path = output_dir / "article_index.json"
    _save_json(article_idx, article_path)
    paths["article_index"] = str(article_path)

    # 4. 통계
    stats = build_stats(repo_path, catalog)
    stats_path = output_dir / "stats.json"
    _save_json(stats, stats_path)
    paths["stats"] = str(stats_path)

    logger.info(f"전체 인덱스 생성 완료: {len(paths)}개 파일 → {output_dir}")
    return paths


# ──────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────
def _parse_frontmatter(content: str) -> dict:
    """YAML frontmatter를 간이 파싱한다."""
    meta = {}
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return meta

    for line in match.group(1).split("\n"):
        # 간단한 key: value 파싱
        kv = re.match(r'^(\S+):\s*"?([^"\n]*)"?\s*$', line)
        if kv:
            key = kv.group(1)
            value = kv.group(2).strip()
            # 숫자 변환
            if value.isdigit():
                meta[key] = int(value)
            else:
                meta[key] = value

    return meta


def _extract_body(content: str) -> str:
    """frontmatter를 제거한 본문을 추출한다."""
    match = re.match(r"^---\s*\n.*?\n---\s*\n", content, re.DOTALL)
    if match:
        return content[match.end():]
    return content


def _extract_field(content: str, field_name: str) -> str:
    """frontmatter에서 특정 필드를 추출한다."""
    match = re.search(rf'{field_name}:\s*"?([^"\n]+)"?', content)
    if match:
        return match.group(1).strip()
    return ""


def _clean_for_search(text: str) -> str:
    """마크다운을 검색용 평문으로 정리한다."""
    # 헤딩 마크 제거
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 빈 줄 압축
    text = re.sub(r"\n{2,}", "\n", text)
    # 특수문자 정리
    text = re.sub(r"[─━═]", "", text)
    return text.strip()


def _split_articles(body: str) -> list[dict]:
    """본문을 조문 단위로 분리한다."""
    articles = []
    # #### 제N조 (제목) 패턴으로 분리
    pattern = r"^####\s+(제\d+조(?:의\d+)?)\s*(?:\(([^)]+)\))?"
    current = None

    for line in body.split("\n"):
        match = re.match(pattern, line)
        if match:
            if current:
                articles.append(current)
            current = {
                "number": match.group(1),
                "title": match.group(2) or "",
                "content": "",
            }
        elif current:
            current["content"] += line + "\n"

    if current:
        articles.append(current)

    return articles


def _save_json(data, path: Path):
    """JSON 파일로 저장한다."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"  → {path.name} ({path.stat().st_size:,} bytes)")
