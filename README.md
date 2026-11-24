# AI YouTube Auto Publisher — Bhakti Edition

यह project GitHub Actions पर रोज़ दो Hindi Bhakti Shorts बनाने के लिए है। यह **Bhakti-only** है; Technology profile workflow में disabled है.

## Schedule

- सुबह **03:00 IST** — Bhakti Short
- दोपहर **15:00 IST** — Bhakti Short

GitHub Actions scheduled runs में load के कारण देरी हो सकती है; cron समय exact start guarantee नहीं करता। Manual run: **Actions → AI YouTube Auto Publisher → Run workflow**.

## Pipeline

1. Gemini नया विषय, title, description, tags, narration, scene captions और visual search queries बनाता है.
2. हर scene के लिए Cloudflare Workers AI से अधिकतम 6 scene images बनाने की कोशिश होती है.
3. Wikimedia Commons और Google Custom Search पूरी तरह disabled हैं; कोई external photo website इस्तेमाल नहीं होती. Cloudflare image न बना पाए तो उस scene में designed placeholder रहेगा.
4. Edge TTS Hindi narration बनाता है.
5. Pillow + FFmpeg 1080×1920 vertical MP4 और subtle zoom movement बनाते हैं.
6. ffprobe QC video file size, audio/video streams, resolution और 25–65 sec duration जाँचता है.
7. कम-से-कम 2 distinct visual files न मिलने पर YouTube upload रोक दिया जाता है.
8. MP4 और JSON metadata GitHub Actions artifact में 7 दिनों तक रखे जाते हैं.

**वर्तमान सीमाएँ:** यह photo-led explainer है, वास्तविक AI talking-head/lip-sync नहीं। हिंदी subtitles वीडियो में burn-in होते हैं। Scene queries के आधार पर अलग-अलग images माँगी जाती हैं, लेकिन image का scene से semantic मिलान अभी किसी vision-model से verify नहीं होता। Telegram success/failure alerts के लिए TELEGRAM_BOT_TOKEN और TELEGRAM_CHAT_ID secrets आवश्यक हैं.

## Safe publishing defaults

`config.example.json` में privacy status **private** रखा गया है। पहली बार test के लिए private ही रखें। वीडियो देखकर और सब सही होने पर ही इसे unlisted/public करें। ध्यान दें: `config.json` मौजूद न होने पर agent `config.example.json` इस्तेमाल करता है.

## Required GitHub Actions secrets

- `GEMINI_API_KEY` — कम-से-कम एक Gemini key आवश्यक.
- `YOUTUBE_TOKEN_B64` — YouTube upload के लिए OAuth token JSON का base64.
- वैकल्पिक backup: `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3`.
- **आवश्यक image worker:** `CLOUDFLARE_IMAGE_WORKER_URL`, `CLOUDFLARE_IMAGE_TOKEN`. इन secrets के बिना सिर्फ designed placeholders बनेंगे और दो distinct visuals न मिलने पर YouTube upload रोक दिया जाएगा.
- वैकल्पिक Telegram alerts: `TELEGRAM_BOT_TOKEN` और `TELEGRAM_CHAT_ID`.

**API keys, OAuth token या client-secret JSON को GitHub repository में commit न करें।** इन्हें GitHub → Settings → Secrets and variables → Actions में रखें.

## Local Termux setup

```bash
pkg update
pkg install python ffmpeg
pip install -r requirements.txt
cp config.example.json config.json
python oauth_setup.py
export GEMINI_API_KEY='YOUR_KEY'
export YOUTUBE_UPLOAD=false
python agent.py
```

OAuth के लिए Google Cloud Console में YouTube Data API v3 enable करके Desktop App client JSON को `client_secret.json` नाम से रखें। `token.json` private रखें; GitHub पर raw token commit न करें.

Local output `output/` में आता है। Android Downloads में copy करने के लिए:

```bash
mkdir -p ~/storage/downloads/AIYouTube
cp output/*.mp4 ~/storage/downloads/AIYouTube/
```

GitHub-hosted runner सीधे Android phone storage में file नहीं लिख सकता; cloud run का video artifact से डाउनलोड करना होगा.

## Quality and free-tier notes

Workflow Python compile checks और unit tests चलाता है। Gemini, image services, Edge TTS और GitHub Actions की free limits बदल सकती हैं; पूरी तरह unlimited/free operation की guarantee नहीं है। Cloudflare-generated images के लिए कोई Wikimedia/Google source credits नहीं होते. Cloudflare Workers AI की उपलब्धता और account limits लागू होंगी.

## Telegram control panel

After enabling GitHub Actions, the Telegram controller checks for owner commands every 5 minutes (GitHub may delay scheduled runs). It uses the existing `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` Actions secrets; commands from any other chat are ignored.

Commands:
- `/help` — list commands
- `/status` — latest workflow run status
- `/run` — start a Bhakti video workflow
- `/pause` — disable the video workflow, including its schedule
- `/resume` — re-enable the video workflow and schedule
- `/lastvideo` — link to the latest successful workflow run/artifact

The controller uses the automatically provided GitHub Actions token with repository-scoped `contents:write` and `actions:write` permissions; no extra GitHub PAT is required. It stores only the Telegram update offset in `.telegram-control-state.json`. Keep the repository's Actions secrets private.

**Limitations:** This is scheduled polling, not an instant webhook; commands can take several minutes. `/lastvideo` currently links to the latest successful run/artifact and does not yet extract the YouTube watch URL. Pausing disables the whole video workflow, including manual runs, but leaves the Telegram controller active so `/resume` still works.
