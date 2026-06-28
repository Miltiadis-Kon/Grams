import os
import sys
import logging
import time
from dotenv import load_dotenv
from supabase import create_client

# Force utf-8 encoding for standard output to prevent logging crashes with Greek characters
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import RecipeDatabase
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from recipe_processor.pipeline import RecipePipeline
from recipe_processor.context import RecipeContext
import config

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.FileHandler(r"c:\Users\M\Desktop\repos\Grams\reprocess.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def main():
    load_dotenv(r'c:\Users\M\Desktop\repos\Grams\.env')
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_KEY")
        return

    client = create_client(url, key)
    
    RECIPES_TABLE = getattr(config, "RECIPES_TABLE", "recipes")
    db = RecipeDatabase(RECIPES_TABLE)
    not_added_db = RecipeDatabase("not_added_recipes")
    analyzer = NutritionAnalyzer()
    tagger = AutoTagger()
    
    pipeline = RecipePipeline(db, not_added_db, analyzer, tagger)
    # The head of the pipeline is DeltaCheckHandler. 
    # We want to skip DeltaCheckHandler and go straight to DescriptionParseHandler.
    bypass_head = pipeline._head._next_handler
    
    import argparse
    parser = argparse.ArgumentParser(description="Reprocess recipes in the database.")
    parser.add_argument("--batch-size", type=int, default=0, help="Number of recipes to process. If 0, processes all.")
    args = parser.parse_args()

    logger.info("Fetching recipes to reprocess...")
    all_recipes = []
    
    if args.batch_size > 0:
        res = client.table(RECIPES_TABLE).select("*").order("updated_at", nullsfirst=True).limit(args.batch_size).execute()
        all_recipes.extend(res.data)
    else:
        page_size = 1000
        offset = 0
        while True:
            res = client.table(RECIPES_TABLE).select("*").range(offset, offset + page_size - 1).execute()
            if not res.data:
                break
            all_recipes.extend(res.data)
            if len(res.data) < page_size:
                break
            offset += page_size

    logger.info("Starting reprocessing of %d recipes...", len(all_recipes))
    reprocessed_count = 0
    
    for idx, row in enumerate(all_recipes):
        if args.batch_size == 0 and idx > 0 and idx % 30 == 0:
            logger.info("Processed %d recipes. Sleeping for 1 hour to prevent API limits...", idx)
            time.sleep(3600)
            
        recipe_id = row.get("recipe_id")
        name = row.get("name", "")
        url_str = row.get("url", "")
        description = row.get("description", "")
        
        # Build a fresh context
        context = RecipeContext(
            recipe_id=recipe_id,
            url=url_str,
            name=name,
            description=description
        )
        
        logger.info(f"Reprocessing [{reprocessed_count+1}/{len(all_recipes)}] - '{recipe_id}'...")
        try:
            # We bypass the DeltaCheckHandler by starting at the next handler
            bypass_head.handle(context)
            reprocessed_count += 1
            # Add a small delay to avoid hitting LLM rate limits immediately
            time.sleep(2)
        except Exception as e:
            logger.error(f"Failed to reprocess {recipe_id}: {e}")
            
    logger.info(f"Reprocess complete. Successfully ran pipeline on {reprocessed_count} recipes.")

if __name__ == "__main__":
    main()
