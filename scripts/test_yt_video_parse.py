import io
import sys
import os
import json
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from youtube_transcript_api import YouTubeTranscriptApi

url = "https://www.youtube.com/watch?v=naS5eVSwHlk"
cmd = ["yt-dlp", "--dump-json", "--no-download", url]
res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
data = json.loads(res.stdout)

print("Title:", data.get("title"))
print("ID:", data.get("id"))
print("Description length:", len(data.get("description", "")))
print("--- Description ---")
print(data.get("description", ""))

print("\n--- Transcript ---")
api = YouTubeTranscriptApi()
transcript_entries = api.fetch(data.get("id"))
full_transcript = " ".join([t.text for t in transcript_entries])
print(f"Transcript length: {len(full_transcript)} chars")
print(full_transcript[:500])
