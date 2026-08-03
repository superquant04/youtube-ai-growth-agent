"""
migrate_history_to_db.py

기존 hypothesis_history.json (파일 기반 히스토리)을 SQLite(database.py)로 이전합니다.

이 프로젝트는 개발 과정에서 히스토리 저장 방식이 두 번 바뀌었습니다:
  [v1] 텍스트 파싱 버전: hypothesis/control/execution이 마크다운에서 정규식으로 추출한 순수 텍스트(str)
  [v2] JSON 구조화 버전: hypothesis/control/execution이 {variable_a, change, ...} 형태의 dict
       (단, verification/question/measurement는 애초에 파일에 저장되지 않았음)

두 형식 모두 자동 감지해서 현재 스키마(OUTPUT_SCHEMA_EXAMPLE)에 맞게 정규화한 뒤 DB에 저장합니다.
v1 텍스트 항목은 구조화된 필드(hypothesis_variable 등)를 복원할 수 없으므로,
전체 텍스트를 full_statement / reason 등에 그대로 보존하고 나머지는 "레거시 데이터"로 표시합니다.

사용법:
    python migrate_history_to_db.py                          # 기본 경로(hypothesis_history.json) 사용
    python migrate_history_to_db.py --file /path/to/old.json
    python migrate_history_to_db.py --dry-run                # 실제 저장 없이 무엇이 이전될지만 확인
"""

import os
import json
import argparse

import database
from ai_analyzer import render_markdown

LEGACY_NOTICE = "(레거시 마이그레이션 데이터 - v1/v2 파일 기반 히스토리에서 이전됨. 원본에 없던 필드)"


def is_legacy_text_format(entry):
    """hypothesis 필드가 dict가 아니라 str이면 v1(텍스트 파싱) 형식으로 판단합니다."""
    return isinstance(entry.get("hypothesis"), str)


def normalize_v1_text_entry(entry):
    """
    v1 텍스트 형식을 현재 JSON 스키마로 최대한 매핑합니다.
    구조화된 하위 필드는 복원 불가하므로 full_statement/reason에 원문 텍스트를 그대로 담습니다.
    """
    return {
        "verification": {
            "is_baseline": False,
            "summary": LEGACY_NOTICE,
            "supporting_metrics": []
        },
        "question": LEGACY_NOTICE,
        "hypothesis": {
            "variable_a": "",
            "change": "",
            "expected_metric": "",
            "expected_direction": "",
            "full_statement": entry.get("hypothesis", "").strip() or LEGACY_NOTICE
        },
        "control": {
            "variables_to_keep": [],
            "reason": entry.get("control", "").strip() or LEGACY_NOTICE
        },
        "execution": {
            "action_items": [
                line.strip("- ").strip()
                for line in entry.get("execution", "").splitlines()
                if line.strip()
            ] or [LEGACY_NOTICE]
        },
        "measurement": {
            "kpis_to_track": [],
            "tracking_period": LEGACY_NOTICE
        }
    }


def normalize_v2_json_entry(entry):
    """
    v2 구조화 형식(hypothesis/control/execution만 dict로 존재)을 현재 스키마로 채웁니다.
    verification/question/measurement는 원본에 없었으므로 레거시 표시로 채웁니다.
    """
    return {
        "verification": {
            "is_baseline": False,
            "summary": LEGACY_NOTICE,
            "supporting_metrics": []
        },
        "question": LEGACY_NOTICE,
        "hypothesis": entry.get("hypothesis", {}) or {"full_statement": LEGACY_NOTICE},
        "control": entry.get("control", {}) or {"reason": LEGACY_NOTICE},
        "execution": entry.get("execution", {}) or {"action_items": [LEGACY_NOTICE]},
        "measurement": {
            "kpis_to_track": [],
            "tracking_period": LEGACY_NOTICE
        }
    }


def migrate(file_path, dry_run=False):
    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            history = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ JSON 파싱 실패: {e}")
            return

    if not history:
        print("⚠️ 파일에 이전할 항목이 없습니다.")
        return

    if not dry_run:
        database.init_db()

    migrated, skipped, failed = 0, 0, 0

    for i, entry in enumerate(history, start=1):
        timestamp = entry.get("timestamp")
        context = entry.get("context", "")

        if not timestamp:
            print(f"⚠️ [{i}] timestamp가 없어 건너뜁니다: {entry}")
            failed += 1
            continue

        if not dry_run and database.analysis_exists(timestamp):
            print(f"⏭️  [{i}] 이미 이전됨 (timestamp={timestamp}), 건너뜀")
            skipped += 1
            continue

        try:
            if is_legacy_text_format(entry):
                fmt = "v1 텍스트"
                analysis_json = normalize_v1_text_entry(entry)
            else:
                fmt = "v2 JSON"
                analysis_json = normalize_v2_json_entry(entry)

            markdown_report = render_markdown(analysis_json)

            print(f"➡️  [{i}] {fmt} 형식 감지 - {timestamp} ({context or '제목 없음'})")

            if not dry_run:
                database.save_analysis(
                    analysis_json,
                    markdown_report,
                    video_title_context=context,
                    created_at=timestamp
                )

            migrated += 1

        except Exception as e:
            print(f"❌ [{i}] 이전 실패: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"✅ 이전 완료: {migrated}건")
    print(f"⏭️  건너뜀(중복): {skipped}건")
    print(f"❌ 실패: {failed}건")
    if dry_run:
        print("\n(--dry-run 모드였습니다. 실제 DB에는 저장되지 않았습니다.)")
    print("=" * 50)


def parse_args():
    parser = argparse.ArgumentParser(description="hypothesis_history.json -> SQLite 마이그레이션")
    parser.add_argument(
        "--file", type=str, default="hypothesis_history.json",
        help="이전할 JSON 히스토리 파일 경로 (기본값: hypothesis_history.json)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="실제로 DB에 저장하지 않고 무엇이 이전될지만 미리 확인"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    migrate(args.file, dry_run=args.dry_run)
