import os
import json
import logging
from dotenv import load_dotenv
from supabase import create_client
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from recipe_processor.llm_parser import parse_recipe_with_llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger(__name__)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    env_path = os.path.join(root_dir, ".env")
    load_dotenv(env_path)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_KEY")
        return

    client = create_client(url, key)
    
    # 1. Fetch all recipes
    logger.info("Fetching recipes to backfill instructions...")
    # Because of pagination limits, we loop
    all_recipes = []
    page_size = 1000
    offset = 0
    while True:
        res = client.table("recipes").select("*").range(offset, offset + page_size - 1).execute()
        if not res.data:
            break
        all_recipes.extend(res.data)
        if len(res.data) < page_size:
            break
        offset += page_size

    logger.info(f"Found {len(all_recipes)} recipes in total.")
    
    updated_count = 0
    
    for row in all_recipes:
        instructions = row.get("instructions")
        
        # If instructions exist and are not empty, skip
        if instructions and isinstance(instructions, list) and len(instructions) > 0:
            continue
            
        recipe_id = row.get("id")
        description = row.get("description", "")
        
        if not description.strip():
            logger.info(f"Skipping {recipe_id} - no description/transcript to parse.")
            continue
            
        logger.info(f"Backfilling instructions for recipe '{recipe_id}' ({row.get('name')})...")
        try:
            # We use our newly created LLM parser
            llm_result = parse_recipe_with_llm(description)
            new_instructions = llm_result.get("instructions", [])
            
            if new_instructions:
                # Update Supabase
                client.table("recipes").update({"instructions": new_instructions}).eq("id", recipe_id).execute()
                logger.info(f" -> Added {len(new_instructions)} instructions.")
                updated_count += 1
            else:
                logger.info(f" -> LLM found no instructions.")
        except Exception as e:
            logger.error(f"Failed to backfill {recipe_id}: {e}")
            
    logger.info(f"Backfill complete. Updated {updated_count} recipes.")

if __name__ == "__main__":
    main()
