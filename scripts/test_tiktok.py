import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recipe_processor.llm_parser import parse_recipe_with_llm, fallback_parse_recipe
from recipe_processor.validator import RecipeValidator
from database.postgres_db import RecipeDatabase

not_added_db = RecipeDatabase(table_name='not_added_recipes')
r = not_added_db.get('tt_7676997033193999638') or not_added_db.get('7676997033193999638')
if r:
    raw = fallback_parse_recipe(r.get('description'))
    print("RAW fallback_parse_recipe:")
    for i in raw.get("ingredients", []):
        print("  RAW:", i)
    
    rec = RecipeValidator.reconcile_recipe_payload(raw)
    print("\nRECONCILED:")
    for i in rec.get("ingredients", []):
        print("  REC:", i)

    parsed = parse_recipe_with_llm(r.get('description'))
    print("\nPARSE_RECIPE_WITH_LLM:")
    for i in parsed.get("ingredients", []):
        print("  PARSED:", i)
