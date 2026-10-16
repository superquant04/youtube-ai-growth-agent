"""
industries.py

랭킹 대상 산업 유니버스와 산업별 "AI 잠재력" 기본 가정치 (주가 미반영 점수 계산에 사용).

각 산업은 다음 정보를 가집니다.
- tickers        : 시장 신호를 읽을 대표 ETF(또는 대표 종목 바스켓, 동일가중)
- exposure/data/value/barrier : AI 잠재력을 구성하는 1~5점 정성 평가

AI 잠재력 4요소 (1~5점)
- exposure (업무 노출도): 업무 중 인지·언어·데이터 처리 비중. 높을수록 AI가 대체/증강할 여지가 큼.
  (Eloundou et al. 2023 "GPTs are GPTs"에서 정보·금융·전문서비스 업종의 노출도가 가장 높게 나타난 경향을 참고)
- data     (데이터 자산): 디지털화 수준과 학습에 쓸 수 있는 독점 데이터의 양.
- value    (가치 레버리지): AI가 만들 수 있는 비용 절감·매출 확대·수요 증가의 크기.
- barrier  (도입 장벽): 규제·안전·물리적 제약. 높을수록 확산이 느리므로 감점.

이 값들은 실시간 데이터가 아니라 "기본 가정치"입니다.
대시보드에서 직접 수정할 수 있고, 여기 값을 바꾸면 기본값이 바뀝니다.
"""

from dataclasses import dataclass

# 상대 성과 비교 기준 (S&P 500)
BENCHMARK_TICKER = "SPY"
BENCHMARK_ID = "__benchmark__"

# AI 잠재력 4요소의 가중치 (합계 1.0). barrier는 (6 - barrier)로 뒤집어 반영합니다.
LEVERAGE_FACTOR_WEIGHTS = {
    "exposure": 0.35,
    "data": 0.20,
    "value": 0.30,
    "barrier": 0.15,
}

LEVERAGE_FACTOR_LABELS = {
    "exposure": "업무 노출도",
    "data": "데이터 자산",
    "value": "가치 레버리지",
    "barrier": "도입 장벽",
}


@dataclass(frozen=True)
class Industry:
    id: str
    name: str
    tickers: tuple
    exposure: int
    data: int
    value: int
    barrier: int
    thesis: str
    risk: str

    @property
    def ai_leverage(self):
        return compute_ai_leverage(self.exposure, self.data, self.value, self.barrier)

    @property
    def ticker_label(self):
        return " · ".join(self.tickers)


def compute_ai_leverage(exposure, data, value, barrier):
    """1~5점 4요소를 0~100점 AI 잠재력 점수로 변환합니다."""
    w = LEVERAGE_FACTOR_WEIGHTS
    raw = (
        w["exposure"] * exposure
        + w["data"] * data
        + w["value"] * value
        + w["barrier"] * (6 - barrier)
    )
    return round((raw - 1) / 4 * 100, 1)


INDUSTRIES = [
    Industry(
        id="biotech", name="신약개발·바이오", tickers=("XBI",),
        exposure=4, data=4, value=5, barrier=4,
        thesis="단백질 구조 예측·분자 생성 모델로 후보물질 발굴과 임상 설계 기간을 압축. 2021년 고점 이후 장기 침체로 반전 여력이 큼.",
        risk="임상 성공률은 여전히 생물학이 결정하며, 금리·FDA 규제 변수의 영향이 큼.",
    ),
    Industry(
        id="medtech", name="의료기기·진단", tickers=("IHI",),
        exposure=3, data=4, value=4, barrier=4,
        thesis="AI 영상판독, 수술 로봇, 웨어러블 기반 조기 진단이 기기의 부가가치를 끌어올림.",
        risk="인허가 절차가 길고 병원 구매 주기가 느림.",
    ),
    Industry(
        id="health_services", name="헬스케어 서비스", tickers=("IHF",),
        exposure=4, data=4, value=4, barrier=4,
        thesis="진료기록 자동 작성(앰비언트 AI), 청구·심사 자동화로 인건비 비중이 큰 행정 비용을 절감.",
        risk="보험 수가·정책 리스크, 개인정보 규제.",
    ),
    Industry(
        id="software", name="소프트웨어(SaaS)", tickers=("IGV",),
        exposure=5, data=5, value=3, barrier=1,
        thesis="코딩 생산성 향상과 AI 에이전트 기능의 신규 과금으로 성장률 재가속 가능.",
        risk="AI 에이전트가 좌석(seat) 기반 과금을 잠식하는 '소프트웨어 디플레이션' 우려.",
    ),
    Industry(
        id="semis", name="반도체", tickers=("SOXX",),
        exposure=3, data=4, value=5, barrier=2,
        thesis="AI 학습·추론 수요의 직접 수혜. AI 확산의 '삽과 곡괭이' 산업.",
        risk="이미 상승분을 상당 부분 선반영했을 수 있어 반전보다는 추세 산업에 가까움.",
    ),
    Industry(
        id="cybersecurity", name="사이버보안", tickers=("CIBR",),
        exposure=4, data=5, value=4, barrier=2,
        thesis="AI로 고도화된 공격에 대응하는 수요 증가 + 보안관제(SOC) 자동화로 마진 개선.",
        risk="플랫폼 통합 경쟁으로 중소 업체 가격 압박.",
    ),
    Industry(
        id="it_services", name="IT서비스·컨설팅", tickers=("ACN", "CTSH", "EPAM", "INFY"),
        exposure=5, data=4, value=3, barrier=1,
        thesis="기업들의 AI 전환 프로젝트 수요를 수주. 인력 기반 사업을 AI 기반 고마진 사업으로 재편할 기회.",
        risk="AI가 인력 단가 기반 아웃소싱 매출을 직접 대체할 위험.",
    ),
    Industry(
        id="banks", name="은행", tickers=("KBE",),
        exposure=4, data=5, value=4, barrier=4,
        thesis="여신 심사·이상거래 탐지·고객 상담 자동화로 비용수익비율(CIR) 개선.",
        risk="금리 사이클과 규제 자본 요건이 실적을 좌우.",
    ),
    Industry(
        id="insurance", name="보험", tickers=("KIE",),
        exposure=4, data=5, value=4, barrier=3,
        thesis="언더라이팅·보상 심사 자동화와 정밀 위험 가격 책정으로 손해율·사업비율 동시 개선.",
        risk="대형 재해 손실, 알고리즘 차별 규제.",
    ),
    Industry(
        id="capital_markets", name="증권·자산운용", tickers=("KCE",),
        exposure=4, data=5, value=4, barrier=3,
        thesis="리서치·트레이딩·자산관리 상담 자동화로 1인당 운용 가능 고객 수가 급증.",
        risk="시장 거래대금 사이클에 크게 의존.",
    ),
    Industry(
        id="legal_info", name="법률·전문정보", tickers=("TRI", "RELX", "WTKWY"),
        exposure=5, data=5, value=4, barrier=2,
        thesis="판례·규정 독점 데이터베이스 위에 생성형 AI를 얹어 고가 구독 상품화(법률 리서치·세무·컴플라이언스).",
        risk="범용 LLM이 독점 데이터의 가치를 희석할 가능성.",
    ),
    Industry(
        id="education", name="교육", tickers=("LRN", "DUOL", "COUR"),
        exposure=5, data=4, value=4, barrier=3,
        thesis="1:1 AI 튜터로 개인화 학습 비용이 급락. 콘텐츠 제작 자동화로 공급 확대.",
        risk="무료 범용 챗봇이 유료 교육 서비스를 대체하는 '양날의 검'.",
    ),
    Industry(
        id="industrials", name="제조·산업재", tickers=("XLI",),
        exposure=2, data=3, value=4, barrier=3,
        thesis="예지보전·공정 최적화·생성형 설계로 생산성 정체를 돌파. 데이터센터 설비 수요도 수혜.",
        risk="현장 데이터 부족과 레거시 설비로 도입 속도가 느림.",
    ),
    Industry(
        id="robotics", name="로봇·자동화", tickers=("BOTZ",),
        exposure=3, data=4, value=5, barrier=3,
        thesis="파운데이션 모델이 로봇에 범용 지능을 부여하는 '피지컬 AI' 전환의 핵심.",
        risk="상용화 시점 불확실, 하드웨어 원가 부담.",
    ),
    Industry(
        id="transport", name="운송·물류", tickers=("IYT",),
        exposure=2, data=4, value=4, barrier=3,
        thesis="경로·적재 최적화, 수요 예측, 자율주행 트럭으로 운임 대비 비용 구조 개선.",
        risk="경기 민감도가 높고 자율주행 규제가 지역마다 다름.",
    ),
    Industry(
        id="retail", name="소매·유통", tickers=("XRT",),
        exposure=3, data=4, value=3, barrier=1,
        thesis="수요 예측·재고 최적화와 초개인화 추천, AI 쇼핑 에이전트로 전환율 상승.",
        risk="AI 쇼핑 에이전트가 가격 비교를 쉽게 만들어 마진 압박.",
    ),
    Industry(
        id="gaming_media", name="게임·엔터테인먼트", tickers=("ESPO",),
        exposure=4, data=4, value=4, barrier=1,
        thesis="생성형 AI로 아트·음성·레벨 제작비를 절감하고 개발 기간 단축. 제작비 증가 추세의 반전.",
        risk="저작권 분쟁, 콘텐츠 공급 과잉.",
    ),
    Industry(
        id="telecom", name="통신", tickers=("IYZ",),
        exposure=3, data=5, value=3, barrier=3,
        thesis="네트워크 운영 자동화와 고객센터 AI로 비용 절감. 엣지 AI 트래픽 증가 수혜.",
        risk="성숙 산업으로 매출 성장 여력이 제한적.",
    ),
    Industry(
        id="utilities", name="전력·유틸리티", tickers=("XLU",),
        exposure=2, data=3, value=5, barrier=4,
        thesis="AI 데이터센터 전력 수요 폭증으로 수십 년 만의 전력 수요 성장 사이클.",
        risk="송전망 증설 지연, 요금 규제.",
    ),
    Industry(
        id="nuclear", name="원자력·우라늄", tickers=("URA",),
        exposure=1, data=2, value=5, barrier=5,
        thesis="24시간 무탄소 전력을 원하는 빅테크 데이터센터의 장기 계약 수요.",
        risk="건설 기간이 길고 인허가·안전 규제가 엄격.",
    ),
    Industry(
        id="real_estate", name="부동산(리츠)", tickers=("XLRE",),
        exposure=2, data=3, value=3, barrier=3,
        thesis="데이터센터 리츠 수요와 자산관리 자동화. 오피스 침체 속 일부 자산군 재평가.",
        risk="금리 민감도가 매우 높음.",
    ),
    Industry(
        id="energy", name="석유·가스", tickers=("XLE",),
        exposure=2, data=4, value=3, barrier=3,
        thesis="탄성파 데이터 해석·시추 최적화로 생산 비용 절감, 데이터센터용 가스발전 수요.",
        risk="유가 변동성이 AI 효과를 압도.",
    ),
    Industry(
        id="agriculture", name="농업·식품", tickers=("MOO",),
        exposure=1, data=3, value=4, barrier=3,
        thesis="정밀농업(위성·드론 데이터), 자율 농기계, 작물 유전체 설계.",
        risk="도입 주체가 영세하고 날씨·곡물가 변동이 큼.",
    ),
    Industry(
        id="aerospace_defense", name="항공우주·방산", tickers=("ITA",),
        exposure=3, data=4, value=4, barrier=4,
        thesis="자율 무인체계, 설계·시뮬레이션 자동화, 정비 예측으로 국방 AI 예산 수혜.",
        risk="정부 예산·수출 규제 의존.",
    ),
    Industry(
        id="autos", name="자동차·자율주행", tickers=("DRIV",),
        exposure=2, data=4, value=5, barrier=4,
        thesis="엔드투엔드 AI 자율주행과 로보택시가 '차량 판매'를 '모빌리티 서비스' 매출로 전환.",
        risk="안전 규제, 막대한 설비 투자, 전기차 가격 경쟁.",
    ),
]

INDUSTRY_BY_ID = {ind.id: ind for ind in INDUSTRIES}


def all_tickers():
    """시장 데이터 수집에 필요한 모든 티커 (벤치마크 포함, 중복 제거)."""
    tickers = {BENCHMARK_TICKER}
    for ind in INDUSTRIES:
        tickers.update(ind.tickers)
    return sorted(tickers)
