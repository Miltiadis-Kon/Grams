import sqlite3
import json
import csv
import os

os.makedirs("data", exist_ok=True)

conn = sqlite3.connect("data/recipes.db")
cur = conn.cursor()

# 1. Summary CSV
summary_file = "data/reprocessed_first_10_summary.csv"
with open(summary_file, mode="w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow([
        "video_index",
        "recipe_id",
        "status",
        "recipe_name",
        "calories_kcal",
        "protein_g",
        "carbs_g",
        "fat_g",
        "serving_info",
        "calculation_type",
        "ingredient_count",
        "instruction_count",
        "tags",
        "last_processed",
        "transcript_length",
        "url",
        "metadata",
        "description",
        "transcript"
    ])

    FIRST_10_IDS = [
        "7660019682480508191",
        "7664529268256427284",
        "7672763431329565983",
        "7641582274529594632",
        "7659367329381322006",
        "7660218141707980054",
        "7661273482776284436",
        "7659485638449794326",
        "7659022462377577750",
        "7659071858679106838",
    ]

    for idx, vid in enumerate(FIRST_10_IDS, start=1):
        # Check recipes table first
        row = cur.execute("SELECT recipe_id, name, url, description, macros, ingredients, instructions, tags, transcript, last_processed, metadata FROM recipes WHERE recipe_id = ?", (vid,)).fetchone()
        status = "Added to Recipes"
        if not row:
            row = cur.execute("SELECT recipe_id, name, url, description, macros, ingredients, instructions, tags, transcript, last_processed, metadata FROM not_added_recipes WHERE recipe_id = ?", (vid,)).fetchone()
            status = "Manual Review (Not Added)"

        if not row:
            continue

        recipe_id, name, url, desc, macros_json, ingr_json, inst_json, tags_json, transcript, last_proc, metadata_val = row
        macros = json.loads(macros_json) if macros_json else {}
        ingredients = json.loads(ingr_json) if ingr_json else []
        instructions = json.loads(inst_json) if inst_json else []
        tags = json.loads(tags_json) if tags_json else []

        calc_type = "Explicit Caption/Speech" if idx in [1, 2] else ("USDA Ingredient Sum (Whole Batch)" if status == "Added to Recipes" else "None")
        
        writer.writerow([
            idx,
            recipe_id,
            status,
            name,
            macros.get("calories", 0),
            macros.get("protein", 0),
            macros.get("carbs", 0),
            macros.get("fats", 0),
            macros.get("serving", "") or "Total Batch (Unscaled)",
            calc_type,
            len(ingredients),
            len(instructions),
            ", ".join(tags) if isinstance(tags, list) else str(tags),
            last_proc,
            len(transcript) if transcript else 0,
            url,
            metadata_val or json.dumps({"transcript": transcript or "", "description": desc or ""}),
            desc or "",
            transcript or ""
        ])

# 2. Detailed Ingredients Breakdown CSV
breakdown_file = "data/reprocessed_first_10_detailed_ingredients.csv"
with open(breakdown_file, mode="w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow([
        "video_index",
        "recipe_id",
        "recipe_name",
        "status",
        "ingredient_raw_name",
        "ingredient_quantity",
        "matched_usda_item",
        "usda_fdc_id",
        "weight_grams",
        "ingredient_calories",
        "ingredient_protein_g",
        "ingredient_carbs_g",
        "ingredient_fat_g"
    ])

    for idx, vid in enumerate(FIRST_10_IDS, start=1):
        row = cur.execute("SELECT recipe_id, name, ingredients, macros FROM recipes WHERE recipe_id = ?", (vid,)).fetchone()
        status = "Added to Recipes"
        if not row:
            row = cur.execute("SELECT recipe_id, name, ingredients, macros FROM not_added_recipes WHERE recipe_id = ?", (vid,)).fetchone()
            status = "Manual Review (Not Added)"

        if not row:
            continue

        recipe_id, name, ingr_json, _ = row
        ingredients = json.loads(ingr_json) if ingr_json else []

        if not ingredients:
            writer.writerow([
                idx,
                recipe_id,
                name,
                status,
                "(No structured ingredients parsed)",
                "",
                "",
                "",
                0,
                0,
                0,
                0,
                0
            ])
        else:
            for ing in ingredients:
                writer.writerow([
                    idx,
                    recipe_id,
                    name,
                    status,
                    ing.get("name", ""),
                    ing.get("quantity", ""),
                    ing.get("name", "") if ing.get("hash") else "No match",
                    ing.get("hash", ""),
                    ing.get("grams", 0),
                    ing.get("calories", 0),
                    ing.get("protein", 0),
                    ing.get("carbs", 0),
                    ing.get("fats", 0)
                ])

print("CSV export complete:")
print(" -", summary_file)
print(" -", breakdown_file)
