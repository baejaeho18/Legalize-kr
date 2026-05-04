"""
legalize-dev 본 프로젝트 Adapter (adapter.py)
───────────────────────────────────────────────
legalize-dev/legalize-es 본 프로젝트의 다국가 구조에 맞게
한국 법령 수집기를 4개의 표준 인터페이스로 래핑한다.

legalize-dev 프로젝트가 요구하는 인터페이스:
  1. LawFetcher    — 법령 목록 및 상세 수집
  2. LawParser     — 원시 데이터를 구조화된 법령 객체로 파싱
  3. LawFormatter  — 구조화된 법령을 마크다운으로 변환
  4. LawCommitter  — Git 커밋 생성

이 adapter를 통해 legalize-kr을 legalize-dev의
공식 한국 모듈로 PR할 수 있다.

사용법:
  from adapter import KoreaLawAdapter
  adapter = KoreaLawAdapter()
  laws = adapter.fetch_laws(kind="법률")
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator, Optional

# legalize-kr 내부 모듈
from config import LAW_KINDS
from fetcher import (
    LawSummary,
    LawDetail,
    LawArticle,
    fetch_all_laws,
    fetch_law_detail,
    fetch_law_history,
    fetch_law_list,
)
from converter import (
    law_to_markdown,
    generate_filename,
    generate_commit_message,
    get_commit_date,
)
from committer import GitCommitter
from assembly import build_assembly_metadata

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 표준 인터페이스 정의 (legalize-dev 호환)
# ──────────────────────────────────────────────
class BaseLawFetcher(ABC):
    """법령 수집 인터페이스"""

    @abstractmethod
    def fetch_law_list(
        self, kind: str = "", page: int = 1, page_size: int = 100,
    ) -> tuple[list[dict], int]:
        """법령 목록 조회. Returns: (법령 목록, 전체 건수)"""
        ...

    @abstractmethod
    def fetch_law_detail(self, law_id: Any) -> Optional[dict]:
        """법령 상세 조회"""
        ...

    @abstractmethod
    def fetch_law_history(self, law_id: Any) -> list[dict]:
        """법령 연혁 조회"""
        ...

    @abstractmethod
    def fetch_recent_changes(
        self, since: datetime, until: Optional[datetime] = None,
    ) -> list[dict]:
        """최근 변경 법령 조회"""
        ...


class BaseLawParser(ABC):
    """법령 파싱 인터페이스"""

    @abstractmethod
    def parse(self, raw_data: dict) -> dict:
        """원시 데이터 → 구조화된 법령 객체"""
        ...

    @abstractmethod
    def get_metadata(self, parsed: dict) -> dict:
        """법령 메타데이터 추출"""
        ...


class BaseLawFormatter(ABC):
    """법령 포맷팅 인터페이스"""

    @abstractmethod
    def to_markdown(self, parsed: dict) -> str:
        """구조화된 법령 → 마크다운"""
        ...

    @abstractmethod
    def get_filename(self, parsed: dict) -> str:
        """법령 파일명 생성"""
        ...


class BaseLawCommitter(ABC):
    """Git 커밋 인터페이스"""

    @abstractmethod
    def commit(
        self,
        file_path: str,
        content: str,
        message: str,
        date: str,
    ) -> bool:
        """커밋 생성"""
        ...


# ──────────────────────────────────────────────
# 한국 구현체
# ──────────────────────────────────────────────
class KoreaLawFetcher(BaseLawFetcher):
    """한국 국가법령정보 API 기반 수집기"""

    COUNTRY = "korea"
    COUNTRY_CODE = "KR"
    SOURCE_NAME = "국가법령정보 공동활용"
    SOURCE_URL = "https://open.law.go.kr"

    def fetch_law_list(
        self, kind: str = "", page: int = 1, page_size: int = 100,
    ) -> tuple[list[dict], int]:
        law_kind_code = LAW_KINDS.get(kind, "")
        summaries, total = fetch_law_list(
            page=page, display=page_size, law_kind=law_kind_code,
        )
        return [self._summary_to_dict(s) for s in summaries], total

    def fetch_law_detail(self, law_id: Any) -> Optional[dict]:
        detail = fetch_law_detail(int(law_id))
        if not detail:
            return None
        return self._detail_to_dict(detail)

    def fetch_law_history(self, law_id: Any) -> list[dict]:
        history = fetch_law_history(int(law_id))
        return [self._summary_to_dict(s) for s in history]

    def fetch_recent_changes(
        self, since: datetime, until: Optional[datetime] = None,
    ) -> list[dict]:
        if until is None:
            until = datetime.now()

        date_from = since.strftime("%Y%m%d")
        date_to = until.strftime("%Y%m%d")

        all_laws = []
        page = 1
        while True:
            summaries, total = fetch_law_list(
                page=page,
                promul_date_from=date_from,
                promul_date_to=date_to,
            )
            all_laws.extend([self._summary_to_dict(s) for s in summaries])
            if len(all_laws) >= total or not summaries:
                break
            page += 1

        return all_laws

    def _summary_to_dict(self, s: LawSummary) -> dict:
        return {
            "id": s.law_id,
            "serial_no": s.serial_no,
            "name": s.name,
            "short_name": s.short_name,
            "promulgation_date": s.promul_date,
            "promulgation_no": s.promul_no,
            "enforcement_date": s.enforce_date,
            "revision_type": s.revision_type,
            "ministry": s.ministry,
            "law_type": s.law_type,
            "country": self.COUNTRY,
        }

    def _detail_to_dict(self, d: LawDetail) -> dict:
        return {
            "id": d.law_id,
            "serial_no": d.serial_no,
            "name": d.name,
            "promulgation_date": d.promul_date,
            "promulgation_no": d.promul_no,
            "enforcement_date": d.enforce_date,
            "revision_type": d.revision_type,
            "ministry": d.ministry,
            "law_type": d.law_type,
            "preamble": d.preamble,
            "articles": [
                {
                    "number": a.number,
                    "title": a.title,
                    "content": a.content,
                    "paragraphs": a.paragraphs,
                }
                for a in d.articles
            ],
            "addenda": d.addenda,
            "chapter_structure": d.chapter_structure,
            "country": self.COUNTRY,
            "_raw_detail": d,  # 내부 사용용
        }


class KoreaLawParser(BaseLawParser):
    """한국 법령 파서"""

    def __init__(self, include_assembly: bool = True):
        self.include_assembly = include_assembly

    def parse(self, raw_data: dict) -> dict:
        """이미 구조화된 dict를 반환 (한국 API는 XML이 구조적)"""
        parsed = dict(raw_data)

        # 국회 메타데이터 추가
        if self.include_assembly:
            detail = raw_data.get("_raw_detail")
            if detail and detail.revision_type in ["제정", "일부개정", "전부개정"]:
                try:
                    assembly_meta = build_assembly_metadata(detail.name)
                    parsed["assembly_metadata"] = assembly_meta
                except Exception as e:
                    logger.warning(f"국회 메타데이터 실패: {e}")

        return parsed

    def get_metadata(self, parsed: dict) -> dict:
        return {
            "name": parsed.get("name", ""),
            "country": "korea",
            "country_code": "KR",
            "law_type": parsed.get("law_type", ""),
            "promulgation_date": parsed.get("promulgation_date", ""),
            "enforcement_date": parsed.get("enforcement_date", ""),
            "revision_type": parsed.get("revision_type", ""),
            "ministry": parsed.get("ministry", ""),
            "article_count": len(parsed.get("articles", [])),
        }


class KoreaLawFormatter(BaseLawFormatter):
    """한국 법령 마크다운 포맷터"""

    def to_markdown(self, parsed: dict) -> str:
        detail = parsed.get("_raw_detail")
        if not detail:
            return ""
        assembly_meta = parsed.get("assembly_metadata")
        return law_to_markdown(detail, assembly_meta)

    def get_filename(self, parsed: dict) -> str:
        detail = parsed.get("_raw_detail")
        if not detail:
            serial = parsed.get("serial_no", 0)
            name = parsed.get("name", "unknown").replace(" ", "_")
            return f"{serial}-{name}.md"
        return generate_filename(detail)


class KoreaLawCommitter(BaseLawCommitter):
    """한국 법령 Git 커밋터"""

    def __init__(self, repo_path: str):
        self.git = GitCommitter(repo_path)

    def commit(
        self,
        file_path: str,
        content: str,
        message: str,
        date: str,
    ) -> bool:
        return self.git.commit_law(
            file_path=file_path,
            content=content,
            commit_message=message,
            commit_date=date,
        )


# ──────────────────────────────────────────────
# 통합 Adapter (편의 클래스)
# ──────────────────────────────────────────────
class KoreaLawAdapter:
    """
    legalize-dev 호환 통합 어댑터.

    사용법:
        adapter = KoreaLawAdapter(repo_path="/path/to/repo")

        # 법령 목록 가져오기
        laws, total = adapter.fetch_laws(kind="법률")

        # 법령 처리 (수집 → 파싱 → 포맷 → 커밋)
        for law in laws:
            adapter.process_law(law)
    """

    COUNTRY = "korea"
    COUNTRY_CODE = "KR"
    LANGUAGE = "ko"
    SOURCE = "국가법령정보 공동활용 + 열린국회정보"

    def __init__(
        self,
        repo_path: str = ".",
        include_assembly: bool = True,
    ):
        self.fetcher = KoreaLawFetcher()
        self.parser = KoreaLawParser(include_assembly=include_assembly)
        self.formatter = KoreaLawFormatter()
        self.committer = KoreaLawCommitter(repo_path)
        self.laws_dir = "korea"

    def fetch_laws(
        self, kind: str = "", page: int = 1, page_size: int = 100,
    ) -> tuple[list[dict], int]:
        """법령 목록 조회"""
        return self.fetcher.fetch_law_list(kind, page, page_size)

    def process_law(self, law_dict: dict) -> bool:
        """
        단일 법령을 전체 파이프라인으로 처리한다.
        fetch_detail → parse → format → commit
        """
        serial_no = law_dict.get("serial_no")
        if not serial_no:
            return False

        # 상세 조회
        detail_dict = self.fetcher.fetch_law_detail(serial_no)
        if not detail_dict:
            return False

        # 파싱 (국회 메타데이터 포함)
        parsed = self.parser.parse(detail_dict)

        # 마크다운 변환
        markdown = self.formatter.to_markdown(parsed)
        if not markdown:
            return False

        # 파일명 및 커밋 정보
        filename = self.formatter.get_filename(parsed)
        file_path = f"{self.laws_dir}/{filename}"

        detail = parsed.get("_raw_detail")
        commit_msg = generate_commit_message(
            detail, parsed.get("assembly_metadata"),
        )
        commit_date = get_commit_date(detail)

        # 커밋
        return self.committer.commit(file_path, markdown, commit_msg, commit_date)

    @classmethod
    def get_info(cls) -> dict:
        """어댑터 메타 정보 (legalize-dev 등록용)"""
        return {
            "country": cls.COUNTRY,
            "country_code": cls.COUNTRY_CODE,
            "language": cls.LANGUAGE,
            "source": cls.SOURCE,
            "maintainer": "legalize-kr contributors",
            "api_docs": [
                "https://open.law.go.kr/LSO/openApi/guideResult.do",
                "https://open.assembly.go.kr/portal/openapi/main.do",
            ],
            "features": [
                "law_text",           # 법률 본문
                "revision_history",   # 개정 이력
                "legislator_info",    # 발의 의원 정보
                "vote_records",       # 표결 기록
                "court_cases",        # 판례 연동
                "english_translation", # 영문 법령
                "subordinate_laws",   # 하위법령
                "cross_references",   # 상호참조
            ],
        }
