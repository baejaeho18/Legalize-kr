"""
Git 커밋 엔진 (committer.py)
────────────────────────────
법령 마크다운 파일을 Git 저장소에 커밋한다.

핵심 전략:
  - 각 법령 개정 = 하나의 Git 커밋
  - GIT_AUTHOR_DATE = 공포일자 (법적 효력 발생 기준)
  - 커밋 메시지에 메타데이터 포함 (소관부처, 의원 정보 등)
  - 시간순 정렬로 git log가 자연스러운 법령 이력이 됨

커밋 분리 원칙:
  - 법령 .md 커밋  → git log -- korea/*.md 에만 표시
  - 메타데이터 커밋 → "meta:" 접두사, metadata/ 디렉토리에 JSON 저장
  - git log -- korea/*.md  = 순수 법 개정 이력
  - git log -- metadata/   = 부가 데이터(판례·표결·상호참조) 이력
"""
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GitCommitter:
    """Git 저장소에 법령 파일을 커밋하는 엔진"""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self._ensure_repo()

    def _ensure_repo(self):
        """Git 저장소가 없으면 초기화한다."""
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            logger.info(f"Git 저장소 초기화: {self.repo_path}")
            self._run_git("init")
            self._run_git("config", "user.name", "legalize-kr")
            self._run_git("config", "user.email", "legalize-kr@github.com")

    def commit_law(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        commit_date: str,
        author_name: str = "legalize-kr",
        author_email: str = "legalize-kr@github.com",
    ) -> bool:
        """
        법령 파일을 저장소에 기록하고 커밋한다.

        Args:
            file_path: 저장소 내 상대 경로 (예: korea/12345-개인정보_보호법.md)
            content: 마크다운 내용
            commit_message: 커밋 메시지
            commit_date: ISO 8601 날짜 (예: 2024-01-15T12:00:00+09:00)
            author_name: Git author 이름
            author_email: Git author 이메일
        """
        full_path = self.repo_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # 기존 파일과 동일하면 스킵
        if full_path.exists():
            existing = full_path.read_text(encoding="utf-8")
            if existing == content:
                logger.debug(f"변경 없음, 스킵: {file_path}")
                return False

        # 파일 쓰기
        full_path.write_text(content, encoding="utf-8")

        # Git add
        self._run_git("add", file_path)

        # 변경 사항 확인
        result = self._run_git("diff", "--cached", "--name-only")
        if not result.stdout.strip():
            logger.debug(f"변경 없음 (diff 기준), 스킵: {file_path}")
            return False

        # Git commit (날짜 지정)
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = commit_date
        env["GIT_COMMITTER_DATE"] = commit_date
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_COMMITTER_NAME"] = author_name
        env["GIT_COMMITTER_EMAIL"] = author_email

        self._run_git("commit", "-m", commit_message, env=env)
        logger.info(f"커밋 완료: {file_path} ({commit_date[:10]})")
        return True

    def delete_law(
        self,
        file_path: str,
        commit_message: str,
        commit_date: str,
    ) -> bool:
        """법령 폐지 시 파일을 삭제하고 커밋한다."""
        full_path = self.repo_path / file_path
        if not full_path.exists():
            return False

        self._run_git("rm", file_path)

        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = commit_date
        env["GIT_COMMITTER_DATE"] = commit_date

        self._run_git("commit", "-m", commit_message, env=env)
        logger.info(f"삭제 커밋: {file_path} ({commit_date[:10]})")
        return True

    def commit_metadata(
        self,
        law_name: str,
        meta_type: str,
        data: dict,
        commit_message: str = "",
        author_name: str = "legalize-kr",
        author_email: str = "legalize-kr@github.com",
    ) -> bool:
        """
        부가 메타데이터(판례·표결·상호참조)를 JSON으로 저장하고 커밋한다.

        법령 .md 파일과 분리된 별도 커밋으로 기록된다.
        커밋 메시지에 "meta:" 접두사를 붙여 git log에서 구분 가능하게 한다.
        커밋 날짜는 현재 시각(수집 시점)을 사용한다.

        Args:
            law_name: 법령명 (JSON 파일명 및 커밋 메시지에 사용)
            meta_type: 메타데이터 종류 ("cases", "votes", "crossrefs")
            data: 저장할 딕셔너리 데이터
            commit_message: 커밋 메시지 (비어 있으면 자동 생성)
            author_name: Git author 이름 (판사명 등)
            author_email: Git author 이메일
        """
        if not data:
            return False

        # 파일 경로: metadata/{meta_type}/{법령명}.json
        safe_name = law_name.replace(" ", "_").replace("/", "_")
        safe_name = safe_name[:80]
        rel_path = f"metadata/{meta_type}/{safe_name}.json"
        full_path = self.repo_path / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # 공통 메타 필드 추가
        data["_law_name"] = law_name
        data["_meta_type"] = meta_type
        data["_updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00")

        new_content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

        # 기존 파일과 동일하면 스킵
        if full_path.exists():
            existing = full_path.read_text(encoding="utf-8")
            if existing == new_content:
                logger.debug(f"메타데이터 변경 없음, 스킵: {rel_path}")
                return False

        # 파일 쓰기
        full_path.write_text(new_content, encoding="utf-8")

        # Git add
        self._run_git("add", rel_path)

        # 변경 사항 확인
        result = self._run_git("diff", "--cached", "--name-only")
        if not result.stdout.strip():
            logger.debug(f"메타데이터 변경 없음 (diff 기준), 스킵: {rel_path}")
            return False

        # 커밋 메시지 생성
        type_labels = {
            "cases": "판례",
            "votes": "표결",
            "crossrefs": "상호참조",
        }
        type_label = type_labels.get(meta_type, meta_type)
        if not commit_message:
            commit_message = f"meta: {type_label} 갱신 — {law_name}"

        # 현재 시각으로 커밋 (공포일자가 아닌 수집 시점)
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00")
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = now
        env["GIT_COMMITTER_DATE"] = now
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_COMMITTER_NAME"] = author_name
        env["GIT_COMMITTER_EMAIL"] = author_email

        self._run_git("commit", "-m", commit_message, env=env)
        logger.info(f"메타 커밋: {rel_path}")
        return True

    def get_latest_commit_date(self, file_path: str) -> Optional[str]:
        """특정 파일의 최신 커밋 날짜를 반환한다."""
        try:
            result = self._run_git(
                "log", "-1", "--format=%aI", "--", file_path
            )
            date = result.stdout.strip()
            return date if date else None
        except Exception:
            return None

    def get_commit_count(self) -> int:
        """전체 커밋 수를 반환한다."""
        try:
            result = self._run_git("rev-list", "--count", "HEAD")
            return int(result.stdout.strip())
        except Exception:
            return 0

    def _run_git(self, *args, env=None) -> subprocess.CompletedProcess:
        """Git 명령어를 실행한다."""
        cmd = ["git", "-C", str(self.repo_path)] + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            if result.stderr and "fatal" in result.stderr:
                logger.error(f"Git 에러: {result.stderr.strip()}")
        return result
