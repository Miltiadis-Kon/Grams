#!/usr/bin/env python3
"""
migrate_from_supabase.py — One-time data migration from Supabase → local PostgreSQL.

Usage:
    # 1. Make sure Docker Compose is running:
    #    docker compose up -d postgres
    #
    # 2. Run this script with your OLD Supabase credentials:
    #    python scripts/migrate_from_supabase.py
    #
    # The script reads SUPABASE_URL and SUPABASE_KEY from .env (old file)
    # and writes to the local PostgreSQL defined in .env.local

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""

import json
import os
import sys

# Load .env (old Supabase creds)
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(base_dir, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Load .env.local (new PG creds)
env_local = os.path.join(base_dir, ".env.local")
if os.path.exists(env_local):
    with open(env_local) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ── Supabase source ───────────────────────────────────────────
try:
    from supabase import create_client
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env")
        sys.exit(1)
    sb = create_client(supabase_url, supabase_key)
    print(f"✓ Connected to Supabase: {supabase_url}")
except ImportError:
    print("ERROR: supabase package not installed. Run: pip install supabase")
    sys.exit(1)

# ── PostgreSQL destination ────────────────────────────────────
try:
    import psycopg2
    import psycopg2.extras

    database_url = os.environ.get("DATABASE_URL")
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
    print("✓ Connected to local PostgreSQL")
except Exception as e:
    print(f"ERROR: Cannot connect to PostgreSQL: {e}")
    print("Make sure `docker compose up -d postgres` is running.")
    sys.exit(1)


def migrate_recipes_table(sb_table: str, pg_table: str):
    """Migrate all rows from a Supabase recipes-style table to local PostgreSQL."""
    print(f"\n── Migrating {sb_table} → {pg_table} ──")

    # Fetch all rows from Supabase (paginated in batches of 1000)
    all_rows = []
    offset = 0
    batch = 1000
    while True:
        resp = sb.table(sb_table).select("*").range(offset, offset + batch - 1).execute()
        rows = resp.data or []
        all_rows.extend(rows)
        print(f"  Fetched {len(all_rows)} rows so far...")
        if len(rows) < batch:
            break
        offset += batch

    print(f"  Total rows to migrate: {len(all_rows)}")

    inserted = 0
    skipped = 0
    with pg:
        with pg.cursor() as cur:
            for row in all_rows:
                try:
                    cur.execute(
                        f"""
                        INSERT INTO {pg_table}
                            (recipe_id, name, url, description, macros, ingredients, instructions, tags, added_on)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                        ON CONFLICT (recipe_id) DO NOTHING
                        """,
                        (
                            row.get("recipe_id"),
                            row.get("name"),
                            row.get("url"),
                            row.get("description"),
                            json.dumps(row.get("macros") or {}),
                            json.dumps(row.get("ingredients") or []),
                            json.dumps(row.get("instructions") or []),
                            json.dumps(row.get("tags") or []),
                            row.get("added_on"),
                        )
                    )
                    inserted += 1
                except Exception as e:
                    print(f"  WARN: Skipped row {row.get('recipe_id')}: {e}")
                    skipped += 1

    print(f"  ✓ Inserted: {inserted}, Skipped (duplicates/errors): {skipped}")


def migrate_foods_table():
    """Migrate all rows from the Supabase foods table to local PostgreSQL."""
    print(f"\n── Migrating foods ──")

    all_rows = []
    offset = 0
    batch = 1000
    while True:
        resp = sb.table("foods").select("*").range(offset, offset + batch - 1).execute()
        rows = resp.data or []
        all_rows.extend(rows)
        print(f"  Fetched {len(all_rows)} rows so far...")
        if len(rows) < batch:
            break
        offset += batch

    print(f"  Total food rows to migrate: {len(all_rows)}")

    inserted = 0
    skipped = 0
    with pg:
        with pg.cursor() as cur:
            for row in all_rows:
                try:
                    cur.execute(
                        """
                        INSERT INTO foods (id, name, protein_g, carbs_g, fat_g, energy_kcal, serving)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            row.get("id"),
                            row.get("name"),
                            row.get("protein_g") or 0,
                            row.get("carbs_g") or 0,
                            row.get("fat_g") or 0,
                            row.get("energy_kcal") or 0,
                            row.get("serving"),
                        )
                    )
                    inserted += 1
                except Exception as e:
                    print(f"  WARN: Skipped food row {row.get('id')}: {e}")
                    skipped += 1

    print(f"  ✓ Inserted: {inserted}, Skipped (duplicates/errors): {skipped}")


if __name__ == "__main__":
    print("=" * 60)
    print("Grams - Supabase -> Local PostgreSQL Migration")
    print("=" * 60)

    migrate_recipes_table("recipes", "recipes")
    migrate_recipes_table("not_added_recipes", "not_added_recipes")

    # Only migrate old foods table if explicitly requested with --include-old-foods
    if "--include-old-foods" in sys.argv:
        migrate_foods_table()
    else:
        print("\nNote: Skipping legacy foods table (using curated CIQUAL foods table instead).")
        print("To seed CIQUAL foods, run: python scripts/seed_ciqual_to_postgres.py")

    pg.close()
    print("\n[OK] Migration complete!")
    print("You can now run `docker compose up` and your data will be available locally.")
