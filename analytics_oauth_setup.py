#!/usr/bin/env python3
"""Create a separate read-only YouTube Analytics OAuth token.
Requires client_secret.json from Google Cloud Console and YouTube Analytics API enabled.
Run: python analytics_oauth_setup.py
Keep analytics_token.json private; never commit it.
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]
CLIENT = Path("client_secret.json")
if not CLIENT.exists():
    raise SystemExit("Missing client_secret.json")
flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
Path("analytics_token.json").write_text(credentials.to_json(), encoding="utf-8")
print("Created analytics_token.json. Keep it secret.")
