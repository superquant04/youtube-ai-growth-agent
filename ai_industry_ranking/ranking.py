"""
ranking.py

수집(market_data) -> 점수화(scoring) -> 저장(storage)을 잇는 오케스트레이션 계층.
Streamlit 앱(industry_ranking_app.py)과 CLI(collect.py)가 공통으로 사용합니다.

점수는 남은 반전 점수와 주가 미반영 점수 두 가지로만 계산합니다.
"""

import numpy as np
import pandas as pd

from ai_industry_ranking import market_data, scoring
from ai_industry_ranking.industries import INDUSTRIES, INDUSTRY_BY_ID, all_tickers


def default_ai_leverage():
    return pd.Series({ind.id: ind.ai_leverage for ind in INDUSTRIES}, name="ai_leverage")


def fetch_market_indices(period="5y"):
    """실시간(약 15분 지연) 가격을 받아 산업 지수 DataFrame으로 변환합니다."""
    close = market_data.fetch_close_prices(all_tickers(), period=period)
    return market_data.build_industry_indices(close)


def build_ranking(indices, weights, ai_leverage=None, as_of=None, compare_days=5):
    """
    산업 랭킹 테이블을 계산합니다.

    indices      : fetch_market_indices() 결과
    weights      : {구성요소: 가중치} (scoring.COMPONENTS)
    ai_leverage  : 사용자가 수정한 AI 잠재력 점수 Series (없으면 기본 가정치)
    compare_days : 순위 변동 비교 기준 (거래일 수, 5 = 1주 전)
    """
    ai_leverage = default_ai_leverage() if ai_leverage is None else ai_leverage

    dates = indices.dropna(how="all").index
    if as_of is not None:
        dates = dates[dates <= as_of]
    if len(dates) == 0:
        raise market_data.MarketDataError("계산할 가격 데이터가 없습니다.")
    as_of = dates[-1]

    table = _rank_at(indices, weights, ai_leverage, as_of)

    prev_as_of = dates[-1 - compare_days] if len(dates) > compare_days else None
    if prev_as_of is not None:
        prev = _rank_at(indices, weights, ai_leverage, prev_as_of)
        table["prev_rank"] = prev["rank"].reindex(table.index)
        table["prev_total_score"] = prev["total_score"].reindex(table.index)
    else:
        table["prev_rank"] = pd.NA
        table["prev_total_score"] = np.nan
    table["rank_change"] = (table["prev_rank"] - table["rank"]).astype("Int64")

    table["name"] = [INDUSTRY_BY_ID[i].name for i in table.index]
    table["tickers"] = [INDUSTRY_BY_ID[i].ticker_label for i in table.index]

    table.attrs["as_of"] = as_of
    table.attrs["prev_as_of"] = prev_as_of
    return table


def _rank_at(indices, weights, ai_leverage, as_of):
    metrics = market_data.compute_all_metrics(indices, as_of=as_of)
    return scoring.rank_industries(metrics, ai_leverage, weights)

