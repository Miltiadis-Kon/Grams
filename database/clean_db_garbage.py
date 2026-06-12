import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Add parent directory to path so we can import helpers
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers.nutrition import NutritionAnalyzer

def clean_database():
    db_path = os.path.join("database", "recipes_db.json")
    not_added_path = os.path.join("database", "not_added_recipes.json")
    
    if not os.path.exists(db_path):
        print("Database file does not exist.")
        return
        
    with open(db_path, "r", encoding="utf-8") as f:
        db = json.load(f)
        
    if os.path.exists(not_added_path):
        with open(not_added_path, "r", encoding="utf-8") as f:
            not_added = json.load(f)
    else:
        not_added = {}
        
    analyzer = NutritionAnalyzer()
    
    migrated_count = 0
    updated_count = 0
    
    for recipe_id, recipe in list(db.items()):
        description = recipe.get("description", "")
        # Re-run analysis
        macros, ingredients = analyzer.analyze(description)
        
        is_empty = (
            macros.protein == 0.0 and
            macros.carbs == 0.0 and
            macros.fats == 0.0 and
            macros.calories == 0
        )
        
        if is_empty:
            # Ensure it is marked as unfilled
            recipe["macros"] = {
                "protein": 0.0,
                "carbs": 0.0,
                "fats": 0.0,
                "calories": 0
            }
            recipe["ingredients"] = []
            not_added[recipe_id] = recipe
            db.pop(recipe_id)
            migrated_count += 1
            print(f"Migrated empty/garbage recipe {recipe_id} ('{recipe.get('name')[:40]}') to manual check list")
        else:
            # Update macros and ingredients with the correct ones
            recipe["macros"] = {
                "protein": macros.protein,
                "carbs": macros.carbs,
                "fats": macros.fats,
                "calories": macros.calories
            }
            recipe["ingredients"] = ingredients
            updated_count += 1
            
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)
        
    with open(not_added_path, "w", encoding="utf-8") as f:
        json.dump(not_added, f, indent=4, ensure_ascii=False)
        
    print(f"Completed DB cleaning. Migrated: {migrated_count}, Updated: {updated_count}")

if __name__ == "__main__":
    clean_database()
