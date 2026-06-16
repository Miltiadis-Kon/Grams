"""
Persistent PostgreSQL database engine for recipe records.

Provides O(1) lookups, SQL transactions, and PostgreSQL storage.
Requires DATABASE_URL to be configured in the environment.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Optional

from .models import Recipe

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class RecipeDatabase:
    """
    Thread-safe, PostgreSQL-only database.
    """

    def __init__(self, db_path: str) -> None:
        # DB path is kept for signature compatibility but unused for JSON storage
        self._db_path = db_path
        self._lock = threading.Lock()
        
        # Detect environment database configuration
        self._db_url = os.environ.get("DATABASE_URL")
        if not self._db_url:
            raise ValueError(
                "DATABASE_URL environment variable is missing! PostgreSQL database is required.\n"
                "Please enable/provision the Replit Database or specify DATABASE_URL in your .env file."
            )
        
        # Map table name based on filepath/identifier
        if "not_added_recipes" in db_path:
            self._table_name = "not_added_recipes"
        else:
            self._table_name = "recipes"
            
        logger.info("Initializing RecipeDatabase with PostgreSQL backend for table: %s", self._table_name)
        self._init_db()

    # ── Database Connection ──────────────────────────

    def _get_conn(self):
        if not HAS_PSYCOPG2:
            raise ImportError(
                "DATABASE_URL is configured, but psycopg2 is not installed. "
                "Please run `pip install psycopg2-binary` to enable the PostgreSQL backend."
            )
        url = self._db_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)

    def _init_db(self) -> None:
        """Ensure PostgreSQL table exists."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self._table_name} (
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
            logger.info("Ensured PostgreSQL table '%s' is created", self._table_name)
        except Exception as exc:
            logger.error("Failed to initialize PostgreSQL database: %s", exc)
            raise
        finally:
            conn.close()

    def _row_to_dict(self, row) -> dict:
        """Convert a SQL Row into canonical recipe JSON structure."""
        return {
            "name": row["name"],
            "url": row["url"],
            "description": row["description"],
            "macros": row["macros"],
            "ingredients": row["ingredients"],
            "tags": row["tags"],
            "added_on": row["added_on"],
        }

    # ── Public API ───────────────────────────────────

    def exists(self, recipe_id: str) -> bool:
        """O(1) check whether a recipe ID is already stored."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM {self._table_name} WHERE recipe_id = %s LIMIT 1;", (recipe_id,))
                return cur.fetchone() is not None
        except Exception as exc:
            logger.error("PostgreSQL exists() query failed: %s", exc)
            return False
        finally:
            conn.close()

    def insert(self, recipe_id: str, recipe: Recipe | dict) -> None:
        """
        Insert a new recipe record and persist.
        """
        recipe_dict = recipe.to_dict() if hasattr(recipe, "to_dict") else recipe

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                # Check existence
                cur.execute(f"SELECT 1 FROM {self._table_name} WHERE recipe_id = %s LIMIT 1;", (recipe_id,))
                if cur.fetchone() is not None:
                    raise ValueError(f"Recipe '{recipe_id}' already exists in database")

                cur.execute(
                    f"""
                    INSERT INTO {self._table_name} (recipe_id, name, url, description, macros, ingredients, tags, added_on)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        recipe_id,
                        recipe_dict.get("name"),
                        recipe_dict.get("url"),
                        recipe_dict.get("description"),
                        json.dumps(recipe_dict.get("macros", {})),
                        json.dumps(recipe_dict.get("ingredients", [])),
                        json.dumps(recipe_dict.get("tags", [])),
                        recipe_dict.get("added_on")
                    )
                )
            conn.commit()
            logger.info("Inserted recipe '%s' to PostgreSQL table '%s'", recipe_id, self._table_name)
        finally:
            conn.close()

    def update(self, recipe_id: str, recipe_data: dict) -> None:
        """
        Update an existing recipe record and persist.
        """
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {self._table_name}
                    SET name = %s, url = %s, description = %s, macros = %s, ingredients = %s, tags = %s, added_on = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE recipe_id = %s;
                    """,
                    (
                        recipe_data.get("name"),
                        recipe_data.get("url"),
                        recipe_data.get("description"),
                        json.dumps(recipe_data.get("macros", {})),
                        json.dumps(recipe_data.get("ingredients", [])),
                        json.dumps(recipe_data.get("tags", [])),
                        recipe_data.get("added_on"),
                        recipe_id
                    )
                )
            conn.commit()
            logger.info("Updated recipe '%s' in PostgreSQL table '%s'", recipe_id, self._table_name)
        finally:
            conn.close()

    def get(self, recipe_id: str) -> Optional[dict]:
        """Retrieve a single recipe by its ID, or None if not found."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT * FROM {self._table_name} WHERE recipe_id = %s LIMIT 1;", (recipe_id,))
                row = cur.fetchone()
                if row:
                    return self._row_to_dict(row)
                return None
        except Exception as exc:
            logger.error("PostgreSQL get() query failed: %s", exc)
            return None
        finally:
            conn.close()

    def get_all(self) -> dict[str, dict]:
        """Return the entire recipe collection."""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT * FROM {self._table_name};")
                rows = cur.fetchall()
                return {row["recipe_id"]: self._row_to_dict(row) for row in rows}
        except Exception as exc:
            logger.error("PostgreSQL get_all() query failed: %s", exc)
            return {}
        finally:
            conn.close()

    def count(self) -> int:
        """Return the number of stored recipes."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {self._table_name};")
                return cur.fetchone()[0]
        except Exception as exc:
            logger.error("PostgreSQL count() query failed: %s", exc)
            return 0
        finally:
            conn.close()

    def delete(self, recipe_id: str) -> bool:
        """Remove a recipe by its ID from the database. Returns True if removed, False otherwise."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self._table_name} WHERE recipe_id = %s;", (recipe_id,))
                deleted = cur.rowcount > 0
            conn.commit()
            if deleted:
                logger.info("Deleted recipe '%s' from PostgreSQL table '%s'", recipe_id, self._table_name)
            return deleted
        except Exception as exc:
            logger.error("PostgreSQL delete() query failed: %s", exc)
            return False
        finally:
            conn.close()

    def __repr__(self) -> str:
        return f"<RecipeDatabase backend=PostgreSQL table={self._table_name}>"
