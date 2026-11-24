#!/usr/bin/env python3
"""Free-first AI YouTube Shorts agent. Generates Hindi content, Cloudflare-only scene images, TTS, subtitles and uploads to YouTube. Missing Cloudflare images use designed placeholders; no external photo sources are used."""
import json, os, re, subprocess, sys, time
from pathlib import Path
from datetime import datetime

import requests
from cloudflare_media import generate_cloudflare_images
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
WORK = ROOT / "work"
OUT = ROOT / "output"
WORK.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)


def env(name, default=""):
    return os.getenv(name, default).strip()


def cfg():
    p = Path(env("CONFIG_FILE", str(ROOT / "config.json")))
    if not p.exists(): p = ROOT / "config.example.json"
    return json.loads(p.read_text(encoding="utf-8"))


def gemini(prompt):
    keys = list(dict.fromkeys(
        value for value in (
            env("GEMINI_API_KEY"), env("GEMINI_API_KEY_2"), env("GEMINI_API_KEY_3")
        ) if value
    ))
    if not keys:
        raise RuntimeError("Add GEMINI_API_KEY (and optionally GEMINI_API_KEY_2 / GEMINI_API_KEY_3) to GitHub Secrets.")
    primary = env("GEMINI_MODEL", "gemini-3.8-flash")
    fallbacks = [x.strip() for x in env("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.5-flash-lite").split(",") if x.strip()]
    models = list(dict.fromkeys([primary] + fallbacks))
    last_error = None

    # Rotate through every configured key and model on quota, overload, auth, or network errors.
    for key_index, key in enumerate(keys, 1):
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for attempt in range(1, 3):
                try:
                    response = requests.post(
                        url,
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        headers={"x-goog-api-key": key},
                        timeout=(12, 75),
                    )
                    response.raise_for_status()
                    body = response.json()
                    candidates = body.get("candidates") or []
                    if not candidates:
                        feedback = body.get("promptFeedback", {})
                        raise RuntimeError(f"Gemini {model} returned no candidate: {feedback or body}")
                    print(f"Gemini key slot {key_index}, model used: {model}")
                    content = candidates[0].get("content") or {}
                    parts = content.get("parts") or []
                    generated = next((part.get("text") for part in parts if isinstance(part, dict) and part.get("text")), None)
                    if not generated:
                        last_error = RuntimeError(f"Gemini {model} returned an empty or blocked candidate")
                        print(f"Gemini key slot {key_index}, model {model} returned no text; switching fallback.")
                        break
                    return generated
                except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                    last_error = exc
                    status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None
                    if isinstance(exc, requests.HTTPError) and exc.response is not None:
                        try:
                            detail = exc.response.json()
                        except ValueError:
                            detail = exc.response.text
                        detail_text = json.dumps(detail, ensure_ascii=False) if isinstance(detail, (dict, list)) else str(detail)
                        # Never print the request URL (it contains the API key); redact key-like values too.
                        detail_text = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_API_KEY]", detail_text)
                        print(f"Gemini API response details (HTTP {status}): {detail_text[:1500]}")
                    if isinstance(exc, requests.HTTPError) and status not in (400, 401, 403, 404, 408, 429, 500, 502, 503, 504):
                        raise
                    # A quota/auth/model error should immediately try the next option.
                    if status in (400, 401, 403, 404, 429):
                        print(f"Gemini key slot {key_index}, model {model} returned HTTP {status}; switching fallback.")
                        break
                    if attempt < 2:
                        print(f"Gemini key slot {key_index}, model {model} temporary error (attempt {attempt}/2): {exc}. Retrying in 4s...")
                        time.sleep(4)
                except RuntimeError as exc:
                    last_error = exc
                    break

    raise RuntimeError(
        f"Gemini generation failed with {len(keys)} configured key(s) and models "
        f"({', '.join(models)}). Last error: {last_error}"
    ) from last_error

def openrouter_generate(prompt):
    """Last-resort text generation through OpenRouter when Gemini options fail."""
    api_key = env("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OpenRouter fallback is not configured.")
    model = env("OPENROUTER_MODEL") or "openrouter/auto"
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json",
                 "HTTP-Referer": "https://github.com", "X-Title": "Bhakti Video Automation"},
        json={"model": model, "messages": [
            {"role": "system", "content": "Return only valid JSON and follow the requested schema."},
            {"role": "user", "content": prompt}], "temperature": 0.7},
        timeout=(15, 120),
    )
    if not response.ok:
        detail = re.sub(r"(?i)(sk-or-v1-[A-Za-z0-9_-]{12,})", "[REDACTED_API_KEY]", response.text[:800])
        raise RuntimeError("OpenRouter HTTP " + str(response.status_code) + ": " + detail)
    body = response.json()
    choices = body.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    generated = message.get("content")
    if isinstance(generated, list):
        generated = "".join(str(part.get("text", "")) for part in generated if isinstance(part, dict))
    if not isinstance(generated, str) or not generated.strip():
        raise RuntimeError("OpenRouter returned an empty response")
    print("OpenRouter fallback model used: " + str(body.get("model") or model))
    return generated.strip()


def groq_generate(prompt):
    """Final text-generation fallback using Groq's OpenAI-compatible API."""
    api_key = env("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Groq fallback is not configured.")
    model = env("GROQ_MODEL") or "llama-3.3-70b-versatile"
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json={"model": model, "messages": [
            {"role": "system", "content": "Return only valid JSON and follow the requested schema."},
            {"role": "user", "content": prompt}], "temperature": 0.7},
        timeout=(15, 120),
    )
    if not response.ok:
        detail = re.sub(r"(?i)(gsk_[A-Za-z0-9_-]{12,})", "[REDACTED_API_KEY]", response.text[:800])
        raise RuntimeError("Groq HTTP " + str(response.status_code) + ": " + detail)
    body = response.json()
    choices = body.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    generated = message.get("content")
    if not isinstance(generated, str) or not generated.strip():
        raise RuntimeError("Groq returned an empty response")
    print("Groq fallback model used: " + str(body.get("model") or model))
    return generated.strip()


def parse_gemini_json(raw):
    """Parse Gemini JSON despite optional markdown fences or surrounding prose."""
    text = (raw or "").strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```\s*$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Gemini response did not contain a JSON object")
    data = json.loads(text[start:end + 1])
    for key in ("title", "narration", "slides"):
        if not data.get(key):
            raise ValueError("Gemini response missing required field: " + key)
    if not isinstance(data["slides"], list) or not all(isinstance(x, str) and x.strip() for x in data["slides"]):
        raise ValueError("Gemini slides must be a non-empty list of text strings")
    if not isinstance(data.get("tags", []), list):
        data["tags"] = []
    if not isinstance(data.get("visual_queries", []), list):
        data["visual_queries"] = []
    return data


def make_content(c):
    profile=env("CONTENT_PROFILE","bhakti").lower()
    # Bhakti videos must always use natural Hindi written in Devanagari.
    # English is reserved only for visual_queries, which are image-generation prompts.
    lang = "Hindi written only in Devanagari script" if profile == "bhakti" else c["content"].get("language","hi")
    if profile == "bhakti":
        niche="Hindi devotional and spiritual content: bhajans, aarti, mantra meaning, festival traditions, stories from Hindu scriptures and practical values"
        profile_rules="""Keep the tone respectful, peaceful and devotional. Choose a different bhakti topic each day: aarti, bhajan meaning, mantra meaning, festival tradition, or a short story/value from a Hindu scripture. Attribute scripture-based stories carefully; do not invent quotations, verses, miracles, historical facts, or claims. Do not present generated lyrics as traditional lyrics. Avoid asking viewers to pay, donate, or perform unsafe rituals."""
        category_id="22"
    else:
        niche="Hindi technology, AI tools, smartphones, internet, useful apps, cybersecurity awareness and digital skills"
        profile_rules="""Keep the tone practical, clear and exciting. Choose a different useful technology topic each day, prioritizing AI tools, Android/mobile tips, internet safety, useful apps and digital skills. Verify product names and avoid fabricated features, fake news, or unsafe hacking instructions."""
        category_id="28"
    seed=c["content"].get("topic_seed","")
    avoid=", ".join(c["content"].get("avoid_topics",[])) or "none"
    target_seconds=max(30,min(60,int(c["content"].get("duration_seconds",60))))
    prompt=f'''Create ONE original short-form YouTube video in {lang} for the niche: {niche}.
Video profile: {profile}. {profile_rules}
LANGUAGE RULE (MANDATORY): For the Bhakti profile, write title, description, tags, narration, and every slide caption entirely in natural Hindi using Devanagari script. Do not write these fields in English or Hinglish. Use simple spoken Hindi that Indian viewers can understand. Do not mix English words into Hindi sentences unless a proper name has no natural Hindi form. The ONLY field allowed to contain English is visual_queries, because it is used for image generation.
No daily topic will be supplied, so choose a fresh, useful topic yourself; do not repeat a generic topic.
Topic hint (optional): {seed or "none"}. Avoid: {avoid}.
Target narration length: 30-60 seconds, ideally about 50-55 seconds.
Write roughly 100-125 Hindi words in natural, conversational spoken Hindi; do not make it too brief.
Start with a strong 2-second hook, explain the topic clearly, and finish with a memorable takeaway.
Return ONLY valid JSON with keys title, description, tags, narration, slides, visual_queries.
slides must contain 6-8 short Hindi scene captions in Devanagari, in the exact order of the narration.
visual_queries must contain exactly the same number of concise English image-generation queries, one per scene, each only 2-5 concrete search terms.
Ask for real photographs of the actual subject (not illustrations, icons, logos, text, or generic backgrounds).
Do not make medical/legal/financial claims or sensational misinformation.'''

    try:
        raw_content = gemini(prompt)
    except Exception as gemini_error:
        if not env("OPENROUTER_API_KEY"):
            raise
        print("Gemini options exhausted (" + type(gemini_error).__name__ + "); trying OpenRouter.")
        try:
            raw_content = openrouter_generate(prompt)
        except Exception as openrouter_error:
            if not env("GROQ_API_KEY"):
                raise
            print("OpenRouter failed (" + type(openrouter_error).__name__ + "); trying Groq.")
            raw_content = groq_generate(prompt)
    data = parse_gemini_json(raw_content)
    data["video_profile"] = profile
    data["youtube_category_id"] = category_id
    # Gemini sometimes ignores the requested word count. Cap narration so Hindi
    # speech reliably fits the requested 30-60 second Shorts format.
    narration=data["narration"].strip()
    if len(narration.split()) > 120:
        sentences=re.split(r"(?<=[।!?])\s+", narration)
        kept=[]; count=0
        for sentence in sentences:
            n=len(sentence.split())
            if count+n > 120:
                break
            kept.append(sentence); count+=n
        if not kept:
            kept=[" ".join(narration.split()[:118])+"।"]
        data["narration"]=" ".join(kept).strip()
        print(f"Shortened Gemini narration from {len(narration.split())} to {len(data['narration'].split())} words")
    data["visual_queries"] = [str(x) for x in data.get("visual_queries", []) if str(x).strip()]
    if not data.get("visual_queries"):
        data["visual_queries"] = [data["title"]] * len(data["slides"])

    # Add a small set of relevant hashtags to the YouTube description.
    # Keep profile hashtags first, then derive topic hashtags from Gemini tags.
    profile_hashtags = (
        ["#Bhakti", "#Krishna", "#SanatanDharma"]
        if profile == "bhakti"
        else ["#Technology", "#AI", "#TechTips"]
    )
    topic_hashtags = []
    for tag in data.get("tags", []):
        clean = re.sub(r"[^\w]", "", str(tag), flags=re.UNICODE)
        if len(clean) >= 2:
            hashtag = "#" + clean
            if hashtag.lower() not in {x.lower() for x in profile_hashtags + topic_hashtags}:
                topic_hashtags.append(hashtag)
        if len(topic_hashtags) >= 2:
            break
    hashtags = (profile_hashtags + topic_hashtags)[:5]
    description = str(data.get("description", "")).strip()
    # Avoid duplicating hashtags if Gemini already supplied them.
    description = re.sub(r"(?:\s*#[\w]+)+\s*$", "", description).rstrip()
    data["hashtags"] = hashtags
    data["description"] = (description + "\n\n" + " ".join(hashtags)).strip()
    print("YouTube hashtags:", " ".join(hashtags))
    return data


def font(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()


def fetch_visuals(data, c):
    """Cloudflare-only visuals; missing generations use designed placeholders."""
    queries = data.get("visual_queries", [])
    (OUT / "visual_credits.json").write_text("[]", encoding="utf-8")
    print("External image search disabled: Cloudflare AI is the only photo provider.")
    return [None for _ in queries], []


def fit_cover(im, size):
    w,h=size; src=im.convert("RGB"); sw,sh=src.size
    scale=max(w/sw,h/sh); nw,nh=int(sw*scale),int(sh*scale)
    src=src.resize((nw,nh),Image.Resampling.LANCZOS)
    left=(nw-w)//2; top=(nh-h)//2
    return src.crop((left,top,left+w,top+h))


def make_slides(slides,c,visual_paths=None):
    """Create scenes using only their own matching image; never cycle unrelated photos."""
    w,h=c["video"].get("width",1080),c["video"].get("height",1920)
    paths=[]; visual_paths=visual_paths or []
    for i,_scene_text in enumerate(slides):
        scene_image = visual_paths[i] if i < len(visual_paths) else None
        if scene_image:
            try:
                with Image.open(scene_image) as src:
                    # Fill the vertical frame with the photo; no overlays or labels.
                    bg=fit_cover(src,(w,h))
                im=bg.convert("RGB")
            except Exception:
                im=Image.new("RGB",(w,h),(12,18,32))
        else:
            im=Image.new("RGB",(w,h),(28,38,62))
            draw=ImageDraw.Draw(im)
            for y in range(h):
                shade=int(28 + 24*y/max(1,h-1))
                draw.line((0,y,w,y), fill=(shade, shade+8, min(110,shade+38)))
            draw.ellipse((w*0.12,h*0.18,w*0.88,h*0.62), outline=(180,150,95), width=max(3,w//180))
            draw.text((w//2,h//2), f"Divya Vichar {i+1}", anchor="mm", font=font(max(28,w//24)), fill=(255,238,205))
        p=WORK/f"slide_{i:02d}.jpg"
        im.save(p,quality=90,optimize=True)
        paths.append(p)
    return paths

def vtt_to_srt(source_path, srt_path):
    """Normalize Edge TTS subtitle output to SRT (edge-tts 7 emits SRT, not VTT)."""
    raw = Path(source_path).read_text(encoding="utf-8-sig")
    # Accept both SRT timestamps (comma) and older WebVTT timestamps (period).
    pattern = r"(?m)^(\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[,.]\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)"
    cues = re.findall(pattern, raw, re.S)
    rows = []
    for n, (begin, finish, caption) in enumerate(cues, 1):
        caption = re.sub(r"<[^>]+>", "", caption).strip()
        caption = " ".join(line.strip() for line in caption.splitlines() if line.strip())
        if caption:
            rows.extend([str(n), f"{begin.replace('.', ',')} --> {finish.replace('.', ',')}", caption, ""])
    Path(srt_path).write_text("\n".join(rows), encoding="utf-8")
    return bool(rows)


def media_duration(path):
    probe=subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],
        capture_output=True,text=True
    )
    if probe.returncode != 0:
        raise RuntimeError("Could not inspect generated media: "+probe.stderr[-1000:])
    return float(probe.stdout.strip())



def validate_video_probe(probe, expected_width=1080, expected_height=1920, min_duration=25, max_duration=65, file_size=0):
    if file_size < 100_000:
        raise RuntimeError(f"Generated MP4 is too small ({file_size} bytes)")
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        raise RuntimeError("Generated MP4 has no video stream")
    if not audio:
        raise RuntimeError("Generated MP4 has no audio stream")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if (width, height) != (int(expected_width), int(expected_height)):
        raise RuntimeError(f"Unexpected video resolution {width}x{height}; expected {expected_width}x{expected_height}")
    try:
        duration = float((probe.get("format") or {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    if not min_duration <= duration <= max_duration:
        raise RuntimeError(f"Video duration {duration:.2f}s is outside {min_duration}-{max_duration}s")
    if not video.get("codec_name") or not audio.get("codec_name"):
        raise RuntimeError("Video or audio codec metadata is missing")
    return {"duration": duration, "width": width, "height": height, "video_codec": video["codec_name"], "audio_codec": audio["codec_name"]}



def make_thumbnail(title, scene_path, c):
    """Create a 1280x720 YouTube thumbnail using the first scene and readable Hindi title."""
    thumb = OUT / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_thumbnail.jpg")
    width, height = 1280, 720
    try:
        with Image.open(scene_path) as source:
            image = fit_cover(source, (width, height)).convert("RGB")
    except Exception:
        image = Image.new("RGB", (width, height), (18, 24, 42))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(height):
        alpha = int(35 + 185 * (y / height))
        draw.line((0, y, width, y), fill=(0, 0, 0, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    title = re.sub(r"\s+", " ", str(title)).strip()
    words, lines, line = title.split(), [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font(66)) [2] <= 1160:
            line = candidate
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)
    lines = lines[:3]
    fnt = font(66)
    y = height - 90 - len(lines) * 82
    for line in lines:
        draw.text((60 + 3, y + 3), line, font=fnt, fill=(0, 0, 0), stroke_width=3, stroke_fill=(0, 0, 0))
        draw.text((60, y), line, font=fnt, fill=(255, 255, 255), stroke_width=2, stroke_fill=(35, 35, 35))
        y += 82
    image.save(thumb, "JPEG", quality=92, optimize=True)
    print("Thumbnail created:", thumb)
    return thumb


def verify_video_quality(path, c):
    video_path = Path(path)
    if not video_path.is_file():
        raise RuntimeError("Generated MP4 file is missing")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video_path)], capture_output=True, text=True, timeout=30)
    if probe.returncode:
        raise RuntimeError("ffprobe could not read generated MP4: " + probe.stderr[-1200:])
    try:
        metadata = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe returned invalid metadata") from exc
    v = c.get("video", {})
    report = validate_video_probe(metadata, v.get("width", 1080), v.get("height", 1920), file_size=video_path.stat().st_size)
    # Detect sustained black frames and long audio dropouts; short fades/pauses are allowed.
    black = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video_path), "-vf", "blackdetect=d=2:pix_th=0.10", "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=90)
    if black.returncode not in (0, 1):
        raise RuntimeError("Black-frame QC could not complete: " + black.stderr[-800:])
    black_events = re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+) black_duration:([0-9.]+)", black.stderr)
    long_black = [float(event[2]) for event in black_events if float(event[2]) >= 2.0]
    if long_black:
        raise RuntimeError("Video QC rejected sustained black frames: " + ", ".join(f"{x:.2f}s" for x in long_black))
    silence = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video_path), "-af", "silencedetect=noise=-50dB:d=3", "-vn", "-f", "null", "-"], capture_output=True, text=True, timeout=90)
    if silence.returncode not in (0, 1):
        raise RuntimeError("Audio-silence QC could not complete: " + silence.stderr[-800:])
    silence_events = re.findall(r"silence_duration: ([0-9.]+)", silence.stderr)
    long_silence = [float(x) for x in silence_events if float(x) >= 3.0]
    if long_silence:
        raise RuntimeError("Video QC rejected long audio dropouts: " + ", ".join(f"{x:.2f}s" for x in long_silence))
    report["black_frame_events"] = len(black_events)
    report["long_silence_events"] = len(long_silence)
    print("Video QC passed: %sx%s, %.2fs, video=%s, audio=%s; black/silence scan passed" % (report["width"], report["height"], report["duration"], report["video_codec"], report["audio_codec"]))
    return report


def _srt_timestamp(seconds):
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_approximate_srt(text, duration, target):
    """Create sentence-level captions for fallback speech without word timings."""
    sentences = [x.strip() for x in re.split(r"(?<=[।!?])\s+|(?<=[.!?])\s+", text) if x.strip()] or [text.strip()]
    total = sum(max(1, len(x)) for x in sentences)
    cursor = 0.0
    rows = []
    for index, sentence in enumerate(sentences, 1):
        finish = duration if index == len(sentences) else cursor + duration * max(1, len(sentence)) / total
        rows.extend([str(index), _srt_timestamp(cursor) + " --> " + _srt_timestamp(finish), sentence, ""])
        cursor = finish
    Path(target).write_text("\n".join(rows), encoding="utf-8")
    return bool(rows)


def tts(text,c):
    audio=WORK/"voice.mp3"; vtt=WORK/"voice.srt"; srt=WORK/"voice.srt"
    voice=c["video"].get("voice","hi-IN-SwaraNeural"); rate=c["video"].get("tts_rate","+0%")
    reason="Edge TTS did not return usable media"
    for attempt in range(1,4):
        audio.unlink(missing_ok=True); vtt.unlink(missing_ok=True); srt.unlink(missing_ok=True)
        cmd=[sys.executable,"-m","edge_tts","--voice",voice,"--rate",rate,"--text",text,"--write-media",str(audio),"--write-subtitles",str(vtt)]
        try:
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        except (subprocess.TimeoutExpired, OSError) as exc:
            r=None; reason=type(exc).__name__ + ": " + str(exc)
        if r is not None and r.returncode:
            reason=(r.stderr or r.stdout)[-1200:]
            print("Hindi Edge TTS attempt " + str(attempt) + "/3 failed: " + reason)
        elif r is not None and audio.exists() and audio.stat().st_size > 10000 and vtt.exists():
            try:
                seconds=media_duration(audio); captions_ok=vtt_to_srt(vtt,srt)
            except Exception as exc:
                seconds=0; captions_ok=False; print("Edge TTS validation failed: " + str(exc))
            if 25 <= seconds <= 65 and captions_ok and srt.stat().st_size > 20:
                print("Hindi Edge TTS succeeded: %.2fs" % seconds)
                return audio,srt
            reason="invalid audio duration or missing/empty timed subtitles"
        elif r is not None:
            reason="audio or subtitle file missing/suspiciously small"
        if attempt < 3: time.sleep(3 * attempt)

    # Edge TTS can return HTTP 403 from hosted runners; use gTTS as a secondary provider.
    audio.unlink(missing_ok=True); vtt.unlink(missing_ok=True); srt.unlink(missing_ok=True)
    try:
        from gtts import gTTS
        print("Trying secondary Hindi TTS provider (gTTS).")
        gTTS(text=text, lang="hi", slow=False).save(str(audio))
        if not audio.exists() or audio.stat().st_size <= 10000:
            raise RuntimeError("gTTS audio missing or too small")
        seconds=media_duration(audio)
        if not 25 <= seconds <= 65:
            raise RuntimeError("gTTS duration %.2fs is outside 25-65 seconds" % seconds)
        write_approximate_srt(text, seconds, srt)
        if not srt.exists() or srt.stat().st_size <= 20:
            raise RuntimeError("gTTS captions could not be created")
        print("Secondary Hindi TTS succeeded: %.2fs" % seconds)
        return audio,srt
    except Exception as exc:
        audio.unlink(missing_ok=True); srt.unlink(missing_ok=True)
        raise RuntimeError("Hindi narration failed: Edge TTS exhausted (" + str(reason) + "); gTTS fallback failed (" + type(exc).__name__ + ": " + str(exc) + ")") from exc


def render(slides,audio,c,subtitles_path=None,video_clip=None):
    out=OUT/(datetime.now().strftime("%Y%m%d_%H%M%S")+".mp4")
    w=c["video"].get("width",1080); h=c["video"].get("height",1920); fps=c["video"].get("fps",30)
    audio_duration=media_duration(audio)
    if not 25 <= audio_duration <= 65:
        raise RuntimeError(f"Refusing invalid narration duration: {audio_duration:.2f}s")
    if not subtitles_path or not Path(subtitles_path).is_file() or Path(subtitles_path).stat().st_size < 20:
        raise RuntimeError("Timed Hindi subtitles are missing; refusing to render an incomplete video")
    duration=audio_duration/len(slides)
    segments=[]
    for i,slide in enumerate(slides):
        segment=WORK/f"segment_{i:02d}.mp4"
        frames=max(1,int(duration*fps))
        zoom=rf"scale={w}:{h},zoompan=z='1+0.07*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps},format=yuv420p"
        if i == 0 and video_clip and Path(video_clip).exists():
            video_filter=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},format=yuv420p"
            cmd=["ffmpeg","-y","-stream_loop","-1","-i",str(video_clip),
                 "-t",f"{duration:.4f}","-vf",video_filter,"-an","-c:v","libx264",
                 "-preset","ultrafast","-crf","21","-r",str(fps),"-pix_fmt","yuv420p",
                 "-movflags","+faststart",str(segment)]
        else:
            cmd=["ffmpeg","-y","-loop","1","-framerate",str(fps),"-i",str(slide),
                 "-t",f"{duration:.4f}","-vf",zoom,"-an","-c:v","libx264",
                 "-preset","ultrafast","-crf","21","-r",str(fps),"-pix_fmt","yuv420p",
                 "-movflags","+faststart",str(segment)]
        result=subprocess.run(cmd,capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError(f"Could not render scene {i+1}: "+result.stderr[-2500:])
        segments.append(segment)
    listfile=WORK/"video_segments.txt"
    with listfile.open("w",encoding="utf-8") as f:
        for segment in segments:
            f.write("file '" + segment.as_posix() + "'\n")
    # Burn readable Hindi captions into the final video using FFmpeg/libass.
    subtitle_file=Path(subtitles_path).resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    subtitle_filter=(
        "subtitles=filename='" + subtitle_file + "':"
        "force_style='FontName=Noto Sans Devanagari,FontSize=18,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,"
        "BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=220'"
    )
    cmd=["ffmpeg","-y","-f","concat","-safe","0","-i",str(listfile),"-i",str(audio),
         "-map","0:v:0","-map","1:a:0","-vf",subtitle_filter,"-r",str(fps),"-c:v","libx264",
         "-preset","ultrafast","-crf","21","-c:a","aac","-b:a","128k",
         "-t",f"{audio_duration:.3f}","-movflags","+faststart",str(out)]
    result=subprocess.run(cmd,capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError("FFmpeg subtitle/video render failed: "+result.stderr[-3500:])
    final_duration=media_duration(out)
    print(f"Final video duration: {final_duration:.2f}s; Hindi subtitles burned in")
    if not 25 <= final_duration <= 65:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"Rendered video duration is invalid: {final_duration:.2f}s; artifact rejected")
    return out


def youtube_upload(video,data,c,thumbnail=None):
    """Upload a video, apply its generated thumbnail, then verify YouTube's saved status."""
    token_path=Path(env("YOUTUBE_TOKEN_FILE",str(ROOT/"token.json")))
    if not token_path.exists(): raise RuntimeError("YouTube OAuth token.json missing. Run oauth_setup.py locally first.")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request
    creds=Credentials.from_authorized_user_file(str(token_path),["https://www.googleapis.com/auth/youtube.upload"])
    if creds.expired:
        if not creds.refresh_token:
            raise RuntimeError("YouTube OAuth token expired and has no refresh token. Re-run oauth_setup.py and update YOUTUBE_TOKEN_B64.")
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    yt=build("youtube","v3",credentials=creds)
    ch=c["channel"]
    privacy=ch.get("privacy_status", "private").strip().lower()
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("channel.privacy_status must be private, unlisted, or public")
    body={"snippet":{"title":data["title"],"description":data.get("description",""),"tags":data.get("tags",[]),"categoryId":str(data.get("youtube_category_id",ch.get("category_id","27"))),"defaultLanguage":ch.get("language","hi")},"status":{"privacyStatus":privacy,"selfDeclaredMadeForKids":False}}
    res=yt.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(video),chunksize=-1,resumable=True)).execute()
    video_id=res.get("id")
    if not video_id:
        raise RuntimeError("YouTube upload response did not include a video ID")
    print("YouTube upload completed:",video_id)
    if thumbnail and Path(thumbnail).is_file():
        try:
            yt.thumbnails().set(videoId=video_id,media_body=MediaFileUpload(str(thumbnail),mimetype="image/jpeg")).execute()
            print("YouTube custom thumbnail applied:",video_id)
        except Exception as exc:
            # The video is already uploaded; thumbnail failure must not trigger a duplicate video retry.
            print("WARNING: Video uploaded, but custom thumbnail could not be applied:",str(exc)[:500])
    # The upload response itself confirms creation and returns the video ID.
    # Do not call videos.list here: the upload-only OAuth scope is sufficient
    # for publishing, but does not grant read access for this extra verification.
    print("YouTube upload confirmed by API response:", video_id, "; privacyStatus="+privacy)
    return video_id


def main():
    c=cfg(); print("Generating content..."); data=make_content(c); print(data["title"])
    cf_images = generate_cloudflare_images(data, WORK)
    visual_paths = [cf_images[i] if i < len(cf_images) else None for i in range(len(data["slides"]))]
    credits = []
    slides=make_slides(data["slides"],c,visual_paths)
    audio, subtitles=tts(data["narration"],c)
    video=render(slides,audio,c,subtitles_path=subtitles)
    qc_report=verify_video_quality(video,c)
    thumbnail=make_thumbnail(data["title"], slides[0], c)
    data["thumbnail"]=str(thumbnail)
    data["quality_check"]=qc_report
    data["visual_credits"]=credits
    (OUT/(video.stem+".json")).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Video:",video)
    unique_visuals = {str(Path(p).resolve()) for p in visual_paths if p and Path(p).is_file()}
    if env("YOUTUBE_UPLOAD","false").lower()=="true":
        if len(unique_visuals) < 2:
            print("WARNING: YouTube upload blocked: fewer than 2 distinct visuals were available; MP4 retained as artifact.")
        else:
            data["youtube_video_id"] = youtube_upload(video,data,c,thumbnail=thumbnail)
            (OUT/(video.stem+".json")).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    else:
        print("Upload skipped (set YOUTUBE_UPLOAD=true after OAuth is configured).")


if __name__=="__main__":
    try: main()
    except Exception as e: print("ERROR:",e); raise
