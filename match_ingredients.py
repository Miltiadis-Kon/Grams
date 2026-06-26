#!/usr/bin/env python3
"""
Database migration script to run ingredient matching for all recipes.
Scans recipes and not_added_recipes, running analyze_ingredients on each to
populate ingredient hashes and update official names from the OpenNutrition DB.
"""

import os
import sys
import logging
import config
from database import RecipeDatabase

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("match_ingredients")


def match_table(table_identifier: str) -> None:
    """Scan and match ingredients for a given table identifier."""
    logger.info("Initializing database wrapper for '%s'...", table_identifier)
    try:
        db = RecipeDatabase(table_identifier)
    except Exception as e:
        logger.error("Failed to initialize RecipeDatabase: %s", e)
        return

    logger.info("Fetching all records from '%s'...", table_identifier)
    try:
        recipes = db.get_all()
    except Exception as e:
        logger.error("Failed to fetch recipes: %s", e)
        return

    total_recipes = len(recipes)
    logger.info("Found %d recipes in '%s'. Processing ingredients...", total_recipes, table_identifier)

    # Initialize analyzer once outside the loop
    analyzer = None
    try:
        from helpers.nutrition import NutritionAnalyzer
        analyzer = NutritionAnalyzer()
    except Exception as e:
        logger.warning("Failed to initialize NutritionAnalyzer, macros will not be recalculated: %s", e)
        return

    updated_count = 0
    for recipe_id, recipe in recipes.items():
        # Ensure ingredients is a list
        ingredients = recipe.get("ingredients")
        if not isinstance(ingredients, list) or not ingredients:
            continue

        try:
            desc = recipe.get("description", "")
            # analyze_ingredients mutates the ingredients list in-place to add hash and update name
            macros = analyzer.analyze_ingredients(ingredients, description_for_servings=desc)
            
            recipe["macros"] = {
                "protein": macros.protein,
                "carbs": macros.carbs,
                "fats": macros.fats,
                "calories": macros.calories
            }
            logger.info("  [%s] '%s' -> Processed ingredients and updated macros",
                        recipe_id, recipe.get("name", "Untitled"))
                        
            # Update the recipe back to the database
            db.update(recipe_id, recipe)
            updated_count += 1
            
        except Exception as e:
            logger.warning("    Failed to process recipe '%s': %s", recipe_id, e)

    if hasattr(analyzer, 'close'):
        try:
            analyzer.close()
        except:
            pass

    logger.info("Completed matching ingredients for table '%s'. Updated %d/%d recipes.", table_identifier, updated_count, total_recipes)


def main():
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
        logger.error("SUPABASE_URL and SUPABASE_KEY environment variables are not set. Please set them in your environment or .env file.")
        sys.exit(1)

    logger.info("Starting ingredient matching migration...")
    # Update main recipes
    match_table(config.RECIPES_TABLE if hasattr(config, "RECIPES_TABLE") else "recipes")
    # Update not added recipes
    match_table(config.NOT_ADDED_RECIPES_TABLE if hasattr(config, "NOT_ADDED_RECIPES_TABLE") else "not_added_recipes")
    logger.info("Ingredient matching migration complete.")


if __name__ == "__main__":
    main()
