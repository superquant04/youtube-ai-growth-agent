"""
scoring.py

"AI 상승 반전 점수" 계산.

산업별 4개 구성요소(0~100점)를 가중 평균합니다.

| 구성요소          | 의미                                  | 계산                                                  |
|-------------------|---------------------------------------|-------------------------------------------------------|
| ai_leverage       | AI가 키울 수 있는 이익 체력           | industries.py 4요소 가정치 (절대 점수)                |
| reversal_room     | 그동안 눌려 있던 정도 (반전 여력)     | 2년 상대수익률 하위 + 3년 고점 대비 낙폭 큰 순 백분위 |
| turn_momentum     | 바닥에서 고개를 드는 정도 (반전 신호) | 3개월 상대수익률·1개월 수익률·상승 가속도 백분위      |
| news_momentum     | AI 내러티브의 확산 속도               | AI+산업 뉴스 비중의 8주 대비 증가율·최근 비중 백분위 |

시장·뉴스 지표는 산업 간 상대 백분위(0~100)로 바꿔 서로 단위가 다른 지표를 합칠 수 있게 합니다.
"""

import numpy as np
import pandas as pd

COMPONENTS = ["ai_leverage", "reversal_room", "turn_momentum", "news_momentum"]

COMPONENT_LABELS = {
    "ai_leverage": "AI 레버리지",
    "reversal_room": "반전 여력",
    "turn_momentum": "반전 모멘텀",
    "news_momentum": "AI 뉴스 모멘텀",
}

DEFAULT_WEIGHTS = {
    "ai_leverage": 35,
    "reversal_room": 20,
    "turn_momentum": 25,
    "news_momentum": 20,
}

# 반전 국면 판정 기준 (절대값 규칙)
DEPRESSED_DRAWDOWN = -0.15   # 3년 고점 대비 -15% 이하
DEPRESSED_REL_2Y = -0.15     # 2년간 SPY 대비 -15%p 이상 부진
TRENDING_RET_12M = 0.15      # 1년 +15% 이상 상승

PHASES = {
    "reversing": "🔥 반전 진행",
    "early": "🌱 반전 초기",
    "bottoming": "⏳ 바닥 탐색",
    "trending": "🚀 상승 추세",
    "neutral": "➖ 횡보",
    "no_data": "❔ 데이터 부족",
}


def percentile_score(values, higher_is_better=True):
    """산업 간 상대 순위를 0~100점으로. 결측은 결측 유지, 유효값이 1개면 50점."""
    s = pd.to_numeric(values, errors="coerce").astype(float)
    if not higher_is_better:
        s = -s
    n = s.count()
    if n == 0:
        return s
    if n == 1:
        return s.where(s.isna(), 50.0)
    return (s.rank(method="average") - 1) / (n - 1) * 100


def _row_mean(parts):
    return pd.concat(parts, axis=1).mean(axis=1, skipna=True)


def compute_components(metrics, ai_leverage, news_metrics=None):
    """
    metrics      : market_data.compute_all_metrics 결과 (index=산업 id)
    ai_leverage  : Series(index=산업 id, 0~100)
    news_metrics : DataFrame(index=산업 id, columns=[news_change, news_share_7d]) 또는 None
    """
    m = metrics.reindex(ai_leverage.index)

    def col(name):
        return m[name] if name in m.columns else pd.Series(np.nan, index=m.index)

    comp = pd.DataFrame(index=ai_leverage.index)
    comp["ai_leverage"] = ai_leverage.astype(float)
    comp["reversal_room"] = _row_mean([
        percentile_score(col("rel_2y"), higher_is_better=False),
        percentile_score(col("drawdown_3y"), higher_is_better=False),
    ])
    comp["turn_momentum"] = _row_mean([
        percentile_score(col("rel_3m")),
        percentile_score(col("ret_1m")),
        percentile_score(col("accel")),
    ])

    if news_metrics is not None and not news_metrics.empty:
        nm = news_metrics.reindex(ai_leverage.index)
        comp["news_momentum"] = _row_mean([
            percentile_score(nm.get("news_change", pd.Series(np.nan, index=nm.index))),
            percentile_score(nm.get("news_share_7d", pd.Series(np.nan, index=nm.index))),
        ])
    else:
        comp["news_momentum"] = np.nan

    return comp


def compute_total(components, weights):
    """
    가중 평균 총점과 구성요소별 기여도(총점에 더해지는 점수)를 계산합니다.
    - 뉴스 데이터가 전 산업에 없으면 뉴스 가중치를 빼고 나머지로 재정규화합니다.
    - 일부 산업만 뉴스가 없으면 그 산업은 중립값 50점으로 채워 산업 간 비교 기준을 맞춥니다.
    - 시장 데이터가 없는 산업은 총점을 비워 순위에서 제외합니다.
    """
    comp = components.copy()
    active = [c for c in COMPONENTS if weights.get(c, 0) > 0 and comp[c].notna().any()]

    if "news_momentum" in active:
        comp["news_momentum"] = comp["news_momentum"].fillna(50.0)

    total_weight = sum(weights[c] for c in active)
    contrib = pd.DataFrame(index=comp.index)
    for c in COMPONENTS:
        contrib[c] = comp[c] * weights[c] / total_weight if c in active and total_weight else 0.0

    total = contrib[active].sum(axis=1, min_count=len(active)) if active else pd.Series(np.nan, index=comp.index)
    no_market = comp["reversal_room"].isna() | comp["turn_momentum"].isna()
    total[no_market] = np.nan
    return total, contrib, active


def classify_phase(m):
    """시장 지표 dict/Series로 반전 국면을 판정합니다 (산업 간 비교가 아닌 절대 기준)."""
    def g(key):
        v = m.get(key, np.nan) if hasattr(m, "get") else np.nan
        return np.nan if v is None else v

    drawdown, rel_2y = g("drawdown_3y"), g("rel_2y")
    ret_1m, ma50_gap, accel, ret_12m = g("ret_1m"), g("ma50_gap"), g("accel"), g("ret_12m")
    if all(pd.isna(x) for x in (drawdown, ret_1m, ma50_gap)):
        return "no_data"

    depressed = (drawdown <= DEPRESSED_DRAWDOWN) or (rel_2y <= DEPRESSED_REL_2Y)
    turning = (ma50_gap > 0) and (ret_1m > 0) and (accel > 0)
    lifting = (ma50_gap > 0) or (ret_1m > 0)
    golden = m.get("ma50_above_ma200", False)
    trending = (not pd.isna(golden)) and bool(golden) and (ret_12m >= TRENDING_RET_12M)

    if depressed and turning:
        return "reversing"
    if depressed and lifting:
        return "early"
    if depressed:
        return "bottoming"
    if trending:
        return "trending"
    return "neutral"


def rank_industries(metrics, ai_leverage, weights, news_metrics=None):
    """
    최종 랭킹 테이블. index=산업 id, 총점 내림차순 정렬.
    columns: rank, total_score, 4개 구성요소, contrib_*, phase, 주요 시장/뉴스 지표
    """
    comp = compute_components(metrics, ai_leverage, news_metrics)
    total, contrib, active = compute_total(comp, weights)

    table = comp.copy()
    table["total_score"] = total
    for c in COMPONENTS:
        table[f"contrib_{c}"] = contrib[c]

    m = metrics.reindex(table.index)
    table["phase"] = [classify_phase(m.loc[i]) for i in table.index]
    for key in ("ret_1d", "ret_1m", "ret_3m", "ret_12m", "rel_3m", "rel_2y", "drawdown_3y", "accel", "ma50_gap", "last_date"):
        table[key] = m[key] if key in m.columns else np.nan
    if news_metrics is not None and not news_metrics.empty:
        nm = news_metrics.reindex(table.index)
        for key in ("news_change", "news_share_7d"):
            table[key] = nm[key] if key in nm.columns else np.nan
    else:
        table["news_change"] = np.nan
        table["news_share_7d"] = np.nan

    table = table.sort_values("total_score", ascending=False, na_position="last")
    table["rank"] = table["total_score"].rank(ascending=False, method="first").astype("Int64")
    table.attrs["active_components"] = active
    return table
