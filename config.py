"""
Configuration module for the Recipe Ingestion & Database Engine.

Centralizes all constants, paths, and extensible mappings used across modules.
Zero external credentials required — all data sources are local/open.
"""

import os

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_FILE_PATH = os.path.join(BASE_DIR, "database", "recipes_db.json")

# OpenNutrition dataset
OPENNUTRITION_DB_PATH = os.path.join(DATA_DIR, "opennutrition.db")
OPENNUTRITION_TSV_PATH = os.path.join(DATA_DIR, "opennutrition_foods.tsv")
OPENNUTRITION_ZIP_URL = (
    "https://downloads.opennutrition.app/opennutrition-dataset-2025.1.zip"
)

# TikTok session cookies path (Netscape/JSON format)
TIKTOK_COOKIES_PATH = os.path.join(BASE_DIR, "tiktok_cookies.json")

# Database path for recipes that failed to parse (manual review list)
NOT_ADDED_FILE_PATH = os.path.join(BASE_DIR, "database", "not_added_recipes.json")

# Supadata API settings
SUPADATA_API_KEY = "sd_506d984360594aae56cc898b068dbfb5"

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
