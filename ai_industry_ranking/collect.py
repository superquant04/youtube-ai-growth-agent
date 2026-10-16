"""
collect.py

AI 상승 반전 산업 랭킹 - 수집/계산 CLI (GitHub Actions 정기 실행용)

파이프라인: 실시간 가격(Yahoo Finance) 수집 -> 점수 계산(남은 반전 + 주가 미반영) -> 스냅샷 DB 저장 -> 콘솔 출력

사용법:
    python -m ai_industry_ranking.collect             # 랭킹 계산 + 스냅샷 저장
    python -m ai_industry_ranking.collect --no-save   # DB에 스냅샷 저장 없이 출력만
"""

import argparse
import sys

import pandas as pd

from ai_industry_ranking import market_data, ranking, storage
from ai_industry_ranking.industries import INDUSTRY_BY_ID
from ai_industry_ranking.scoring import DEFAULT_WEIGHTS


def parse_args():
    parser = argparse.ArgumentParser(description="AI 상승 반전 산업 랭킹 수집기")
    parser.add_argument("--no-save", action="store_true", help="랭킹 스냅샷을 DB에 저장하지 않음")
    parser.add_argument("--top", type=int, default=25, help="출력할 순위 개수 (기본값: 25)")
    return parser.parse_args()


def main():
    args = parse_args()
    storage.init_db()

    print("📈 [1/2] 실시간 시장 데이터 수집 중 (Yahoo Finance)...")
    try:
        indices = ranking.fetch_market_indices()
    except market_data.MarketDataError as e:
        print(f"❌ {e}")
        sys.exit(1)
    print(f"✅ {indices.shape[1] - 1}개 산업 지수 생성 (기준일 {indices.index[-1]:%Y-%m-%d})\n")

    table = ranking.build_ranking(indices, DEFAULT_WEIGHTS)

    print(f"🏆 [2/2] AI 상승 반전 산업 랭킹 (시장 기준일 {table.attrs['as_of']:%Y-%m-%d})")
    print("    점수 = 남은 반전 점수 50% + 주가 미반영 점수 50%\n")
    print(format_table(table.head(args.top)))

    if not args.no_save:
        names = {iid: ind.name for iid, ind in INDUSTRY_BY_ID.items()}
        created_at = storage.save_ranking_snapshot(table, names)
        print(f"\n💾 스냅샷 저장 완료: {storage.DB_FILE} ({created_at})")


def format_table(table):
    out = table[["rank", "name", "total_score", "rank_change", "remaining_reversal", "unpriced",
                 "upside_to_high", "ai_leverage", "priced_in"]].copy()
    out.columns = ["순위", "산업", "총점", "1주 변동", "남은반전", "주가미반영", "고점까지", "AI잠재력", "반영도"]
    out["1주 변동"] = out["1주 변동"].map(lambda v: "NEW" if pd.isna(v) else (f"{int(v):+d}" if v else "–"))
    out["반영도"] = out["반영도"].map(lambda v: "-" if pd.isna(v) else f"{v:.0%}")
    out["고점까지"] = out["고점까지"].map(lambda v: "-" if pd.isna(v) else f"+{v:.0%}")
    return out.to_markdown(index=False, floatfmt=".1f")


if __name__ == "__main__":
    main()
