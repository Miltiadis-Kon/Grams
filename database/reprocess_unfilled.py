import sys
import os
import json
import logging

# Ensure root dir is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("reprocess_unfilled")

from helpers.engine import RecipeEngine
from database.models import MacroNutrients

def main():
    engine = RecipeEngine()
    not_added_db = engine._not_added_database
    main_db = engine._database
    nutrition = engine._nutrition
    tagger = engine._tagger
    
    # Load raw dicts from not_added_recipes.json
    not_added_path = not_added_db._db_path
    if not os.path.exists(not_added_path):
        logger.error("Not added recipes file not found.")
        return
        
    with open(not_added_path, "r", encoding="utf-8") as f:
        not_added_data = json.load(f)
        
    moved_count = 0
    updated_not_added = {}
    
    for recipe_id, recipe_dict in not_added_data.items():
        # Check if it has ingredients and zero macros
        ingredients = recipe_dict.get("ingredients", [])
        macros_dict = recipe_dict.get("macros", {})
        protein = macros_dict.get("protein", 0.0)
        carbs = macros_dict.get("carbs", 0.0)
        fats = macros_dict.get("fats", 0.0)
        calories = macros_dict.get("calories", 0)
        
        is_empty_macros = (protein == 0.0 and carbs == 0.0 and fats == 0.0 and calories == 0)
        
        if ingredients and is_empty_macros:
            description = recipe_dict.get("description", "")
            logger.info("Processing empty macro recipe '%s' (%s) with %d ingredients...", 
                        recipe_id, recipe_dict.get("name"), len(ingredients))
            
            # Use NutritionAnalyzer to calculate macros directly from the ingredients list
            calculated_macros = nutrition.analyze_ingredients(ingredients, description_for_servings=description)
            if calculated_macros and (calculated_macros.protein > 0 or calculated_macros.carbs > 0 or calculated_macros.fats > 0):
                logger.info("  -> Calculated macros: P:%.1f C:%.1f F:%.1f Cal:%d",
                            calculated_macros.protein, calculated_macros.carbs, calculated_macros.fats, calculated_macros.calories)
                
                # Update recipe dict macros
                recipe_dict["macros"] = {
                    "protein": calculated_macros.protein,
                    "carbs": calculated_macros.carbs,
                    "fats": calculated_macros.fats,
                    "calories": calculated_macros.calories
                }
                
                # Re-tag based on new macros
                # Need to convert dictionary to Recipe object for tagger
                from database import Recipe
                recipe_obj = Recipe(
                    name=recipe_dict["name"],
                    url=recipe_dict["url"],
                    description=recipe_dict["description"],
                    macros=calculated_macros,
                    ingredients=recipe_dict["ingredients"],
                    added_on=recipe_dict.get("added_on", "")
                )
                recipe_dict["tags"] = tagger.tag(recipe_obj)
                
                # Insert into main db dict if not already exists
                if not main_db.exists(recipe_id):
                    main_db.insert(recipe_id, recipe_obj)
                moved_count += 1
                logger.info("  -> Moved to main database!")
            else:
                logger.info("  -> Could not calculate macros. Keeping in manual check list.")
                updated_not_added[recipe_id] = recipe_dict
        else:
            updated_not_added[recipe_id] = recipe_dict
            
    if moved_count > 0:
        logger.info("Saving updated databases...")
        with open(not_added_path, "w", encoding="utf-8") as f:
            json.dump(updated_not_added, f, indent=4, ensure_ascii=False)
        logger.info("Successfully reprocessed and moved %d recipes!", moved_count)
    else:
        logger.info("No recipes were moved.")

if __name__ == "__main__":
    main()
