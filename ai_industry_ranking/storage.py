"""
storage.py

랭킹 스냅샷과 GDELT 뉴스 캐시를 저장하는 SQLite 저장소.

1. news_timelines     -> 산업별 최신 뉴스 비중 시계열 (참고 정보, GDELT 요청 제한 때문에 캐시해서 재사용)
2. ranking_snapshots  -> 랭킹 계산 결과 누적 (순위 변화 히스토리 차트용)

DB 경로는 환경변수 INDUSTRY_RANKING_DB로 바꿀 수 있습니다.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from io import StringIO

import pandas as pd

DB_FILE = os.getenv(
    "INDUSTRY_RANKING_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "industry_ranking.db"),
)

SNAPSHOT_COLUMNS = [
    "rank", "total_score", "remaining_reversal", "unpriced", "ai_leverage", "priced_in",
    "phase", "upside_to_high", "rel_2y", "rel_12m", "rebound_52w", "ret_1m",
]


@contextmanager
def get_connection(db_file=None):
    conn = sqlite3.connect(db_file or DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_file=None):
    """테이블이 없으면 생성합니다 (여러 번 호출해도 안전)."""
    with get_connection(db_file) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_timelines (
                industry_id TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                query TEXT NOT NULL,
                timeline_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ranking_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                market_date TEXT,
                industry_id TEXT NOT NULL,
                industry_name TEXT NOT NULL,
                rank INTEGER,
                total_score REAL,
                remaining_reversal REAL,
                unpriced REAL,
                ai_leverage REAL,
                priced_in REAL,
                phase TEXT,
                upside_to_high REAL,
                rel_2y REAL,
                rel_12m REAL,
                rebound_52w REAL,
                ret_1m REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_created ON ranking_snapshots(created_at)")


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_news_timeline(industry_id, query, series, fetched_at=None, db_file=None):
    """산업별 최신 뉴스 시계열 1건만 유지합니다 (덮어쓰기)."""
    payload = series.copy()
    payload.index = payload.index.strftime("%Y-%m-%d")
    with get_connection(db_file) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO news_timelines (industry_id, fetched_at, query, timeline_json) VALUES (?, ?, ?, ?)",
            (industry_id, fetched_at or utc_now_iso(), query, payload.to_json()),
        )


def load_news_timelines(db_file=None):
    """{industry_id: (fetched_at, query, Series)}"""
    with get_connection(db_file) as conn:
        rows = conn.execute("SELECT industry_id, fetched_at, query, timeline_json FROM news_timelines").fetchall()

    result = {}
    for r in rows:
        s = pd.read_json(StringIO(r["timeline_json"]), typ="series")
        s.index = pd.to_datetime(s.index)
        result[r["industry_id"]] = (r["fetched_at"], r["query"], s.sort_index().astype(float))
    return result


def save_ranking_snapshot(table, industry_names, created_at=None, db_file=None):
    """rank_industries() 결과를 한 시점의 스냅샷으로 저장합니다."""
    created_at = created_at or utc_now_iso()
    rows = []
    for industry_id, row in table.iterrows():
        last_date = row.get("last_date")
        rows.append((
            created_at,
            None if pd.isna(last_date) else pd.Timestamp(last_date).strftime("%Y-%m-%d"),
            industry_id,
            industry_names.get(industry_id, industry_id),
            *[_to_db(row.get(c)) for c in SNAPSHOT_COLUMNS],
        ))

    placeholders = ", ".join(["?"] * (4 + len(SNAPSHOT_COLUMNS)))
    with get_connection(db_file) as conn:
        conn.executemany(f"""
            INSERT INTO ranking_snapshots (
                created_at, market_date, industry_id, industry_name,
                {", ".join(SNAPSHOT_COLUMNS)}
            ) VALUES ({placeholders})
        """, rows)
    return created_at


def load_rank_history(days=180, db_file=None):
    """최근 N일 스냅샷 전체 (순위 추이 차트용)."""
    cutoff = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).isoformat(timespec="seconds")
    with get_connection(db_file) as conn:
        rows = conn.execute(
            "SELECT * FROM ranking_snapshots WHERE created_at >= ? ORDER BY created_at ASC", (cutoff,)
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def _to_db(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if hasattr(v, "item"):  # numpy 스칼라 -> 파이썬 기본형
        return v.item()
    return v


if __name__ == "__main__":
    init_db()
    print(f"✅ 데이터베이스 초기화 완료: {DB_FILE}")
