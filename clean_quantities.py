#!/usr/bin/env python3
"""
Database migration script to clean up non-numeric ingredient quantities.
Scans recipes and not_added_recipes, replacing empty or non-numeric quantities
(like 'to taste', 'for topping', 'optional') with the default quantity '1'.
"""

import os
import sys
import logging
import config
from database import RecipeDatabase

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("clean_quantities")


def is_digit_or_fraction(char: str) -> bool:
    """Check if character is a digit or a unicode vulgar fraction."""
    if char.isdigit():
        return True
    return '\u00bc' <= char <= '\u00be' or '\u2150' <= char <= '\u2189'


def has_numeric_quantity(qty_str: str) -> bool:
    """Determine if a quantity string contains at least one digit or fraction."""
    if not qty_str:
        return False
    return any(is_digit_or_fraction(c) for c in qty_str)


def clean_table(table_identifier: str) -> None:
    """Scan and clean quantities for a given table identifier."""
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
    logger.info("Found %d recipes in '%s'. Checking ingredients...", total_recipes, table_identifier)

    updated_count = 0
    for recipe_id, recipe in recipes.items():
        # Ensure ingredients is a list
        ingredients = recipe.get("ingredients")
        if not isinstance(ingredients, list):
            continue

        modified = False
        new_ingredients = []

        for ing in ingredients:
            name = ing.get("name", "").strip()
            qty = ing.get("quantity", "")
            
            # Convert quantity to string if it isn't one
            if qty is None:
                qty_str = ""
            else:
                qty_str = str(qty).strip()

            if not has_numeric_quantity(qty_str):
                logger.info(
                    "  [%s] Recipe '%s' -> Ingredient '%s': replacing non-numeric quantity '%s' with '1'",
                    recipe_id, recipe.get("name", "Untitled"), name, qty
                )
                ing["quantity"] = "1"
                modified = True
            
            new_ingredients.append(ing)

        if modified:
            recipe["ingredients"] = new_ingredients
            
            # Recalculate macros for the recipe since ingredients/quantities modified
            try:
                from helpers.nutrition import NutritionAnalyzer
                analyzer = NutritionAnalyzer()
                # Recalculate macros
                desc = recipe.get("description", "")
                macros = analyzer.analyze_ingredients(new_ingredients, description_for_servings=desc)
                recipe["macros"] = {
                    "protein": macros.protein,
                    "carbs": macros.carbs,
                    "fats": macros.fats,
                    "calories": macros.calories
                }
                logger.info("    Recalculated macros: P:%.1f C:%.1f F:%.1f Cal:%d",
                            macros.protein, macros.carbs, macros.fats, macros.calories)
            except Exception as e:
                logger.warning("    Failed to recalculate macros for recipe '%s': %s", recipe_id, e)

            try:
                db.update(recipe_id, recipe)
                updated_count += 1
            except Exception as e:
                logger.error("    Failed to update recipe '%s' in database: %s", recipe_id, e)

    logger.info("Completed cleaning table '%s'. Updated %d/%d recipes.", table_identifier, updated_count, total_recipes)


def main():
    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL environment variable is not set. Please set it in your environment or .env file.")
        sys.exit(1)

    logger.info("Starting quantity cleanup migration...")
    # Clean main recipes
    clean_table("recipes")
    # Clean not added recipes
    clean_table("not_added_recipes")
    logger.info("Cleanup migration complete.")


if __name__ == "__main__":
    main()
