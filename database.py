"""
database.py

YouTube AI Growth Hacking Agent의 SQLite 데이터 저장소.

두 개의 핵심 테이블로 구성됩니다:
1. video_stats  -> 매 수집마다 쌓이는 영상 성과 데이터 (트렌드 차트용)
2. analyses     -> 매 분석마다 쌓이는 6단계 리포트 (가설 검증 히스토리 + 대시보드용)

대시보드 연동을 염두에 두고, 자주 쿼리할 필드(hypothesis_statement, expected_metric 등)는
JSON blob과 별개로 개별 컬럼에도 뽑아서 저장합니다 (SQL WHERE/GROUP BY로 바로 조회 가능하도록).
"""

import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

DB_FILE = "growth_agent.db"


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """테이블이 없으면 생성합니다. 앱 시작 시 항상 호출해도 안전합니다 (idempotent)."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT,
                title TEXT NOT NULL,
                published_at TEXT NOT NULL,
                views INTEGER,
                likes INTEGER,
                comments INTEGER,
                ctr TEXT,
                avd TEXT,
                fetched_at TEXT NOT NULL,
                UNIQUE(video_id, fetched_at)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                video_context TEXT,

                is_baseline INTEGER NOT NULL DEFAULT 0,
                verification_summary TEXT,
                question TEXT,

                hypothesis_variable TEXT,
                hypothesis_change TEXT,
                hypothesis_metric TEXT,
                hypothesis_direction TEXT,
                hypothesis_statement TEXT,

                control_reason TEXT,

                measurement_period TEXT,

                raw_json TEXT NOT NULL,
                markdown_report TEXT NOT NULL
            )
        """)

        # 자주 조회할 시계열 쿼리(최신순 정렬, 특정 지표 추적)를 위한 인덱스
        conn.execute("CREATE INDEX IF NOT EXISTS idx_video_stats_published ON video_stats(published_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at)")


def save_video_stats(df):
    """
    youtube_fetcher가 수집한 DataFrame을 video_stats 테이블에 저장합니다.
    같은 (video_id, fetched_at) 조합은 중복 저장하지 않습니다.
    df에 video_id 컬럼이 없으면 title로 대체 저장합니다.
    """
    fetched_at = datetime.now().isoformat()

    with get_connection() as conn:
        for _, row in df.iterrows():
            conn.execute("""
                INSERT OR IGNORE INTO video_stats
                (video_id, title, published_at, views, likes, comments, ctr, avd, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get("video_id", row["title"]),
                row["title"],
                row["published_at"],
                int(row["views"]),
                int(row["likes"]),
                int(row["comments"]),
                str(row["ctr"]),
                str(row["avd"]),
                fetched_at,
            ))


def save_analysis(analysis_json, markdown_report, video_title_context="", created_at=None):
    """
    ai_analyzer.py가 생성한 분석 결과(JSON dict)를 analyses 테이블에 저장합니다.
    대시보드에서 바로 쿼리할 수 있도록 핵심 필드를 개별 컬럼으로도 추출합니다.

    created_at: 지정하지 않으면 현재 시각 사용. 마이그레이션 시 원본 타임스탬프 보존용.
    """
    v = analysis_json.get("verification", {})
    h = analysis_json.get("hypothesis", {})
    c = analysis_json.get("control", {})
    m = analysis_json.get("measurement", {})
    created_at = created_at or datetime.now().isoformat()

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO analyses (
                created_at, video_context,
                is_baseline, verification_summary, question,
                hypothesis_variable, hypothesis_change, hypothesis_metric,
                hypothesis_direction, hypothesis_statement,
                control_reason, measurement_period,
                raw_json, markdown_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            created_at,
            video_title_context,
            1 if v.get("is_baseline") else 0,
            v.get("summary", ""),
            analysis_json.get("question", ""),
            h.get("variable_a", ""),
            h.get("change", ""),
            h.get("expected_metric", ""),
            h.get("expected_direction", ""),
            h.get("full_statement", ""),
            c.get("reason", ""),
            m.get("tracking_period", ""),
            json.dumps(analysis_json, ensure_ascii=False),
            markdown_report,
        ))
        return cursor.lastrowid


def load_last_hypothesis():
    """
    가장 최근 분석 기록을 ai_analyzer.py가 기대하는 형식으로 반환합니다.
    {timestamp, context, hypothesis, control, execution} 형태 (raw_json에서 복원).
    기록이 없으면 None.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT created_at, video_context, raw_json FROM analyses ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    if not row:
        return None

    raw = json.loads(row["raw_json"])
    return {
        "timestamp": row["created_at"],
        "context": row["video_context"],
        "hypothesis": raw.get("hypothesis", {}),
        "control": raw.get("control", {}),
        "execution": raw.get("execution", {}),
    }


def get_analysis_history(limit=20):
    """대시보드용: 최근 분석 기록 목록 (핵심 컬럼만, 최신순)."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, created_at, video_context, is_baseline,
                   hypothesis_statement, hypothesis_metric, hypothesis_direction,
                   verification_summary
            FROM analyses
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return [dict(r) for r in rows]


def get_video_stats_history(limit=100):
    """대시보드용: 영상 성과 시계열 데이터 (트렌드 차트에 바로 사용 가능)."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT video_id, title, published_at, views, likes, comments, ctr, avd, fetched_at
            FROM video_stats
            ORDER BY published_at ASC
            LIMIT ?
        """, (limit,)).fetchall()

    return [dict(r) for r in rows]


def analysis_exists(created_at):
    """주어진 created_at 타임스탬프의 분석이 이미 저장되어 있는지 확인합니다 (마이그레이션 중복 방지용)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM analyses WHERE created_at = ? LIMIT 1", (created_at,)
        ).fetchone()
    return row is not None


def get_analysis_by_id(analysis_id):
    """특정 분석의 전체 JSON + 마크다운 리포트를 가져옵니다 (상세 보기용)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()

    if not row:
        return None

    result = dict(row)
    result["raw_json"] = json.loads(result["raw_json"])
    return result


if __name__ == "__main__":
    init_db()
    print(f"✅ 데이터베이스 초기화 완료: {DB_FILE}")
    print("\n테이블: video_stats, analyses")
