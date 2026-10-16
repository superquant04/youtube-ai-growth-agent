"""
industry_ranking_app.py

🚀 AI 상승 반전 산업 랭킹 - 실시간 대시보드

AI 도입으로 가장 큰 "상승 반전"이 기대되는 산업을, 이미 일어난 상승은 빼고 앞으로 남은 몫만으로 점수화합니다.
- 남은 반전 점수   : 3년 고점을 되찾기까지 남은 상승률 + 2년간 시장 대비 뒤처진 폭 (실시간 시장 데이터)
- 주가 미반영 점수 : AI 잠재력 × (1 − 최근 1년 주가 반영도)

사용법:
    pip install -r requirements.txt
    streamlit run industry_ranking_app.py
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai_industry_ranking import market_data, news_data, ranking, storage
from ai_industry_ranking.industries import (
    BENCHMARK_ID, BENCHMARK_TICKER, INDUSTRIES, INDUSTRY_BY_ID, LEVERAGE_FACTOR_LABELS,
    build_news_query, compute_ai_leverage,
)
from ai_industry_ranking.market_data import W3Y
from ai_industry_ranking.scoring import COMPONENT_LABELS, COMPONENTS, DEFAULT_WEIGHTS, PHASES

KST = ZoneInfo("Asia/Seoul")
PRICE_CACHE_TTL = 60  # 초. 자동 새로고침 시 최대 이 간격으로 Yahoo Finance를 다시 조회

st.set_page_config(page_title="AI 상승 반전 산업 랭킹", page_icon="🚀", layout="wide")
storage.init_db()


# ---------------------------------------------------------------------------
# 색상 (라이트/다크 모드별로 검증된 범주형 팔레트, 순서 고정)
# ---------------------------------------------------------------------------

PALETTE = {
    "light": {"series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
              "muted": "#898781", "grid": "#e1e0d9", "surface": "#ffffff", "ink2": "#52514e"},
    "dark": {"series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
             "muted": "#898781", "grid": "#2c2c2a", "surface": "#0e1117", "ink2": "#c3c2b7"},
}


def colors():
    theme = getattr(getattr(st.context, "theme", None), "type", None)
    return PALETTE["dark" if theme == "dark" else "light"]


def base_layout(fig, height, legend=True):
    c = colors()
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=32 if legend else 8, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=None, traceorder="normal") if legend else None,
        showlegend=legend, hoverlabel=dict(namelength=-1),
    )
    fig.update_xaxes(gridcolor=c["grid"], zeroline=False)
    fig.update_yaxes(gridcolor=c["grid"], zeroline=False)
    return fig


# ---------------------------------------------------------------------------
# 데이터 로드 (캐시)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=PRICE_CACHE_TTL, show_spinner="실시간 시장 데이터 불러오는 중...")
def load_indices():
    indices = ranking.fetch_market_indices()
    return indices, datetime.now(KST)


@st.cache_data(ttl=600, show_spinner=False)
def load_news():
    return ranking.load_cached_news()


@st.cache_data(ttl=1800, show_spinner="최신 기사 불러오는 중 (GDELT)...")
def load_articles(query):
    return news_data.fetch_latest_articles(query, max_records=10)


@st.cache_data(ttl=600, show_spinner=False)
def load_history():
    return storage.load_rank_history(days=180)


def fmt_age(iso_ts):
    if not iso_ts:
        return "-"
    delta = datetime.now(KST) - pd.Timestamp(iso_ts).tz_convert(KST).to_pydatetime()
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() // 60)}분 전"
    if hours < 48:
        return f"{hours:.0f}시간 전"
    return f"{hours / 24:.0f}일 전"


def kpi(col, label, value, sub):
    # 산업명이 길어 st.metric의 큰 글씨에서는 잘리므로 한 단계 작은 제목으로 표시
    with col:
        st.caption(label)
        st.markdown(f"### {value}")
        st.caption(sub)


def fmt_rank_change(v):
    if pd.isna(v):
        return "NEW"
    v = int(v)
    return f"▲ {v}" if v > 0 else (f"▼ {-v}" if v < 0 else "–")


def fmt_pct(v, signed=True):
    if pd.isna(v):
        return "-"
    return f"{v:+.0%}" if signed else f"{v:.0%}"


# ---------------------------------------------------------------------------
# 사이드바: 가중치 · 새로고침 · 참고 뉴스
# ---------------------------------------------------------------------------

st.sidebar.header("⚙️ 점수 가중치")
weights = {}
for comp in COMPONENTS:
    weights[comp] = st.sidebar.slider(COMPONENT_LABELS[comp], 0, 100, DEFAULT_WEIGHTS[comp], step=5, key=f"w_{comp}")
if sum(weights.values()) == 0:
    st.sidebar.error("가중치가 모두 0입니다. 하나 이상 올려 주세요.")
    st.stop()

st.sidebar.header("🔄 실시간 갱신")
compare_label = st.sidebar.radio("순위 변동 비교 기준", ["1주 전", "1개월 전"], horizontal=True)
compare_days = 5 if compare_label == "1주 전" else 21
auto_refresh = st.sidebar.toggle("자동 새로고침", value=False)
refresh_minutes = st.sidebar.select_slider("새로고침 주기 (분)", options=[1, 5, 15, 30], value=5, disabled=not auto_refresh)
if st.sidebar.button("지금 새로고침", width="stretch"):
    load_indices.clear()
    load_news.clear()
    load_history.clear()

st.sidebar.header("📰 참고: AI 뉴스 추이")
st.sidebar.caption("산업 상세 화면에만 표시되며 점수에는 반영되지 않습니다.")
if st.sidebar.button("뉴스 추이 지금 갱신 (약 2~3분)", width="stretch"):
    bar = st.sidebar.progress(0.0, text="GDELT 뉴스 수집 준비 중...")

    def _progress(i, n, ind):
        bar.progress(i / n, text=f"{ind.name} 수집 중 ({i + 1}/{n})" if ind else "완료")

    _, errors = ranking.refresh_news(progress_cb=_progress)
    load_news.clear()
    if errors:
        st.sidebar.warning(f"{len(errors)}개 산업 수집 실패: " + ", ".join(INDUSTRY_BY_ID[i].name for i in errors))
    else:
        st.sidebar.success("뉴스 추이 갱신 완료")

st.sidebar.caption(
    "시장 데이터: Yahoo Finance (약 15분 지연) · 뉴스: GDELT DOC 2.0\n\n"
    "⚠️ 이 랭킹은 정량 신호와 가정치를 결합한 참고 지표이며 투자 권유가 아닙니다."
)


# ---------------------------------------------------------------------------
# 헤더 + 탭
# ---------------------------------------------------------------------------

st.title("🚀 AI 상승 반전 산업 랭킹")
st.caption(
    "이미 오른 몫은 빼고, **앞으로 남은 반전**과 **아직 주가에 반영되지 않은 AI 잠재력**만으로 산업 순위를 매깁니다."
)

tab_rank, tab_history, tab_assumptions, tab_method = st.tabs(
    ["🏆 실시간 랭킹", "📜 순위 히스토리", "🧩 AI 잠재력 가정", "📖 방법론"]
)


# --- AI 잠재력 가정 편집 (랭킹 계산보다 먼저 값을 읽어야 하므로 먼저 렌더링) ---

with tab_assumptions:
    st.markdown(
        "AI 잠재력은 실시간 데이터가 아닌 **구조적 가정치**로, `주가 미반영 점수 = AI 잠재력 × (1 − 주가 반영도)` 계산에 쓰입니다. "
        "아래 1~5점 값을 바꾸면 랭킹에 즉시 반영됩니다. 도입 장벽은 높을수록 감점됩니다."
    )
    factor_cols = list(LEVERAGE_FACTOR_LABELS)
    base_df = pd.DataFrame([
        {"id": ind.id, "산업": ind.name, **{LEVERAGE_FACTOR_LABELS[f]: getattr(ind, f) for f in factor_cols},
         "AI 촉매": ind.thesis}
        for ind in INDUSTRIES
    ]).set_index("id")

    if st.button("기본값으로 되돌리기"):
        st.session_state.pop("leverage_editor", None)

    edited = st.data_editor(
        base_df, key="leverage_editor", hide_index=True, width="stretch", height=35 * (len(base_df) + 1) + 3,
        disabled=["산업", "AI 촉매"],
        column_config={
            LEVERAGE_FACTOR_LABELS[f]: st.column_config.NumberColumn(min_value=1, max_value=5, step=1, width=125)
            for f in factor_cols
        },
    )
    ai_leverage = pd.Series({
        iid: compute_ai_leverage(*(
            int(row[LEVERAGE_FACTOR_LABELS[f]]) if pd.notna(row[LEVERAGE_FACTOR_LABELS[f]])
            else getattr(INDUSTRY_BY_ID[iid], f)  # 빈칸으로 지운 셀은 기본값 사용
            for f in factor_cols
        ))
        for iid, row in edited.iterrows()
    })
    changed = int((ai_leverage != ranking.default_ai_leverage().reindex(ai_leverage.index)).sum())
    if changed:
        st.info(f"✏️ {changed}개 산업의 AI 잠재력을 기본값에서 수정해 랭킹에 반영 중입니다.")


# --- 방법론 ---

with tab_method:
    st.markdown(f"""
### 상승 반전 점수 = 남은 반전 점수와 주가 미반영 점수의 가중 평균 (0~100점, 기본 50:50)

이미 일어난 상승(최근 모멘텀, 뉴스 열기)은 점수에 넣지 않고 **앞으로 남은 몫**만 평가합니다.

| 구성요소 | 의미 | 계산 |
|---|---|---|
| **남은 반전 점수** | 가격이 앞으로 되찾을 거리 | ① 3년 고점을 회복하려면 남은 상승률, ② 2년간 {BENCHMARK_TICKER} 대비 뒤처진 폭 — 두 지표의 산업 간 백분위 평균 |
| **주가 미반영 점수** | AI 잠재력 중 아직 주가에 반영되지 않은 몫 | AI 잠재력(0~100) × (1 − 주가 반영도) |

- **AI 잠재력**: 업무 노출도·데이터 자산·가치 레버리지·도입 장벽(역) 1~5점의 가중합. '🧩 AI 잠재력 가정' 탭에서 수정할 수 있습니다.
- **주가 반영도(0~100%)**: 최근 1년 {BENCHMARK_TICKER} 대비 상대수익률과 52주 저점 대비 반등폭의 산업 간 백분위 평균.
  최근 1년 동안 이미 많이 오른 산업일수록 AI 기대가 주가에 반영됐다고 봅니다.
- 예) AI 잠재력 80점, 반영도 25% → 주가 미반영 점수 60점. 같은 잠재력이라도 반영도 90%면 8점.
- 시장 지표는 **산업 간 상대 백분위**(최하위 0점, 최상위 100점)로 환산합니다. 산업 시세는 대표 ETF(또는 대표 종목 동일가중 바스켓)로 대신하며,
  티커는 `ai_industry_ranking/industries.py`에서 바꿀 수 있습니다.

### 반전 국면 (참고 표시, 점수에는 미반영)

| 국면 | 조건 |
|---|---|
| {PHASES['reversing']} | 눌림(3년 고점 대비 −15% 이하 또는 2년 상대수익률 −15%p 이하) + 50일선 위 + 1개월 상승 + 상승 가속 |
| {PHASES['early']} | 눌림 + (50일선 위 또는 1개월 상승) |
| {PHASES['bottoming']} | 눌림 + 아직 반등 신호 없음 |
| {PHASES['trending']} | 눌림 아님 + 50일선 > 200일선 + 1년 +15% 이상 (상승이 이미 가격에 반영) |
| {PHASES['neutral']} | 그 외 |

### 한계
- AI 잠재력은 문헌(예: Eloundou et al. 2023 *GPTs are GPTs*)의 경향을 참고한 **주관적 가정**입니다.
- 주가 반영도는 가격 움직임으로만 추정합니다. 밸류에이션(PER 등)이나 실적 전망은 들어가지 않습니다.
- ETF 가격은 금리·경기 등 AI 외 요인의 영향을 함께 받습니다. 남은 반전이 크다는 것이 "AI 덕분에 반드시 회복한다"는 뜻은 아닙니다.
""")


# ---------------------------------------------------------------------------
# 실시간 랭킹 (자동 새로고침 시 이 부분만 주기적으로 다시 실행)
# ---------------------------------------------------------------------------

def render_ranking(weights, ai_leverage, compare_days):
    try:
        indices, fetched_at = load_indices()
    except market_data.MarketDataError as e:
        st.error(f"❌ 시장 데이터를 불러오지 못했습니다: {e}")
        st.caption("Yahoo Finance(query1/query2.finance.yahoo.com) 접속이 막혀 있지 않은지 확인한 뒤 '지금 새로고침'을 눌러 주세요.")
        return

    table = ranking.build_ranking(indices, weights, ai_leverage=ai_leverage, compare_days=compare_days)
    ranked = table[table["total_score"].notna()]
    if ranked.empty:
        st.error("점수를 계산할 수 있는 산업이 없습니다 (가격 이력 부족).")
        return

    # --- KPI ---
    k1, k2, k3, k4 = st.columns(4)
    top = ranked.iloc[0]
    kpi(k1, "🥇 현재 1위", top["name"], f"상승 반전 점수 {top['total_score']:.1f}점")
    top_rem = ranked.loc[ranked["remaining_reversal"].idxmax()]
    kpi(k2, "🎯 남은 반전 1위", top_rem["name"], f"3년 고점까지 {fmt_pct(top_rem['upside_to_high'])}")
    top_unp = ranked.loc[ranked["unpriced"].idxmax()]
    kpi(k3, "💎 주가 미반영 1위", top_unp["name"],
        f"AI 잠재력 {top_unp['ai_leverage']:.0f}점 · 반영도 {fmt_pct(top_unp['priced_in'], signed=False)}")
    kpi(k4, "📈 시장 데이터 기준일", f"{table.attrs['as_of']:%Y-%m-%d}", f"조회 {fetched_at:%H:%M:%S} KST")

    # --- TOP 3 ---
    cols = st.columns(3)
    for col, (iid, row) in zip(cols, ranked.head(3).iterrows()):
        with col.container(border=True):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}[int(row["rank"])]
            st.markdown(f"#### {medal} {row['name']}")
            st.markdown(
                f"**{row['total_score']:.1f}점** · 변동 {fmt_rank_change(row['rank_change'])}  \n"
                f"남은 반전 {row['remaining_reversal']:.0f} · 주가 미반영 {row['unpriced']:.0f}"
            )
            st.caption(
                f"3년 고점까지 {fmt_pct(row['upside_to_high'])} · "
                f"AI 잠재력 {row['ai_leverage']:.0f}점 중 반영도 {fmt_pct(row['priced_in'], signed=False)}"
            )
            st.caption(INDUSTRY_BY_ID[iid].thesis)

    # --- 랭킹 표 ---
    st.subheader("🏆 전체 랭킹")
    show = table.copy()
    show.attrs = {}  # Timestamp가 든 attrs는 Arrow 직렬화 경고를 내므로 표시용 사본에서는 비움
    show["변동"] = show["rank_change"].map(fmt_rank_change)
    for key in ("priced_in", "upside_to_high", "rel_2y", "rel_12m", "ret_1d"):
        show[key] = show[key] * 100
    st.dataframe(
        show[["rank", "변동", "name", "total_score", *COMPONENTS, "ai_leverage", "priced_in",
              "upside_to_high", "rel_2y", "rel_12m", "ret_1d", "phase_label", "tickers"]],
        hide_index=True, width="stretch", height=35 * (len(show) + 1) + 3,
        column_config={
            "rank": st.column_config.NumberColumn("순위", width="small"),
            "변동": st.column_config.TextColumn(f"{'1주' if compare_days == 5 else '1개월'} 변동", width="small"),
            "name": st.column_config.TextColumn("산업"),
            "total_score": st.column_config.ProgressColumn("상승 반전 점수", min_value=0, max_value=100, format="%.1f"),
            "remaining_reversal": st.column_config.NumberColumn("남은 반전", format="%.0f"),
            "unpriced": st.column_config.NumberColumn("주가 미반영", format="%.0f"),
            "ai_leverage": st.column_config.NumberColumn("AI 잠재력", format="%.0f"),
            "priced_in": st.column_config.NumberColumn("주가 반영도", format="%.0f%%"),
            "upside_to_high": st.column_config.NumberColumn("3년 고점까지", format="%+.0f%%"),
            "rel_2y": st.column_config.NumberColumn(f"2년 vs {BENCHMARK_TICKER}", format="%+.0f%%"),
            "rel_12m": st.column_config.NumberColumn(f"1년 vs {BENCHMARK_TICKER}", format="%+.0f%%"),
            "ret_1d": st.column_config.NumberColumn("1일", format="%+.1f%%"),
            "phase_label": st.column_config.TextColumn("국면(참고)"),
            "tickers": st.column_config.TextColumn("대표 티커"),
        },
    )

    # --- 차트 ---
    c_left, c_right = st.columns([3, 2])
    with c_left:
        st.markdown("**점수 구성** · 구성요소별 기여 점수 (합계 = 상승 반전 점수)")
        st.plotly_chart(contribution_chart(ranked), width="stretch")
    with c_right:
        st.markdown("**반전 매트릭스** · 오른쪽 위일수록 남은 반전과 미반영 AI 잠재력이 모두 큼 · 원 크기 = AI 잠재력")
        st.plotly_chart(reversal_matrix(ranked), width="stretch")

    # --- 산업 상세 ---
    st.subheader("🔎 산업 상세")
    options = list(ranked.index)
    selected = st.selectbox(
        "산업 선택", options, format_func=lambda i: f"{int(table.loc[i, 'rank'])}위 · {INDUSTRY_BY_ID[i].name}",
        key="detail_industry",
    )
    news_series, news_fetched_at = load_news()
    render_detail(selected, table, indices, news_series, news_fetched_at)


def contribution_chart(ranked):
    c = colors()
    df = ranked.iloc[::-1]  # 1위가 위에 오도록
    fig = go.Figure()
    for i, comp in enumerate(COMPONENTS):
        fig.add_bar(
            y=df["name"], x=df[f"contrib_{comp}"], orientation="h", name=COMPONENT_LABELS[comp],
            marker=dict(color=c["series"][i], line=dict(color=c["surface"], width=2)),
            customdata=df[comp],
            hovertemplate="<b>%{y}</b><br>" + COMPONENT_LABELS[comp] + " 기여 %{x:.1f}점 (원점수 %{customdata:.0f})<extra></extra>",
        )
    fig.add_scatter(
        y=df["name"], x=df["total_score"] + 1.5, mode="text", text=df["total_score"].map("{:.1f}".format),
        textposition="middle right", showlegend=False, hoverinfo="skip", textfont=dict(color=c["ink2"]),
    )
    fig.update_layout(barmode="stack", bargap=0.25)
    fig.update_xaxes(range=[0, max(100, df["total_score"].max() + 12)], title=None)
    fig.update_yaxes(title=None)
    return base_layout(fig, height=max(420, 26 * len(df) + 80))


def reversal_matrix(ranked):
    c = colors()
    top_n = 5
    is_top = ranked["rank"] <= top_n
    fig = go.Figure()
    for flag, color, name in ((False, c["muted"], "기타 산업"), (True, c["series"][0], f"상위 {top_n}개 산업")):
        d = ranked[is_top == flag]
        fig.add_scatter(
            x=d["remaining_reversal"], y=d["unpriced"], mode="markers+text" if flag else "markers", name=name,
            text=d["name"] if flag else None, textfont=dict(size=11),
            # 오른쪽 끝 점의 이름표가 잘리지 않도록 왼쪽으로 붙임
            textposition=["top left" if x > 75 else "top center" for x in d["remaining_reversal"]],
            marker=dict(size=8 + d["ai_leverage"] / 5, color=color, opacity=0.9, line=dict(color=c["surface"], width=2)),
            customdata=d[["name", "rank", "total_score", "ai_leverage", "priced_in"]].astype(object).to_numpy(),
            hovertemplate="<b>%{customdata[1]}위 %{customdata[0]}</b><br>남은 반전 %{x:.0f} · 주가 미반영 %{y:.0f}"
                          "<br>AI 잠재력 %{customdata[3]:.0f} · 반영도 %{customdata[4]:.0%}"
                          " · 총점 %{customdata[2]:.1f}<extra></extra>",
        )
    for x, y, label, anchor in ((98, 98, "최우선 후보", "right"), (98, 2, "가격만 눌림", "right"),
                                (2, 98, "가격 회복 · AI 미반영", "left"), (2, 2, "반영 완료", "left")):
        fig.add_annotation(x=x, y=y, text=label, showarrow=False, xanchor=anchor,
                           font=dict(color=c["muted"], size=11))
    fig.add_hline(y=50, line=dict(color=c["grid"], width=1))
    fig.add_vline(x=50, line=dict(color=c["grid"], width=1))
    fig.update_xaxes(range=[-5, 105], title="남은 반전 점수 →")
    fig.update_yaxes(range=[-5, 108], title="주가 미반영 점수 →")
    return base_layout(fig, height=max(420, 26 * len(ranked) + 80))


def render_detail(iid, table, indices, news_series, news_fetched_at):
    ind = INDUSTRY_BY_ID[iid]
    row = table.loc[iid]
    c = colors()

    left, right = st.columns([2, 3])
    with left:
        st.markdown(f"### {int(row['rank'])}위 · {ind.name}")
        st.markdown(f"**{row['total_score']:.1f}점** · 국면(참고) {row['phase_label']} · 대표 티커 `{ind.ticker_label}`")
        st.markdown(
            f"- **남은 반전 {row['remaining_reversal']:.0f}점** — 3년 고점까지 {fmt_pct(row['upside_to_high'])}, "
            f"2년간 {BENCHMARK_TICKER} 대비 {fmt_pct(row['rel_2y'])}\n"
            f"- **주가 미반영 {row['unpriced']:.0f}점** — AI 잠재력 {row['ai_leverage']:.0f} × "
            f"(1 − 반영도 {fmt_pct(row['priced_in'], signed=False)}) · 1년 {BENCHMARK_TICKER} 대비 {fmt_pct(row['rel_12m'])}"
        )
        st.markdown(f"**AI 촉매** — {ind.thesis}")
        st.markdown(f"**반전 리스크** — {ind.risk}")
    with right:
        s = indices[iid].dropna().iloc[-W3Y:]
        b = indices[BENCHMARK_ID].reindex(s.index).ffill()
        s, b = s / s.iloc[0] * 100, b / b.iloc[0] * 100
        fig = go.Figure()
        fig.add_scatter(x=b.index, y=b, name=f"{BENCHMARK_TICKER} (S&P 500)", line=dict(color=c["muted"], width=2))
        fig.add_scatter(x=s.index, y=s, name=ind.name, line=dict(color=c["series"][0], width=2))
        fig.add_hline(
            y=s.max(), line=dict(color=c["series"][0], width=1, dash="dot"),
            annotation_text=f"3년 고점 (남은 반전 {fmt_pct(row['upside_to_high'])})", annotation_position="top left",
            annotation_font=dict(color=c["ink2"], size=11),
        )
        fig.update_layout(hovermode="x unified")
        fig.update_yaxes(title=None)
        st.markdown(f"**최근 3년 주가 흐름** · {ind.name} vs {BENCHMARK_TICKER}, 시작=100")
        st.plotly_chart(base_layout(fig, height=360), width="stretch")

    ns = news_series.get(iid)
    if ns is not None and len(ns):
        fig = go.Figure()
        fig.add_scatter(x=ns.index, y=ns, mode="lines", line=dict(color=c["series"][0], width=2),
                        fill="tozeroy", name="AI 뉴스 비중",
                        hovertemplate="%{x|%Y-%m-%d}<br>전체 기사 중 %{y:.3f}%<extra></extra>")
        fig.update_yaxes(title=None, rangemode="tozero")
        st.markdown(
            f"**(참고) 'AI + {ind.name}' 뉴스 비중 추이** · GDELT 전 세계 기사 중 비율(%) · "
            f"수집 {fmt_age(news_fetched_at)} · 점수에는 미반영"
        )
        st.plotly_chart(base_layout(fig, height=240, legend=False), width="stretch")

    with st.expander("📰 (참고) 최신 AI 뉴스 헤드라인 (GDELT, 최근 7일)"):
        if st.button("헤드라인 불러오기", key=f"news_{iid}"):
            try:
                articles = load_articles(build_news_query(ind))
            except news_data.NewsFetchError as e:
                st.warning(f"기사를 불러오지 못했습니다: {e}")
                articles = None
            if articles == []:
                st.caption("최근 7일간 해당 쿼리의 기사가 없습니다.")
            for a in articles or []:
                when = f"{a['seendate']:%m-%d %H:%M} UTC" if a["seendate"] is not None else ""
                st.markdown(f"- [{a['title']}]({a['url']})  \n  <small>{a['domain']} · {when}</small>",
                            unsafe_allow_html=True)


with tab_rank:
    run_every = f"{refresh_minutes}m" if auto_refresh else None
    st.fragment(render_ranking, run_every=run_every)(weights, ai_leverage, compare_days)


# ---------------------------------------------------------------------------
# 순위 히스토리 (collect.py 정기 실행으로 쌓인 스냅샷)
# ---------------------------------------------------------------------------

with tab_history:
    hist = load_history()
    if hist.empty:
        st.info(
            "아직 저장된 랭킹 스냅샷이 없습니다. `python -m ai_industry_ranking.collect`를 실행하거나 "
            "GitHub Actions 정기 실행(`industry_ranking.yml`)을 켜면 순위 변화가 여기에 쌓입니다."
        )
    else:
        hist["created_at"] = pd.to_datetime(hist["created_at"], utc=True).dt.tz_convert(KST)
        latest = hist[hist["created_at"] == hist["created_at"].max()].sort_values("rank")
        top_ids = latest["industry_id"].head(5).tolist()
        c = colors()
        fig = go.Figure()
        for i, iid in enumerate(top_ids):
            d = hist[hist["industry_id"] == iid]
            fig.add_scatter(
                x=d["created_at"], y=d["rank"], name=d["industry_name"].iloc[-1], mode="lines+markers",
                line=dict(color=c["series"][i], width=2), marker=dict(size=8, line=dict(color=c["surface"], width=2)),
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y}위<extra>" + d["industry_name"].iloc[-1] + "</extra>",
            )
        max_rank = int(hist.loc[hist["industry_id"].isin(top_ids), "rank"].max())
        fig.update_yaxes(range=[max_rank + 0.5, 0.5], title="순위", dtick=1 if max_rank <= 12 else 2, tick0=1)
        st.markdown(f"**순위 추이** · 최근 스냅샷 기준 상위 5개 산업 (스냅샷 {hist['created_at'].nunique()}회)")
        st.plotly_chart(base_layout(fig, height=420), width="stretch")

        st.caption(f"최근 스냅샷: {latest['created_at'].iloc[0]:%Y-%m-%d %H:%M} KST · 시장 기준일 {latest['market_date'].iloc[0]}")
        st.dataframe(
            latest[["rank", "industry_name", "total_score", "remaining_reversal", "unpriced"]],
            hide_index=True, width="stretch",
            column_config={
                "rank": "순위", "industry_name": "산업",
                "total_score": st.column_config.ProgressColumn("상승 반전 점수", min_value=0, max_value=100, format="%.1f"),
                "remaining_reversal": st.column_config.NumberColumn("남은 반전", format="%.0f"),
                "unpriced": st.column_config.NumberColumn("주가 미반영", format="%.0f"),
            },
        )
