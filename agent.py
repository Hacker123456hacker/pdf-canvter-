#!/usr/bin/env python3
"""Free-first AI YouTube Shorts agent. Generates a script with Gemini, TTS audio,
animated text slides with Pillow/FFmpeg, then optionally uploads to YouTube.
Secrets are read only from environment variables / local files.
"""
import base64, json, os, re, subprocess, sys, textwrap
from pathlib import Path
from datetime import datetime, timezone

import requests
from PIL import Image, ImageDraw, ImageFont
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
    key = env("GEMINI_API_KEY")
    if not key: raise RuntimeError("GEMINI_API_KEY is missing")
    model = env("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]}, timeout=90)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

def make_content(c):
    lang=c["content"].get("language","hi"); niche=c["content"].get("niche","technology")
    seed=c["content"].get("topic_seed","")
    avoid=", ".join(c["content"].get("avoid_topics",[])) or "none"
    prompt=f'''Create ONE original short-form YouTube video in {lang} for the niche: {niche}.
No daily topic will be supplied, so choose a useful, factual, evergreen topic yourself.
Topic hint (optional): {seed or "none"}. Avoid: {avoid}.
Return ONLY valid JSON with keys title, description, tags, narration, slides.
Narration should be about 45-70 seconds, natural spoken {lang}, no markdown, no citations.
slides must be 6-8 short strings, each suitable for a vertical video card.
Do not make medical/legal/financial claims or sensational misinformation.'''
    raw=gemini(prompt).strip()
    raw=re.sub(r'^```json\s*|\s*```$','',raw,flags=re.I)
    data=json.loads(raw)
    if not data.get("narration") or not data.get("slides"): raise ValueError("Gemini returned incomplete content")
    return data

def font(size):
    candidates=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for p in candidates:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def make_slides(slides,c):
    w,h=c["video"].get("width",1080),c["video"].get("height",1920)
    paths=[]
    for i,text in enumerate(slides):
        im=Image.new("RGB",(w,h),(15,18,28)); d=ImageDraw.Draw(im)
        # subtle geometric background
        for x in range(-h,w,h//3): d.ellipse((x,200,x+h,200+h),outline=(45,55,85),width=5)
        title=font(74); small=font(34)
        words=text.split(); lines=[]; cur=""
        for word in words:
            test=(cur+" "+word).strip()
            if d.textbbox((0,0),test,font=title)[2] < w-140: cur=test
            else: lines.append(cur); cur=word
        if cur: lines.append(cur)
        total=len(lines)*100; y=(h-total)//2
        for line in lines:
            box=d.textbbox((0,0),line,font=title); tw=box[2]
            d.text(((w-tw)//2,y),line,font=title,fill=(245,245,250)); y+=100
        d.text((60,h-110),f"AI Short • {i+1}/{len(slides)}",font=small,fill=(160,170,190))
        p=WORK/f"slide_{i:02d}.png"; im.save(p); paths.append(p)
    return paths

def tts(text,c):
    audio=WORK/"voice.mp3"; voice=c["video"].get("voice","hi-IN-SwaraNeural"); rate=c["video"].get("tts_rate","+0%")
    # edge-tts is intentionally optional and installed by the workflow/local setup.
    cmd=[sys.executable,"-m","edge_tts","--voice",voice,"--rate",rate,"--text",text,"--write-media",str(audio)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode: raise RuntimeError("TTS failed. Install edge-tts: pip install edge-tts")
    return audio

def render(slides,audio,c):
    out=OUT/(datetime.now().strftime("%Y%m%d_%H%M%S")+".mp4")
    # concat slides with equal duration, then trim to audio length
    listfile=WORK/"slides.txt"; duration=max(1.0, 60.0/len(slides))
    with listfile.open("w",encoding="utf-8") as f:
        for p in slides: f.write(f"file '{p.as_posix()}'\nduration {duration}\n")
        f.write(f"file '{slides[-1].as_posix()}'\n")
    cmd=["ffmpeg","-y","-f","concat","-safe","0","-i",str(listfile),"-i",str(audio),"-vf",f"fps={c['video'].get('fps',30)},format=yuv420p","-c:v","libx264","-c:a","aac","-shortest",str(out)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode: raise RuntimeError(r.stderr[-3000:])
    return out

def youtube_upload(video,data,c):
    token_path=Path(env("YOUTUBE_TOKEN_FILE",str(ROOT/"token.json")))
    if not token_path.exists():
        raise RuntimeError("YouTube OAuth token.json missing. Run oauth_setup.py locally first, then configure it as a secret for GitHub Actions.")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request
    creds=Credentials.from_authorized_user_file(str(token_path),["https://www.googleapis.com/auth/youtube.upload"])
    if creds.expired and creds.refresh_token: creds.refresh(Request())
    yt=build("youtube","v3",credentials=creds)
    ch=c["channel"]; body={"snippet":{"title":data["title"],"description":data.get("description",""),"tags":data.get("tags",[]),"categoryId":ch.get("category_id","27"),"defaultLanguage":ch.get("language","hi")},"status":{"privacyStatus":ch.get("privacy_status","private"),"selfDeclaredMadeForKids":False}}
    res=yt.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(video),chunksize=-1,resumable=True)).execute()
    print("YouTube upload:",res.get("id")); return res.get("id")

def main():
    c=cfg(); print("Generating content..."); data=make_content(c); print(data["title"])
    slides=make_slides(data["slides"],c); audio=tts(data["narration"],c); video=render(slides,audio,c)
    (OUT/(video.stem+".json")).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Video:",video)
    if env("YOUTUBE_UPLOAD","false").lower()=="true": youtube_upload(video,data,c)
    else: print("Upload skipped (set YOUTUBE_UPLOAD=true after OAuth is configured).")

if __name__=="__main__":
    try: main()
    except Exception as e: print("ERROR:",e); raise
