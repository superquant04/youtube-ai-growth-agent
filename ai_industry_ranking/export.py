"""
export.py

랭킹 결과를 JSON 파일로 내보냅니다. Claude 정기 작업이 이 파일을 claude.ai 대시보드(Artifact)에 올려
GitHub 없이 결과를 보여 주는 데 씁니다.

- ranking.json : 최신 랭킹 (산업별 한 줄)
- history.json : 실행할 때마다 산업별 순위·점수를 시장 기준일 단위로 누적 (순위 추이용)

두 파일 모두 {"rows": [...]} 형태의 행 객체 배열입니다.
"""

import json
import math
import os

import pandas as pd

HISTORY_KEEP_DATES = 260  # 시장 기준일 약 1년치만 보관

RANKING_FIELDS = {
    # 키: (표시용 설명, 반올림 자릿수)
    "rank": ("순위", None),
    "rank_change": ("1주 전 대비 순위 변동 (+ 상승)", None),
    "total_score": ("상승 반전 점수 0~100", 1),
    "remaining_reversal": ("남은 반전 점수 0~100", 1),
    "unpriced": ("주가 미반영 점수 0~100", 1),
    "upside_to_high": ("3년 고점까지 남은 상승률 (비율)", 4),
    "rel_2y": ("2년 SPY 대비 상대수익률 (비율)", 4),
    "ai_leverage": ("AI 잠재력 0~100", 1),
    "priced_in": ("주가 반영도 0~1", 4),
    "rel_12m": ("1년 SPY 대비 상대수익률 (비율)", 4),
    "rebound_52w": ("52주 저점 대비 반등폭 (비율)", 4),
}

HISTORY_FIELDS = ("rank", "total_score", "remaining_reversal", "unpriced")


def ranking_rows(table, generated_at):
    """build_ranking() 결과 -> JSON 직렬화 가능한 행 목록 (순위순)."""
    market_date = _date(table.attrs.get("as_of"))
    rows = []
    for industry_id, r in table.iterrows():
        row = {
            "industry_id": industry_id,
            "name": r["name"],
            "tickers": r["tickers"],
            "market_date": market_date,
            "generated_at": generated_at,
        }
        for key, (_, digits) in RANKING_FIELDS.items():
            row[key] = _clean(r.get(key), digits)
        rows.append(row)
    return rows


def write_ranking_json(table, path, generated_at):
    _write(path, {"rows": ranking_rows(table, generated_at), "fields": {k: v[0] for k, v in RANKING_FIELDS.items()}})


def merge_history(table, path, generated_at, keep_dates=HISTORY_KEEP_DATES):
    """
    history.json에 이번 랭킹을 더합니다. 같은 시장 기준일의 기존 행은 이번 결과로 바꿉니다.
    파일이 없으면 새로 만듭니다. 반환: 누적된 시장 기준일 수.
    """
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("rows", [])

    market_date = _date(table.attrs.get("as_of"))
    rows = [r for r in rows if r.get("market_date") != market_date]
    for r in ranking_rows(table, generated_at):
        rows.append({k: r[k] for k in ("market_date", "generated_at", "industry_id", "name", *HISTORY_FIELDS)})

    dates = sorted({r["market_date"] for r in rows if r.get("market_date")})
    keep = set(dates[-keep_dates:])
    rows = [r for r in rows if r.get("market_date") in keep]
    rows.sort(key=lambda r: (r["market_date"], r["rank"] if r["rank"] is not None else 999))
    _write(path, {"rows": rows})
    return len(keep)


def _write(path, payload):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


def _date(ts):
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def _clean(v, digits):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        if math.isinf(v):
            return None
        return round(v, digits) if digits is not None else v
    return v
