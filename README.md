# 🎥 YouTube AI Growth Hacking Agent

유튜브 채널 성과 데이터를 자동 수집하고, "과학적 실험 6단계 프레임워크"
(검증 → 질문 → 가설 → 통제 → 실행 → 관찰과 측정)에 따라
AI가 데이터 기반 성장 인사이트를 도출하는 에이전트입니다.

매 실행마다 이전 가설이 실제로 맞았는지 검증한 뒤 다음 가설을 세우기 때문에,
느낌이 아닌 데이터로 채널을 성장시키는 반복 실험 루프를 만듭니다.

---

## 📁 프로젝트 구조

```
.
├── main.py                     # 진입점: fetcher → analyzer → DB 저장 파이프라인
├── youtube_fetcher.py          # YouTube Data API + Analytics API로 영상 데이터 수집
├── ai_analyzer.py              # 6단계 프레임워크로 LLM 분석 (구조화 JSON 출력)
├── database.py                 # SQLite 저장소 (video_stats, analyses 테이블)
├── dashboard.py                # Streamlit 대시보드 (트렌드 차트 + 가설 히스토리)
├── migrate_history_to_db.py    # 구버전 hypothesis_history.json → SQLite 이전 스크립트
├── generate_token.py           # (최초 1회) GitHub Actions용 refresh token 발급
├── .github/workflows/
│   ├── scheduled_run.yml       # 정기 자동 실행 워크플로우
│   └── industry_ranking.yml    # AI 산업 랭킹 스냅샷 평일 정기 수집
├── requirements.txt
├── .env.example
├── .gitignore
├── reports/                    # main.py 실행 시 리포트(json/md) 자동 저장
│
├── industry_ranking_app.py     # 🚀 AI 상승 반전 산업 랭킹 대시보드 (아래 별도 섹션 참고)
└── ai_industry_ranking/        # 랭킹 엔진 패키지 (수집 → 점수화 → 저장, tests/ 포함)
```

---

## ⚙️ 설치

### 1. 의존성 설치

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. OpenAI API 키 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 `OPENAI_API_KEY`를 실제 키로 채웁니다.

### 3. YouTube API 사용 설정

영상의 **조회수/좋아요/댓글**은 API 키만으로 가져올 수 있지만,
**CTR(클릭률)과 평균 시청 지속시간(AVD)** 은 채널 소유자 본인만 조회 가능한
비공개 지표라 OAuth 인증이 반드시 필요합니다.

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트 생성
2. **YouTube Data API v3**, **YouTube Analytics API** 두 개 모두 활성화
3. "사용자 인증 정보" → OAuth 클라이언트 ID 생성 (애플리케이션 유형: **데스크톱 앱**)
4. 다운로드한 JSON 파일을 프로젝트 루트에 `client_secret.json`으로 저장

> `token.pickle`은 최초 실행 시 브라우저 인증 후 자동 생성되며, 이후 재인증 없이 재사용됩니다.

---

## 🚀 사용법

### 전체 파이프라인 실행 (데이터 수집 → 분석 → 저장)

```bash
python main.py                     # 최근 10개 영상 분석
python main.py --max-results 5     # 최근 5개 영상만 분석
python main.py --no-save           # 리포트 파일 저장 없이 콘솔 출력만
```

최초 실행 시 브라우저 창이 열리며 Google 계정 인증을 요청합니다.

실행 결과:
- `growth_agent.db`에 영상 통계 + 분석 리포트 누적 저장
- `reports/report_YYYYMMDD_HHMMSS.{json,md}`에 리포트 백업

### 대시보드 실행

```bash
streamlit run dashboard.py
```

브라우저에서 다음을 확인할 수 있습니다:
- 조회수 / CTR / AVD / 좋아요·댓글 추이 차트
- 가설 방향(증가·감소) 및 실험 지표 분포
- 분석 히스토리 목록 + 개별 리포트 전체 보기

### 구버전 히스토리(JSON 파일) 이전

과거에 `hypothesis_history.json` 파일 기반으로 실행한 이력이 있다면:

```bash
python migrate_history_to_db.py --dry-run   # 미리보기
python migrate_history_to_db.py             # 실제 이전
```

---

## 🧪 6단계 과학적 실험 프레임워크

`ai_analyzer.py`가 매 분석마다 강제하는 구조입니다.

| 단계 | 내용 |
|---|---|
| 1. 검증 (Verification) | 이전 가설이 이번 데이터로 지지되는지 수치로 평가 |
| 2. 질문 (Question) | 데이터에서 발견된 가장 아쉬운 점 또는 기회 |
| 3. 가설 (Hypothesis) | "만약 A를 바꾸면 B가 변할 것이다" 형태의 인과관계 가설 |
| 4. 통제 (Control) | 가설 검증을 위해 다음 영상에서 유지해야 할 조건 |
| 5. 실행 (Execution) | 다음 영상 제작 시 실제로 실행할 행동 지침 |
| 6. 관찰과 측정 (Measurement) | 성과 판별을 위해 추적할 핵심 지표(KPI) |

이전 실행의 가설/통제/실행 내용은 `database.py`에 저장되어 있다가,
다음 실행 시 자동으로 프롬프트에 포함되어 "1. 검증" 단계의 근거로 쓰입니다.

---

## 🗄️ 데이터베이스 스키마

**`video_stats`** — 수집할 때마다 쌓이는 영상 성과 시계열
```
video_id, title, published_at, views, likes, comments, ctr, avd, fetched_at
```

**`analyses`** — 매 분석의 6단계 리포트 (대시보드 쿼리를 위해 핵심 필드를 개별 컬럼으로도 저장)
```
created_at, video_context, is_baseline, verification_summary, question,
hypothesis_variable, hypothesis_change, hypothesis_metric, hypothesis_direction,
hypothesis_statement, control_reason, measurement_period,
raw_json, markdown_report
```

---

## ⚠️ 참고 사항

- **API 쿼터**: YouTube Data API는 일일 쿼터 제한이 있습니다(기본 10,000 유닛). Analytics API는 별도 쿼터로 관리됩니다.
- **CTR/AVD 지연**: 업로드 직후 영상은 Analytics 데이터가 아직 집계되지 않아 `N/A`로 표시될 수 있습니다.
- **LLM 비용**: `gpt-4o` 모델을 사용하며, 분석 1회당 입력 데이터 크기에 따라 비용이 발생합니다.
- **OpenAI 모델 지정**: `ai_analyzer.py`의 `model="gpt-4o"` 부분을 필요에 따라 다른 모델로 교체할 수 있습니다.

---

## 🤖 자동화: GitHub Actions로 정기 실행

CI(헤드리스 환경)는 브라우저를 띄울 수 없어서, 로컬 개발용 OAuth 흐름과는
다른 인증 방식이 필요합니다. `youtube_fetcher.py`는 두 방식을 자동으로 분기합니다:

- 로컬: 브라우저 인증 → `token.pickle`에 캐싱
- CI: 환경변수의 `refresh_token`으로 헤드리스 인증

### 1단계: refresh token 최초 발급 (로컬에서 1회만)

```bash
python generate_token.py
```

브라우저 인증 후 아래 3개 값이 출력됩니다:
```
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
YOUTUBE_REFRESH_TOKEN
```

### 2단계: GitHub Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**에서 다음 4개를 등록합니다.

| Secret 이름 | 값 |
|---|---|
| `OPENAI_API_KEY` | `.env`에 쓰던 OpenAI 키 |
| `YOUTUBE_CLIENT_ID` | generate_token.py 출력값 |
| `YOUTUBE_CLIENT_SECRET` | generate_token.py 출력값 |
| `YOUTUBE_REFRESH_TOKEN` | generate_token.py 출력값 |

### 3단계: 워크플로우 확인

`.github/workflows/scheduled_run.yml`이 매주 월요일 UTC 00:00(KST 오전 9시)에
`main.py`를 실행하고, 갱신된 `growth_agent.db`와 `reports/`를 저장소에 자동 커밋합니다.

- 주기를 바꾸려면 워크플로우 파일의 `cron` 표현식을 수정하세요 ([crontab.guru](https://crontab.guru) 참고).
- Actions 탭에서 **Run workflow** 버튼으로 수동 실행도 가능합니다(`workflow_dispatch`).

> ⚠️ `client_secret.json`, `token.pickle`, `.env`는 `.gitignore`에 포함되어 있어
> 실수로 커밋되지 않습니다. 반면 `growth_agent.db`와 `reports/`는 의도적으로
> 커밋 대상입니다 (다음 단계인 Streamlit Cloud 자동 배포의 트리거이기 때문).

---

## 🌐 배포: Streamlit Cloud에 대시보드 올리기

대시보드는 `growth_agent.db`를 읽기만 하므로, DB가 저장소에 최신 상태로
커밋되어 있으면(위 GitHub Actions 단계) 별도 서버 없이 바로 배포할 수 있습니다.

1. 이 저장소를 GitHub에 push
2. [share.streamlit.io](https://share.streamlit.io) 접속 → GitHub 계정 연동
3. **New app** → 저장소 선택 → Main file path에 `dashboard.py` 입력 → Deploy
4. 배포 완료 후, GitHub Actions가 `growth_agent.db`를 새로 커밋할 때마다
   Streamlit Cloud가 해당 push를 감지해 **자동으로 재배포**됩니다.

대시보드 자체는 OpenAI/YouTube API를 직접 호출하지 않으므로 Streamlit Cloud
Secrets에 별도로 등록할 값은 없습니다 (DB 파일만 읽음).

### 전체 흐름 정리

```
[로컬] generate_token.py       → refresh token 최초 1회 발급
    ↓
[GitHub Secrets] 4개 값 등록
    ↓
[GitHub Actions] 매주 자동 실행 → main.py → growth_agent.db 갱신 → 자동 커밋
    ↓
[Streamlit Cloud] push 감지 → 자동 재배포 → 대시보드에 최신 데이터 반영
```


---

## 🚀 AI 상승 반전 산업 랭킹 (실시간 대시보드)

**"AI를 도입했을 때 가장 큰 상승 반전을 일으킬 산업"** 의 순위를 실시간 데이터로 계산해 보여 주는 별도 앱입니다.
이미 오른 몫(최근 모멘텀·뉴스 열기)은 점수에서 빼고, **앞으로 남은 반전**과
**아직 주가에 반영되지 않은 AI 잠재력**이 큰 산업이 위로 올라옵니다.

### 실행

```bash
pip install -r requirements.txt
streamlit run industry_ranking_app.py
```

API 키가 필요 없습니다. 시세는 Yahoo Finance(약 15분 지연)에서 받습니다.

### 점수 계산

**상승 반전 점수 (0~100) = 남은 반전 점수와 주가 미반영 점수의 가중 평균** (기본 50 : 50, 사이드바에서 조정)

| 구성요소 | 의미 | 계산 |
|---|---|---|
| 남은 반전 점수 | 가격이 앞으로 되찾을 거리 | 3년 고점을 회복하려면 남은 상승률, 2년간 SPY 대비 뒤처진 폭의 산업 간 백분위 평균 |
| 주가 미반영 점수 | AI 잠재력 중 아직 주가에 반영되지 않은 몫 | AI 잠재력(0~100) × (1 − 주가 반영도) |

- **AI 잠재력**: 업무 노출도·데이터 자산·가치 레버리지·도입 장벽(역) 1~5점 가정치의 가중합. 대시보드에서 수정할 수 있습니다.
- **주가 반영도(0~100%)**: 최근 1년 SPY 대비 상대수익률과 52주 저점 대비 반등폭의 산업 간 백분위 평균.
  최근 1년간 이미 많이 오른 산업일수록 AI 기대가 주가에 반영됐다고 봅니다.
  예) AI 잠재력 80점, 반영도 25% → 주가 미반영 점수 60점.
- 반전 국면(🔥 반전 진행, ⏳ 바닥 탐색 등)과 AI 뉴스 추이는 **참고용으로만 표시**하며 점수에는 들어가지 않습니다.

산업 시세는 대표 ETF(예: 바이오 `XBI`, 소프트웨어 `IGV`)나 대표 종목 동일가중 바스켓(예: 법률·전문정보 `TRI·RELX·WTKWY`)으로 대신합니다.
산업 목록, 티커, 뉴스 키워드, AI 잠재력 기본값은 모두 `ai_industry_ranking/industries.py` 한 곳에서 수정합니다.

### 화면 구성

| 탭 | 내용 |
|---|---|
| 🏆 실시간 랭킹 | 1위·남은 반전 1위·주가 미반영 1위, 1~3위 카드, 전체 25개 산업 순위표(1주/1개월 전 대비 순위 변동), 점수 구성 막대, 반전 매트릭스(남은 반전 × 주가 미반영), 산업 상세(3년 주가와 고점까지 거리, AI 촉매·리스크, 참고용 AI 뉴스 추이·헤드라인) |
| 📜 순위 히스토리 | 정기 수집 스냅샷으로 본 상위 산업의 순위 추이 |
| 🧩 AI 잠재력 가정 | 산업별 1~5점 가정치를 표에서 직접 수정 → 랭킹에 즉시 반영 |
| 📖 방법론 | 점수 공식, 반전 국면 판정 기준, 한계 |

### 정기 수집

```bash
python -m ai_industry_ranking.collect                  # 랭킹 계산 → 스냅샷 저장
python -m ai_industry_ranking.collect --refresh-news   # 참고용 AI 뉴스 추이(GDELT)도 갱신 (~3분 추가)
```

- `.github/workflows/industry_ranking.yml`이 평일 UTC 21:30(KST 다음날 06:30, 미국 장 마감 후)에
  `--refresh-news`로 실행하고 `ai_industry_ranking/industry_ranking.db`를 커밋합니다. 별도 Secrets 등록은 필요 없습니다.
  Streamlit Cloud에 배포했다면 이 커밋으로 순위 히스토리와 뉴스 추이가 자동 반영됩니다 (Main file path: `industry_ranking_app.py`).
- GDELT는 IP당 5초에 1회 요청 제한이 있어 뉴스 추이는 DB에 캐시해 재사용합니다. 대시보드 사이드바 버튼으로도 갱신할 수 있습니다.

### 테스트

```bash
pip install pytest
python -m pytest ai_industry_ranking/tests -q
```

네트워크 없이 합성 데이터로 지표 계산, 점수화, 저장소, Streamlit 화면 렌더링까지 검증합니다.

> ⚠️ AI 잠재력은 주관적 가정치이고, 주가 반영도는 가격 움직임만으로 추정합니다(밸류에이션 미포함).
> ETF 가격에는 금리·경기 등 AI 외 요인도 섞여 있습니다. 이 랭킹은 참고 지표이며 투자 권유가 아닙니다.
