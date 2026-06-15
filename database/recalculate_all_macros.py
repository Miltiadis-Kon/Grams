import sys
import os
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("recalculate_all_macros")

from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from database import Recipe
from database.models import MacroNutrients

def main():
    db_path = "database/recipes_db.json"
    if not os.path.exists(db_path):
        logger.error("Database file not found.")
        return
        
    with open(db_path, "r", encoding="utf-8") as f:
        db_data = json.load(f)
        
    nutrition = NutritionAnalyzer()
    tagger = AutoTagger()
    
    updated_count = 0
    
    for recipe_id, recipe_dict in db_data.items():
        ingredients = recipe_dict.get("ingredients", [])
        description = recipe_dict.get("description", "")
        old_macros = recipe_dict.get("macros", {})
        
        logger.info("Recalculating macros for recipe '%s' (%s)...", recipe_id, recipe_dict.get("name"))
        
        # Calculate new macros using OpenNutrition analyze_ingredients
        new_macros = nutrition.analyze_ingredients(ingredients, description_for_servings=description)
        
        # Check if they changed
        changed = (
            abs(new_macros.protein - old_macros.get("protein", 0.0)) > 0.01 or
            abs(new_macros.carbs - old_macros.get("carbs", 0.0)) > 0.01 or
            abs(new_macros.fats - old_macros.get("fats", 0.0)) > 0.01 or
            new_macros.calories != old_macros.get("calories", 0)
        )
        
        if changed:
            logger.info("  -> Old macros: P:%.1f C:%.1f F:%.1f Cal:%d", 
                        old_macros.get("protein", 0.0), old_macros.get("carbs", 0.0), 
                        old_macros.get("fats", 0.0), old_macros.get("calories", 0))
            logger.info("  -> New macros: P:%.1f C:%.1f F:%.1f Cal:%d", 
                        new_macros.protein, new_macros.carbs, new_macros.fats, new_macros.calories)
            
            recipe_dict["macros"] = {
                "protein": new_macros.protein,
                "carbs": new_macros.carbs,
                "fats": new_macros.fats,
                "calories": new_macros.calories
            }
            
            # Re-tag based on new macros
            recipe_obj = Recipe(
                name=recipe_dict["name"],
                url=recipe_dict["url"],
                description=recipe_dict["description"],
                macros=new_macros,
                ingredients=recipe_dict["ingredients"],
                added_on=recipe_dict.get("added_on", "")
            )
            recipe_dict["tags"] = tagger.tag(recipe_obj)
            updated_count += 1
            
    if updated_count > 0:
        logger.info("Saving database with %d updated recipes...", updated_count)
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(db_data, f, indent=4, ensure_ascii=False)
        logger.info("Database updated successfully!")
    else:
        logger.info("No macros were updated.")

if __name__ == "__main__":
    main()
