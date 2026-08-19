#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_ciqual_to_postgres.py - Seed PostgreSQL foods table with curated CIQUAL dataset.

Downloads / uses the CIQUAL SQLite database (via ciqual-mcp data_loader)
and populates the PostgreSQL `foods` table with all 3,484+ foods and their macros.

Usage:
    python scripts/seed_ciqual_to_postgres.py
"""

import os
import sys
import sqlite3

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)

try:
    import data_loader
except ImportError:
    user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python313\\site-packages")
    if os.path.exists(user_site):
        sys.path.insert(0, user_site)
        try:
            import data_loader
        except ImportError:
            data_loader = None
    else:
        data_loader = None

for env_file in (".env.local", ".env"):
    p = os.path.join(base_dir, env_file)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def ensure_ciqual_db():
    db_path = os.path.expanduser("~/.ciqual/ciqual.db")
    if not os.path.exists(db_path):
        print("CIQUAL SQLite database not found. Initializing via data_loader...")
        if data_loader is None:
            raise RuntimeError("ciqual-mcp package is not installed. Please run: pip install ciqual-mcp")
        data_loader.initialize_database(force_update=True)
    return db_path


def extract_ciqual_foods(sqlite_path):
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    cur = conn.cursor()

    query = """
    SELECT 
        f.alim_code,
        TRIM(f.alim_nom_eng) as name_en,
        TRIM(f.alim_nom_fr) as name_fr,
        COALESCE(MAX(CASE WHEN c.const_code = 25000 THEN c.teneur WHEN c.const_code = 25003 THEN c.teneur END), 0) as protein_g,
        COALESCE(MAX(CASE WHEN c.const_code = 31000 THEN c.teneur END), 0) as carbs_g,
        COALESCE(MAX(CASE WHEN c.const_code = 40000 THEN c.teneur END), 0) as fat_g,
        COALESCE(MAX(CASE WHEN c.const_code = 328 THEN c.teneur WHEN c.const_code = 333 THEN c.teneur END), 0) as energy_kcal
    FROM foods f
    LEFT JOIN composition c ON f.alim_code = c.alim_code
    WHERE f.alim_nom_eng IS NOT NULL AND TRIM(f.alim_nom_eng) != ''
    GROUP BY f.alim_code, f.alim_nom_eng, f.alim_nom_fr;
    """

    foods = []
    for row in cur.execute(query):
        alim_code, name_en, name_fr, protein, carbs, fat, kcal = row
        protein = round(float(protein or 0), 2)
        carbs = round(float(carbs or 0), 2)
        fat = round(float(fat or 0), 2)
        kcal = round(float(kcal or 0), 1)

        # Fallback Atwater calculation if energy_kcal is 0
        if kcal <= 0:
            kcal = round((protein * 4.0) + (carbs * 4.0) + (fat * 9.0), 1)

        foods.append({
            "id": f"ciqual_{alim_code}",
            "name": name_en,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
            "energy_kcal": kcal,
            "serving": "100g"
        })

    conn.close()
    return foods


def export_sql_dump(foods, output_path):
    """Write an SQL insert file that Docker or psql can load directly."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("-- Auto-generated CIQUAL foods seed for Grams PostgreSQL\n")
        f.write("TRUNCATE TABLE public.foods;\n\n")
        f.write("INSERT INTO public.foods (id, name, protein_g, carbs_g, fat_g, energy_kcal, serving) VALUES\n")
        lines = []
        for food in foods:
            name_escaped = food["name"].replace("'", "''")
            fid = food["id"]
            p = food["protein_g"]
            c = food["carbs_g"]
            fat = food["fat_g"]
            kcal = food["energy_kcal"]
            srv = food["serving"]
            lines.append(f"('{fid}', '{name_escaped}', {p}, {c}, {fat}, {kcal}, '{srv}')")
        f.write(",\n".join(lines))
        f.write("\nON CONFLICT (id) DO UPDATE SET\n")
        f.write("  name=EXCLUDED.name,\n")
        f.write("  protein_g=EXCLUDED.protein_g,\n")
        f.write("  carbs_g=EXCLUDED.carbs_g,\n")
        f.write("  fat_g=EXCLUDED.fat_g,\n")
        f.write("  energy_kcal=EXCLUDED.energy_kcal,\n")
        f.write("  serving=EXCLUDED.serving;\n")
    print(f"[OK] Generated SQL seed: {output_path} ({len(foods)} items)")


def seed_postgres(foods):
    try:
        import psycopg2
    except ImportError:
        print("psycopg2-binary not installed. Skipping direct DB connection (SQL dump generated).")
        return

    database_url = os.environ.get("DATABASE_URL")
    try:
        if database_url:
            pg = psycopg2.connect(database_url)
        else:
            pg = psycopg2.connect(
                host=os.environ.get("PG_HOST", "localhost"),
                port=int(os.environ.get("PG_PORT", 5432)),
                dbname=os.environ.get("PG_DB", "grams"),
                user=os.environ.get("PG_USER", "grams"),
                password=os.environ.get("PG_PASSWORD", "grams"),
            )
    except Exception as e:
        print(f"Could not connect to PostgreSQL ({e}). SQL seed file was created for Docker startup.")
        return

    print("Connected to PostgreSQL. Clearing and inserting CIQUAL foods...")
    with pg:
        with pg.cursor() as cur:
            cur.execute("TRUNCATE TABLE foods;")
            inserted = 0
            for f in foods:
                cur.execute(
                    """
                    INSERT INTO foods (id, name, protein_g, carbs_g, fat_g, energy_kcal, serving)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        protein_g = EXCLUDED.protein_g,
                        carbs_g = EXCLUDED.carbs_g,
                        fat_g = EXCLUDED.fat_g,
                        energy_kcal = EXCLUDED.energy_kcal,
                        serving = EXCLUDED.serving;
                    """,
                    (f["id"], f["name"], f["protein_g"], f["carbs_g"], f["fat_g"], f["energy_kcal"], f["serving"])
                )
                inserted += 1

    pg.close()
    print(f"[OK] Successfully seeded {inserted} CIQUAL foods into PostgreSQL!")


if __name__ == "__main__":
    print("=" * 60)
    print("Grams - CIQUAL Dataset Seeder for PostgreSQL")
    print("=" * 60)

    db_path = ensure_ciqual_db()
    print(f"Using CIQUAL database from: {db_path}")

    foods = extract_ciqual_foods(db_path)
    print(f"Extracted {len(foods)} curated whole foods from CIQUAL.")

    sql_path = os.path.join(base_dir, "database", "ciqual_foods_seed.sql")
    export_sql_dump(foods, sql_path)

    seed_postgres(foods)

    print("\nCIQUAL whole foods setup complete!")
