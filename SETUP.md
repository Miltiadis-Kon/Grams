# Grams — Vanilla PC Setup Guide

This guide walks you through setting up **Grams** from scratch on a brand new (vanilla) machine (Windows, macOS, or Linux).

---

## 📋 System Prerequisites

Ensure you have the following installed on your machine:

1. **Git**: [git-scm.com/downloads](https://git-scm.com/downloads)
2. **Python 3.10+** (Python 3.11 or 3.12 recommended): [python.org/downloads](https://www.python.org/downloads/)
   - *Windows Note*: Check the box **"Add python.exe to PATH"** during installation.
3. **yt-dlp** (For video metadata and playlist extraction):
   - Automatically installed via `pip install -r requirements.txt`.
4. *(Optional)* **Docker Desktop** (If you prefer running in containers): [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
5. *(Optional)* **FFmpeg**: [ffmpeg.org/download.html](https://ffmpeg.org/download.html) *(Recommended for local audio processing)*.

---

## 🚀 1. Clone Repository & Create Virtual Environment

Open your terminal (PowerShell or Bash) and clone the repository:

```bash
git clone https://github.com/Miltiadis-Kon/Grams.git
cd Grams
```

Create and activate a Python virtual environment:

### On Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### On Linux / macOS (Bash / Zsh):
```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## 📦 2. Install Dependencies

Install all required Python packages and browser binaries:

```bash
# 1. Upgrade pip
python -m pip install --upgrade pip

# 2. Install all project dependencies
pip install -r requirements.txt

# 3. Install Playwright browser engine (for TikTok scraping)
playwright install chromium
```

---

## ⚙️ 3. Environment Configuration (`.env.local`)

Copy or create a `.env.local` file in the root directory of the project:

```ini
# --- Groq LLM & Whisper API Key ---
# Used for Llama 3 ingredient parsing & TikTok Whisper transcription
GROQ_API_KEY=your_groq_api_key_here

# --- Web Server Settings ---
HOST=0.0.0.0
PORT=5000

# --- Database Mode ---
# SQLite is used automatically out-of-the-box (zero configuration needed).
# To use PostgreSQL instead, specify your connection details:
PG_HOST=localhost
PG_PORT=5432
PG_DB=grams
PG_USER=grams
PG_PASSWORD=your_password
```

> **Note on Groq API**:
> - Get a free API key at [console.groq.com](https://console.groq.com/).
> - If Groq runs out of credits or rate limits, the system automatically falls back to processing descriptions without updating `last_processed`.
> - **YouTube videos use direct YouTube transcripts and do not consume Groq Whisper credits!**

---

## 🗄️ 4. Database Setup

Grams supports **Zero-Config Local SQLite** by default with automatic schema migration, or a full **PostgreSQL** instance:

### Option A: SQLite (Default & Instant)
No extra setup is required! The system automatically creates and manages:
- `data/recipes.db` (Recipes, not-added manual review list, transcripts, metadata).
- `data/nutrition.db` (USDA and pantry foods nutritional database with FTS5 search).

### Option B: PostgreSQL (Production / Docker)
If you want to run PostgreSQL:
```bash
# Run via Docker Compose
docker compose --env-file .env.local up -d postgres
```

---

## 🎥 5. Ingesting Recipes

### Ingesting YouTube Videos & Playlists (Zero Groq Credits Required!)
YouTube ingestion fetches direct transcripts natively:

```bash
# Ingest an entire YouTube Playlist
python -c "
from database import RecipeDatabase
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from helpers.youtube_ingester import YouTubeIngester
from recipe_processor.pipeline import RecipePipeline

db = RecipeDatabase('recipes')
not_added_db = RecipeDatabase('not_added_recipes')
pipeline = RecipePipeline(db, not_added_db, NutritionAnalyzer(), AutoTagger())
ingester = YouTubeIngester(pipeline)

ingester.ingest_playlist('https://www.youtube.com/playlist?list=PL9_z7arfoMrv0i0RFhxVxf4QbdjUC6JDL')
"
```

Or ingest a single YouTube video:
```bash
python -c "
from database import RecipeDatabase
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from helpers.youtube_ingester import YouTubeIngester
from recipe_processor.pipeline import RecipePipeline

db = RecipeDatabase('recipes')
not_added_db = RecipeDatabase('not_added_recipes')
pipeline = RecipePipeline(db, not_added_db, NutritionAnalyzer(), AutoTagger())
ingester = YouTubeIngester(pipeline)

ingester.ingest_single('https://www.youtube.com/watch?v=naS5eVSwHlk', force=True)
"
```

### Ingesting TikTok Playlists / Videos
```bash
# Ingest a TikTok single video
python -c "
from database import RecipeDatabase
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from helpers.ingester import TikTokIngester
from recipe_processor.pipeline import RecipePipeline

db = RecipeDatabase('recipes')
not_added_db = RecipeDatabase('not_added_recipes')
pipeline = RecipePipeline(db, not_added_db, NutritionAnalyzer(), AutoTagger())
ingester = TikTokIngester(pipeline)

ingester.ingest_single('https://www.tiktok.com/@noahperlofit/video/7660019682480508191', force=True)
"
```

---

## 🌐 6. Starting the Web Application

Launch the Flask backend and web interface:

```bash
python app.py
```

Open your browser and navigate to:
👉 **[http://localhost:5000](http://localhost:5000)**

---

## 📱 7. Access Anywhere with Tailscale

Access your recipe collection securely from your phone, tablet, or secondary computer:

1. Install **Tailscale** on your host PC and phone: [tailscale.com/download](https://tailscale.com/download).
2. Run `tailscale up` and log in on both devices.
3. Find your host PC's Tailscale IP:
   ```bash
   tailscale ip -4
   # Example: 100.85.120.45
   ```
4. On your mobile browser, open `http://<your-tailscale-ip>:5000` (e.g. `http://100.85.120.45:5000`).

---

## 🧪 8. Verifying & Running Tests

To verify all components:
```bash
# Test single YouTube video ingestion & metadata
python scripts/test_single_youtube_ingest.py

# Test single TikTok video ingestion & metadata
python scripts/test_single_recipe_metadata.py

# Export analysis CSVs
python scripts/export_analysis_csv.py
```
