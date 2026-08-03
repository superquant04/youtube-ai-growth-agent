"""
youtube_fetcher.py

YouTube 채널의 최근 영상 데이터를 가져와 ai_analyzer.py가 기대하는
DataFrame 형식(title, published_at, views, likes, comments, ctr, avd)으로 반환합니다.

두 개의 서로 다른 API를 사용합니다:
1. YouTube Data API v3   -> 공개 지표 (조회수, 좋아요, 댓글, 제목, 업로드일). API 키만으로 가능.
2. YouTube Analytics API v2 -> 비공개 지표 (CTR, 평균 시청 지속시간). 채널 소유자의 OAuth 인증 필수.

사전 준비물:
- pip install google-api-python-client google-auth-oauthlib google-auth-httplib2 pandas python-dotenv
- Google Cloud Console에서 프로젝트 생성 후 "YouTube Data API v3"와 "YouTube Analytics API" 활성화
- OAuth 2.0 클라이언트 ID(데스크톱 앱) 다운로드 -> client_secret.json 으로 저장
- .env 파일에 YOUTUBE_API_KEY=... (Data API용, 선택사항 - OAuth 토큰으로도 대체 가능)
"""

import os
import pickle
import pandas as pd
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# OAuth 스코프: 채널 조회 + Analytics 읽기 권한
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.pickle"


def _get_credentials_from_env():
    """
    GitHub Actions 등 헤드리스 환경용. 브라우저 없이 refresh_token만으로 인증합니다.
    YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN 세 환경변수가
    모두 존재할 때만 사용됩니다 (generate_token.py로 최초 1회 로컬에서 발급).
    """
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())  # refresh_token으로 새 access_token 발급
    return creds


def _get_credentials_from_local_flow():
    """
    로컬 개발 환경용. 브라우저를 띄워 인증하고 token.pickle에 캐싱합니다.
    """
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET_FILE):
                raise FileNotFoundError(
                    f"{CLIENT_SECRET_FILE}이 없습니다. Google Cloud Console에서 "
                    "OAuth 클라이언트(데스크톱 앱)를 만들고 다운로드해 주세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return creds


def get_authenticated_services():
    """
    OAuth 인증을 통해 Data API와 Analytics API 클라이언트를 모두 생성합니다.

    우선순위:
    1. 환경변수(YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN)가 있으면 헤드리스 인증 (CI용)
    2. 없으면 브라우저 기반 로컬 인증 (개발용, token.pickle로 캐싱)
    """
    creds = _get_credentials_from_env()
    if creds is None:
        creds = _get_credentials_from_local_flow()

    youtube = build("youtube", "v3", credentials=creds)
    youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)

    return youtube, youtube_analytics


def get_my_channel_id(youtube):
    """인증된 계정 소유 채널의 ID를 가져옵니다."""
    response = youtube.channels().list(part="id,contentDetails", mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("채널 정보를 찾을 수 없습니다. 인증된 계정에 채널이 있는지 확인하세요.")
    return items[0]["id"], items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_recent_video_ids(youtube, uploads_playlist_id, max_results=10):
    """업로드 재생목록에서 최신 영상 ID 목록을 가져옵니다."""
    video_ids = []
    request = youtube.playlistItems().list(
        part="contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=min(max_results, 50)
    )
    response = request.execute()

    for item in response.get("items", []):
        video_ids.append(item["contentDetails"]["videoId"])

    return video_ids[:max_results]


def get_public_video_stats(youtube, video_ids):
    """
    Data API로 영상별 공개 지표(제목, 업로드일, 조회수, 좋아요, 댓글)를 가져옵니다.
    """
    if not video_ids:
        return []

    response = youtube.videos().list(
        part="snippet,statistics",
        id=",".join(video_ids)
    ).execute()

    results = []
    for item in response.get("items", []):
        snippet = item["snippet"]
        stats = item.get("statistics", {})
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )
        results.append({
            "video_id": item["id"],
            "title": snippet["title"],
            "published_at": snippet["publishedAt"][:10],  # YYYY-MM-DD
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "thumbnail_url": thumbnail_url,
        })

    return results


def get_video_analytics(youtube_analytics, channel_id, video_id, published_at):
    """
    Analytics API로 특정 영상의 CTR과 평균 시청 지속시간을 가져옵니다.
    업로드일부터 오늘까지의 누적 지표를 조회합니다.
    """
    start_date = published_at
    end_date = datetime.now().strftime("%Y-%m-%d")

    try:
        response = youtube_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="impressions,impressionsClickThroughRate,averageViewDuration,averageViewPercentage",
            dimensions="video",
            filters=f"video=={video_id}"
        ).execute()
    except Exception as e:
        # 업로드 직후라 데이터가 아직 집계되지 않았거나, impressions 데이터가 없는 경우 등
        print(f"⚠️ 영상 {video_id}의 Analytics 데이터를 가져오지 못했습니다: {e}")
        return {"ctr": None, "avd": None}

    rows = response.get("rows", [])
    if not rows:
        return {"ctr": None, "avd": None}

    # 컬럼 순서: video, impressions, impressionsClickThroughRate, averageViewDuration, averageViewPercentage
    row = rows[0]
    ctr_percent = row[2]  # 이미 %로 반환됨 (예: 5.8)
    avd_seconds = row[3]

    avd_formatted = str(timedelta(seconds=int(avd_seconds)))
    if avd_formatted.startswith("0:"):
        avd_formatted = "00" + avd_formatted[1:]  # 0:02:15 -> 00:02:15 형태 정리는 필요시 조정

    return {
        "ctr": f"{ctr_percent:.1f}%",
        "avd": avd_formatted
    }


def fetch_recent_video_dataframe(max_results=10):
    """
    ai_analyzer.py의 generate_scientific_insight()에 바로 넘길 수 있는
    DataFrame(title, published_at, views, likes, comments, ctr, avd)을 반환합니다.
    """
    youtube, youtube_analytics = get_authenticated_services()
    channel_id, uploads_playlist_id = get_my_channel_id(youtube)

    video_ids = get_recent_video_ids(youtube, uploads_playlist_id, max_results=max_results)
    public_stats = get_public_video_stats(youtube, video_ids)

    rows = []
    for video in public_stats:
        analytics = get_video_analytics(
            youtube_analytics, channel_id, video["video_id"], video["published_at"]
        )
        rows.append({
            "video_id": video["video_id"],
            "title": video["title"],
            "published_at": video["published_at"],
            "views": video["views"],
            "likes": video["likes"],
            "comments": video["comments"],
            "ctr": analytics["ctr"] or "N/A",
            "avd": analytics["avd"] or "N/A",
            "thumbnail_url": video["thumbnail_url"],
        })

    # 오래된 순 -> 최신 순으로 정렬 (ai_analyzer.py가 마지막 행을 "최신 영상"으로 사용)
    df = pd.DataFrame(rows)
    df = df.sort_values("published_at").reset_index(drop=True)
    return df


if __name__ == "__main__":
    print("🎥 YouTube 채널 데이터 수집 중 (최초 실행 시 브라우저 인증 필요)...")
    df = fetch_recent_video_dataframe(max_results=5)
    print("\n===== 수집된 데이터 =====\n")
    print(df.to_markdown(index=False))
