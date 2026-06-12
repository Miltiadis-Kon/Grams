import os
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("migration")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "database", "recipes_db.json")
NOT_ADDED_PATH = os.path.join(BASE_DIR, "database", "not_added_recipes.json")

def main():
    if not os.path.exists(DB_PATH):
        logger.error(f"Main database file not found at {DB_PATH}")
        return

    logger.info(f"Loading main database: {DB_PATH}")
    with open(DB_PATH, "r", encoding="utf-8") as f:
        try:
            db_data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode main database JSON: {e}")
            return

    # Load existing not_added recipes or initialize empty
    not_added_data = {}
    if os.path.exists(NOT_ADDED_PATH):
        logger.info(f"Loading existing not-added database: {NOT_ADDED_PATH}")
        with open(NOT_ADDED_PATH, "r", encoding="utf-8") as f:
            try:
                not_added_data = json.load(f)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode not-added database JSON: {e}. Starting fresh.")

    logger.info(f"Total recipes in main database: {len(db_data)}")
    
    clean_db = {}
    migrated_count = 0

    for recipe_id, recipe in db_data.items():
        macros = recipe.get("macros", {})
        protein = macros.get("protein", 0.0)
        carbs = macros.get("carbs", 0.0)
        fats = macros.get("fats", 0.0)
        calories = macros.get("calories", 0)

        is_empty = (protein == 0.0 and carbs == 0.0 and fats == 0.0 and calories == 0)

        if is_empty:
            not_added_data[recipe_id] = recipe
            migrated_count += 1
        else:
            clean_db[recipe_id] = recipe

    logger.info(f"Identified {migrated_count} empty recipes to migrate.")
    logger.info(f"Remaining active recipes: {len(clean_db)}")

    # Write main database back
    logger.info("Saving main database...")
    temp_db_path = DB_PATH + ".tmp"
    with open(temp_db_path, "w", encoding="utf-8") as f:
        json.dump(clean_db, f, indent=4, ensure_ascii=False)
    if os.path.exists(DB_PATH):
        os.replace(temp_db_path, DB_PATH)
    else:
        os.rename(temp_db_path, DB_PATH)

    # Write not-added database
    logger.info("Saving not-added database...")
    temp_not_added_path = NOT_ADDED_PATH + ".tmp"
    with open(temp_not_added_path, "w", encoding="utf-8") as f:
        json.dump(not_added_data, f, indent=4, ensure_ascii=False)
    if os.path.exists(NOT_ADDED_PATH):
        os.replace(temp_not_added_path, NOT_ADDED_PATH)
    else:
        os.rename(temp_not_added_path, NOT_ADDED_PATH)

    logger.info("Migration completed successfully!")

if __name__ == "__main__":
    main()
