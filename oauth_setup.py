#!/usr/bin/env python3
"""One-time local YouTube OAuth setup.
Download OAuth client JSON from Google Cloud Console and save it as client_secret.json.
Run: python oauth_setup.py
Then keep token.json private; never commit it.
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
SCOPES=["https://www.googleapis.com/auth/youtube.upload"]
CLIENT=Path("client_secret.json")
if not CLIENT.exists(): raise SystemExit("Missing client_secret.json")
flow=InstalledAppFlow.from_client_secrets_file(str(CLIENT),SCOPES)
creds=flow.run_local_server(port=0, access_type="offline", prompt="consent")
Path("token.json").write_text(creds.to_json(),encoding="utf-8")
print("Created token.json. Keep it secret. For GitHub Actions, store its base64 content as YOUTUBE_TOKEN_B64.")
