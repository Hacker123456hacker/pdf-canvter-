#!/usr/bin/env python3
"""Free-first AI YouTube Shorts agent.
Generates a Hindi script with Gemini, automatically finds topic-relevant visuals
(Google Custom Search when configured, otherwise Wikimedia Commons), adds Hindi
TTS, animated B-roll cards and a presenter, adds topic-related real photos, animated camera movement and Hindi subtitles, then optionally uploads to YouTube.
Secrets are read from environment variables / local files.
"""
import json, os, re, subprocess, sys, time
from pathlib import Path
from datetime import datetime

import requests
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
    primary = env("GEMINI_MODEL", "gemini-2.5-flash")
    fallbacks = [x.strip() for x in env("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash-lite").split(",") if x.strip()]
    models = list(dict.fromkeys([primary] + fallbacks))
    last_error = None

    # Rotate through every configured key and model on quota, overload, auth, or network errors.
    for key_index, key in enumerate(keys, 1):
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            for attempt in range(1, 3):
                try:
                    response = requests.post(
                        url,
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        timeout=(20, 180),
                    )
                    response.raise_for_status()
                    body = response.json()
                    candidates = body.get("candidates") or []
                    if not candidates:
                        feedback = body.get("promptFeedback", {})
                        raise RuntimeError(f"Gemini {model} returned no candidate: {feedback or body}")
                    print(f"Gemini key slot {key_index}, model used: {model}")
                    return candidates[0]["content"]["parts"][0]["text"]
                except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                    last_error = exc
                    status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None
                    if isinstance(exc, requests.HTTPError) and status not in (400, 401, 403, 404, 408, 429, 500, 502, 503, 504):
                        raise
                    # A quota/auth/model error should immediately try the next option.
                    if status in (400, 401, 403, 404, 429):
                        print(f"Gemini key slot {key_index}, model {model} returned HTTP {status}; switching fallback.")
                        break
                    if attempt == 1:
                        print(f"Gemini key slot {key_index}, model {model} temporary error (attempt 1/2): {exc}. Retrying in 8s...")
                        time.sleep(8)
                except RuntimeError as exc:
                    last_error = exc
                    break

    raise RuntimeError(
        f"Gemini generation failed with {len(keys)} configured key(s) and models "
        f"({', '.join(models)}). Last error: {last_error}"
    ) from last_error

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
    lang=c["content"].get("language","hi"); niche=c["content"].get("niche","technology")
    seed=c["content"].get("topic_seed","")
    avoid=", ".join(c["content"].get("avoid_topics",[])) or "none"
    target_seconds=max(30,min(60,int(c["content"].get("duration_seconds",60))))
    prompt=f'''Create ONE original short-form YouTube video in {lang} for the niche: {niche}.
No daily topic will be supplied, so choose a useful, factual, evergreen topic yourself.
Topic hint (optional): {seed or "none"}. Avoid: {avoid}.
Target narration length: 30-60 seconds, ideally about 50-55 seconds.
Write roughly 100-125 words in natural, conversational spoken {lang}; do not make it too brief.
Start with a strong 2-second hook, explain one useful idea with a concrete example, and finish with a memorable takeaway.
Return ONLY valid JSON with keys title, description, tags, narration, slides, visual_queries.
slides must contain 6-8 short scene captions in the exact order of the narration.
visual_queries must contain exactly the same number of concise English image-search queries, one per scene, each only 2-5 concrete search terms.
Ask for real photographs of the actual subject (not illustrations, icons, logos, text, or generic backgrounds).
Do not make medical/legal/financial claims or sensational misinformation.'''
    data = parse_gemini_json(gemini(prompt))
    # Gemini sometimes ignores the requested word count. Cap narration so Hindi
    # speech reliably fits the requested 30-60 second Shorts format.
    narration=data["narration"].strip()
    if len(narration.split()) > 120:
        sentences=re.split(r"(?<=[।!?])\\s+", narration)
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
    return data


def font(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()


def search_google_images(query, limit=8):
    """Search licensed images through Google's Custom Search JSON API when keys exist."""
    key, cx = env("GOOGLE_CSE_API_KEY"), env("GOOGLE_CSE_ID")
    if not key or not cx: return []
    params = {
        "key": key, "cx": cx, "q": query, "searchType": "image", "num": min(limit, 10),
        "safe": "active", "imgType": "photo", "rights": "cc_publicdomain,cc_attribute,cc_sharealike",
        "gl": "in", "lr": "lang_en"
    }
    r = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=30)
    r.raise_for_status()
    out=[]
    for item in r.json().get("items",[]):
        if item.get("link"):
            out.append({"url":item["link"],"source":item.get("displayLink","Google Images"),"title":item.get("title",query),"page":item.get("image",{}).get("contextLink","")})
    return out


def search_wikimedia(query, limit=8):
    """Keyless fallback using Wikimedia Commons search and thumbnail URLs."""
    params={
        "action":"query","generator":"search","gsrsearch":query,"gsrnamespace":"6","gsrlimit":limit,
        "prop":"imageinfo","iiprop":"url|extmetadata","iiurlwidth":"1200","format":"json","formatversion":"2"
    }
    r=requests.get("https://commons.wikimedia.org/w/api.php",params=params,headers={"User-Agent":"AIYouTubeAgent/1.0"},timeout=30)
    r.raise_for_status()
    out=[]
    for page in r.json().get("query",{}).get("pages",[]):
        info=(page.get("imageinfo") or [{}])[0]
        url=info.get("thumburl") or info.get("url")
        if not url: continue
        meta=info.get("extmetadata",{})
        artist=(meta.get("Artist") or {}).get("value","")
        license_name=(meta.get("LicenseShortName") or {}).get("value","")
        out.append({"url":url,"source":"Wikimedia Commons","title":page.get("title",query).replace("File:",""),"page":"https://commons.wikimedia.org/wiki/"+page.get("title","").replace(" ","_"),"artist":artist,"license":license_name})
    return out


def download_visual(item, index):
    path=WORK/f"visual_{index:02d}.jpg"
    try:
        r=requests.get(item["url"],headers={"User-Agent":"AIYouTubeAgent/1.0"},timeout=30,stream=True)
        r.raise_for_status()
        ctype=r.headers.get("content-type","").lower()
        if not ctype.startswith("image/"): return None
        limit = 12 * 1024 * 1024
        if int(r.headers.get("content-length", "0") or 0) > limit:
            return None
        total = 0
        with path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > limit:
                    path.unlink(missing_ok=True)
                    return None
                f.write(chunk)
        with Image.open(path) as im:
            im.verify()
        return path
    except Exception:
        path.unlink(missing_ok=True)
        return None


def fetch_visuals(data, c):
    visual_cfg=c.get("visuals",{})
    if not visual_cfg.get("enabled",True): return [], []
    provider=env("IMAGE_SEARCH_PROVIDER",visual_cfg.get("provider","wikimedia")).lower()
    max_per= int(visual_cfg.get("images_per_video",8))
    items=[]
    queries=data.get("visual_queries",[])
    for q in queries:
        if len(items)>=max_per: break
        try:
            found=[]
            if provider in ("google","auto"):
                found=search_google_images(q,limit=4)
            if not found:
                found=search_wikimedia(q,limit=5)
            # Retry Commons with a simpler query if the detailed search returns no usable photo.
            downloaded=False
            for item in found:
                p=download_visual(item,len(items))
                if p:
                    item["path"]=str(p); items.append(item); downloaded=True; break
            if not downloaded and provider in ("wikimedia","auto","google"):
                simple=" ".join(str(q).split()[:4])
                if simple and simple.lower()!=str(q).lower():
                    for item in search_wikimedia(simple,limit=5):
                        p=download_visual(item,len(items))
                        if p:
                            item["path"]=str(p); items.append(item); break
        except Exception as e:
            print(f"Visual search failed for '{q}': {e}")
        time.sleep(0.2)
    (OUT/"visual_credits.json").write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Visuals downloaded: {len(items)} / requested {min(len(queries), max_per)}")
    if not items:
        print("WARNING: No real photos downloaded from image providers; generated video will use designed backgrounds.")
    return [Path(x["path"]) for x in items], items


def fit_cover(im, size):
    w,h=size; src=im.convert("RGB"); sw,sh=src.size
    scale=max(w/sw,h/sh); nw,nh=int(sw*scale),int(sh*scale)
    src=src.resize((nw,nh),Image.Resampling.LANCZOS)
    left=(nw-w)//2; top=(nh-h)//2
    return src.crop((left,top,left+w,top+h))


def make_slides(slides,c,visual_paths=None):
    """Create photo-led vertical scenes; no cartoon/avatar overlay."""
    w,h=c["video"].get("width",1080),c["video"].get("height",1920)
    paths=[]; visual_paths=visual_paths or []
    for i,text in enumerate(slides):
        if visual_paths:
            try:
                with Image.open(visual_paths[i % len(visual_paths)]) as src:
                    bg=fit_cover(src,(w,h)).filter(ImageFilter.GaussianBlur(radius=0.6))
                im=bg.convert("RGBA")
                overlay=Image.new("RGBA",(w,h),(5,9,20,112))
                im=Image.alpha_composite(im,overlay)
            except Exception:
                im=Image.new("RGBA",(w,h),(12,18,32,255))
        else:
            im=Image.new("RGBA",(w,h),(12,18,32,255))
            d=ImageDraw.Draw(im)
            for x in range(-h,w,h//3):
                d.ellipse((x,220,x+h,220+h),outline=(42,62,95,255),width=5)
        d=ImageDraw.Draw(im)
        # Editorial top label and readable headline panel.
        small=font(max(24,int(w*0.027)),False)
        title=font(max(48,int(w*0.064)),True)
        d.rounded_rectangle((48,70,w-48,142),radius=28,fill=(8,15,28,190),outline=(255,255,255,70),width=2)
        d.text((78,87),"HINDI • EXPLAINED",font=small,fill=(225,235,250,255))
        words=text.split(); lines=[]; cur=""
        for word in words:
            test=(cur+" "+word).strip()
            if d.textbbox((0,0),test,font=title)[2] < w-150:
                cur=test
            else:
                if cur: lines.append(cur)
                cur=word
        if cur: lines.append(cur)
        line_h=int(title.size*1.35)
        block_h=min(len(lines[:5]),5)*line_h+70
        y=int(h*0.31)
        d.rounded_rectangle((42,y-38,w-42,y+block_h),radius=34,fill=(4,9,20,205),outline=(255,255,255,75),width=2)
        for line in lines[:5]:
            box=d.textbbox((0,0),line,font=title); tw=box[2]-box[0]
            d.text(((w-tw)//2,y),line,font=title,fill=(255,255,255,255),stroke_width=1,stroke_fill=(0,0,0,180))
            y+=line_h
        # Minimal progress marker; FFmpeg adds subtle camera motion.
        bar_y=h-105
        d.rounded_rectangle((55,bar_y,w-55,bar_y+10),radius=5,fill=(255,255,255,85))
        progress=int((w-110)*(i+1)/max(1,len(slides)))
        d.rounded_rectangle((55,bar_y,55+progress,bar_y+10),radius=5,fill=(255,205,90,255))
        d.text((55,h-78),f"{i+1:02d} / {len(slides):02d}",font=small,fill=(245,245,250,230))
        p=WORK/f"slide_{i:02d}.png"; im.convert("RGB").save(p,quality=94); paths.append(p)
    return paths
def vtt_to_srt(vtt_path, srt_path):
    """Convert Edge TTS WebVTT captions to SRT for FFmpeg/libass."""
    import re
    raw=Path(vtt_path).read_text(encoding="utf-8")
    cues=re.findall(r"(?m)^(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)",raw,re.S)
    def stamp(value):
        return value.replace(".",",")
    rows=[]
    for n,(begin,finish,caption) in enumerate(cues,1):
        caption=re.sub(r"<[^>]+>","",caption).strip()
        caption=" ".join(line.strip() for line in caption.splitlines() if line.strip())
        if caption:
            rows.extend([str(n),f"{stamp(begin)} --> {stamp(finish)}",caption,""])
    Path(srt_path).write_text("\n".join(rows),encoding="utf-8")
    return bool(rows)


def media_duration(path):
    probe=subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],
        capture_output=True,text=True
    )
    if probe.returncode != 0:
        raise RuntimeError("Could not inspect generated media: "+probe.stderr[-1000:])
    return float(probe.stdout.strip())


def tts(text,c):
    audio=WORK/"voice.mp3"; captions=WORK/"voice.vtt"
    voice=c["video"].get("voice","hi-IN-SwaraNeural"); rate=c["video"].get("tts_rate","+0%")
    # A successful CLI exit is not enough: Edge TTS can occasionally leave a tiny,
    # truncated MP3 behind. Never allow that to become a 0.2-second Shorts artifact.
    words=len(text.split())
    for attempt in range(1,4):
        audio.unlink(missing_ok=True); captions.unlink(missing_ok=True)
        cmd=[sys.executable,"-m","edge_tts","--voice",voice,"--rate",rate,"--text",text,
             "--write-media",str(audio),"--write-subtitles",str(captions)]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        if r.returncode:
            reason=(r.stderr or r.stdout)[-1500:]
            print(f"Hindi TTS attempt {attempt}/3 failed: {reason}")
        elif audio.exists() and audio.stat().st_size > 10_000:
            try:
                seconds=media_duration(audio)
            except Exception as exc:
                seconds=0
                print(f"Hindi TTS output probe failed: {exc}")
            print(f"Hindi TTS audio duration: {seconds:.2f}s for {words} words")
            if 25 <= seconds <= 65:
                srt=WORK/"captions.srt"
                if captions.exists() and vtt_to_srt(captions,srt):
                    return audio
                if captions.exists():
                    captions.unlink(missing_ok=True)
                # Captions are optional; a complete voice track is not.
                return audio
            reason=f"audio duration {seconds:.2f}s is outside the valid 25-65s Shorts range"
            print(f"Hindi TTS attempt {attempt}/3 rejected: {reason}")
        else:
            reason="audio file missing or suspiciously small"
            print(f"Hindi TTS attempt {attempt}/3 rejected: {reason}")
        if attempt < 3:
            time.sleep(3 * attempt)
    raise RuntimeError("Hindi TTS did not produce a valid 25-65 second narration after 3 attempts. "+str(reason))


def render(slides,audio,c):
    out=OUT/(datetime.now().strftime("%Y%m%d_%H%M%S")+".mp4")
    w=c["video"].get("width",1080); h=c["video"].get("height",1920); fps=c["video"].get("fps",30)
    audio_duration=media_duration(audio)
    if not 25 <= audio_duration <= 65:
        raise RuntimeError(f"Refusing invalid narration duration: {audio_duration:.2f}s")
    duration=audio_duration/len(slides)
    # The previous concat-of-PNGs pipeline emitted only one frame per still image.
    # Render each still as a real timed video segment, then concatenate video segments.
    segments=[]
    for i,slide in enumerate(slides):
        segment=WORK/f"segment_{i:02d}.mp4"
        frames=max(1,int(duration*fps))
        zoom=rf"scale={w}:{h},zoompan=z='1+0.07*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps},format=yuv420p"
        cmd=["ffmpeg","-y","-loop","1","-framerate",str(fps),"-i",str(slide),
             "-t",f"{duration:.4f}","-vf",zoom,"-an","-c:v","libx264",
             "-preset","veryfast","-crf","21","-r",str(fps),"-pix_fmt","yuv420p",
             "-movflags","+faststart",str(segment)]
        result=subprocess.run(cmd,capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError(f"Could not render scene {i+1}: "+result.stderr[-2500:])
        segments.append(segment)
    listfile=WORK/"video_segments.txt"
    with listfile.open("w",encoding="utf-8") as f:
        for segment in segments:
            f.write("file '" + segment.as_posix() + "'\\n")
    vf="null"
    srt=WORK/"captions.srt"
    if srt.exists() and srt.stat().st_size:
        subtitle_path=str(srt.resolve()).replace("\\\\","/").replace(":","\\\\:")
        vf+=f",subtitles='{subtitle_path}':force_style='FontName=Noto Sans Devanagari,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=180'"
    cmd=["ffmpeg","-y","-f","concat","-safe","0","-i",str(listfile),"-i",str(audio),
         "-map","0:v:0","-map","1:a:0","-vf",vf,"-r",str(fps),"-c:v","libx264",
         "-preset","veryfast","-crf","21","-c:a","aac","-b:a","128k",
         "-t",f"{audio_duration:.3f}","-movflags","+faststart",str(out)]
    result=subprocess.run(cmd,capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-3500:])
    final_duration=media_duration(out)
    print(f"Final video duration: {final_duration:.2f}s")
    if not 25 <= final_duration <= 65:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"Rendered video duration is invalid: {final_duration:.2f}s; artifact rejected")
    return out

def youtube_upload(video,data,c):
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
    ch=c["channel"]; body={"snippet":{"title":data["title"],"description":data.get("description",""),"tags":data.get("tags",[]),"categoryId":ch.get("category_id","27"),"defaultLanguage":ch.get("language","hi")},"status":{"privacyStatus":ch.get("privacy_status","private"),"selfDeclaredMadeForKids":False}}
    res=yt.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(video),chunksize=-1,resumable=True)).execute()
    print("YouTube upload:",res.get("id")); return res.get("id")


def main():
    c=cfg(); print("Generating content..."); data=make_content(c); print(data["title"])
    visual_paths, credits=fetch_visuals(data,c)
    slides=make_slides(data["slides"],c,visual_paths); audio=tts(data["narration"],c); video=render(slides,audio,c)
    data["visual_credits"]=credits
    (OUT/(video.stem+".json")).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Video:",video)
    if env("YOUTUBE_UPLOAD","false").lower()=="true": youtube_upload(video,data,c)
    else: print("Upload skipped (set YOUTUBE_UPLOAD=true after OAuth is configured).")


if __name__=="__main__":
    try: main()
    except Exception as e: print("ERROR:",e); raise
