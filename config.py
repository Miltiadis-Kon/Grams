"""
Configuration module for the Recipe Ingestion & Database Engine.

Centralizes all constants, paths, and extensible mappings used across modules.
Zero external credentials required — all data sources are local/open.
"""

import os

# Load local environment variables from .env if it exists
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

# ──────────────────────────────────────────────
# Database & Table Names (Supabase Backend)
# ──────────────────────────────────────────────
RECIPES_TABLE = "recipes"
NOT_ADDED_RECIPES_TABLE = "not_added_recipes"
FOODS_TABLE = "foods"

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# TikTok session cookies path (Netscape/JSON format)
TIKTOK_COOKIES_PATH = os.path.join(BASE_DIR, "tiktok_cookies.json")

# Groq API settings
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Ollama settings (local LLM used as fallback for recipe parsing via transcript)
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"

# ──────────────────────────────────────────────
# HTTP / Download settings
# ──────────────────────────────────────────────
HTTP_TIMEOUT_SECONDS = 30
HTTP_MAX_RETRIES = 3

# ──────────────────────────────────────────────
# Playwright / TikTok Ingester settings
# ──────────────────────────────────────────────
PLAYWRIGHT_HEADLESS = True
TIKTOK_SCROLL_PAUSE_SEC = 2.0
TIKTOK_MAX_SCROLL_ATTEMPTS = 50
TIKTOK_INGEST_DELAY_SEC = 5.0

# ──────────────────────────────────────────────
# Auto-Tagger: Keyword → Tag mapping
# ──────────────────────────────────────────────
# Keys are matched case-insensitively against recipe name + description.
# Values are the tags assigned when a keyword is found.
KEYWORD_TAG_MAP: dict[str, str] = {
    # Meal timing / style
    "prep": "Meal Prep",
    "meal prep": "Meal Prep",
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snack": "Snack",
    "dessert": "Dessert",
    # Proteins — Meat
    "chicken": "Meat",
    "beef": "Meat",
    "pork": "Meat",
    "turkey": "Meat",
    "lamb": "Meat",
    "steak": "Meat",
    "ground meat": "Meat",
    # Proteins — Seafood
    "fish": "Seafood",
    "salmon": "Seafood",
    "tuna": "Seafood",
    "shrimp": "Seafood",
    "prawns": "Seafood",
    "cod": "Seafood",
    # Diet styles
    "vegan": "Vegan",
    "plant": "Vegan",
    "vegetarian": "Vegetarian",
    "gluten free": "Gluten-Free",
    "gluten-free": "Gluten-Free",
    "dairy free": "Dairy-Free",
    "dairy-free": "Dairy-Free",
    # Cooking methods
    "air fryer": "Air Fryer",
    "slow cooker": "Slow Cooker",
    "instant pot": "Instant Pot",
    "grill": "Grilled",
    "bake": "Baked",
}

# ──────────────────────────────────────────────
# Auto-Tagger: Macro thresholds
# ──────────────────────────────────────────────
TAG_HIGH_PROTEIN_MIN = 30.0        # grams
TAG_KETO_CARBS_MAX = 15.0          # grams
TAG_KETO_FATS_MIN = 15.0           # grams
TAG_LOW_CALORIE_MAX = 450          # kcal
