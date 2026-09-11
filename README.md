# AI YouTube Auto Publisher

यह repo रोज़ सुबह **05:00 IST** पर बिना daily topic input के एक short educational video बनाने और YouTube पर upload करने के लिए free-first automation देता है.

## क्या करता है
- Gemini API से नया topic + script + title/description/tags चुनता है
- Hindi (या config में चुनी language) narration बनाता है
- TTS audio + vertical 1080x1920 text slides + FFmpeg से MP4 बनाता है
- YouTube OAuth के जरिए upload करता है
- GitHub Actions generated MP4 को artifact के रूप में 7 दिन रखता है
- Manual run के लिए `workflow_dispatch` भी है

## जरूरी बात
**API keys/token को repo में कभी commit न करें.** GitHub Actions में `GEMINI_API_KEY` और `YOUTUBE_TOKEN_B64` secrets रखें.

## GitHub setup
1. Google Cloud Console में YouTube Data API v3 enable करें और OAuth Desktop App credentials डाउनलोड करके local machine/Termux में `client_secret.json` रखें.
2. `pip install -r requirements.txt && python oauth_setup.py` चलाएँ. इससे private `token.json` बनेगा.
3. `base64 -w0 token.json` (Android/Termux में `base64 -w0 token.json`) का output GitHub repository secret `YOUTUBE_TOKEN_B64` में रखें.
4. Gemini API key को repository secret `GEMINI_API_KEY` में रखें.
5. Actions में **AI YouTube Auto Publisher** workflow को पहले `Run workflow` से test करें.

## Local Termux mode
```bash
pkg update
pkg install python ffmpeg
pip install -r requirements.txt
cp config.example.json config.json
python oauth_setup.py
export GEMINI_API_KEY='YOUR_KEY'
export YOUTUBE_UPLOAD=true
python agent.py
```

Local mode में MP4 `output/` में रहता है. Android storage में copy करने के लिए:
```bash
mkdir -p ~/storage/downloads/AIYouTube
cp output/*.mp4 ~/storage/downloads/AIYouTube/
```

## Configuration
`config.json` में niche, language, voice, duration, privacy status आदि बदलें. Default YouTube privacy `private` है ताकि पहली automated run public न हो. Test के बाद `unlisted` या `public` कर सकते हैं.

## Free limits / reality
यह code paid video-generation service पर निर्भर नहीं है; Gemini/TTS/API services की free-tier limits बदल सकती हैं. GitHub Actions भी usage limits के अधीन है. Phone में automatic local save केवल तब reliable है जब Termux/device automation वास्तव में चल रही हो; GitHub-hosted runner सीधे आपके phone storage में file नहीं लिख सकता. Cloud run में video GitHub Actions artifact के रूप में मिलता है.

## Safety
यह system generic educational content के लिए बनाया गया है. Publish करने से पहले facts/rights/YouTube policies की जाँच करें. Copyrighted music, clips या images बिना अधिकार के न जोड़ें.
