# AI YouTube Auto Publisher

यह repo रोज़ सुबह **05:00 IST** पर बिना daily topic input के एक short educational video बनाने और YouTube पर upload करने के लिए free-first automation देता है.

## क्या करता है
- Gemini API से नया topic + script + title/description/tags चुनता है
- Hindi (या config में चुनी language) narration बनाता है
- TTS audio + vertical 1080x1920 text slides + FFmpeg से MP4 बनाता है
- YouTube OAuth के जरिए upload करता है
- GitHub Actions generated MP4 को artifact के रूप में 7 दिन रखता है
- Manual run के लिए `workflow_dispatch` भी है

## API key के बारे में साफ जानकारी

इस project में **वीडियो बनाने वाली कोई अलग API key नहीं लगती** और न ही किसी paid AI video-generation service (जैसे text-to-video API) की जरूरत है.

- **केवल Gemini Text API key (`GEMINI_API_KEY`)** topic, title, narration/script और slide text बनाने के लिए जरूरी है.
- Default text model अब `gemini-3.8-flash` है; पुराने `gemini-2.5-flash` पर निर्भर नहीं है. चाहो तो `GEMINI_MODEL` environment variable से model बदल सकते हो.
- Hindi voice **Edge TTS** से बनती है.
- Images अब default रूप से Wikimedia Commons से बिना API key के खोजी जाती हैं. Google Custom Search वैकल्पिक है; उसे चुनने पर भी परिणाम न मिलने पर Wikimedia fallback रहेगा. हर image का source/license metadata `output/visual_credits.json` में सेव होता है; इस्तेमाल से पहले संबंधित license की शर्तें देखें.
- Images + text slides + voice को **Python/Pillow और FFmpeg** जोड़कर MP4 बनाते हैं.
- यह वास्तविक AI-generated moving presenter या lip-sync video नहीं है; अभी presenter एक animated-style graphic है और मुख्य visuals slides/images हैं.

**API keys/token को repo में कभी commit न करें.** GitHub Actions में:- `GEMINI_API_KEY` आवश्यक है — इसके बिना वीडियो नहीं बनेगा.
- `YOUTUBE_TOKEN_B64` अपलोड के लिए आवश्यक है. अगर यह secret नहीं है, workflow वीडियो बनाकर artifact सेव करेगा और upload को स्पष्ट warning के साथ skip करेगा.
- `GOOGLE_CSE_API_KEY` और `GOOGLE_CSE_ID` वैकल्पिक हैं; इनके बिना Wikimedia Commons से visuals खोजे जाएँगे.

Workflow अब Python syntax और Gemini JSON parser के unit tests भी चलाता है. YouTube OAuth token में refresh token होना चाहिए; उसे बनाने के लिए `oauth_setup.py` को consent के साथ चलाएँ.

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
