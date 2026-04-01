"""
legalize-kr 로컬 설정 파일 (API 키)
────────────────────────────────────
이 파일을 복사하여 config_local.py를 만들고, 실제 API 키를 입력하세요.

    cp config_local.example.py config_local.py

config_local.py는 .gitignore에 등록되어 있어 Git에 포함되지 않습니다.
"""

# 국가법령정보 공동활용 API
# 1. 회원가입: https://open.law.go.kr/LSO/login.do
# 2. 마이페이지 > API인증값변경 에서 OC 값 확인
# 3. 마이페이지 > 사용자정보관리 에서 호출할 서버의 IP 주소 등록 필수!
# OC 값: 마이페이지에서 확인한 API 인증값 (이메일 전체가 아닌 인증값만)
LAW_API_OC = "your_oc_value"

# 열린국회정보 API (선택사항 — 없어도 법령 수집은 동작)
# 인증키 발급: https://open.assembly.go.kr/portal/openapi/main.do
ASSEMBLY_API_KEY = "9c1c8bc9e500480896f53ddb2a6fc23e"

# GitHub 저장소 URL (RSS 피드 등에 사용)
GITHUB_REPO_URL = "https://github.com/baejaeho18/legalize-kr"
