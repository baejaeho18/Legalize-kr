# Legalize — 대한민국

대한민국 법률을 Git으로 추적합니다. **모든 법률은 마크다운 파일, 모든 개정은 커밋.**

[legalize-es](https://github.com/legalize-dev/legalize-es) (스페인 법률 Git 추적)에서 영감을 받아, 대한민국의 공개 법령 API를 활용하여 동일한 구조를 구현했습니다.

## 빠른 시작

```bash
git clone https://github.com/YOUR_USERNAME/legalize-kr.git
cd legalize-kr

# 개인정보 보호법의 현재 내용 확인
cat korea/*개인정보_보호법.md

# 개인정보 보호법의 전체 개정 이력 확인
git log --oneline -- korea/*개인정보_보호법.md

# 가장 최근 개정에서 무엇이 바뀌었는지 확인
git log -1 -p -- korea/*개인정보_보호법.md

# 특정 시점의 법률 내용 확인
git log --after="2020-01-01" --before="2020-12-31" -- korea/*개인정보_보호법.md
```

## 데이터 소스

| 소스 | 제공 데이터 | URL |
|------|-----------|-----|
| 국가법령정보 공동활용 | 법령 본문, 조문, 공포일, 시행일, 개정이력, 소관부처 | [open.law.go.kr](https://open.law.go.kr) |
| 열린국회정보 | 발의법률안, 대표발의자, 공동발의자, 표결 결과 | [open.assembly.go.kr](https://open.assembly.go.kr) |
| 국가법령정보 판례 API | 판례 검색, 판시사항, 참조조문, 선고일자 | [law.go.kr](https://www.law.go.kr) |
| 국가법령정보 영문법령 | 영문 번역 법령 본문 | [elaw.klri.re.kr](https://elaw.klri.re.kr) |

## 직접 실행하기

### 1. 환경 설정

```bash
pip install -r requirements.txt
```

### 2. API 키 설정

```bash
# 국가법령정보 API (필수)
# open.law.go.kr 회원가입 후, 이메일 ID가 OC 값
export LAW_API_OC="your_email_id"

# 열린국회정보 API (선택 — 발의의원/표결 정보가 필요한 경우)
# open.assembly.go.kr에서 인증키 발급
export ASSEMBLY_API_KEY="your_api_key"
```

### 3. 실행

```bash
# 테스트: 5건만 처리
python scripts/main.py --init --kind 법률 --limit 5 --repo .

# 전체 법률 초기 구축
python scripts/main.py --init --kind 법률 --repo .

# 전체 법률 + 국회 메타데이터 + 표결 정보 포함
python scripts/main.py --init --kind 법률 --assembly --votes --repo .

# 특정 법령의 전체 연혁 재구축
python scripts/main.py --history --law "형법" --repo .

# 최근 7일 변경사항 업데이트
python scripts/main.py --update --days 7 --assembly --votes --repo .

# 판례 수집
python scripts/main.py --cases --law "개인정보 보호법" --repo .

# 영문 법령 수집
python scripts/main.py --english --limit 10 --repo .

# 상호참조 그래프 생성
python scripts/main.py --crossref --repo .

# RSS/Atom 피드 생성
python scripts/main.py --feed --repo .

# 검색 인덱스 생성
python scripts/main.py --index --repo .

# 후처리 전체 (피드 + 인덱스 + 상호참조)
python scripts/main.py --postprocess --repo .

# 통계 확인
python scripts/main.py --stats --repo .
```

## 파일 구조

```
legalize-kr/
├── korea/                          # 한글 법령 마크다운
│   ├── 12345-개인정보_보호법.md
│   ├── 12346-형법.md
│   └── ...
├── korea-en/                       # 영문 법령 마크다운
│   ├── 99999-Personal_Information_Protection_Act.md
│   └── ...
├── metadata/                       # 메타데이터 (자동 생성)
│   ├── catalog.json                # 법령 카탈로그
│   ├── search_index.json           # 전문 검색 인덱스
│   ├── article_index.json          # 조문별 인덱스
│   ├── stats.json                  # 통계 데이터
│   ├── reference_graph.json        # 법률 간 상호참조 그래프
│   ├── subordinate_map.json        # 하위법령 매핑
│   └── cases/                      # 판례 데이터
│       ├── 개인정보_보호법.json
│       └── ...
├── feeds/                          # RSS/Atom 피드 (자동 생성)
│   ├── feed.xml                    # 전체 RSS
│   ├── atom.xml                    # 전체 Atom
│   ├── by-type/                    # 제개정 종류별
│   │   ├── 일부개정.xml
│   │   └── ...
│   └── by-ministry/                # 소관부처별
│       ├── 법무부.xml
│       └── ...
├── scripts/                        # 수집/변환/커밋 스크립트
│   ├── config.py                   # 설정
│   ├── fetcher.py                  # 국가법령정보 API 수집
│   ├── assembly.py                 # 열린국회정보 API 수집
│   ├── vote.py                     # 본회의 표결 기록 수집
│   ├── courtcase.py                # 판례 연동
│   ├── english.py                  # 영문 법령 수집
│   ├── crossref.py                 # 상호참조 + 하위법령 연결
│   ├── converter.py                # XML → Markdown 변환
│   ├── committer.py                # Git 커밋 엔진
│   ├── rss.py                      # RSS/Atom 피드 생성
│   ├── search_index.py             # 검색 인덱스 생성
│   ├── adapter.py                  # legalize-dev 호환 어댑터
│   └── main.py                     # 메인 오케스트레이터
├── .github/workflows/update.yml    # 매일 자동 업데이트
├── requirements.txt
└── README.md
```

## 마크다운 파일 형식

각 법령 파일은 YAML frontmatter에 메타데이터를 포함합니다:

```markdown
---
법령명: "개인정보 보호법"
법령구분: "법률"
법령ID: 12345
공포일자: "2024-01-15"
공포번호: "제20000호"
시행일자: "2024-07-15"
제개정구분: "일부개정"
소관부처: "개인정보보호위원회"
국회정보:
  의안명: "개인정보 보호법 일부개정법률안"
  제안일: "2023-09-20"
  대표발의자: "홍길동"
  소관위원회: "행정안전위원회"
  처리결과: "원안가결"
  발의의원:
    - "홍길동 [더불어민주당] (대표)"
    - "김철수 [국민의힘]"
표결정보:
  표결일: "2024-01-10"
  결과: "가결"
  재적: 299
  찬성: 240
  반대: 35
  기권: 10
  불참: 14
  정당별:
    더불어민주당: "찬성 150, 반대 5, 기권 3"
    국민의힘: "찬성 85, 반대 28, 기권 5"
하위법령:
  - 명칭: "개인정보 보호법 시행령"
    유형: "시행령"
  - 명칭: "개인정보 보호법 시행규칙"
    유형: "시행규칙"
참조법률:
  - "형법"
  - "정보통신망법"
관련판례:
  - 사건번호: "2023다12345"
    법원: "대법원"
    선고일: "2023-06-15"
    요지: "개인정보 유출에 대한 손해배상 책임..."
---

# 개인정보 보호법

## 제1장 총칙

#### 제1조 (목적)
이 법은 개인정보의 처리 및 보호에 관한 사항을 정함으로써...

<!-- 관련 판례: 2023다12345, 2022다67890 -->
```

## Git 커밋 형식

커밋 메시지에는 개정 메타데이터가 포함됩니다:

```
일부개정: 개인정보 보호법

공포일자: 2024-01-15
공포번호: 제20000호
시행일자: 2024-07-15
소관부처: 개인정보보호위원회

[국회 정보]
대표발의: 홍길동의원
제안자: 홍길동의원 등 12인
소관위원회: 행정안전위원회
처리결과: 원안가결

[표결 정보]
찬성 240 / 반대 35 / 기권 10 / 불참 14
결과: 가결
```

`git log`로 법령의 전체 개정 이력을 자연스럽게 추적할 수 있습니다:

```bash
$ git log --oneline -- korea/*개인정보_보호법.md
a1b2c3d 일부개정: 개인정보 보호법 (2024-01-15)
d4e5f6g 일부개정: 개인정보 보호법 (2023-03-14)
h7i8j9k 전부개정: 개인정보 보호법 (2020-08-05)
l0m1n2o 제정: 개인정보 보호법 (2011-03-29)
```

## 확장 기능

### 판례 연동
법률의 조문별로 관련 대법원 판례를 자동 연결합니다. 국가법령정보 판례 API를 통해 판례번호, 선고일, 판시사항, 참조조문을 수집하고, 각 조문 하단에 HTML 주석으로 관련 판례를 기록합니다.

### 표결 기록
열린국회정보 API를 통해 본회의 표결 결과(찬/반/기권/불참)와 정당별 표결 현황을 수집합니다. 이를 통해 어떤 법이 어떤 표결 분포로 통과되었는지 추적할 수 있습니다.

### 영문 법령
국가법령정보 영문법령 API를 통해 영문 번역본을 별도 디렉토리(`korea-en/`)에 수집합니다. 한글 법령과 1:1 매핑되어 이중 언어 참조가 가능합니다.

### 상호참조 그래프
법률 본문에서 `「○○법」 제○조` 패턴을 자동 추출하여 법률 간 참조 관계 그래프를 생성합니다. 하위법령(시행령/시행규칙) 매핑도 포함됩니다.

### RSS/Atom 피드
법령 변경사항을 RSS/Atom 피드로 구독할 수 있습니다. 전체 피드 외에 제개정 종류별, 소관부처별 필터링 피드도 제공됩니다.

### 검색 인덱스
정적 JSON 인덱스를 생성하여 GitHub Pages 등에서 fuse.js/lunr.js 기반 클라이언트 검색을 구현할 수 있습니다. 법령별, 조문별 인덱스를 모두 지원합니다.

### legalize-dev 호환 어댑터
`adapter.py`를 통해 legalize-dev 본 프로젝트의 4개 표준 인터페이스(Fetcher/Parser/Formatter/Committer)를 구현합니다. 이를 통해 legalize-kr을 legalize-dev의 공식 한국 모듈로 기여할 수 있습니다.

## GitHub Actions 자동화

`.github/workflows/update.yml`이 매일 한국 시간 06:00에 자동 실행되어:

1. 최근 7일간 공포된 법령을 국가법령정보 API에서 조회
2. 변경된 법령의 조문을 마크다운으로 변환
3. 열린국회정보 API에서 발의 의원 정보와 표결 결과를 조회
4. 공포일자를 커밋 날짜로 하여 Git 커밋 생성
5. 상호참조 그래프, RSS 피드, 검색 인덱스를 갱신
6. 자동으로 push

### GitHub Secrets 설정

| Secret 이름 | 설명 | 필수 |
|-------------|------|------|
| `LAW_API_OC` | 국가법령정보 API의 OC 값 (이메일 ID) | 필수 |
| `ASSEMBLY_API_KEY` | 열린국회정보 API 인증키 | 선택 |

## legalize-es와의 비교

| 항목 | legalize-es (스페인) | legalize-kr (한국) |
|------|---------------------|-------------------|
| 데이터 소스 | BOE 공개 API | 국가법령정보 + 열린국회정보 |
| 법령 수 | 8,600+ | 2,000+ (법률 기준) |
| 파일 형식 | Markdown | Markdown |
| 개정 추적 | Git commit | Git commit |
| 발의 의원 정보 | - | O |
| 표결 정보 | - | O |
| 판례 연동 | - | O |
| 영문 법령 | - | O |
| 상호참조 | - | O |
| RSS 피드 | - | O |
| 검색 인덱스 | - | O |
| 자동 업데이트 | O | O (GitHub Actions) |

## 활용 사례

- **법령 변경 추적**: `git diff`로 어떤 조문이 바뀌었는지 정확히 확인
- **입법 투명성**: 누가 어떤 법안을 발의했는지, 어떤 표결로 통과했는지 추적
- **판례 연구**: 특정 조문에 대한 대법원 판례를 자동으로 연결
- **법률 데이터 분석**: 전체 법률 텍스트를 구조화된 형태로 활용
- **알림 시스템**: RSS 피드로 관심 법령 변경 시 자동 알림
- **교육/연구**: 법령 개정 과정의 시계열 분석
- **국제 비교**: 영문 법령으로 해외 연구자들도 접근 가능

## 기여하기

이슈, PR 모두 환영합니다. 특히 다음 영역에서 도움이 필요합니다:

- 조문 파싱 정확도 개선 (별표, 서식 등)
- 검색 UI 프론트엔드 (GitHub Pages)
- 시각화 대시보드 (통계, 상호참조 그래프)
- 다른 나라 법령 어댑터 구현

## 라이선스

MIT License

법령 원문의 저작권은 대한민국 정부에 있으며, 공공누리 제1유형에 따라 자유롭게 이용 가능합니다.
