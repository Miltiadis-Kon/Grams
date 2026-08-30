import os
import subprocess
import tempfile
import json
import requests
import logging

logger = logging.getLogger(__name__)

def fetch_groq_whisper_transcript(video_url: str) -> str:
    from config import GROQ_API_KEY
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is required for Whisper transcription.")

    # Create a temporary directory to store the extracted audio
    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, "extracted_audio.%(ext)s")
        
        # Use yt-dlp to download the smallest stream silently (Groq Whisper accepts mp4, m4a, webm, mp3 natively)
        ydl_cmd = [
            "yt-dlp",
            "-f", "worst/b/best",
            "--no-playlist",
            "-o", output_template,
            video_url
        ]
        
        try:
            logger.info("Extracting audio/video from %s using yt-dlp...", video_url)
            subprocess.run(ydl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"yt-dlp failed to download audio: {e}")

        downloaded_files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
        if not downloaded_files:
            raise FileNotFoundError("Audio extraction failed; no downloaded file found.")
        audio_path = downloaded_files[0]

        # Read the file bytes to build a multipart form request
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        
        logger.info("Sending %s to Groq Whisper API for transcription...", os.path.basename(audio_path))
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f, "application/octet-stream")}
            data = {"model": "whisper-large-v3", "response_format": "json"}
            
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                files=files,
                data=data,
                timeout=120
            )
            
        if response.status_code == 200:
            return response.json().get("text", "")
        else:
            raise RuntimeError(f"Groq Whisper API returned error {response.status_code}: {response.text}")
