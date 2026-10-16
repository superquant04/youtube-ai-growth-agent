"""
scoring.py

"AI 상승 반전 점수" 계산. 이미 일어난 상승은 빼고 앞으로 남은 몫만
두 가지 구성요소(0~100점)로 평가해 가중 평균합니다. 다른 구성요소는 없습니다.

| 구성요소            | 의미                                        | 계산                                                        |
|---------------------|---------------------------------------------|-------------------------------------------------------------|
| remaining_reversal  | 앞으로 남은 반전 (가격이 되찾을 거리)       | 3년 고점 회복까지 남은 상승률, 2년 SPY 대비 부진폭의 백분위 |
| unpriced            | AI 잠재력 중 아직 주가에 반영되지 않은 몫   | AI 잠재력 × (1 − 주가 반영도)                               |

- AI 잠재력: industries.py의 4요소 가정치 (0~100, 편집 가능)
- 주가 반영도(0~1): 1년 SPY 대비 상대수익률, 52주 저점 대비 반등폭의 백분위 평균.
  최근 1년 동안 이미 많이 오른 산업일수록 AI 잠재력이 주가에 반영됐다고 봅니다.

시장 지표는 산업 간 상대 백분위(0~100)로 바꿔 단위가 다른 지표를 합칩니다.
"""

import numpy as np
import pandas as pd

COMPONENTS = ["remaining_reversal", "unpriced"]

COMPONENT_LABELS = {
    "remaining_reversal": "남은 반전 점수",
    "unpriced": "주가 미반영 점수",
}

DEFAULT_WEIGHTS = {
    "remaining_reversal": 50,
    "unpriced": 50,
}

# 랭킹 테이블에 함께 싣는 시장 지표 (두 구성요소의 입력값)
METRIC_COLUMNS = ("upside_to_high", "drawdown_3y", "rel_2y", "rel_12m", "rebound_52w", "last_date")


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


def compute_components(metrics, ai_leverage):
    """
    metrics     : market_data.compute_all_metrics 결과 (index=산업 id)
    ai_leverage : Series(index=산업 id, 0~100) - AI 잠재력

    반환 columns: remaining_reversal, unpriced, ai_leverage, priced_in(0~1)
    """
    m = metrics.reindex(ai_leverage.index)

    def col(name):
        return m[name] if name in m.columns else pd.Series(np.nan, index=m.index)

    comp = pd.DataFrame(index=ai_leverage.index)
    comp["remaining_reversal"] = _row_mean([
        percentile_score(col("upside_to_high")),
        percentile_score(col("rel_2y"), higher_is_better=False),
    ])
    comp["priced_in"] = _row_mean([
        percentile_score(col("rel_12m")),
        percentile_score(col("rebound_52w")),
    ]) / 100
    comp["ai_leverage"] = ai_leverage.astype(float)
    comp["unpriced"] = comp["ai_leverage"] * (1 - comp["priced_in"])
    return comp


def compute_total(components, weights):
    """
    가중 평균 총점과 구성요소별 기여도(총점에 더해지는 점수)를 계산합니다.
    두 구성요소 중 하나라도 계산할 수 없는 산업(시장 데이터 부족)은 총점을 비워 순위에서 제외합니다.
    """
    active = [c for c in COMPONENTS if weights.get(c, 0) > 0]
    total_weight = sum(weights[c] for c in active)

    contrib = pd.DataFrame(index=components.index)
    for c in COMPONENTS:
        contrib[c] = components[c] * weights[c] / total_weight if c in active else 0.0

    if not active:
        return pd.Series(np.nan, index=components.index), contrib, active

    total = contrib[active].sum(axis=1, min_count=len(active))
    total[components[COMPONENTS].isna().any(axis=1)] = np.nan
    return total, contrib, active


def rank_industries(metrics, ai_leverage, weights):
    """
    최종 랭킹 테이블. index=산업 id, 총점 내림차순 정렬.
    columns: rank, total_score, 구성요소 점수, contrib_*, ai_leverage, priced_in, 입력 시장 지표
    """
    table = compute_components(metrics, ai_leverage)
    total, contrib, active = compute_total(table, weights)

    table["total_score"] = total
    for c in COMPONENTS:
        table[f"contrib_{c}"] = contrib[c]

    m = metrics.reindex(table.index)
    for key in METRIC_COLUMNS:
        table[key] = m[key] if key in m.columns else np.nan

    table = table.sort_values("total_score", ascending=False, na_position="last")
    table["rank"] = table["total_score"].rank(ascending=False, method="first").astype("Int64")
    table.attrs["active_components"] = active
    return table
