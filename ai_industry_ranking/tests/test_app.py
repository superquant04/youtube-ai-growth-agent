"""Streamlit 앱 스모크 테스트: 네트워크 대신 합성 데이터를 주입해 화면이 예외 없이 그려지는지 확인합니다."""

import os

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from ai_industry_ranking import market_data, ranking, storage  # noqa: E402
from ai_industry_ranking.industries import INDUSTRIES, build_news_query  # noqa: E402
from ai_industry_ranking.scoring import DEFAULT_WEIGHTS  # noqa: E402
from ai_industry_ranking.tests.fixtures import synthetic_close, synthetic_news  # noqa: E402

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


def test_app_renders_without_news(app_env):
    at = run_app()
    assert any("1위" in m.label for m in at.metric)
    assert any("뉴스 가중치를 제외" in i.value for i in at.info)
    assert len(at.dataframe) >= 2


def test_app_renders_with_cached_news_and_history(app_env):
    news = synthetic_news()
    for ind in INDUSTRIES:
        storage.save_news_timeline(ind.id, build_news_query(ind), news[ind.id])
    table = ranking.build_ranking(app_env, DEFAULT_WEIGHTS, news_series=news)
    storage.save_ranking_snapshot(table, {i.id: i.name for i in INDUSTRIES}, news_included=True)

    at = run_app()
    assert not any("뉴스 가중치를 제외" in i.value for i in at.info)
    news_metric = next(m for m in at.metric if "뉴스" in m.label)
    assert news_metric.value == f"{len(INDUSTRIES)}개 산업"
    top_metric = next(m for m in at.metric if "1위" in m.label)
    assert top_metric.value == table.iloc[0]["name"]


def test_app_weight_change_reranks(app_env):
    at = run_app()
    for comp in ("reversal_room", "turn_momentum", "news_momentum"):
        at.slider(key=f"w_{comp}").set_value(0)
    at.run()
    assert not at.exception
    top = max(INDUSTRIES, key=lambda i: i.ai_leverage)
    assert next(m for m in at.metric if "1위" in m.label).value == top.name


def test_app_shows_error_when_market_data_fails(app_env, monkeypatch):
    def boom(period="5y"):
        raise market_data.MarketDataError("blocked")

    monkeypatch.setattr(ranking, "fetch_market_indices", boom)
    at = run_app()
    assert any("시장 데이터를 불러오지 못했습니다" in e.value for e in at.error)
