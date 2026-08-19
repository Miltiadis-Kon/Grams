import io
import sys
import os
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import RecipeDatabase
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from helpers.youtube_ingester import YouTubeIngester
from recipe_processor.pipeline import RecipePipeline

# Initialize DBs
db = RecipeDatabase("recipes")
not_added_db = RecipeDatabase("not_added_recipes")
analyzer = NutritionAnalyzer()
tagger = AutoTagger()

pipeline = RecipePipeline(
    database=db,
    not_added_database=not_added_db,
    nutrition_analyzer=analyzer,
    tagger=tagger
)

yt_ingester = YouTubeIngester(pipeline)

test_url = "https://www.youtube.com/watch?v=naS5eVSwHlk"
video_id = "yt_naS5eVSwHlk"

print("=" * 80)
print(f"TESTING SINGLE YOUTUBE INGESTION: {test_url}")
print("=" * 80)

status = yt_ingester.ingest_single(test_url, force=True)
print(f"Pipeline Result Status: {status}")

# Check DB
rec = db.get(video_id)
if not rec:
    rec = not_added_db.get(video_id)
    print("Found in NOT_ADDED_RECIPES table")
else:
    print("Found in RECIPES table")

if rec:
    print(f"\nName: {rec.get('name')}")
    print(f"URL: {rec.get('url')}")
    print(f"Macros: {rec.get('macros')}")
    print(f"Tags: {rec.get('tags')}")
    print(f"Ingredients count: {len(rec.get('ingredients', []))}")
    print(f"Instructions count: {len(rec.get('instructions', []))}")
    meta = rec.get("metadata", {})
    print(f"Metadata Keys: {list(meta.keys()) if isinstance(meta, dict) else 'none'}")
    print(f"Transcript length: {len(rec.get('transcript', ''))}")
    print(f"\nSample Ingredients:")
    for ing in rec.get('ingredients', [])[:5]:
        print(f" - {ing}")
