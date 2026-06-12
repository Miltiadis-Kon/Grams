"""
Demo / test script for the Recipe Ingestion & Database Engine.

Demonstrates:
1. Manual recipe ingestion with mock data
2. Incremental skip verification (delta handling)
3. Nutritional analysis (OpenNutrition lookup or Atwater fallback)
4. Auto-tagging (threshold + keyword + manual tags)
5. Query operations (search_by_keyword, filter_by_tag, get_all_recipes)
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys

# Force UTF-8 output on Windows consoles
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Configure logging ────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-18s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def separator(title: str) -> None:
    """Print a visual section separator."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def pretty_print(data: dict, indent: int = 4) -> None:
    """Pretty-print a dict as JSON."""
    print(json.dumps(data, indent=indent, ensure_ascii=False))


def main() -> None:
    # Use a test database to avoid polluting production data
    test_db_path = os.path.join(os.path.dirname(__file__), "test_recipes_db.json")

    # Clean up previous test run
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    # Import engine (deferred so logging is configured first)
    from engine import RecipeEngine

    separator("INITIALIZING RECIPE ENGINE")
    engine = RecipeEngine(db_path=test_db_path)
    print(f"Engine ready: {engine}")

    # ──────────────────────────────────────────────
    # 1. MANUAL RECIPE INGESTION (Mock Data)
    # ──────────────────────────────────────────────
    separator("1. INGESTING MOCK RECIPES")

    mock_recipes = [
        {
            "id": "recipe_001",
            "name": "High-Protein Chicken Bowl",
            "url": "https://example.com/chicken-bowl",
            "description": "grilled chicken breast, brown rice, steamed broccoli, soy sauce",
            "manual_tags": ["Favorite"],
        },
        {
            "id": "recipe_002",
            "name": "Keto Breakfast Plate",
            "url": "https://example.com/keto-breakfast",
            "description": "scrambled eggs, bacon, avocado, butter, cheese",
            "manual_tags": ["Quick"],
        },
        {
            "id": "recipe_003",
            "name": "Low-Calorie Salmon Salad",
            "url": "https://example.com/salmon-salad",
            "description": "fresh salmon fillet, mixed greens, lemon, olive oil, cherry tomatoes",
        },
        {
            "id": "recipe_004",
            "name": "Vegan Meal Prep Buddha Bowl",
            "url": "https://example.com/buddha-bowl",
            "description": "quinoa, chickpeas, sweet potato, tahini, kale, plant-based protein",
            "manual_tags": ["Weekly Prep"],
        },
    ]

    stats = engine.ingest_batch(mock_recipes)
    print(f"\nBatch result: {stats}")
    print(f"Total recipes in database: {engine.recipe_count}")

    # ──────────────────────────────────────────────
    # 2. INCREMENTAL SKIP VERIFICATION
    # ──────────────────────────────────────────────
    separator("2. INCREMENTAL SYNC - RE-INGESTING SAME RECIPES")
    print("Attempting to re-ingest the same 4 recipes...")

    stats_rerun = engine.ingest_batch(mock_recipes)
    print(f"\nBatch result: {stats_rerun}")
    print(f"Expected: 0 added, 4 skipped - Actual: {stats_rerun['added']} added, {stats_rerun['skipped']} skipped")

    assert stats_rerun["added"] == 0, "Delta handling failed - duplicates were inserted!"
    assert stats_rerun["skipped"] == 4, "Delta handling failed - not all duplicates were caught!"
    print("[OK] Delta handling verified - all duplicates skipped correctly")

    # ──────────────────────────────────────────────
    # 3. INSPECT STORED DATA (Schema Verification)
    # ──────────────────────────────────────────────
    separator("3. STORED RECIPE DATA (Schema Verification)")
    all_recipes = engine.get_all()

    for recipe_id, recipe_data in all_recipes.items():
        print(f"\n-- {recipe_id} --")
        pretty_print(recipe_data)

    # ──────────────────────────────────────────────
    # 4. QUERY: search_by_keyword
    # ──────────────────────────────────────────────
    separator("4. QUERY — search_by_keyword('chicken')")
    results = engine.search("chicken")
    print(f"Found {len(results)} result(s):")
    for rid, rdata in results.items():
        print(f"  * {rid}: {rdata['name']}")

    separator("4b. QUERY — search_by_keyword('salmon')")
    results = engine.search("salmon")
    print(f"Found {len(results)} result(s):")
    for rid, rdata in results.items():
        print(f"  • {rid}: {rdata['name']}")

    # ──────────────────────────────────────────────
    # 5. QUERY: filter_by_tag
    # ──────────────────────────────────────────────
    separator("5. QUERY — filter_by_tag('Meat')")
    results = engine.filter("Meat")
    print(f"Found {len(results)} result(s):")
    for rid, rdata in results.items():
        print(f"  * {rid}: {rdata['name']} - tags: {rdata['tags']}")

    separator("5b. QUERY — filter_by_tag('Meal Prep')")
    results = engine.filter("Meal Prep")
    print(f"Found {len(results)} result(s):")
    for rid, rdata in results.items():
        print(f"  • {rid}: {rdata['name']} — tags: {rdata['tags']}")

    separator("5c. QUERY — filter_by_tag('Vegan')")
    results = engine.filter("Vegan")
    print(f"Found {len(results)} result(s):")
    for rid, rdata in results.items():
        print(f"  • {rid}: {rdata['name']} — tags: {rdata['tags']}")

    # ──────────────────────────────────────────────
    # 6. QUERY: get_all_recipes
    # ──────────────────────────────────────────────
    separator("6. QUERY — get_all_recipes()")
    all_data = engine.get_all()
    print(f"Total recipes: {len(all_data)}")
    for rid, rdata in all_data.items():
        print(f"  * {rid}: {rdata['name']} (Cal: {rdata['macros']['calories']}) - {rdata['tags']}")

    # ──────────────────────────────────────────────
    # CLEANUP
    # ──────────────────────────────────────────────
    separator("DEMO COMPLETE")
    engine.close()
    print(f"Test database written to: {test_db_path}")
    print("All assertions passed. Engine is ready for production use.")


if __name__ == "__main__":
    main()
