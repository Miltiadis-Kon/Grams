#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_usda_nutrition_db.py — Build SQLite nutrition.db & PostgreSQL seed from USDA FoodData Central CSV files.

Parses:
  - food.csv (fdc_id, description, data_type)
  - food_portion.csv (fdc_id, amount, measure_unit_id, modifier, gram_weight, portion_description)
  - measure_unit.csv (id, name)
  - food_nutrient.csv (fdc_id, nutrient_id, amount)

Extracts Standard USDA Nutrient IDs per 100g:
  - Calories (kcal): 1008, 2047, 2048
  - Protein (g): 1003, 1053
  - Total Fat (g): 1004, 1085
  - Carbohydrates (g): 1005, 1050, 2039
  - Fiber (g): 1079, 2033
"""

import os
import sqlite3
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_DIR = os.path.join(BASE_DIR, "data", "FoodData_Central_foundation_food_csv_2026-04-30")
DB_PATH = os.path.join(BASE_DIR, "data", "nutrition.db")
SQL_SEED_PATH = os.path.join(BASE_DIR, "database", "usda_foods_seed.sql")

def build_db():
    print(f"1. Loading CSV tables from: {CSV_DIR}")
    food_df = pd.read_csv(os.path.join(CSV_DIR, "food.csv"), usecols=["fdc_id", "description", "data_type"], low_memory=False)
    portion_df = pd.read_csv(os.path.join(CSV_DIR, "food_portion.csv"), usecols=["fdc_id", "amount", "measure_unit_id", "modifier", "gram_weight", "portion_description"], low_memory=False)
    measure_df = pd.read_csv(os.path.join(CSV_DIR, "measure_unit.csv"), usecols=["id", "name"]).rename(columns={"id": "measure_unit_id", "name": "unit_name"})
    nutrient_df = pd.read_csv(os.path.join(CSV_DIR, "food_nutrient.csv"), usecols=["fdc_id", "nutrient_id", "amount"], low_memory=False)

    print("2. Processing macros per 100g...")
    MACRO_MAP = {
        1008: "calories",
        2047: "calories_atw_gen",
        2048: "calories_atw_spec",
        1003: "protein_g",
        1053: "protein_g_adj",
        1004: "fat_g",
        1085: "fat_g_nlea",
        1005: "carbs_g",
        1050: "carbs_g_sum",
        2039: "carbs_g_tot",
        1079: "fiber_g",
        2033: "fiber_g_aoac"
    }

    # Filter only for macro nutrient rows and map names
    macros_only = nutrient_df[nutrient_df["nutrient_id"].isin(MACRO_MAP.keys())].copy()
    macros_only["macro_name"] = macros_only["nutrient_id"].map(MACRO_MAP)

    macros_pivoted = macros_only.pivot_table(
        index="fdc_id", 
        columns="macro_name", 
        values="amount", 
        aggfunc="first"
    ).reset_index().fillna(0.0)

    # Merge food description with its macro profile
    foods_clean = food_df.merge(macros_pivoted, on="fdc_id", how="inner")

    # Combine fallbacks
    def resolve_calories(row):
        for col in ["calories", "calories_atw_spec", "calories_atw_gen"]:
            if col in row and row[col] > 0:
                return float(row[col])
        p = float(row.get("protein_g", 0) or 0)
        c = float(row.get("carbs_g", 0) or 0)
        f = float(row.get("fat_g", 0) or 0)
        return round((p * 4.0) + (c * 4.0) + (f * 9.0), 1)

    def resolve_col(row, primary_col, fallback_cols):
        val = row.get(primary_col, 0)
        if val > 0:
            return round(float(val), 2)
        for fb in fallback_cols:
            if fb in row and row[fb] > 0:
                return round(float(row[fb]), 2)
        return 0.0

    foods_clean["calories"] = foods_clean.apply(resolve_calories, axis=1)
    foods_clean["protein_g"] = foods_clean.apply(lambda r: resolve_col(r, "protein_g", ["protein_g_adj"]), axis=1)
    foods_clean["fat_g"] = foods_clean.apply(lambda r: resolve_col(r, "fat_g", ["fat_g_nlea"]), axis=1)
    foods_clean["carbs_g"] = foods_clean.apply(lambda r: resolve_col(r, "carbs_g", ["carbs_g_sum", "carbs_g_tot"]), axis=1)
    foods_clean["fiber_g"] = foods_clean.apply(lambda r: resolve_col(r, "fiber_g", ["fiber_g_aoac"]), axis=1)

    # Keep only final columns
    foods_final = foods_clean[["fdc_id", "description", "data_type", "calories", "protein_g", "fat_g", "carbs_g", "fiber_g"]]

    print("3. Processing portion conversion weights...")
    portions_clean = portion_df.merge(measure_df, on="measure_unit_id", how="left")

    def format_label(row):
        parts = []
        if pd.notna(row["amount"]) and row["amount"] > 0:
            parts.append(f"{row['amount']:g}")
        if pd.notna(row["unit_name"]) and str(row["unit_name"]).strip() not in ["undetermined", "", "nan"]:
            parts.append(str(row["unit_name"]))
        if pd.notna(row["modifier"]) and str(row["modifier"]).strip() not in ["nan", ""]:
            parts.append(str(row["modifier"]))
        elif pd.notna(row["portion_description"]) and str(row["portion_description"]).strip() not in ["nan", ""]:
            parts.append(str(row["portion_description"]))
        return " ".join(parts).strip()

    portions_clean["portion_name"] = portions_clean.apply(format_label, axis=1)
    portions_final = portions_clean[["fdc_id", "portion_name", "gram_weight"]].dropna(subset=["gram_weight"])

    print(f"4. Writing to SQLite ({DB_PATH})...")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    foods_final.to_sql("foods", conn, if_exists="replace", index=False)
    portions_final.to_sql("portions", conn, if_exists="replace", index=False)

    # Add indexes for high-speed queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_foods_fdc_id ON foods(fdc_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_foods_desc ON foods(description);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_portions_fdc ON portions(fdc_id);")

    # Create FTS5 virtual table for fast full-text search
    try:
        conn.execute("DROP TABLE IF EXISTS foods_fts;")
        conn.execute("CREATE VIRTUAL TABLE foods_fts USING fts5(fdc_id UNINDEXED, description, tokenize='unicode61 remove_diacritics 1');")
        conn.execute("INSERT INTO foods_fts (fdc_id, description) SELECT fdc_id, description FROM foods;")
    except Exception as e:
        print("Note on FTS5 creation:", e)

    conn.commit()

    food_count = conn.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
    portion_count = conn.execute("SELECT COUNT(*) FROM portions").fetchone()[0]
    print(f"[OK] Database ready: {DB_PATH}")
    print(f"  - {food_count} USDA foods with macronutrients")
    print(f"  - {portion_count} household portion conversion rules")

    conn.close()

if __name__ == "__main__":
    build_db()
