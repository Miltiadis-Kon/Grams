import sys
from supadata import Supadata, SupadataError

sys.stdout.reconfigure(encoding='utf-8')

client = Supadata(api_key="sd_dc7e73c6a7dae725af667c3e5b0dcf85")
url = "https://www.tiktok.com/@dimi_nikolako_fitness/video/7630895764956368150"

print(f"Fetching transcript for: {url}")
try:
    transcript = client.transcript(url=url, text=True, mode="auto")
    if hasattr(transcript, 'content'):
        print("SUCCESS!")
        print(f"Content: {transcript.content}")
        print(f"Language: {transcript.lang}")
    else:
        print(f"No content attribute. Transcript object: {transcript}")
except Exception as e:
    print(f"Error: {e}")
