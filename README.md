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
│   └── scheduled_run.yml       # 정기 자동 실행 워크플로우
├── requirements.txt
├── .env.example
├── .gitignore
└── reports/                    # main.py 실행 시 리포트(json/md) 자동 저장
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

