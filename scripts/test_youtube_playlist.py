import io
import sys
import os
import json
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from youtube_transcript_api import YouTubeTranscriptApi

playlist_url = "https://www.youtube.com/playlist?list=PL9_z7arfoMrv0i0RFhxVxf4QbdjUC6JDL"

# Use yt-dlp to extract flat playlist info
cmd = [
    "yt-dlp",
    "--flat-playlist",
    "-J",
    playlist_url
]

print("Extracting YouTube playlist metadata...")
res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
if res.returncode != 0:
    print("yt-dlp failed:", res.stderr)
    sys.exit(1)

data = json.loads(res.stdout)
entries = data.get("entries", [])
print(f"Total videos in playlist: {len(entries)}")

for idx, entry in enumerate(entries[:5], start=1):
    v_id = entry.get("id")
    title = entry.get("title")
    url = f"https://www.youtube.com/watch?v={v_id}"
    print(f"\n[{idx}] ID: {v_id} | Title: {title}")
    print(f"    URL: {url}")
    
    # Try fetching transcript
    try:
        # In youtube-transcript-api 1.2.4:
        # YouTubeTranscriptApi().get_transcript(v_id) or YouTubeTranscriptApi.get_transcript(v_id)
        api = YouTubeTranscriptApi()
        t_list = api.get_transcript(v_id)
        full_text = " ".join([t['text'] for t in t_list])
        print(f"    Transcript length: {len(full_text)} chars")
        print(f"    Preview: {full_text[:120]}...")
    except Exception as e:
        print(f"    Transcript error: {e}")
