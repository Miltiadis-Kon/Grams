import io
import sys
import os
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recipe_processor.pipeline import RecipePipeline
from database import RecipeDatabase
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from helpers.ingester import TikTokIngester

# Initialize databases
db = RecipeDatabase("recipes")
not_added_db = RecipeDatabase("not_added_recipes")
analyzer = NutritionAnalyzer()
tagger = AutoTagger()

# Initialize pipeline & ingester
pipeline = RecipePipeline(
    database=db,
    not_added_database=not_added_db,
    nutrition_analyzer=analyzer,
    tagger=tagger
)
ingester = TikTokIngester(pipeline)

# Target 1 recipe (Video 1)
test_video_url = "https://www.tiktok.com/@noahperlofit/video/7660019682480508191"
recipe_id = "7660019682480508191"

print("=" * 80)
print(f"TESTING SINGLE RECIPE METADATA INGESTION FOR: {recipe_id}")
print("=" * 80)

# Process video with force=True
status = ingester.ingest_single(test_video_url, force=True)
print(f"Pipeline Result Status: {status}")

# Read directly from DB
record = db.get(recipe_id)

print("\n" + "=" * 80)
print("DATABASE RECORD VERIFICATION")
print("=" * 80)
if record:
    print(f"Recipe ID: {recipe_id}")
    print(f"Name: {record.get('name')}")
    print(f"Last Processed: {record.get('last_processed')}")
    print(f"Macros: {record.get('macros')}")
    
    meta = record.get("metadata")
    print(f"\nMetadata Type: {type(meta)}")
    print(f"Metadata Keys: {list(meta.keys()) if isinstance(meta, dict) else 'Not a dict'}")
    if isinstance(meta, dict):
        desc = meta.get("description", "")
        trans = meta.get("transcript", "")
        print(f"Metadata Description Length: {len(desc)} characters")
        print(f"Metadata Transcript Length: {len(trans)} characters")
        print(f"\n--- Metadata Transcript Sample ---\n{trans[:200]}...")
        print(f"\n--- Metadata Description Sample ---\n{desc[:200]}...")
        print("\n>>> METADATA VERIFICATION SUCCESSFUL! <<<")
else:
    print("ERROR: Record not found in recipes DB!")
