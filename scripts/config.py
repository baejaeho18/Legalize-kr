"""
legalize-kr 설정 파일
──────────────────────
API 키 설정 방법 (2가지 중 택1):

  1) config_local.py 파일 (권장)
     cp scripts/config_local.example.py scripts/config_local.py
     → config_local.py에 실제 키 입력 (.gitignore에 등록됨)

  2) 환경변수
     export LAW_API_OC="your_oc_value"
     export ASSEMBLY_API_KEY="your_key"

config.local.py가 있으면 해당 값을 우선 사용하고,
없으면 환경변수 → 기본값 순으로 fallback합니다.
"""
import os

# ──────────────────────────────────────────────
# config.local.py 로드 (있으면 덮어씌움)
# ──────────────────────────────────────────────
_local_config = {}
try:
    from config_local import *  # noqa: F401,F403
    import config_local as _lc
    _local_config = {k: v for k, v in vars(_lc).items() if not k.startswith("_")}
except ImportError:
    pass

def _get(key: str, env_key: str = "", default: str = "") -> str:
    """config.local.py → 환경변수 → 기본값 순으로 설정값을 가져온다."""
    if key in _local_config:
        return _local_config[key]
    if env_key:
        return os.environ.get(env_key, default)
    return default

# ──────────────────────────────────────────────
# 국가법령정보 공동활용 API (open.law.go.kr)
# ──────────────────────────────────────────────
LAW_API_BASE = "http://www.law.go.kr/DRF"
LAW_API_OC = _get("LAW_API_OC", "LAW_API_OC", "test")

# 법령 검색 API
LAW_SEARCH_URL = f"{LAW_API_BASE}/lawSearch.do"
# 법령 상세 API
LAW_SERVICE_URL = f"{LAW_API_BASE}/lawService.do"

# ──────────────────────────────────────────────
# 열린국회정보 API (open.assembly.go.kr)
# ──────────────────────────────────────────────
ASSEMBLY_API_KEY = _get("ASSEMBLY_API_KEY", "ASSEMBLY_API_KEY", "")
ASSEMBLY_API_BASE = "https://open.assembly.go.kr/portal/openapi"

# 국회의원 발의법률안 서비스코드
ASSEMBLY_BILL_SVC = "nzmimeepazxkubdpn"

# 본회의 표결 정보 서비스코드
VOTE_RESULT_SVC = _get("VOTE_RESULT_SVC", "VOTE_RESULT_SVC", "pvoterncwbillgatljpazxkubdpn")

# 의원별 표결 내역 서비스코드
VOTE_MEMBER_SVC = _get("VOTE_MEMBER_SVC", "VOTE_MEMBER_SVC", "noloaborlsonaaborlsnaapamqyz")

# ──────────────────────────────────────────────
# 프로젝트 설정
# ──────────────────────────────────────────────
# Git repo 내 법률 파일 저장 경로
LAWS_DIR = "korea"

# 영문 법령 저장 경로
LAWS_EN_DIR = "korea-en"

# 메타데이터 저장 경로
METADATA_DIR = "metadata"

# 피드 저장 경로
FEEDS_DIR = "feeds"

# 법령 종류 코드
LAW_KINDS = {
    "법률": "A",
    "대통령령": "B",
    "총리령": "C",
    "부령": "D",
}

# 제개정 구분 코드
REVISION_TYPES = {
    "300201": "제정",
    "300202": "일부개정",
    "300203": "전부개정",
    "300204": "폐지",
    "300205": "폐지제정",
    "300206": "일괄개정",
    "300207": "일괄폐지",
    "300208": "기타",
    "300209": "타법개정",
    "300210": "타법폐지",
}

# API 요청 간 대기 시간 (초) — 서버 부하 방지
REQUEST_DELAY = float(_get("REQUEST_DELAY", "REQUEST_DELAY", "0.5"))

# 한 번에 가져올 법령 수
PAGE_SIZE = 100

# 로그 레벨
LOG_LEVEL = _get("LOG_LEVEL", "LOG_LEVEL", "INFO")

# GitHub 저장소 URL (RSS 피드 등에 사용)
GITHUB_REPO_URL = _get(
    "GITHUB_REPO_URL", "GITHUB_REPO_URL",
    "https://github.com/YOUR_USERNAME/legalize-kr",
)
