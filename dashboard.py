"""
dashboard.py

YouTube AI Growth Hacking Agent 대시보드

video_stats(영상 성과 시계열)와 analyses(6단계 가설 히스토리)를 시각화합니다.

사용법:
    pip install streamlit plotly
    streamlit run dashboard.py
"""

import re
import json
import pandas as pd
import streamlit as st
import plotly.express as px

import database

st.set_page_config(
    page_title="YouTube AI Growth Hacking Agent",
    page_icon="🎥",
    layout="wide"
)


# ---------------------------------------------------------------------------
# 데이터 로드 & 파싱 헬퍼
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10)
def load_video_stats():
    rows = database.get_video_stats_history(limit=500)
    return pd.DataFrame(rows)


@st.cache_data(ttl=10)
def load_analyses(limit=200):
    rows = database.get_analysis_history(limit=limit)
    return pd.DataFrame(rows)


def parse_ctr(ctr_str):
    """'5.8%' -> 5.8 (float). 파싱 불가하면 None."""
    if not ctr_str or ctr_str == "N/A":
        return None
    match = re.search(r"[\d.]+", str(ctr_str))
    return float(match.group()) if match else None


def parse_avd_to_seconds(avd_str):
    """'00:02:15' 또는 '02:15' -> 초 단위 정수. 파싱 불가하면 None."""
    if not avd_str or avd_str == "N/A":
        return None
    parts = str(avd_str).split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None

    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    elif len(parts) == 2:
        m, s = parts
        return m * 60 + s
    return None


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------

st.title("🎥 YouTube AI Growth Hacking Agent")
st.caption("영상 성과 트렌드 + 6단계 과학적 실험 히스토리")

col_refresh, _ = st.columns([1, 6])
with col_refresh:
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()

video_df = load_video_stats()
analyses_df = load_analyses()

if video_df.empty and analyses_df.empty:
    st.warning("아직 데이터가 없습니다. `python main.py`를 먼저 실행해서 데이터를 수집/분석해 주세요.")
    st.stop()


# ---------------------------------------------------------------------------
# 상단 요약 지표
# ---------------------------------------------------------------------------

st.subheader("📊 요약")
m1, m2, m3, m4 = st.columns(4)

with m1:
    st.metric("수집된 영상 통계 수", len(video_df))
with m2:
    st.metric("총 분석(가설) 수", len(analyses_df))
with m3:
    if not video_df.empty:
        latest_ctr = video_df.iloc[-1]["ctr"]
        st.metric("최신 영상 CTR", latest_ctr)
    else:
        st.metric("최신 영상 CTR", "N/A")
with m4:
    if not video_df.empty:
        latest_views = video_df.iloc[-1]["views"]
        st.metric("최신 영상 조회수", f"{latest_views:,}")
    else:
        st.metric("최신 영상 조회수", "N/A")

st.divider()


# ---------------------------------------------------------------------------
# 영상 성과 트렌드
# ---------------------------------------------------------------------------

st.subheader("📈 영상 성과 트렌드")

if video_df.empty:
    st.info("영상 통계 데이터가 없습니다.")
else:
    plot_df = video_df.copy()
    plot_df["ctr_value"] = plot_df["ctr"].apply(parse_ctr)
    plot_df["avd_seconds"] = plot_df["avd"].apply(parse_avd_to_seconds)
    plot_df["avd_minutes"] = plot_df["avd_seconds"].apply(lambda s: round(s / 60, 2) if s else None)
    plot_df["published_at"] = pd.to_datetime(plot_df["published_at"])
    plot_df = plot_df.sort_values("published_at")

    tab_views, tab_ctr, tab_avd, tab_engagement = st.tabs(
        ["조회수", "CTR (클릭률)", "AVD (평균 시청시간)", "좋아요/댓글"]
    )

    with tab_views:
        fig = px.line(
            plot_df, x="published_at", y="views", markers=True,
            hover_data=["title"], title="영상별 조회수 추이"
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab_ctr:
        if plot_df["ctr_value"].notna().any():
            fig = px.line(
                plot_df, x="published_at", y="ctr_value", markers=True,
                hover_data=["title"], title="클릭률(CTR) 추이 (%)",
                labels={"ctr_value": "CTR (%)"}
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("CTR 데이터가 없습니다 (Analytics API 인증 및 집계 대기 필요).")

    with tab_avd:
        if plot_df["avd_minutes"].notna().any():
            fig = px.line(
                plot_df, x="published_at", y="avd_minutes", markers=True,
                hover_data=["title"], title="평균 시청 지속시간 추이 (분)",
                labels={"avd_minutes": "평균 시청시간 (분)"}
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("AVD 데이터가 없습니다 (Analytics API 인증 및 집계 대기 필요).")

    with tab_engagement:
        engagement_df = plot_df.melt(
            id_vars=["published_at", "title"],
            value_vars=["likes", "comments"],
            var_name="metric", value_name="count"
        )
        fig = px.bar(
            engagement_df, x="published_at", y="count", color="metric",
            barmode="group", hover_data=["title"], title="좋아요 / 댓글 수"
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("원본 영상 통계 데이터 보기"):
        st.dataframe(
            video_df[["title", "published_at", "views", "likes", "comments", "ctr", "avd"]],
            use_container_width=True
        )

st.divider()


# ---------------------------------------------------------------------------
# 가설 히스토리
# ---------------------------------------------------------------------------

st.subheader("🧪 6단계 실험 히스토리")

if analyses_df.empty:
    st.info("분석 기록이 없습니다.")
else:
    display_df = analyses_df.copy()
    display_df["baseline"] = display_df["is_baseline"].apply(lambda x: "🆕 베이스라인" if x else "🔁 검증")
    display_df["created_at"] = pd.to_datetime(display_df["created_at"])
    display_df = display_df.sort_values("created_at", ascending=False)

    # 가설 방향(증가/감소)별 분포 요약
    direction_counts = display_df["hypothesis_direction"].value_counts()
    if not direction_counts.empty:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.caption("가설 방향 분포")
            fig = px.pie(
                names=direction_counts.index, values=direction_counts.values,
                hole=0.4
            )
            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=250)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.caption("실험한 지표(metric) 분포")
            metric_counts = display_df["hypothesis_metric"].value_counts()
            fig2 = px.bar(x=metric_counts.index, y=metric_counts.values)
            fig2.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=250,
                                xaxis_title="", yaxis_title="횟수")
            st.plotly_chart(fig2, use_container_width=True)

    st.caption("분석 목록 (최신순) - 행을 선택하면 아래에 전체 리포트가 표시됩니다")
    st.dataframe(
        display_df[["id", "created_at", "video_context", "baseline", "hypothesis_statement"]],
        use_container_width=True,
        hide_index=True
    )

    st.markdown("#### 📄 상세 리포트 보기")
    selected_id = st.selectbox(
        "분석 ID 선택",
        options=display_df["id"].tolist(),
        format_func=lambda x: f"#{x} - " + display_df.loc[display_df['id'] == x, 'video_context'].values[0]
    )

    if selected_id:
        detail = database.get_analysis_by_id(int(selected_id))
        if detail:
            st.markdown(f"**분석 시각:** {detail['created_at']} · **영상:** {detail['video_context']}")
            st.markdown(detail["markdown_report"])
            with st.expander("원본 JSON 보기"):
                st.json(detail["raw_json"])
