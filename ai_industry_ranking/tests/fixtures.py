"""테스트용 합성 가격/뉴스 시계열 (네트워크 없이 파이프라인을 검증하기 위한 고정 데이터)."""

import numpy as np
import pandas as pd

from ai_industry_ranking.industries import BENCHMARK_TICKER, INDUSTRIES


def business_days(n=1000, end="2026-10-16"):
    return pd.bdate_range(end=end, periods=n)


def path(n, segments, start=100.0):
    """segments = [(비율, 총수익률), ...] 구간별 로그선형 가격 경로."""
    parts, total = [], 0
    for i, (frac, ret) in enumerate(segments):
        k = n - total if i == len(segments) - 1 else int(n * frac)
        parts.append(np.full(k, np.log1p(ret) / k))
        total += k
    return start * np.exp(np.cumsum(np.concatenate(parts)))


def synthetic_close(n=1000, seed=7):
    """
    산업별로 서로 다른 국면이 나오도록 만든 종가 DataFrame.
    - biotech     : 장기 하락 후 최근 강한 반등 (반전 진행)
    - semis       : 꾸준한 강세 (상승 추세)
    - real_estate : 하락 지속 (바닥 탐색)
    - 나머지       : 완만한 랜덤워크
    """
    idx = business_days(n)
    rng = np.random.default_rng(seed)
    data = {BENCHMARK_TICKER: path(n, [(1.0, 0.45)])}

    special = {
        "XBI": path(n, [(0.80, -0.60), (0.20, 0.30)]),
        "SOXX": path(n, [(1.0, 1.60)]),
        "XLRE": path(n, [(0.90, -0.35), (0.10, -0.08)]),
    }
    for ind in INDUSTRIES:
        for t in ind.tickers:
            if t in special:
                data[t] = special[t]
            elif t not in data:
                drift = rng.normal(0.0002, 0.0002)
                data[t] = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    return pd.DataFrame(data, index=idx)


def synthetic_news(days=90, end="2026-10-16"):
    """biotech은 최근 7일 뉴스 비중이 급증, 나머지는 평탄."""
    idx = pd.date_range(end=end, periods=days, freq="D")
    out = {}
    for i, ind in enumerate(INDUSTRIES):
        base = 0.05 + 0.01 * i
        values = np.full(days, base)
        if ind.id == "biotech":
            values[-7:] = base * 3
        out[ind.id] = pd.Series(values, index=idx)
    return out
