"""
collect.py

AI 상승 반전 산업 랭킹 - 수집/계산 CLI (GitHub Actions 정기 실행용)

파이프라인: 실시간 가격(Yahoo Finance) + AI 뉴스(GDELT) 수집 -> 점수 계산 -> 스냅샷 DB 저장 -> 콘솔 출력

사용법:
    python -m ai_industry_ranking.collect              # 뉴스 갱신 포함 전체 실행 (~3분)
    python -m ai_industry_ranking.collect --cached-news  # 뉴스는 DB 캐시 사용 (빠름)
    python -m ai_industry_ranking.collect --no-news    # 시장 데이터 + AI 레버리지만으로 계산
    python -m ai_industry_ranking.collect --no-save    # DB에 스냅샷 저장 없이 출력만
"""

import argparse
import sys

import pandas as pd

from ai_industry_ranking import market_data, ranking, storage
from ai_industry_ranking.industries import INDUSTRY_BY_ID
from ai_industry_ranking.scoring import DEFAULT_WEIGHTS


def parse_args():
    parser = argparse.ArgumentParser(description="AI 상승 반전 산업 랭킹 수집기")
    news = parser.add_mutually_exclusive_group()
    news.add_argument("--no-news", action="store_true", help="뉴스 신호 제외")
    news.add_argument("--cached-news", action="store_true", help="GDELT를 다시 호출하지 않고 DB 캐시 사용")
    parser.add_argument("--no-save", action="store_true", help="랭킹 스냅샷을 DB에 저장하지 않음")
    parser.add_argument("--top", type=int, default=25, help="출력할 순위 개수 (기본값: 25)")
    return parser.parse_args()


def print_progress(i, n, ind):
    if ind is not None:
        print(f"  [{i + 1}/{n}] {ind.name} 뉴스 수집 중...", flush=True)


def main():
    args = parse_args()
    storage.init_db()

    print("📈 [1/3] 실시간 시장 데이터 수집 중 (Yahoo Finance)...")
    try:
        indices = ranking.fetch_market_indices()
    except market_data.MarketDataError as e:
        print(f"❌ {e}")
        sys.exit(1)
    print(f"✅ {indices.shape[1] - 1}개 산업 지수 생성 (기준일 {indices.index[-1]:%Y-%m-%d})\n")

    news_series = None
    if args.no_news:
        print("📰 [2/3] --no-news 옵션으로 뉴스 신호 생략")
    elif args.cached_news:
        news_series, fetched_at = ranking.load_cached_news()
        print(f"📰 [2/3] 캐시된 뉴스 신호 사용: {len(news_series)}개 산업 (수집 시각 {fetched_at or '없음'})")
    else:
        print("📰 [2/3] AI 뉴스 신호 수집 중 (GDELT, 산업당 약 5.5초)...")
        news_series, errors = ranking.refresh_news(progress_cb=print_progress)
        for iid, err in errors.items():
            print(f"  ⚠️ {INDUSTRY_BY_ID[iid].name}: {err}")
        print(f"✅ {len(news_series)}개 산업 뉴스 신호 수집 완료")

    table = ranking.build_ranking(indices, DEFAULT_WEIGHTS, news_series=news_series)
    news_included = "news_momentum" in table.attrs.get("active_components", [])

    print(f"\n🏆 [3/3] AI 상승 반전 산업 랭킹 (시장 기준일 {table.attrs['as_of']:%Y-%m-%d})\n")
    print(format_table(table.head(args.top)))

    if not args.no_save:
        names = {iid: ind.name for iid, ind in INDUSTRY_BY_ID.items()}
        created_at = storage.save_ranking_snapshot(table, names, news_included)
        print(f"\n💾 스냅샷 저장 완료: {storage.DB_FILE} ({created_at})")


def format_table(table):
    out = table[["rank", "name", "total_score", "rank_change", "phase_label",
                 "ai_leverage", "reversal_room", "turn_momentum", "news_momentum"]].copy()
    out.columns = ["순위", "산업", "총점", "1주 변동", "국면", "AI레버리지", "반전여력", "반전모멘텀", "뉴스모멘텀"]
    out["1주 변동"] = out["1주 변동"].map(lambda v: "NEW" if pd.isna(v) else (f"{int(v):+d}" if v else "–"))
    return out.to_markdown(index=False, floatfmt=".1f")


if __name__ == "__main__":
    main()
