"""
news_data.py

GDELT DOC 2.0 API로 "AI + 산업" 뉴스 신호를 수집합니다 (API 키 불필요, 전 세계 65개 언어 뉴스 모니터링).

- fetch_news_timeline   : 최근 12주간 일별 기사 비중(전체 모니터링 기사 중 해당 쿼리 기사 비율, %)
- compute_news_metrics  : 최근 7일 비중과 직전 8주 대비 증가율
- fetch_latest_articles : 최신 기사 헤드라인 목록

GDELT는 IP당 "5초에 1회" 요청 제한이 있어 모든 요청을 전역 스로틀로 직렬화합니다.
산업 25개 전체 갱신에 약 2~3분이 걸리므로 결과를 DB(storage.py)에 캐시해 재사용합니다.
"""

import json
import threading
import time

import numpy as np
import pandas as pd
import requests

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "ai-industry-ranking/1.0 (+https://github.com/superquant04/youtube-ai-growth-agent)"
MIN_REQUEST_INTERVAL = 5.5  # 초

RECENT_DAYS = 7
BASELINE_DAYS = 56  # 직전 8주

_throttle_lock = threading.Lock()
_last_request_at = 0.0


class NewsFetchError(RuntimeError):
    pass


def _gdelt_get(params, timeout=30):
    global _last_request_at
    with _throttle_lock:
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = requests.get(
                GDELT_DOC_URL, params=params, timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.RequestException as e:
            raise NewsFetchError(f"GDELT 요청 실패: {e}") from e
        finally:
            _last_request_at = time.monotonic()

    if resp.status_code != 200:
        raise NewsFetchError(f"GDELT HTTP {resp.status_code}: {resp.text[:200]}")

    text = resp.text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # 쿼리 문법 오류나 요청 제한 시 GDELT는 JSON 대신 안내 문장을 돌려줍니다.
        raise NewsFetchError(f"GDELT 응답이 JSON이 아닙니다: {text[:200]}") from e


def fetch_news_timeline(query, timespan="12w"):
    """쿼리의 일별 기사 비중(%) 시계열을 반환합니다. 기사가 없으면 빈 Series."""
    payload = _gdelt_get({
        "query": query,
        "mode": "timelinevol",
        "format": "json",
        "timespan": timespan,
    })
    return parse_timeline(payload)


def parse_timeline(payload):
    """GDELT timeline JSON -> 일별 Series(index=날짜, 값=비중 %). 하루보다 잘게 나뉜 응답은 일평균으로 묶습니다."""
    timeline = (payload or {}).get("timeline") or []
    if not timeline:
        return pd.Series(dtype=float)

    points = timeline[0].get("data") or []
    if not points:
        return pd.Series(dtype=float)

    df = pd.DataFrame(points)
    df["date"] = parse_gdelt_dates(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"])
    if df.empty:
        return pd.Series(dtype=float)

    daily = df.groupby(df["date"].dt.normalize())["value"].mean()
    daily.index.name = "date"
    return daily.sort_index()


def parse_gdelt_dates(values):
    """GDELT 날짜("20261015T120000Z")를 tz 없는 UTC Timestamp로. 형식이 다르면 일반 파서로 재시도합니다."""
    parsed = pd.to_datetime(values, format="%Y%m%dT%H%M%SZ", errors="coerce")
    if parsed.isna().all():
        parsed = pd.to_datetime(values, errors="coerce", utc=True).dt.tz_localize(None)
    return parsed


def compute_news_metrics(series, as_of=None):
    """
    최근 7일 평균 기사 비중(news_share_7d)과 직전 8주 대비 증가율(news_change)을 계산합니다.
    데이터가 부족하면 빈 dict.
    """
    if series is None or len(series) == 0:
        return {}
    s = series.dropna().sort_index()
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of).normalize()]
    if len(s) < RECENT_DAYS + 14:
        return {}

    recent = s.iloc[-RECENT_DAYS:].mean()
    baseline = s.iloc[-(RECENT_DAYS + BASELINE_DAYS):-RECENT_DAYS].mean()
    eps = 1e-6
    return {
        "news_share_7d": recent,
        "news_change": (recent + eps) / (baseline + eps) - 1 if not np.isnan(baseline) else np.nan,
    }


def fetch_latest_articles(query, max_records=10, timespan="7d"):
    """최신 기사 목록 [{title, url, domain, seendate, language, sourcecountry}, ...]."""
    payload = _gdelt_get({
        "query": query,
        "mode": "artlist",
        "format": "json",
        "timespan": timespan,
        "maxrecords": max_records,
        "sort": "DateDesc",
    })
    articles = []
    for a in (payload or {}).get("articles") or []:
        seen = parse_gdelt_dates(pd.Series([a.get("seendate")])).iloc[0]
        articles.append({
            "title": a.get("title", "").strip(),
            "url": a.get("url", ""),
            "domain": a.get("domain", ""),
            "language": a.get("language", ""),
            "sourcecountry": a.get("sourcecountry", ""),
            "seendate": None if pd.isna(seen) else seen,
        })
    return articles
