"""
main.py

YouTube AI Growth Hacking Agent - 실행 진입점

파이프라인: youtube_fetcher (데이터 수집) -> ai_analyzer (6단계 과학적 분석) -> 리포트 저장/출력

사용법:
    python main.py                     # 최근 10개 영상 분석
    python main.py --max-results 5     # 최근 5개 영상만 분석
    python main.py --no-save           # 리포트 파일 저장 없이 콘솔 출력만
"""

import os
import sys
import json
import argparse
from datetime import datetime

from youtube_fetcher import fetch_recent_video_dataframe
from ai_analyzer import generate_scientific_insight
import database

REPORTS_DIR = "reports"


def parse_args():
    parser = argparse.ArgumentParser(description="YouTube AI Growth Hacking Agent")
    parser.add_argument(
        "--max-results", type=int, default=10,
        help="분석할 최근 영상 개수 (기본값: 10)"
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="리포트를 파일로 저장하지 않고 콘솔에만 출력"
    )
    return parser.parse_args()


def save_report(analysis_json, markdown_report):
    """리포트를 reports/ 디렉토리에 JSON + 마크다운 두 형식으로 저장합니다."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = os.path.join(REPORTS_DIR, f"report_{timestamp}.json")
    md_path = os.path.join(REPORTS_DIR, f"report_{timestamp}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(analysis_json, f, ensure_ascii=False, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_report)

    return json_path, md_path


def run_pipeline(max_results=10, save=True):
    """전체 파이프라인 실행: 데이터 수집 -> DB 저장 -> 분석 -> (리포트 저장)"""

    database.init_db()

    print(f"🎥 [1/3] YouTube 채널 데이터 수집 중 (최근 {max_results}개 영상)...")
    try:
        df = fetch_recent_video_dataframe(max_results=max_results)
    except FileNotFoundError as e:
        print(f"❌ 인증 파일 오류: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 데이터 수집 실패: {e}")
        sys.exit(1)

    if df.empty:
        print("⚠️ 수집된 영상이 없습니다. 채널에 업로드된 영상이 있는지 확인하세요.")
        sys.exit(1)

    print(f"✅ {len(df)}개 영상 데이터 수집 완료\n")
    print(df.to_markdown(index=False))

    database.save_video_stats(df)
    print("💾 영상 통계 DB 저장 완료 (video_stats 테이블)")

    print("\n🤖 [2/3] 6단계 과학적 분석 엔진 가동 중...")
    try:
        analysis_json, markdown_report = generate_scientific_insight(df)
    except RuntimeError as e:
        print(f"❌ 분석 실패: {e}")
        sys.exit(1)

    print("✅ 분석 완료\n")
    print("=" * 50)
    print(markdown_report)
    print("=" * 50)

    if save:
        print("\n💾 [3/3] 리포트 저장 중...")
        json_path, md_path = save_report(analysis_json, markdown_report)
        print(f"✅ 저장 완료:\n  - {json_path}\n  - {md_path}")
    else:
        print("\n[3/3] --no-save 옵션으로 파일 저장 생략됨")

    return analysis_json, markdown_report


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(max_results=args.max_results, save=not args.no_save)
