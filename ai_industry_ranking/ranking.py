"""
ranking.py

수집(market_data, news_data) -> 점수화(scoring) -> 저장(storage)을 잇는 오케스트레이션 계층.
Streamlit 앱(industry_ranking_app.py)과 CLI(collect.py)가 공통으로 사용합니다.
"""

import numpy as np
import pandas as pd

from ai_industry_ranking import market_data, news_data, scoring, storage
from ai_industry_ranking.industries import INDUSTRIES, INDUSTRY_BY_ID, all_tickers, build_news_query


def default_ai_leverage():
    return pd.Series({ind.id: ind.ai_leverage for ind in INDUSTRIES}, name="ai_leverage")


def fetch_market_indices(period="5y"):
    """실시간(약 15분 지연) 가격을 받아 산업 지수 DataFrame으로 변환합니다."""
    close = market_data.fetch_close_prices(all_tickers(), period=period)
    return market_data.build_industry_indices(close)


def news_metrics_frame(news_series, as_of=None):
    if not news_series:
        return None
    rows = {iid: news_data.compute_news_metrics(s, as_of=as_of) for iid, s in news_series.items()}
    frame = pd.DataFrame.from_dict(rows, orient="index")
    return frame if not frame.empty else None


def build_ranking(indices, weights, news_series=None, ai_leverage=None, as_of=None, compare_days=5):
    """
    산업 랭킹 테이블을 계산합니다.

    indices      : fetch_market_indices() 결과
    weights      : {구성요소: 가중치}
    news_series  : {산업 id: 일별 뉴스 비중 Series} 또는 None (뉴스 신호 제외)
    ai_leverage  : 사용자가 수정한 AI 레버리지 점수 Series (없으면 기본 가정치)
    compare_days : 순위 변동 비교 기준 (거래일 수, 5 = 1주 전)
    """
    ai_leverage = default_ai_leverage() if ai_leverage is None else ai_leverage

    dates = indices.dropna(how="all").index
    if as_of is not None:
        dates = dates[dates <= as_of]
    if len(dates) == 0:
        raise market_data.MarketDataError("계산할 가격 데이터가 없습니다.")
    as_of = dates[-1]

    table = _rank_at(indices, weights, news_series, ai_leverage, as_of)

    prev_as_of = dates[-1 - compare_days] if len(dates) > compare_days else None
    if prev_as_of is not None:
        prev = _rank_at(indices, weights, news_series, ai_leverage, prev_as_of)
        table["prev_rank"] = prev["rank"].reindex(table.index)
        table["prev_total_score"] = prev["total_score"].reindex(table.index)
    else:
        table["prev_rank"] = pd.NA
        table["prev_total_score"] = np.nan
    table["rank_change"] = (table["prev_rank"] - table["rank"]).astype("Int64")

    table["name"] = [INDUSTRY_BY_ID[i].name for i in table.index]
    table["tickers"] = [INDUSTRY_BY_ID[i].ticker_label for i in table.index]
    table["phase_label"] = table["phase"].map(scoring.PHASES)

    table.attrs["as_of"] = as_of
    table.attrs["prev_as_of"] = prev_as_of
    return table


def _rank_at(indices, weights, news_series, ai_leverage, as_of):
    metrics = market_data.compute_all_metrics(indices, as_of=as_of)
    nm = news_metrics_frame(news_series, as_of=as_of)
    return scoring.rank_industries(metrics, ai_leverage, weights, nm)


def refresh_news(industries=INDUSTRIES, progress_cb=None, db_file=None):
    """
    전 산업의 GDELT 뉴스 시계열을 새로 받아 DB에 저장합니다 (요청 제한으로 산업당 약 5.5초).
    반환: ({산업 id: Series}, {산업 id: 오류 메시지})
    """
    storage.init_db(db_file)
    series, errors = {}, {}
    for i, ind in enumerate(industries):
        if progress_cb:
            progress_cb(i, len(industries), ind)
        query = build_news_query(ind)
        try:
            s = news_data.fetch_news_timeline(query)
        except news_data.NewsFetchError as e:
            errors[ind.id] = str(e)
            continue
        series[ind.id] = s
        if len(s):
            storage.save_news_timeline(ind.id, query, s, db_file=db_file)
    if progress_cb:
        progress_cb(len(industries), len(industries), None)
    return series, errors


def load_cached_news(db_file=None):
    """
    DB에 캐시된 뉴스 시계열을 불러옵니다. 산업 정의의 쿼리가 바뀐 캐시는 무시합니다.
    반환: ({산업 id: Series}, 가장 오래된 수집 시각 ISO 문자열 또는 None)
    """
    storage.init_db(db_file)
    cached = storage.load_news_timelines(db_file)
    series, fetched = {}, []
    for iid, (fetched_at, query, s) in cached.items():
        ind = INDUSTRY_BY_ID.get(iid)
        if ind is None or query != build_news_query(ind):
            continue
        series[iid] = s
        fetched.append(fetched_at)
    return series, (min(fetched) if fetched else None)
