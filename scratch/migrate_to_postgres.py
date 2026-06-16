import os
import json
import logging
import psycopg2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate_to_postgres")

def migrate():
    # Load environment variables from .env if it exists
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL is not set in the environment. Migration cannot run.")
        logger.info("To run locally, set DATABASE_URL=postgresql://user:password@localhost/dbname")
        return
        
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    logger.info("Connecting to PostgreSQL database...")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # 1. Create tables
            for table_name in ["recipes", "not_added_recipes"]:
                logger.info(f"Creating/verifying table: {table_name}")
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        recipe_id VARCHAR PRIMARY KEY,
                        name VARCHAR,
                        url VARCHAR,
                        description TEXT,
                        macros JSONB,
                        ingredients JSONB,
                        tags JSONB,
                        added_on VARCHAR,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            conn.commit()
            
            # 2. Load and migrate recipes_db.json
            recipes_path = "database/recipes_db.json"
            if os.path.exists(recipes_path):
                logger.info(f"Reading {recipes_path}...")
                with open(recipes_path, "r", encoding="utf-8") as f:
                    recipes = json.load(f)
                
                logger.info(f"Migrating {len(recipes)} recipes to 'recipes' table...")
                for recipe_id, r in recipes.items():
                    cur.execute(
                        """
                        INSERT INTO recipes (recipe_id, name, url, description, macros, ingredients, tags, added_on)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (recipe_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            url = EXCLUDED.url,
                            description = EXCLUDED.description,
                            macros = EXCLUDED.macros,
                            ingredients = EXCLUDED.ingredients,
                            tags = EXCLUDED.tags,
                            added_on = EXCLUDED.added_on,
                            updated_at = CURRENT_TIMESTAMP;
                        """,
                        (
                            recipe_id,
                            r.get("name"),
                            r.get("url"),
                            r.get("description"),
                            json.dumps(r.get("macros", {})),
                            json.dumps(r.get("ingredients", [])),
                            json.dumps(r.get("tags", [])),
                            r.get("added_on")
                        )
                    )
                conn.commit()
                logger.info("Main recipes migration complete.")
            else:
                logger.warning(f"File {recipes_path} not found. Skipping main recipes migration.")
                
            # 3. Load and migrate not_added_recipes.json
            not_added_path = "database/not_added_recipes.json"
            if os.path.exists(not_added_path):
                logger.info(f"Reading {not_added_path}...")
                with open(not_added_path, "r", encoding="utf-8") as f:
                    not_added = json.load(f)
                
                logger.info(f"Migrating {len(not_added)} recipes to 'not_added_recipes' table...")
                for recipe_id, r in not_added.items():
                    cur.execute(
                        """
                        INSERT INTO not_added_recipes (recipe_id, name, url, description, macros, ingredients, tags, added_on)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (recipe_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            url = EXCLUDED.url,
                            description = EXCLUDED.description,
                            macros = EXCLUDED.macros,
                            ingredients = EXCLUDED.ingredients,
                            tags = EXCLUDED.tags,
                            added_on = EXCLUDED.added_on,
                            updated_at = CURRENT_TIMESTAMP;
                        """,
                        (
                            recipe_id,
                            r.get("name"),
                            r.get("url"),
                            r.get("description"),
                            json.dumps(r.get("macros", {})),
                            json.dumps(r.get("ingredients", [])),
                            json.dumps(r.get("tags", [])),
                            r.get("added_on")
                        )
                    )
                conn.commit()
                logger.info("Not-added recipes migration complete.")
            else:
                logger.warning(f"File {not_added_path} not found. Skipping not-added migration.")
                
        logger.info("PostgreSQL Database migration finished successfully!")
    except Exception as exc:
        conn.rollback()
        logger.error(f"Migration failed: {exc}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
