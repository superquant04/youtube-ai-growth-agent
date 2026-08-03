"""
generate_token.py

최초 1회, 로컬 환경에서만 실행하는 스크립트입니다.
브라우저 OAuth 인증을 거쳐 refresh_token을 발급받고 화면에 출력합니다.

이 refresh_token을 GitHub Secrets에 저장하면, 이후 GitHub Actions는
브라우저 없이도(헤드리스 환경에서도) YouTube API 인증을 계속 갱신할 수 있습니다.

사용법:
    python generate_token.py

실행하면 브라우저가 열리고 Google 계정 인증을 요청합니다.
완료되면 client_id / client_secret / refresh_token 세 가지가 출력됩니다.
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

CLIENT_SECRET_FILE = "client_secret.json"


def main():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(CLIENT_SECRET_FILE, "r", encoding="utf-8") as f:
        client_config = json.load(f)
    client_info = client_config.get("installed") or client_config.get("web")

    print("\n" + "=" * 60)
    print("✅ 인증 완료! 아래 3개 값을 GitHub Secrets에 등록하세요.")
    print("=" * 60)
    print(f"\nYOUTUBE_CLIENT_ID:\n{client_info['client_id']}")
    print(f"\nYOUTUBE_CLIENT_SECRET:\n{client_info['client_secret']}")
    print(f"\nYOUTUBE_REFRESH_TOKEN:\n{creds.refresh_token}")
    print("\n" + "=" * 60)
    print("⚠️  이 값들은 client_secret.json과 마찬가지로 절대 커밋하지 마세요.")
    print("   GitHub 저장소 -> Settings -> Secrets and variables -> Actions 에 등록합니다.")
    print("=" * 60)


if __name__ == "__main__":
    main()
