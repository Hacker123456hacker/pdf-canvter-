#!/usr/bin/env python3
"""Poll Telegram for allow-listed owner commands and control the YouTube workflow."""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
REPO = os.environ["GITHUB_REPOSITORY"]
BOT = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT = str(os.environ["TELEGRAM_CHAT_ID"])
GH = os.environ["GITHUB_TOKEN"]
WORKFLOW = "auto-youtube.yml"
STATE_PATH = Path(".telegram-control-state.json")
HEADERS = {
    "Authorization": "Bearer " + GH,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "Bhakti-Telegram-Control",
}


def request_json(url, method="GET", data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = response.read()
        return json.loads(raw.decode()) if raw else {}


def gh(path, method="GET", data=None):
    h = dict(HEADERS)
    if data is not None:
        h["Content-Type"] = "application/json"
    return request_json(API + path, method, data, h)


def telegram(method, data):
    url = f"https://api.telegram.org/bot{BOT}/{method}"
    return request_json(url, "POST", data, {"Content-Type": "application/json"})


def reply(text):
    telegram("sendMessage", {
        "chat_id": CHAT,
        "text": text[:3900],
        "disable_web_page_preview": True,
    })


def read_state():
    if not STATE_PATH.exists():
        return {"offset": 0}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {"offset": max(0, int(state.get("offset", 0)))}
    except Exception:
        return {"offset": 0}


def save_state(state):
    # Persist only the Telegram update offset. Pause/resume is the workflow's
    # enabled/disabled state at GitHub, not a second source of truth.
    STATE_PATH.write_text(json.dumps(state, separators=(",", ":")) + "\n", encoding="utf-8")
    path = "/repos/" + REPO + "/contents/" + STATE_PATH.name
    try:
        old = gh(path)
        sha = old["sha"]
    except Exception:
        sha = None
    import base64
    payload = {
        "message": "chore: update Telegram control offset",
        "content": base64.b64encode(STATE_PATH.read_bytes()).decode(),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    gh(path, "PUT", payload)


def workflow_enabled():
    data = gh(f"/repos/{REPO}/actions/workflows/{WORKFLOW}")
    return data.get("state") == "active"


def run_status():
    data = gh(f"/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page=5")
    runs = data.get("workflow_runs", [])
    if not runs:
        return "अभी तक कोई workflow run नहीं मिला।"
    latest = runs[0]
    return (
        "📊 Latest run status\n"
        f"Status: {latest.get('status', 'unknown')}\n"
        f"Result: {latest.get('conclusion') or 'running/not finished'}\n"
        f"Run: #{latest.get('run_number')}\n"
        f"Started: {latest.get('run_started_at') or latest.get('created_at')}\n"
        f"Details: {latest.get('html_url')}"
    )


def latest_run():
    data = gh(f"/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page=10")
    runs = data.get("workflow_runs", [])
    if not runs:
        return "अभी कोई video workflow run नहीं मिला।"
    done = next((x for x in runs if x.get("conclusion") == "success"), runs[0])
    return (
        "🎬 Latest available video run\n"
        f"Run: #{done.get('run_number')}\n"
        f"Result: {done.get('conclusion') or done.get('status')}\n"
        f"Started: {done.get('run_started_at') or done.get('created_at')}\n"
        "YouTube video URL metadata से यहाँ अभी उपलब्ध नहीं है।\n"
        f"Run/artifact: {done.get('html_url')}"
    )


def handle(command):
    cmd = command.split()[0].lower().split("@")[0]
    if cmd in ("/start", "/help"):
        reply(
            "🤖 Bhakti YouTube Control\n"
            "/status — latest run status\n"
            "/run — start a Bhakti video now\n"
            "/pause — pause scheduled/manual video workflow\n"
            "/resume — resume workflow and schedule\n"
            "/lastvideo — latest successful run/artifact\n"
            "/help — show commands\n\n"
            "Commands are accepted only from your configured Telegram chat."
        )
    elif cmd == "/status":
        reply(run_status())
    elif cmd == "/lastvideo":
        reply(latest_run())
    elif cmd == "/run":
        gh(f"/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches", "POST", {
            "ref": "main",
            "inputs": {"video_type": "bhakti"},
        })
        reply("🚀 Bhakti video workflow start request GitHub को भेज दी गई है। थोड़ी देर में /status से देख सकते हैं।")
    elif cmd == "/pause":
        gh(f"/repos/{REPO}/actions/workflows/{WORKFLOW}/disable", "PUT")
        reply("⏸️ Video workflow pause कर दिया गया है। Scheduled और manual runs बंद रहेंगे। /resume से फिर चालू करें।")
    elif cmd == "/resume":
        gh(f"/repos/{REPO}/actions/workflows/{WORKFLOW}/enable", "PUT")
        reply("▶️ Video workflow resume कर दिया गया है। अगला scheduled run अपने समय पर होगा।")
    else:
        reply("यह command उपलब्ध नहीं है। /help भेजें।")


def main():
    if not BOT or not CHAT or not GH:
        raise SystemExit("Telegram/GitHub control secrets are missing.")
    state = read_state()
    # Polling is used instead of a permanently running server; this keeps the
    # controller compatible with the existing GitHub Actions/free-first setup.
    updates = telegram("getUpdates", {
        "offset": state["offset"],
        "timeout": 0,
        "allowed_updates": ["message"],
    }).get("result", [])
    for update in updates:
        state["offset"] = max(state["offset"], int(update.get("update_id", 0)) + 1)
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if chat_id != CHAT or not text.startswith("/"):
            continue
        try:
            handle(text)
        except Exception as exc:
            # Do not echo credentials or full request URLs into Telegram.
            reply("❌ Command execute नहीं हुआ: " + type(exc).__name__ + ". GitHub Actions/permissions जाँचें।")
            print("Command failed:", type(exc).__name__, str(exc)[:500], file=sys.stderr)
    if updates:
        save_state(state)


if __name__ == "__main__":
    main()
