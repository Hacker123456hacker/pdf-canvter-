#!/usr/bin/env python3
"""Free-first AI YouTube Shorts agent.
Generates a script with Gemini, Hindi TTS, animated slides with a talking cartoon
character, then optionally uploads to YouTube. Secrets are read from environment
variables / local files.
"""
import json, os, re, subprocess, sys
from pathlib import Path
from datetime import datetime

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

def font(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def make_character_frame(w=1080, h=1920, talking=False, blink=False):
    """Draw a friendly cartoon presenter with an animated mouth."""
    im = Image.new("RGBA", (w, h), (0,0,0,0)); d = ImageDraw.Draw(im)
    cx, cy = w//2, int(h*0.68)
    # body / shirt
    d.rounded_rectangle((cx-245, cy+205, cx+245, cy+620), radius=150, fill=(64,92,180,255))
    # neck
    d.rectangle((cx-70, cy+135, cx+70, cy+245), fill=(206,145,104,255))
    # ears + head
    d.ellipse((cx-245,cy-170,cx-185,cy-50), fill=(206,145,104,255))
    d.ellipse((cx+185,cy-170,cx+245,cy-50), fill=(206,145,104,255))
    d.ellipse((cx-200,cy-230,cx+200,cy+180), fill=(224,166,121,255), outline=(70,45,35,255), width=8)
    # hair
    d.pieslice((cx-205,cy-265,cx+205,cy-20),180,360,fill=(38,29,28,255))
    d.ellipse((cx-175,cy-245,cx-80,cy-115), fill=(38,29,28,255)); d.ellipse((cx+80,cy-245,cx+175,cy-115), fill=(38,29,28,255))
    # eyes
    if blink:
        d.line((cx-110,cy-45,cx-45,cy-45), fill=(35,25,25,255), width=12)
        d.line((cx+45,cy-45,cx+110,cy-45), fill=(35,25,25,255), width=12)
    else:
        d.ellipse((cx-105,cy-65,cx-45,cy-5), fill=(255,255,255,255)); d.ellipse((cx+45,cy-65,cx+105,cy-5), fill=(255,255,255,255))
        d.ellipse((cx-83,cy-48,cx-57,cy-22), fill=(25,25,25,255)); d.ellipse((cx+57,cy-48,cx+83,cy-22), fill=(25,25,25,255))
    # nose
    d.line((cx,cy-25,cx-12,cy+35,cx+18,cy+38), fill=(130,80,65,255), width=7)
    # mouth: clearly changes between speaking and resting states
    if talking:
        d.ellipse((cx-62,cy+70,cx+62,cy+145), fill=(55,22,28,255), outline=(85,40,35,255), width=5)
        d.rounded_rectangle((cx-35,cy+76,cx+35,cy+98), radius=8, fill=(250,250,250,255))
    else:
        d.arc((cx-65,cy+55,cx+65,cy+135), 15, 165, fill=(75,35,35,255), width=9)
    # small presenter badge
    badge_font=font(30,True)
    label="AI PRESENTER"
    bb=d.textbbox((0,0),label,font=badge_font)
    d.rounded_rectangle((cx-120,cy+640,cx+120,cy+700),radius=25,fill=(20,25,40,235))
    d.text((cx-(bb[2]-bb[0])//2,cy+650),label,font=badge_font,fill=(245,245,250,255))
    return im

def make_slides(slides,c):
    w,h=c["video"].get("width",1080),c["video"].get("height",1920)
    paths=[]
    for i,text in enumerate(slides):
        im=Image.new("RGB",(w,h),(15,18,28)); d=ImageDraw.Draw(im)
        for x in range(-h,w,h//3): d.ellipse((x,200,x+h,200+h),outline=(45,55,85),width=5)
        title=font(74,True); small=font(34,False)
        words=text.split(); lines=[]; cur=""
        for word in words:
            test=(cur+" "+word).strip()
            if d.textbbox((0,0),test,font=title)[2] < w-140: cur=test
            else: lines.append(cur); cur=word
        if cur: lines.append(cur)
        total=len(lines)*100; y=260
        for line in lines:
            box=d.textbbox((0,0),line,font=title); tw=box[2]-box[0]
            d.text(((w-tw)//2,y),line,font=title,fill=(245,245,250)); y+=100
        # Leave a clean area for the presenter and add a speaking character.
        character=make_character_frame(w,h,talking=(i%2==0),blink=(i%7==0))
        im=Image.alpha_composite(im.convert("RGBA"),character).convert("RGB")
        d=ImageDraw.Draw(im)
        d.text((60,h-110),f"AI Short • {i+1}/{len(slides)}",font=small,fill=(160,170,190))
        p=WORK/f"slide_{i:02d}.png"; im.save(p); paths.append(p)
    return paths

def tts(text,c):
    audio=WORK/"voice.mp3"; voice=c["video"].get("voice","hi-IN-SwaraNeural"); rate=c["video"].get("tts_rate","+0%")
    cmd=[sys.executable,"-m","edge_tts","--voice",voice,"--rate",rate,"--text",text,"--write-media",str(audio)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode: raise RuntimeError("TTS failed. Install edge-tts: pip install edge-tts")
    return audio

def render(slides,audio,c):
    out=OUT/(datetime.now().strftime("%Y%m%d_%H%M%S")+".mp4")
    listfile=WORK/"slides.txt"; duration=max(1.0, c["content"].get("duration_seconds",60)/len(slides))
    with listfile.open("w",encoding="utf-8") as f:
        for p in slides: f.write(f"file '{p.as_posix()}'\nduration {duration}\n")
        f.write(f"file '{slides[-1].as_posix()}'\n")
    cmd=["ffmpeg","-y","-f","concat","-safe","0","-i",str(listfile),"-i",str(audio),"-vf",f"fps={c['video'].get('fps',30)},format=yuv420p","-c:v","libx264","-c:a","aac","-shortest",str(out)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode: raise RuntimeError(r.stderr[-3000:])
    return out

def youtube_upload(video,data,c):
    token_path=Path(env("YOUTUBE_TOKEN_FILE",str(ROOT/"token.json")))
    if not token_path.exists(): raise RuntimeError("YouTube OAuth token.json missing. Run oauth_setup.py locally first.")
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
