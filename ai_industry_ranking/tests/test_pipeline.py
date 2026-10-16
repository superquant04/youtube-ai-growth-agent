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
    assert m["upside_to_high"] == pytest.approx(1 / (1 + m["drawdown_3y"]) - 1)


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


def test_unpriced_is_ai_potential_times_unreflected_share():
    idx = ["a", "b", "c"]
    metrics = pd.DataFrame({
        "upside_to_high": [0.8, 0.4, 0.0],
        "rel_2y": [-0.5, -0.2, 0.3],
        "rel_12m": [-0.3, 0.0, 0.5],
        "rebound_52w": [0.05, 0.2, 0.6],
    }, index=idx)
    lev = pd.Series([80.0, 80.0, 80.0], index=idx)
    comp = scoring.compute_components(metrics, lev)

    # 가장 덜 오른 a는 반영도 0, 가장 많이 오른 c는 반영도 1
    assert comp["priced_in"].tolist() == pytest.approx([0.0, 0.5, 1.0])
    assert comp["unpriced"].tolist() == pytest.approx([80.0, 40.0, 0.0])
    # 고점까지 많이 남고 2년간 가장 부진한 a가 남은 반전 최대
    assert comp["remaining_reversal"].tolist() == pytest.approx([100.0, 50.0, 0.0])


def test_total_is_weighted_mean_and_needs_both_components():
    comp = pd.DataFrame({"remaining_reversal": [80.0, 40.0, np.nan], "unpriced": [20.0, 60.0, 50.0]},
                        index=["a", "b", "c"])
    total, contrib, active = scoring.compute_total(comp, {"remaining_reversal": 75, "unpriced": 25})
    assert active == ["remaining_reversal", "unpriced"]
    assert total["a"] == pytest.approx(0.75 * 80 + 0.25 * 20)
    assert contrib.loc["b"].sum() == pytest.approx(total["b"])
    assert np.isnan(total["c"])

    total, _, active = scoring.compute_total(comp, {"remaining_reversal": 0, "unpriced": 100})
    assert active == ["unpriced"]
    assert total["b"] == pytest.approx(60.0)


def test_momentum_and_news_not_in_score():
    assert scoring.COMPONENTS == ["remaining_reversal", "unpriced"]


# ---------------------------------------------------------------------------
# ranking (end-to-end on fixtures)
# ---------------------------------------------------------------------------

@pytest.fixture
def indices():
    return market_data.build_industry_indices(synthetic_close())


def test_build_ranking_end_to_end(indices):
    table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS)

    assert len(table) == len(INDUSTRIES)
    assert table["rank"].tolist() == list(range(1, len(INDUSTRIES) + 1))
    assert table["total_score"].is_monotonic_decreasing
    assert table["total_score"].between(0, 100).all()
    assert table["rank_change"].notna().all()
    contrib_cols = [f"contrib_{c}" for c in scoring.COMPONENTS]
    assert table[contrib_cols].sum(axis=1).to_numpy() == pytest.approx(table["total_score"].to_numpy())

    # 하락이 이어진 부동산은 남은 반전 상위권, 꾸준히 오른 반도체는 남은 반전·미반영 모두 최하위 -> 꼴찌
    assert table.loc["real_estate", "remaining_reversal"] >= 75
    assert table.loc["semis", "remaining_reversal"] == table["remaining_reversal"].min()
    assert table.loc["semis", "priced_in"] > 0.9
    assert table.index[-1] == "semis"
    # 바이오는 고점까지 거리는 크지만 최근 1년 이미 크게 반등 -> 주가 반영도가 높아 미반영 점수는 낮음
    assert table.loc["biotech", "upside_to_high"] > 0.3
    assert table.loc["biotech", "priced_in"] > 0.9 and table.loc["biotech", "unpriced"] < 10
    # 국면은 참고 표시로 계속 제공
    assert table.loc["biotech", "phase"] == "reversing"
    assert table.loc["semis", "phase"] == "trending"
    assert table.loc["real_estate", "phase"] == "bottoming"


def test_rallied_industry_scores_lower_with_equal_ai_potential(indices):
    lev = pd.Series(70.0, index=ranking.default_ai_leverage().index)
    table = ranking.build_ranking(indices, {"remaining_reversal": 0, "unpriced": 100}, ai_leverage=lev)
    # AI 잠재력이 같으면 최근 1년간 덜 오른(반영도 낮은) 산업일수록 주가 미반영 점수가 높다
    assert table["unpriced"].rank().corr(table["priced_in"].rank()) == pytest.approx(-1.0)


def test_ai_leverage_override_changes_rank(indices):
    base = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS)
    target = base["priced_in"].idxmin()
    lev = ranking.default_ai_leverage()
    lev[target] = 100.0
    lev[lev.index != target] = 0.0
    table = ranking.build_ranking(indices, {"remaining_reversal": 0, "unpriced": 100}, ai_leverage=lev)
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

    table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS)
    names = {i.id: i.name for i in INDUSTRIES}
    storage.save_ranking_snapshot(table, names, db_file=db)
    hist = storage.load_rank_history(db_file=db)
    assert len(hist) == len(INDUSTRIES)
    top = hist.sort_values("rank").iloc[0]
    assert top["industry_id"] == table.index[0]
    assert top["unpriced"] == pytest.approx(table.iloc[0]["unpriced"])


def test_cached_news_with_stale_query_is_ignored(tmp_path):
    db = str(tmp_path / "t.db")
    storage.init_db(db)
    storage.save_news_timeline(INDUSTRIES[0].id, "old query", synthetic_news()[INDUSTRIES[0].id], db_file=db)
    loaded, fetched_at = ranking.load_cached_news(db_file=db)
    assert loaded == {} and fetched_at is None
