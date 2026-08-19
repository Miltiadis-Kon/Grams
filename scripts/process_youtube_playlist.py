import io
import sys
import os
import json
import csv
import logging

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("YouTubePlaylistProcessor")

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

playlist_url = "https://www.youtube.com/playlist?list=PL9_z7arfoMrv0i0RFhxVxf4QbdjUC6JDL"

print("=" * 90)
print(f"STARTING YOUTUBE PLAYLIST INGESTION: {playlist_url}")
print("=" * 90)

# Process all videos from playlist
stats = yt_ingester.ingest_playlist(
    playlist_url=playlist_url,
    force=True, # Ensure complete reprocessing with direct transcripts
    delay_sec=0.2
)

print("\n" + "=" * 90)
print("PLAYLIST INGESTION FINISHED!")
print(f"Stats: Total={stats['total']}, Added={stats['added']}, Skipped={stats['skipped']}, Not Added={stats['not_added']}, Errors={stats['errors']}")
print("=" * 90)

# Export summary CSV of all YouTube playlist videos
videos = yt_ingester.extract_playlist_videos(playlist_url)
summary_csv = "data/youtube_playlist_summary.csv"
detailed_csv = "data/youtube_playlist_detailed_ingredients.csv"

os.makedirs("data", exist_ok=True)

with open(summary_csv, mode="w", newline="", encoding="utf-8-sig") as f_sum, \
     open(detailed_csv, mode="w", newline="", encoding="utf-8-sig") as f_det:
    
    sum_writer = csv.writer(f_sum)
    det_writer = csv.writer(f_det)
    
    sum_writer.writerow([
        "video_index",
        "recipe_id",
        "status",
        "title",
        "calories_kcal",
        "protein_g",
        "carbs_g",
        "fats_g",
        "ingredient_count",
        "instruction_count",
        "tags",
        "transcript_length",
        "url",
        "metadata"
    ])
    
    det_writer.writerow([
        "video_index",
        "recipe_id",
        "recipe_title",
        "ingredient_name",
        "ingredient_quantity",
        "usda_hash",
        "weight_grams",
        "calories",
        "protein_g",
        "carbs_g",
        "fats_g"
    ])
    
    for idx, v in enumerate(videos, start=1):
        vid_id = v["id"]
        rec = db.get(vid_id)
        status_label = "Added to Recipes"
        if not rec:
            rec = not_added_db.get(vid_id)
            status_label = "Manual Review (Not Added)" if rec else "Failed / Missing"
        
        if not rec:
            continue
            
        macros = rec.get("macros", {})
        ingredients = rec.get("ingredients", [])
        instructions = rec.get("instructions", [])
        tags = rec.get("tags", [])
        meta = rec.get("metadata", {})
        transcript = rec.get("transcript", "")
        
        sum_writer.writerow([
            idx,
            vid_id,
            status_label,
            rec.get("name"),
            macros.get("calories", 0),
            macros.get("protein", 0),
            macros.get("carbs", 0),
            macros.get("fats", 0),
            len(ingredients),
            len(instructions),
            ", ".join(tags) if isinstance(tags, list) else str(tags),
            len(transcript),
            rec.get("url"),
            json.dumps(meta) if isinstance(meta, dict) else str(meta)
        ])
        
        for ing in ingredients:
            det_writer.writerow([
                idx,
                vid_id,
                rec.get("name"),
                ing.get("name"),
                ing.get("quantity"),
                ing.get("hash"),
                ing.get("grams"),
                ing.get("calories"),
                ing.get("protein"),
                ing.get("carbs"),
                ing.get("fats")
            ])

print(f"\nExports created:")
print(f" - {summary_csv}")
print(f" - {detailed_csv}")
