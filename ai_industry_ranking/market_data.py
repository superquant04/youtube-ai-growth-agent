"""
market_data.py

산업별 시장 신호 수집 및 지표 계산.

- fetch_close_prices      : Yahoo Finance(yfinance)에서 일별 종가를 한 번에 일괄 수집
                            (장중에는 마지막 행이 당일 실시간 가격, 약 15분 지연)
- build_industry_indices  : 산업별 ETF/바스켓을 하나의 지수 시계열로 합성
- compute_market_metrics  : 남은 반전·주가 반영도 계산에 쓰는 지표 (고점까지 거리, 상대수익률, 저점 대비 반등)
"""

import math

import numpy as np
import pandas as pd

from ai_industry_ranking.industries import BENCHMARK_ID, BENCHMARK_TICKER, INDUSTRIES

# 거래일 기준 기간
W12M, W2Y, W3Y = 252, 504, 756
MIN_HISTORY = 200  # 이보다 짧으면 장기 지표를 신뢰할 수 없어 산업을 제외


class MarketDataError(RuntimeError):
    pass


def fetch_close_prices(tickers, period="5y"):
    """
    여러 티커의 수정 종가를 일괄 다운로드합니다.
    반환: index=날짜, columns=티커 인 DataFrame. 수집에 실패한 티커는 컬럼에서 빠집니다.
    """
    import yfinance as yf  # 테스트에서 네트워크 없이 모듈을 불러올 수 있도록 지연 import

    try:
        raw = yf.download(
            list(tickers), period=period, interval="1d",
            auto_adjust=True, progress=False, threads=True,
        )
    except Exception as e:
        raise MarketDataError(f"Yahoo Finance 다운로드 실패: {e}") from e

    if raw is None or raw.empty:
        raise MarketDataError("Yahoo Finance에서 받은 가격 데이터가 없습니다 (네트워크 차단 또는 일시 장애).")

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": list(tickers)[0]})

    close = close.dropna(axis=1, how="all").sort_index()
    if close.empty:
        raise MarketDataError("모든 티커의 가격 데이터가 비어 있습니다.")
    return close


def build_industry_indices(close, industries=INDUSTRIES):
    """
    산업별 지수 시계열을 만듭니다. 티커가 여러 개면 일별 동일가중 리밸런싱 바스켓으로 합성합니다.
    반환 DataFrame의 컬럼: 산업 id들 + BENCHMARK_ID. 데이터가 없는 산업은 컬럼이 없습니다.
    """
    indices = {}
    for ind in industries:
        available = [t for t in ind.tickers if t in close.columns]
        if not available:
            continue
        indices[ind.id] = _equal_weight_index(close[available])

    if BENCHMARK_TICKER in close.columns:
        indices[BENCHMARK_ID] = _equal_weight_index(close[[BENCHMARK_TICKER]])

    return pd.DataFrame(indices)


def _equal_weight_index(prices):
    # 휴장일 차이로 생긴 빈칸은 직전 가격으로 채워 해당일 수익률을 0으로 둡니다.
    daily_returns = prices.ffill().pct_change(fill_method=None)
    basket_returns = daily_returns.mean(axis=1, skipna=True)
    first_valid = prices.dropna(how="all").index.min()
    basket_returns = basket_returns[basket_returns.index >= first_valid].fillna(0.0)
    return 100 * (1 + basket_returns).cumprod()


def compute_market_metrics(index, benchmark=None, as_of=None):
    """
    한 산업 지수의 점수 계산용 지표를 계산합니다. as_of를 주면 그 시점까지의 데이터만 사용합니다.

    반환 키
    - upside_to_high : 3년 고점을 되찾으려면 남은 상승률 (>= 0)      -> 남은 반전 점수
    - rel_2y         : 2년간 벤치마크(SPY) 대비 상대 수익률           -> 남은 반전 점수
    - rel_12m        : 1년간 SPY 대비 상대 수익률                     -> 주가 반영도
    - rebound_52w    : 52주 저점 대비 반등폭                          -> 주가 반영도
    - drawdown_3y    : 3년 고점 대비 낙폭 (<= 0, 표시용)
    """
    s = index.dropna()
    if as_of is not None:
        s = s[s.index <= as_of]

    metrics = {"last_date": s.index[-1] if len(s) else pd.NaT, "history_days": len(s)}
    if len(s) < MIN_HISTORY:
        return metrics

    b = None
    if benchmark is not None:
        b = benchmark.reindex(s.index).ffill()

    last = s.iloc[-1]
    if b is not None:
        for key, n in (("rel_12m", W12M), ("rel_2y", W2Y)):
            metrics[key] = _relative_return(_period_return(s, n), _period_return(b, n))

    high_3y = s.iloc[-W3Y:].max()
    metrics["drawdown_3y"] = last / high_3y - 1
    metrics["upside_to_high"] = high_3y / last - 1
    metrics["rebound_52w"] = last / s.iloc[-W12M:].min() - 1
    return metrics


def _period_return(s, n):
    if s is None or len(s) <= n:
        return np.nan
    prev = s.iloc[-1 - n]
    if _isnan(prev) or prev == 0:
        return np.nan
    return s.iloc[-1] / prev - 1


def _relative_return(r, rb):
    if _isnan(r) or _isnan(rb):
        return np.nan
    return (1 + r) / (1 + rb) - 1


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def compute_all_metrics(indices, as_of=None, industries=INDUSTRIES):
    """모든 산업의 시장 지표를 DataFrame(index=산업 id)으로 계산합니다."""
    benchmark = indices[BENCHMARK_ID] if BENCHMARK_ID in indices.columns else None
    rows = {}
    for ind in industries:
        if ind.id not in indices.columns:
            rows[ind.id] = {"history_days": 0}
            continue
        rows[ind.id] = compute_market_metrics(indices[ind.id], benchmark, as_of=as_of)
    return pd.DataFrame.from_dict(rows, orient="index")
