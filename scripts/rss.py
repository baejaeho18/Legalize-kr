"""
RSS/Atom 피드 생성기 (rss.py)
─────────────────────────────
법령 변경사항을 RSS 및 Atom 피드로 제공한다.

기능:
  - Git 커밋 로그 기반 RSS 피드 생성
  - 법령 종류별/부처별 필터링 피드
  - Atom 1.0 형식 지원
  - GitHub Pages 배포용 정적 XML 생성
"""
import logging
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring, ElementTree
import xml.dom.minidom

from config import LAWS_DIR

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────
class FeedEntry:
    """피드 항목"""
    def __init__(
        self,
        title: str = "",
        link: str = "",
        description: str = "",
        pub_date: str = "",       # ISO 8601
        author: str = "",
        guid: str = "",
        category: str = "",
        law_name: str = "",
        revision_type: str = "",
        ministry: str = "",
    ):
        self.title = title
        self.link = link
        self.description = description
        self.pub_date = pub_date
        self.author = author
        self.guid = guid
        self.category = category
        self.law_name = law_name
        self.revision_type = revision_type
        self.ministry = ministry


# ──────────────────────────────────────────────
# Git 로그에서 피드 항목 추출
# ──────────────────────────────────────────────
def extract_entries_from_git(
    repo_path: str,
    max_entries: int = 50,
    base_url: str = "https://github.com/YOUR_USERNAME/legalize-kr",
) -> list[FeedEntry]:
    """
    Git 커밋 로그에서 RSS 피드 항목을 추출한다.
    """
    cmd = [
        "git", "-C", repo_path,
        "log",
        f"--max-count={max_entries}",
        "--format=%H|%aI|%s|%b",
        "--", f"{LAWS_DIR}/*.md",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"git log 실패: {result.stderr}")
            return []
    except Exception as e:
        logger.error(f"Git 명령 실행 실패: {e}")
        return []

    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue

        parts = line.split("|", 3)
        if len(parts) < 3:
            continue

        commit_hash = parts[0]
        date = parts[1]
        subject = parts[2]
        body = parts[3] if len(parts) > 3 else ""

        # 커밋 메시지에서 메타데이터 추출
        revision_type = ""
        law_name = ""
        ministry = ""

        # "일부개정: 개인정보 보호법" 형식 파싱
        match = re.match(r"^(\S+):\s+(.+)$", subject)
        if match:
            revision_type = match.group(1)
            law_name = match.group(2)

        # 본문에서 소관부처 추출
        ministry_match = re.search(r"소관부처:\s+(.+)", body)
        if ministry_match:
            ministry = ministry_match.group(1).strip()

        # 변경된 파일 목록
        file_cmd = [
            "git", "-C", repo_path,
            "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash,
        ]
        try:
            file_result = subprocess.run(file_cmd, capture_output=True, text=True)
            changed_files = [
                f for f in file_result.stdout.strip().split("\n")
                if f.endswith(".md")
            ]
        except Exception:
            changed_files = []

        # 피드 항목 구성
        link = f"{base_url}/commit/{commit_hash}"
        description = body.replace("\n", "<br/>") if body else subject

        if changed_files:
            description += "<br/><br/>변경 파일:<br/>"
            for cf in changed_files[:5]:
                description += f"- {cf}<br/>"

        entry = FeedEntry(
            title=subject,
            link=link,
            description=description,
            pub_date=date,
            author="legalize-kr",
            guid=commit_hash,
            category=revision_type,
            law_name=law_name,
            revision_type=revision_type,
            ministry=ministry,
        )
        entries.append(entry)

    logger.info(f"RSS 피드 항목 {len(entries)}건 추출")
    return entries


# ──────────────────────────────────────────────
# RSS 2.0 피드 생성
# ──────────────────────────────────────────────
def generate_rss(
    entries: list[FeedEntry],
    title: str = "legalize-kr — 대한민국 법령 변경 추적",
    description: str = "대한민국 법률의 모든 개정 이력을 Git으로 추적합니다",
    link: str = "https://github.com/YOUR_USERNAME/legalize-kr",
    language: str = "ko",
) -> str:
    """
    RSS 2.0 형식의 XML을 생성한다.
    """
    rss = Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = title
    SubElement(channel, "description").text = description
    SubElement(channel, "link").text = link
    SubElement(channel, "language").text = language
    SubElement(channel, "lastBuildDate").text = datetime.now(
        timezone.utc
    ).strftime("%a, %d %b %Y %H:%M:%S +0000")
    SubElement(channel, "generator").text = "legalize-kr"

    # Atom self link
    atom_link = SubElement(channel, "atom:link")
    atom_link.set("href", f"{link}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for entry in entries:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = entry.title
        SubElement(item, "link").text = entry.link
        SubElement(item, "description").text = entry.description
        SubElement(item, "pubDate").text = _to_rss_date(entry.pub_date)
        SubElement(item, "guid").text = entry.guid
        if entry.category:
            SubElement(item, "category").text = entry.category
        if entry.author:
            SubElement(item, "author").text = entry.author

    return _pretty_xml(rss)


# ──────────────────────────────────────────────
# Atom 1.0 피드 생성
# ──────────────────────────────────────────────
def generate_atom(
    entries: list[FeedEntry],
    title: str = "legalize-kr — 대한민국 법령 변경 추적",
    subtitle: str = "대한민국 법률의 모든 개정 이력을 Git으로 추적합니다",
    base_url: str = "https://github.com/YOUR_USERNAME/legalize-kr",
    author_name: str = "legalize-kr",
) -> str:
    """
    Atom 1.0 형식의 XML을 생성한다.
    """
    ns = "http://www.w3.org/2005/Atom"
    feed = Element("feed", xmlns=ns)

    SubElement(feed, "title").text = title
    SubElement(feed, "subtitle").text = subtitle
    SubElement(feed, "id").text = base_url

    link_self = SubElement(feed, "link")
    link_self.set("href", f"{base_url}/atom.xml")
    link_self.set("rel", "self")

    link_alt = SubElement(feed, "link")
    link_alt.set("href", base_url)
    link_alt.set("rel", "alternate")

    SubElement(feed, "updated").text = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    author = SubElement(feed, "author")
    SubElement(author, "name").text = author_name

    SubElement(feed, "generator").text = "legalize-kr"

    for entry_data in entries:
        entry = SubElement(feed, "entry")
        SubElement(entry, "title").text = entry_data.title

        link = SubElement(entry, "link")
        link.set("href", entry_data.link)

        SubElement(entry, "id").text = entry_data.guid or entry_data.link
        SubElement(entry, "updated").text = _to_atom_date(entry_data.pub_date)
        SubElement(entry, "summary").text = _strip_html(entry_data.description)

        if entry_data.category:
            cat = SubElement(entry, "category")
            cat.set("term", entry_data.category)

    return _pretty_xml(feed)


# ──────────────────────────────────────────────
# 필터링 피드 생성
# ──────────────────────────────────────────────
def generate_filtered_feeds(
    entries: list[FeedEntry],
    output_dir: str,
    base_url: str = "https://github.com/YOUR_USERNAME/legalize-kr",
):
    """
    법령 종류별, 부처별 필터링 피드를 생성한다.

    생성 파일:
      feeds/
        feed.xml          — 전체 피드 (RSS)
        atom.xml          — 전체 피드 (Atom)
        by-type/
          제정.xml
          일부개정.xml
          전부개정.xml
        by-ministry/
          법무부.xml
          행정안전부.xml
    """
    output = Path(output_dir) / "feeds"
    output.mkdir(parents=True, exist_ok=True)

    # 전체 피드
    rss_xml = generate_rss(entries, link=base_url)
    (output / "feed.xml").write_text(rss_xml, encoding="utf-8")

    atom_xml = generate_atom(entries, base_url=base_url)
    (output / "atom.xml").write_text(atom_xml, encoding="utf-8")

    # 종류별 피드
    by_type_dir = output / "by-type"
    by_type_dir.mkdir(exist_ok=True)

    type_groups = {}
    for e in entries:
        if e.revision_type:
            type_groups.setdefault(e.revision_type, []).append(e)

    for rtype, rtype_entries in type_groups.items():
        safe_name = rtype.replace("/", "_")
        rss = generate_rss(
            rtype_entries,
            title=f"legalize-kr — {rtype}",
            link=base_url,
        )
        (by_type_dir / f"{safe_name}.xml").write_text(rss, encoding="utf-8")

    # 부처별 피드
    by_ministry_dir = output / "by-ministry"
    by_ministry_dir.mkdir(exist_ok=True)

    ministry_groups = {}
    for e in entries:
        if e.ministry:
            ministry_groups.setdefault(e.ministry, []).append(e)

    for ministry, ministry_entries in ministry_groups.items():
        safe_name = ministry.replace("/", "_").replace(" ", "_")
        rss = generate_rss(
            ministry_entries,
            title=f"legalize-kr — {ministry}",
            link=base_url,
        )
        (by_ministry_dir / f"{safe_name}.xml").write_text(rss, encoding="utf-8")

    total_files = 2 + len(type_groups) + len(ministry_groups)
    logger.info(f"피드 {total_files}개 생성 → {output}")


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _to_rss_date(iso_date: str) -> str:
    """ISO 8601 → RFC 822 (RSS 형식)"""
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    except (ValueError, AttributeError):
        return iso_date


def _to_atom_date(iso_date: str) -> str:
    """ISO 8601 정규화"""
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    except (ValueError, AttributeError):
        return iso_date


def _strip_html(text: str) -> str:
    """HTML 태그 제거"""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text)


def _pretty_xml(element: Element) -> str:
    """XML을 보기 좋게 포맷팅"""
    raw = tostring(element, encoding="unicode", xml_declaration=True)
    dom = xml.dom.minidom.parseString(raw)
    return dom.toprettyxml(indent="  ", encoding=None)
