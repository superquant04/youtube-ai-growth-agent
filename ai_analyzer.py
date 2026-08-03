import os
import json
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv

import database

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# AI가 반드시 따라야 하는 출력 스키마 (프롬프트에도 그대로 포함시켜 강제)
OUTPUT_SCHEMA_EXAMPLE = {
    "thumbnail_observations": [
        {
            "video_title": "영상 제목 (표에 있는 것과 동일하게)",
            "observation": "실제로 이 썸네일 이미지를 보고 관찰한 내용 (텍스트 양, 글자 크기, 얼굴 유무, 색상/대비, 복잡도 등 구체적으로)"
        }
    ],
    "verification": {
        "is_baseline": False,
        "summary": "이전 가설이 지지되었는지에 대한 데이터 기반 판단 (2~4문장)",
        "supporting_metrics": ["CTR이 5.8%에서 6.1%로 상승", "AVD가 2배 증가"]
    },
    "question": "현재 데이터와 썸네일 관찰에서 발견된 가장 아쉬운 점이나 파고들 기회 (1~2문장)",
    "hypothesis": {
        "variable_a": "바꿀 변수 (예: 썸네일 텍스트 크기)",
        "change": "구체적으로 어떻게 바꿀지",
        "expected_metric": "영향을 받을 지표 (예: CTR)",
        "expected_direction": "increase 또는 decrease",
        "full_statement": "만약 [A]를 [C]하면 [B]가 [D]할 것이다 형식의 완전한 문장"
    },
    "control": {
        "variables_to_keep": ["영상 길이", "업로드 시간대", "주제 카테고리"],
        "reason": "왜 이 조건들을 유지해야 하는지"
    },
    "execution": {
        "action_items": ["다음 영상에서 실행할 구체적 행동 1", "행동 2"]
    },
    "measurement": {
        "kpis_to_track": ["CTR", "AVD", "초반 30초 이탈률"],
        "tracking_period": "업로드 후 며칠/시간 동안 관찰할지"
    }
}

# 한 번의 분석에서 실제로 이미지를 보내 분석할 최대 영상 수
# (너무 많이 보내면 비용/응답시간이 커지므로 최신 영상 위주로 제한)
MAX_THUMBNAILS_TO_ANALYZE = 8


def build_previous_context(last):
    """이전 기록을 프롬프트에 넣을 텍스트로 변환."""
    if not last:
        return "[이전 실험 기록 없음] 이번이 최초 분석입니다. verification.is_baseline을 true로 설정하세요."

    return f"""[이전 실험 기록 - verification 섹션에서 반드시 검증에 활용하세요]
- 이전 분석 시점: {last['timestamp']}
- 이전 가설: {json.dumps(last['hypothesis'], ensure_ascii=False)}
- 이전 통제 조건: {json.dumps(last['control'], ensure_ascii=False)}
- 이전 실행 항목: {json.dumps(last['execution'], ensure_ascii=False)}

이 가설이 이번 데이터로 지지되는지 구체적 수치로 판단하고 verification.is_baseline은 false로 설정하세요."""


def build_thumbnail_message_content(df_recent_videos, max_images=MAX_THUMBNAILS_TO_ANALYZE):
    """
    최근 영상들의 썸네일 이미지를 GPT-4o에 함께 보낼 수 있는 형태(content 리스트)로 만듭니다.
    OpenAI Vision 입력은 {"type": "image_url", "image_url": {"url": ...}} 형태를 사용하며,
    공개 URL을 그대로 넘기면 별도 base64 인코딩 없이 처리됩니다.
    """
    content = []

    if "thumbnail_url" not in df_recent_videos.columns:
        return content

    # 최신 영상 위주로 최대 max_images개만 전송 (비용/속도 관리)
    subset = df_recent_videos.tail(max_images)

    for _, row in subset.iterrows():
        url = row.get("thumbnail_url")
        if not url or pd.isna(url):
            continue
        content.append({"type": "text", "text": f"[영상 제목: {row['title']}] 썸네일:"})
        content.append({"type": "image_url", "image_url": {"url": url}})

    return content


def generate_scientific_insight(df_recent_videos):
    """
    최근 영상 데이터(통계 + 썸네일 이미지) + 이전 가설 히스토리를 바탕으로
    6단계 과학적 방법론을 적용한 인사이트를 JSON으로 생성합니다.
    반환값: (report_dict, report_markdown)
    """
    stats_context = df_recent_videos[
        [c for c in ['title', 'published_at', 'views', 'likes', 'comments', 'ctr', 'avd']
         if c in df_recent_videos.columns]
    ].to_markdown()

    last = database.load_last_hypothesis()
    previous_context = build_previous_context(last)

    system_prompt = f"""당신은 데이터 기반 유튜브 성장 해킹(Growth Hacking) 전문가이자 데이터 과학자입니다.
제공된 유튜브 영상 통계 데이터와 실제 썸네일 이미지를 함께 분석하여 [과학적 실험 6단계 프레임워크]에 따라 인사이트를 도출하세요.
막연한 추측이 아닌 숫자 데이터와 실제로 눈으로 관찰한 썸네일 특징에 근거해야 합니다.

{previous_context}

[과학적 실험 6단계 프레임워크]
0. thumbnail_observations (썸네일 관찰): 함께 제공된 각 영상의 썸네일 이미지를 실제로 보고, 텍스트 양/글자 크기/얼굴 유무/색상 대비/복잡도 등을 구체적으로 기술하세요. 절대 이미지를 보지 않은 것처럼 일반론으로 넘어가지 마세요.
1. verification (검증): 이전 가설이 이번 데이터로 지지되는지 평가. 최초 분석이면 baseline 설정.
2. question (질문): 데이터와 썸네일 관찰에서 발견된 가장 아쉬운 점이나 기회.
3. hypothesis (가설): "만약 A를 C하면 B가 D할 것이다" 형태의 명확한 인과관계 가설. 가능하면 썸네일 관찰 내용과 연결하세요.
4. control (통제): 가설 검증을 위해 다음 영상에서 유지해야 할 조건들.
5. execution (실행): 다음 영상 제작 시 즉시 실행할 구체적 행동 지침.
6. measurement (관찰과 측정): 성과 판별을 위해 추적할 핵심 지표(KPI).

반드시 아래 JSON 스키마와 정확히 동일한 키 구조로만 응답하세요.
다른 설명, 마크다운, 코드블록 없이 순수 JSON 객체만 출력하세요.
썸네일 이미지가 하나도 제공되지 않았다면 thumbnail_observations는 빈 배열로 두세요.

스키마 예시:
{json.dumps(OUTPUT_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}
"""

    user_text = f"다음은 최근 영상들의 성과 데이터입니다.\n\n{stats_context}\n\n이어서 각 영상의 썸네일 이미지를 순서대로 제공합니다. 이미지를 실제로 관찰한 뒤 6단계 분석을 JSON으로 작성해 주세요."

    user_content = [{"type": "text", "text": user_text}]
    user_content.extend(build_thumbnail_message_content(df_recent_videos))

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}  # JSON 출력 강제
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API 호출 실패: {e}")

    raw_text = response.choices[0].message.content

    try:
        analysis = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"AI 응답 JSON 파싱 실패: {e}\n원문: {raw_text}")

    # 필수 키 검증 (스키마 누락 방지). thumbnail_observations는 이미지가 없으면 빈 배열일 수 있어 완화 검증.
    required_keys = ["verification", "question", "hypothesis", "control", "execution", "measurement"]
    missing = [k for k in required_keys if k not in analysis]
    if missing:
        raise RuntimeError(f"AI 응답에 필수 키 누락: {missing}\n원문: {raw_text}")
    analysis.setdefault("thumbnail_observations", [])

    latest_video_title = df_recent_videos.iloc[-1]['title'] if not df_recent_videos.empty else ""
    markdown_report = render_markdown(analysis)

    database.save_analysis(analysis, markdown_report, video_title_context=latest_video_title)

    return analysis, markdown_report


def render_markdown(analysis):
    """JSON 분석 결과를 사람이 읽기 좋은 마크다운 리포트로 변환합니다."""
    v = analysis["verification"]
    h = analysis["hypothesis"]
    c = analysis["control"]
    e = analysis["execution"]
    m = analysis["measurement"]

    lines = []

    observations = analysis.get("thumbnail_observations", [])
    if observations:
        lines.append("### 0. 썸네일 관찰 (Thumbnail Observations)")
        for obs in observations:
            lines.append(f"- **{obs.get('video_title', '')}**: {obs.get('observation', '')}")

    lines.append("\n### 1. 검증 (Verification)")
    if v.get("is_baseline"):
        lines.append(v.get("summary", "베이스라인 설정."))
    else:
        lines.append(v.get("summary", ""))
        for metric in v.get("supporting_metrics", []):
            lines.append(f"- {metric}")

    lines.append("\n### 2. 질문 (Question)")
    lines.append(analysis.get("question", ""))

    lines.append("\n### 3. 가설 (Hypothesis)")
    lines.append(f"**{h.get('full_statement', '')}**")
    lines.append(f"- 변수: {h.get('variable_a', '')} → {h.get('change', '')}")
    lines.append(f"- 예상 영향 지표: {h.get('expected_metric', '')} ({h.get('expected_direction', '')})")

    lines.append("\n### 4. 통제 (Control)")
    for var in c.get("variables_to_keep", []):
        lines.append(f"- {var}")
    if c.get("reason"):
        lines.append(f"\n이유: {c['reason']}")

    lines.append("\n### 5. 실행 (Execution)")
    for item in e.get("action_items", []):
        lines.append(f"- {item}")

    lines.append("\n### 6. 관찰과 측정 (Measurement)")
    for kpi in m.get("kpis_to_track", []):
        lines.append(f"- {kpi}")
    if m.get("tracking_period"):
        lines.append(f"\n추적 기간: {m['tracking_period']}")

    return "\n".join(lines)


if __name__ == "__main__":
    database.init_db()

    dummy_data = {
        'title': ['[Vlog] 일반적인 코딩 일상', '[실험] 썸네일 텍스트 크기 2배 키움', '[실험] 오프닝 5초 결론 선공개'],
        'published_at': ['2026-07-15', '2026-07-22', '2026-07-29'],
        'views': [1500, 3200, 8500],
        'likes': [50, 110, 350],
        'comments': [10, 25, 90],
        'ctr': ['3.2%', '5.8%', '6.1%'],
        'avd': ['02:15', '02:10', '04:30']
    }
    df = pd.DataFrame(dummy_data)

    print("🤖 과학적 6단계 분석 엔진 가동 중 (JSON 구조화 출력)...")
    analysis_json, markdown_report = generate_scientific_insight(df)

    print("\n===== 마크다운 리포트 =====\n")
    print(markdown_report)

    print("\n===== 원본 JSON (DB 저장/대시보드 연동용) =====\n")
    print(json.dumps(analysis_json, ensure_ascii=False, indent=2))

    print(f"\n✅ 가설이 {database.DB_FILE}에 저장되었습니다. 다음 실행 시 자동으로 검증에 활용됩니다.")
