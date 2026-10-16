"""Streamlit 앱 스모크 테스트: 네트워크 대신 합성 데이터를 주입해 화면이 예외 없이 그려지는지 확인합니다."""

import os

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from ai_industry_ranking import market_data, ranking, storage  # noqa: E402
from ai_industry_ranking.industries import INDUSTRIES  # noqa: E402
from ai_industry_ranking.scoring import DEFAULT_WEIGHTS  # noqa: E402
from ai_industry_ranking.tests.fixtures import synthetic_close  # noqa: E402

APP_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "industry_ranking_app.py")


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    import streamlit as st

    st.cache_data.clear()
    db = str(tmp_path / "app.db")
    monkeypatch.setattr(storage, "DB_FILE", db)
    storage.init_db()

    indices = market_data.build_industry_indices(synthetic_close())
    monkeypatch.setattr(ranking, "fetch_market_indices", lambda period="5y": indices)
    return indices


def run_app():
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


KPI_ORDER = ["🥇 현재 1위", "🎯 남은 반전 1위", "💎 주가 미반영 1위", "📈 시장 데이터 기준일"]


def kpi_value(at, label):
    """KPI 타일은 caption(라벨) + markdown('### 값')으로 그려지며 화면 맨 위 '### ' 블록 4개가 KPI 값입니다."""
    assert any(c.value == label for c in at.caption), f"KPI '{label}' 없음"
    values = [m.value.removeprefix("### ") for m in at.markdown if m.value.startswith("### ")]
    return values[KPI_ORDER.index(label)]


def test_app_renders_ranking(app_env):
    at = run_app()
    table = ranking.build_ranking(app_env, DEFAULT_WEIGHTS)
    assert kpi_value(at, "🥇 현재 1위") == table.iloc[0]["name"]
    assert kpi_value(at, "🎯 남은 반전 1위") == table.loc[table["remaining_reversal"].idxmax(), "name"]
    assert kpi_value(at, "💎 주가 미반영 1위") == table.loc[table["unpriced"].idxmax(), "name"]
    assert len(at.dataframe) >= 2


def test_app_shows_only_two_components(app_env):
    at = run_app()
    assert [s.label for s in at.slider] == ["남은 반전 점수", "주가 미반영 점수"]
    page = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    for removed in ("국면", "뉴스", "GDELT", "모멘텀 반영"):
        assert removed not in page.replace("뉴스 열기", ""), removed


def test_app_renders_history(app_env):
    table = ranking.build_ranking(app_env, DEFAULT_WEIGHTS)
    storage.save_ranking_snapshot(table, {i.id: i.name for i in INDUSTRIES})

    at = run_app()
    assert any("순위 추이" in m.value for m in at.markdown)


def test_app_weight_change_reranks(app_env):
    at = run_app()
    at.slider(key="w_remaining_reversal").set_value(0)
    at.run()
    assert not at.exception
    table = ranking.build_ranking(app_env, {"remaining_reversal": 0, "unpriced": 100})
    assert kpi_value(at, "🥇 현재 1위") == table.iloc[0]["name"]


def test_app_shows_error_when_market_data_fails(app_env, monkeypatch):
    def boom(period="5y"):
        raise market_data.MarketDataError("blocked")

    monkeypatch.setattr(ranking, "fetch_market_indices", boom)
    at = run_app()
    assert any("시장 데이터를 불러오지 못했습니다" in e.value for e in at.error)
