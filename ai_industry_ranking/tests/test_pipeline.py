import numpy as np
import pandas as pd
import pytest

from ai_industry_ranking import market_data, ranking, scoring, storage
from ai_industry_ranking.industries import BENCHMARK_ID, INDUSTRIES, Industry, compute_ai_leverage
from ai_industry_ranking.tests.fixtures import path, synthetic_close


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


# ---------------------------------------------------------------------------
# market_data
# ---------------------------------------------------------------------------

def test_equal_weight_basket_index():
    idx = pd.bdate_range("2026-01-01", periods=3)
    close = pd.DataFrame({"A": [100, 110, 121], "B": [50, 50, 55]}, index=idx, dtype=float)
    ind = Industry("basket", "b", ("A", "B"), 3, 3, 3, 3, "", "")
    out = market_data.build_industry_indices(close, [ind])
    # 일별 수익률 평균: day2 = (10% + 0%)/2 = 5%, day3 = (10% + 10%)/2 = 10%
    assert out["basket"].tolist() == pytest.approx([100, 105, 115.5])


def test_basket_handles_ticker_with_shorter_history():
    idx = pd.bdate_range("2026-01-01", periods=4)
    close = pd.DataFrame({"A": [100, 110, 121, 121], "B": [np.nan, np.nan, 50, 55]}, index=idx)
    ind = Industry("basket", "b", ("A", "B"), 3, 3, 3, 3, "", "")
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

    assert m["drawdown_3y"] < -0.15
    assert m["upside_to_high"] == pytest.approx(1 / (1 + m["drawdown_3y"]) - 1)
    assert m["rel_2y"] < 0
    assert m["rebound_52w"] == pytest.approx(s.iloc[-1] / s.iloc[-252:].min() - 1)
    # 점수에 쓰이지 않는 단기 지표는 계산하지 않음
    assert not {"ret_1d", "ret_1m", "accel", "ma50_gap"} & set(m)


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
# scoring
# ---------------------------------------------------------------------------

def test_percentile_score():
    s = scoring.percentile_score(pd.Series([3.0, 1.0, np.nan, 2.0]))
    assert s.tolist()[:2] == [100.0, 0.0]
    assert np.isnan(s.iloc[2]) and s.iloc[3] == 50.0
    assert scoring.percentile_score(pd.Series([1.0, 3.0]), higher_is_better=False).tolist() == [100.0, 0.0]


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


def test_only_two_components():
    assert scoring.COMPONENTS == ["remaining_reversal", "unpriced"]
    assert set(scoring.DEFAULT_WEIGHTS) == set(scoring.COMPONENTS)


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
    assert "phase" not in table.columns


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


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def test_storage_roundtrip(tmp_path, indices):
    db = str(tmp_path / "t.db")
    storage.init_db(db)

    table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS)
    names = {i.id: i.name for i in INDUSTRIES}
    storage.save_ranking_snapshot(table, names, db_file=db)
    hist = storage.load_rank_history(db_file=db)
    assert len(hist) == len(INDUSTRIES)
    top = hist.sort_values("rank").iloc[0]
    assert top["industry_id"] == table.index[0]
    assert top["unpriced"] == pytest.approx(table.iloc[0]["unpriced"])


# ---------------------------------------------------------------------------
# export (claude.ai 대시보드 업로드용 JSON)
# ---------------------------------------------------------------------------

def test_ranking_json_is_plain_json(tmp_path, indices):
    import json

    from ai_industry_ranking import export

    table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS)
    path = tmp_path / "ranking.json"
    export.write_ranking_json(table, str(path), "2026-10-16T21:00:00+00:00")
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]

    assert len(rows) == len(INDUSTRIES)
    assert [r["rank"] for r in rows] == list(range(1, len(INDUSTRIES) + 1))
    top = rows[0]
    assert top["industry_id"] == table.index[0] and top["market_date"] == "2026-10-16"
    assert top["total_score"] == pytest.approx(table.iloc[0]["total_score"], abs=0.05)
    assert all(type(r["rank"]) is int for r in rows)


def test_history_merge_replaces_same_market_date(tmp_path, indices):
    import json

    from ai_industry_ranking import export

    path = str(tmp_path / "history.json")
    for as_of in (indices.index[-6], indices.index[-1], indices.index[-1]):
        table = ranking.build_ranking(indices, scoring.DEFAULT_WEIGHTS, as_of=as_of)
        n_dates = export.merge_history(table, path, "t")
    rows = json.loads(open(path, encoding="utf-8").read())["rows"]
    assert n_dates == 2
    assert len(rows) == 2 * len(INDUSTRIES)

    export.merge_history(table, path, "t", keep_dates=1)
    rows = json.loads(open(path, encoding="utf-8").read())["rows"]
    assert {r["market_date"] for r in rows} == {"2026-10-16"}
