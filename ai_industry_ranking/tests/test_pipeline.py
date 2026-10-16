import numpy as np
import pandas as pd
import pytest

from ai_industry_ranking import market_data, news_data, ranking, scoring, storage
from ai_industry_ranking.industries import (
    BENCHMARK_ID, INDUSTRIES, Industry, build_news_query, compute_ai_leverage,
)
from ai_industry_ranking.tests.fixtures import path, synthetic_close, synthetic_news


# ---------------------------------------------------------------------------
# industries
# ---------------------------------------------------------------------------

def test_ai_leverage_bounds():
    assert compute_ai_leverage(1, 1, 1, 5) == 0
    assert compute_ai_leverage(5, 5, 5, 1) == 100
    for ind in INDUSTRIES:
        assert 0 <= ind.ai_leverage <= 100


def test_industry_ids_unique():
    ids = [ind.id for ind in INDUSTRIES]
    assert len(ids) == len(set(ids))


def test_news_query_format():
    ind = Industry("x", "x", ("X",), ("drug discovery", "biotech"), 3, 3, 3, 3, "", "")
    assert build_news_query(ind) == '("artificial intelligence" OR "machine learning") ("drug discovery" OR biotech)'
    single = Industry("y", "y", ("Y",), ("robotics",), 3, 3, 3, 3, "", "")
    assert build_news_query(single).endswith(" robotics")


def test_news_keywords_long_enough_for_gdelt():
    # GDELT는 3글자 미만 단어를 거부하므로 키워드의 모든 단어가 3글자 이상이어야 합니다.
    for ind in INDUSTRIES:
        for kw in ind.news_keywords:
            assert all(len(w) >= 3 for w in kw.split()), (ind.id, kw)


# ---------------------------------------------------------------------------
# market_data
# ---------------------------------------------------------------------------

def test_equal_weight_basket_index():
    idx = pd.bdate_range("2026-01-01", periods=3)
    close = pd.DataFrame({"A": [100, 110, 121], "B": [50, 50, 55]}, index=idx, dtype=float)
    ind = Industry("basket", "b", ("A", "B"), ("x",), 3, 3, 3, 3, "", "")
    out = market_data.build_industry_indices(close, [ind])
    # 일별 수익률 평균: day2 = (10% + 0%)/2 = 5%, day3 = (10% + 10%)/2 = 10%
    assert out["basket"].tolist() == pytest.approx([100, 105, 115.5])


def test_basket_handles_ticker_with_shorter_history():
    idx = pd.bdate_range("2026-01-01", periods=4)
    close = pd.DataFrame({"A": [100, 110, 121, 121], "B": [np.nan, np.nan, 50, 55]}, index=idx)
    ind = Industry("basket", "b", ("A", "B"), ("x",), 3, 3, 3, 3, "", "")
    out = market_data.build_industry_indices(close, [ind])["basket"]
    assert out.notna().all()
    assert out.iloc[-1] == pytest.approx(100 * 1.1 * 1.1 * 1.05)


def test_missing_ticker_drops_industry():
    close = pd.DataFrame({"SPY": [1.0, 2.0]}, index=pd.bdate_range("2026-01-01", periods=2))
    out = market_data.build_industry_indices(close)
    assert list(out.columns) == [BENCHMARK_ID]


def test_market_metrics_values():
    n = 800
    idx = pd.bdate_range(end="2026-10-16", periods=n)
    s = pd.Series(path(n, [(0.75, -0.40), (0.25, 0.25)]), index=idx)
    bench = pd.Series(path(n, [(1.0, 0.30)]), index=idx)
    m = market_data.compute_market_metrics(s, bench)

    assert m["ret_1m"] == pytest.approx(s.iloc[-1] / s.iloc[-22] - 1)
    assert m["drawdown_3y"] < -0.15
    assert m["rel_2y"] < 0
    assert m["ret_1m"] > 0 and m["accel"] > 0 and m["ma50_gap"] > 0


def test_market_metrics_as_of_ignores_future():
    close = synthetic_close()
    indices = market_data.build_industry_indices(close)
    as_of = indices.index[-30]
    m = market_data.compute_market_metrics(indices["biotech"], indices[BENCHMARK_ID], as_of=as_of)
    assert m["last_date"] == as_of


def test_short_history_returns_no_long_metrics():
    idx = pd.bdate_range(end="2026-10-16", periods=50)
    m = market_data.compute_market_metrics(pd.Series(np.linspace(1, 2, 50), index=idx))
    assert "drawdown_3y" not in m


# ---------------------------------------------------------------------------
# news_data
# ---------------------------------------------------------------------------

def test_parse_timeline_aggregates_to_daily():
    payload = {"timeline": [{"series": "Volume Intensity", "data": [
        {"date": "20261014T000000Z", "value": 0.2},
        {"date": "20261014T120000Z", "value": 0.4},
        {"date": "20261015T000000Z", "value": 0.5},
    ]}]}
    s = news_data.parse_timeline(payload)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-10-14", "2026-10-15"]
    assert s.tolist() == pytest.approx([0.3, 0.5])


def test_parse_gdelt_dates_fallback_format():
    out = news_data.parse_gdelt_dates(pd.Series(["2026-10-15T12:00:00Z"]))
    assert out.iloc[0] == pd.Timestamp("2026-10-15 12:00:00")


def test_fetch_latest_articles_parses(monkeypatch):
    class Resp:
        status_code = 200
        text = '{"articles": [{"url": "https://e.com/a", "title": " AI drug ", "seendate": "20261015T120000Z", "domain": "e.com"}]}'

    monkeypatch.setattr(news_data, "MIN_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(news_data.requests, "get", lambda *a, **k: Resp())
    [a] = news_data.fetch_latest_articles("x")
    assert a["title"] == "AI drug" and a["seendate"] == pd.Timestamp("2026-10-15 12:00:00")


@pytest.mark.parametrize("payload", [None, {}, {"timeline": []}, {"timeline": [{"data": []}]}])
def test_parse_timeline_empty(payload):
    assert news_data.parse_timeline(payload).empty


def test_news_metrics_detects_surge():
    s = synthetic_news()["biotech"]
    m = news_data.compute_news_metrics(s)
    assert m["news_change"] == pytest.approx(2.0, rel=1e-3)


def test_news_metrics_short_series():
    s = pd.Series([0.1] * 10, index=pd.date_range(end="2026-10-16", periods=10))
    assert news_data.compute_news_metrics(s) == {}


def test_gdelt_non_json_raises(monkeypatch):
    class Resp:
        status_code = 200
        text = "Please limit requests to one every 5 seconds"

    monkeypatch.setattr(news_data, "MIN_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(news_data.requests, "get", lambda *a, **k: Resp())
    with pytest.raises(news_data.NewsFetchError):
        news_data.fetch_news_timeline("x")


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def test_percentile_score():
    s = scoring.percentile_score(pd.Series([3.0, 1.0, np.nan, 2.0]))
    assert s.tolist()[:2] == [100.0, 0.0]
    assert np.isnan(s.iloc[2]) and s.iloc[3] == 50.0
    assert scoring.percentile_score(pd.Series([1.0, 3.0]), higher_is_better=False).tolist() == [100.0, 0.0]


def test_phase_rules():
    assert scoring.classify_phase({"drawdown_3y": -0.4, "ma50_gap": 0.05, "ret_1m": 0.05, "accel": 0.1}) == "reversing"
    assert scoring.classify_phase({"drawdown_3y": -0.4, "ma50_gap": 0.05, "ret_1m": -0.01, "accel": -0.1}) == "early"
    assert scoring.classify_phase({"drawdown_3y": -0.4, "ma50_gap": -0.05, "ret_1m": -0.05, "accel": -0.1}) == "bottoming"
    assert scoring.classify_phase({"drawdown_3y": -0.02, "rel_2y": 0.3, "ma50_gap": 0.03, "ret_1m": 0.02,
                                   "accel": 0.0, "ret_12m": 0.4, "ma50_above_ma200": True}) == "trending"
    assert scoring.classify_phase({"drawdown_3y": np.nan, "ma50_gap": np.nan, "ret_1m": np.nan}) == "no_data"


def test_weights_renormalize_without_news():
    comp = pd.DataFrame({
        "ai_leverage": [80.0, 40.0], "reversal_room": [50.0, 50.0],
        "turn_momentum": [50.0, 50.0], "news_momentum": [np.nan, np.nan],
    }, index=["a", "b"])
    total, contrib, active = scoring.compute_total(comp, scoring.DEFAULT_WEIGHTS)
    assert "news_momentum" not in active
    w = scoring.DEFAULT_WEIGHTS
    expected_a = (80 * w["ai_leverage"] + 50 * w["reversal_room"] + 50 * w["turn_momentum"]) / (
        w["ai_leverage"] + w["reversal_room"] + w["turn_momentum"])
    assert total["a"] == pytest.approx(expected_a)
    assert contrib.loc["a"].sum() == pytest.approx(total["a"])


def test_partial_news_filled_neutral():
    comp = pd.DataFrame({
        "ai_leverage": [50.0, 50.0], "reversal_room": [50.0, 50.0],
        "turn_momentum": [50.0, 50.0], "news_momentum": [100.0, np.nan],
    }, index=["a", "b"])
    total, _, active = scoring.compute_total(comp, scoring.DEFAULT_WEIGHTS)
    assert "news_momentum" in active
    assert total["b"] == pytest.approx(50.0)
    assert total["a"] > total["b"]


# ---------------------------------------------------------------------------
# ranking (end-to-end on fixtures)
# ---------------------------------------------------------------------------

@pytest.fixture
def indices():
    return market_data.build_industry_indices(synthetic_close())


def test_build_ranking_end_to_end(indices):
    table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS, news_series=synthetic_news())

    assert len(table) == len(INDUSTRIES)
    assert table["rank"].tolist() == list(range(1, len(INDUSTRIES) + 1))
    assert table["total_score"].is_monotonic_decreasing
    assert table["total_score"].between(0, 100).all()
    assert "news_momentum" in table.attrs["active_components"]

    # 장기 하락 후 반등 + 뉴스 급증 + 높은 AI 레버리지 -> 최상위
    assert table.index[0] == "biotech"
    assert table.loc["biotech", "phase"] == "reversing"
    assert table.loc["semis", "phase"] == "trending"
    assert table.loc["real_estate", "phase"] == "bottoming"
    assert table["rank_change"].notna().all()


def test_build_ranking_without_news(indices):
    table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS)
    assert "news_momentum" not in table.attrs["active_components"]
    assert (table["contrib_news_momentum"] == 0).all()
    contrib_cols = [f"contrib_{c}" for c in scoring.COMPONENTS]
    assert table[contrib_cols].sum(axis=1).to_numpy() == pytest.approx(table["total_score"].to_numpy())


def test_ai_leverage_override_changes_rank(indices):
    base = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS)
    target = base.index[-1]
    lev = ranking.default_ai_leverage()
    lev[target] = 100.0
    lev[lev.index != target] = 0.0
    weights = {"ai_leverage": 100, "reversal_room": 0, "turn_momentum": 0, "news_momentum": 0}
    table = ranking.build_ranking(indices, weights, ai_leverage=lev)
    assert table.index[0] == target


def test_industry_without_market_data_ranked_last():
    close = synthetic_close().drop(columns=["XBI"])
    indices = market_data.build_industry_indices(close)
    table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS)
    assert table.index[-1] == "biotech"
    assert pd.isna(table.loc["biotech", "total_score"])
    assert table.loc["biotech", "phase"] == "no_data"


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def test_storage_roundtrip(tmp_path, indices):
    db = str(tmp_path / "t.db")
    storage.init_db(db)

    news = synthetic_news()
    ind = INDUSTRIES[0]
    storage.save_news_timeline(ind.id, build_news_query(ind), news[ind.id], db_file=db)
    loaded, fetched_at = ranking.load_cached_news(db_file=db)
    assert fetched_at is not None
    pd.testing.assert_series_equal(loaded[ind.id], news[ind.id], check_names=False, check_freq=False)

    table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS, news_series=news)
    names = {i.id: i.name for i in INDUSTRIES}
    storage.save_ranking_snapshot(table, names, news_included=True, db_file=db)
    hist = storage.load_rank_history(db_file=db)
    assert len(hist) == len(INDUSTRIES)
    assert hist.sort_values("rank").iloc[0]["industry_id"] == table.index[0]


def test_cached_news_with_stale_query_is_ignored(tmp_path):
    db = str(tmp_path / "t.db")
    storage.init_db(db)
    storage.save_news_timeline(INDUSTRIES[0].id, "old query", synthetic_news()[INDUSTRIES[0].id], db_file=db)
    loaded, fetched_at = ranking.load_cached_news(db_file=db)
    assert loaded == {} and fetched_at is None
