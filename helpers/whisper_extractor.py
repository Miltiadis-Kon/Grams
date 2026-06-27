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
        audio_path = os.path.join(tmpdir, "extracted_audio.mp3")
        
        # Use yt-dlp to download only the audio track silently
        ydl_cmd = [
            "yt-dlp",
            "-vn", 
            "--no-playlist",
            "-x", "--audio-format", "mp3",
            "-o", audio_path,
            video_url
        ]
        
        try:
            logger.info("Extracting audio from %s using yt-dlp...", video_url)
            subprocess.run(ydl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"yt-dlp failed to download audio: {e}")

        if not os.path.exists(audio_path):
            raise FileNotFoundError("Audio extraction failed; file not found.")

        # Read the file bytes to build a multipart form request
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        
        logger.info("Sending audio to Groq Whisper API for transcription...")
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f, "audio/mp3")}
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
