# Grams — Recipe Ingestion & Database Engine

Grams is a structured, local-first recipe cataloging, nutritional analysis, and meal planning system. It automates scraping TikTok recipe videos, parsing ingredients using Natural Language Processing (NLP), mapping them to a curated PostgreSQL whole foods database (**ANSES CIQUAL dataset**), auto-tagging diets and cooking methods, and exposing a modern Web UI for searching and filtering.

> **100% Local & Private**: The entire stack runs on your local machine via Docker Compose — zero cloud database dependencies. Access your recipes anywhere securely via **Tailscale**.

---

## 🖥️ Setup on a Vanilla PC (Fresh Machine)

Follow either **Method 1 (Docker — Recommended)** or **Method 2 (Bare Metal / Python)**.

---

### Method 1: 1-Step Setup with Docker (Recommended)

This method requires only **Git** and **Docker Desktop**. It starts both the PostgreSQL database and the Flask web application in isolated containers, auto-initializes the database schema, and seeds **3,484+ curated CIQUAL whole foods**.

#### 1. Install Prerequisites
- **Git**: [git-scm.com/downloads](https://git-scm.com/downloads)
- **Docker Desktop**: [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) *(Ensure Docker Desktop is running)*

#### 2. Clone Repository
```bash
git clone https://github.com/Miltiadis-Kon/Grams.git
cd Grams
```

#### 3. Configure Local Secrets (`.env.local`)
Create or edit your `.env.local` file in the project root:
```ini
# PostgreSQL credentials
PG_HOST=localhost
PG_PORT=5432
PG_DB=grams
PG_USER=grams
PG_PASSWORD=your_secure_password_here

# Groq API key (for Llama 3 NLP recipe parsing)
GROQ_API_KEY=your_groq_api_key_here

# Ollama local LLM fallback (optional)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1

# Flask server settings
HOST=0.0.0.0
PORT=5000
```

#### 4. Launch the Application Stack
```bash
docker compose --env-file .env.local up -d
```

#### 5. Open in Browser
- **Local Access**: Open [http://localhost:5000](http://localhost:5000)
- Database schema and **all 3,484 CIQUAL foods** are automatically created and seeded on first launch!

---

### Method 2: Bare-Metal Setup (Python & Local Postgres)

If you prefer running Python directly on your host machine for development:

#### 1. Install Prerequisites
- **Python 3.11+**: [python.org/downloads](https://www.python.org/downloads/)
- **PostgreSQL 15 or 16**: [postgresql.org/download](https://www.postgresql.org/download/) *(or run PostgreSQL in a minimal docker container)*

#### 2. Setup Local PostgreSQL Database
Open your PostgreSQL terminal (`psql`) or pgAdmin and run:
```sql
CREATE DATABASE grams;
CREATE USER grams WITH PASSWORD 'grams';
GRANT ALL PRIVILEGES ON DATABASE grams TO grams;
```

#### 3. Initialize Database Schema & Seed CIQUAL Foods
Run the initialization scripts against your local database:
```bash
# Load full database schema
psql -h localhost -U grams -d grams -f database/schema_full.sql

# Seed 3,484+ curated CIQUAL whole foods dataset
psql -h localhost -U grams -d grams -f database/ciqual_foods_seed.sql
```

#### 4. Setup Python Environment
```bash
# Create and activate virtual environment
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser for TikTok scraper
playwright install chromium
```

#### 5. Start the Web Server
```bash
python app.py
```
Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## 🌐 Remote Access via Tailscale

Access your local Grams server securely from your smartphone, tablet, or laptop wherever you are — without port forwarding or exposing ports to the public internet.

1. **Install Tailscale**: Download from [tailscale.com/download](https://tailscale.com/download) on your PC and your phone.
2. **Log In on Both Devices**:
   ```bash
   tailscale up
   ```
3. **Find your PC’s Tailscale IP**:
   ```bash
   tailscale ip -4
   # Output example: 100.85.120.45
   ```
4. **Access from Phone or Secondary Device**:
   Open your browser and navigate to:
   ```
   http://100.85.120.45:5000
   ```
*(For complete details including Tailscale MagicDNS and Public HTTPS Funnel, see [TAILSCALE_SETUP.md](TAILSCALE_SETUP.md)).*

---

## 📁 Project Structure

```
Grams/
├── database/                   # Persistence Layer & Canonical Schemas
│   ├── __init__.py             # Database package exports
│   ├── postgres_db.py          # Thread-safe PostgreSQL RecipeDatabase (psycopg2)
│   ├── schema_full.sql         # Full PostgreSQL schema with FTS & Trigram indexes
│   ├── ciqual_foods_seed.sql   # Curated CIQUAL 3,484 whole foods dataset seed
│   └── models.py               # Recipe & MacroNutrient dataclasses
├── interface/                  # Frontend Assets (Single Page App)
│   ├── index.html              # Modern Web UI (Macro Finder)
│   ├── manifest.json           # Progressive Web App (PWA) manifest
│   ├── sw.js                   # Service Worker for offline/caching support
│   └── baker.png               # Application logo
├── helpers/                    # Core Application Logic
│   ├── __init__.py             # Helpers package exports
│   ├── engine.py               # RecipeEngine orchestrator
│   ├── ingester.py             # Playwright TikTok Scraper (Playlist/Single)
│   ├── nutrition.py            # CIQUAL PostgreSQL FTS search & macro calculator
│   ├── query.py                # Read-only search & filter interfaces
│   └── tagger.py               # Rule-based auto-tagging engine
├── scripts/
│   ├── seed_ciqual_to_postgres.py  # CIQUAL dataset extractor & seeder
│   └── migrate_from_supabase.py    # One-time Supabase → PostgreSQL data migrator
├── data/                       # Downloaded media & datasets (gitignored)
├── app.py                      # Flask Web Server entry point
├── config.py                   # Centralized configurations & paths
├── Dockerfile                  # Container image definition (Python 3.11 + Playwright)
├── docker-compose.yml          # Multi-service orchestration (Postgres + Flask App)
├── .env.local                  # Local secrets template (gitignored)
├── TAILSCALE_SETUP.md          # Tailscale setup & configuration guide
├── requirements.txt            # Python dependencies
└── README.md                   # System documentation
```

---

## 🥗 Curated Whole Foods Dataset (CIQUAL)

Grams uses the **ANSES CIQUAL 2024 Food Composition Database** for precise macronutrient matching:
- **3,484 curated whole foods and ingredients**.
- High-precision macronutrient breakdown: Protein, Carbohydrates, Fats, and Energy (kcal) per 100g.
- Full-text search (PostgreSQL `tsvector`) and fuzzy matching (`pg_trgm`) for ingredient lookup and auto-completion.
- Supports barcode scanning via Open Food Facts with automatic local caching.

To refresh or re-seed the CIQUAL dataset at any time:
```bash
python scripts/seed_ciqual_to_postgres.py
```

---

## 🔄 Ingesting Recipes

### Continuous Slow Synchronization (CLI)

Use the `sync_recipes.py` CLI script to scrape a TikTok playlist. It extracts video links, checks the local database, and visits detailed pages for **new videos only**, sleeping between hits to avoid rate limits:

```bash
# Sync playlist with default 5-second delay
python sync_recipes.py "https://www.tiktok.com/@creator/playlist/1234567"

# Sync with custom delay
python sync_recipes.py "https://www.tiktok.com/@creator/playlist/1234567" --delay 10.0
```

### Authentication Cookies (Optional)
To scrape private playlists or bypass bot verification, export your TikTok session cookies to `tiktok_cookies.json` in the root folder:
```json
[
  {
    "name": "sessionid",
    "value": "YOUR_SESSION_ID_HERE",
    "domain": ".tiktok.com",
    "path": "/"
  }
]
```

---

## 🔌 Web API Routes

- `GET /` — Serves the main Single Page Application (`interface/index.html`).
- `GET /recipes_db.json` — Returns all saved recipes with rounded macronutrients.
- `POST /api/recipes/calculate_macros` — Calculates aggregated macros from ingredient items and quantities.
- `POST /api/recipes/update` — Updates a recipe record, recalculating macros strictly from ingredient items.
- `POST /api/recipes/delete` — Deletes a recipe record.
- `GET /api/ingredients/search?q=<term>` — Full-text search autocomplete against the CIQUAL foods database.
- `GET /api/barcode/lookup?barcode=<code>` — Barcode lookup with Open Food Facts fallback and local DB caching.
- `GET /api/manual_check/recipes` — Lists recipes flagged for manual ingredient review.
- `POST /api/manual_check/approve` — Approves and saves a manually reviewed recipe.
