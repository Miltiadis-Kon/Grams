"""
Nutritional analysis module using the OpenNutrition dataset in a local PostgreSQL database.

Requires DATABASE_URL or PG_* environment variables to be configured.
"""

from __future__ import annotations

import json
import logging
import os
import re
import concurrent.futures
from typing import Optional
from functools import lru_cache

from translate import Translator
from ingredient_parser import parse_ingredient
import psycopg2
import psycopg2.extras

from database import MacroNutrients

logger = logging.getLogger(__name__)


def _get_pg_connection():
    """Create a new psycopg2 connection from environment variables."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ.get("PG_DB", "grams"),
        user=os.environ.get("PG_USER", "grams"),
        password=os.environ.get("PG_PASSWORD", "grams"),
    )


class NutritionAnalyzer:
    """
    Nutritional analysis engine backed by USDA FoodData Central (SQLite) and PostgreSQL.
    """

    def __init__(self) -> None:
        self._pg_available = False
        try:
            conn = _get_pg_connection()
            conn.close()
            self._pg_available = True
            logger.info("NutritionAnalyzer connected to PostgreSQL.")
        except Exception as exc:
            logger.info("PostgreSQL not active for NutritionAnalyzer — using local USDA SQLite database.")

    def _query_foods(self, sql: str, params: tuple) -> list[dict]:
        """Execute a foods query and return list of row dicts."""
        if not getattr(self, "_pg_available", False):
            return []
        conn = None
        try:
            conn = _get_pg_connection()
            with conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning("foods query failed: %s | SQL: %s", exc, sql)
            return []
        finally:
            if conn:
                conn.close()

    def _upsert_food(self, data: dict) -> None:
        """Upsert a food row (for barcode lookups)."""
        if not getattr(self, "_pg_available", False):
            return
        conn = None
        try:
            conn = _get_pg_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO foods (id, name, protein_g, carbs_g, fat_g, energy_kcal, serving)
                        VALUES (%(id)s, %(name)s, %(protein_g)s, %(carbs_g)s, %(fat_g)s, %(energy_kcal)s, %(serving)s)
                        ON CONFLICT (id) DO UPDATE SET
                            name=EXCLUDED.name,
                            protein_g=EXCLUDED.protein_g,
                            carbs_g=EXCLUDED.carbs_g,
                            fat_g=EXCLUDED.fat_g,
                            energy_kcal=EXCLUDED.energy_kcal,
                            serving=EXCLUDED.serving
                        """,
                        data
                    )
        except Exception as exc:
            logger.error("upsert_food failed: %s", exc)
        finally:
            if conn:
                conn.close()

    # ── Public API ───────────────────────────────────

    def _translate_if_greek(self, text: str) -> str:
        """Translate text to English if it contains Greek characters."""
        if not text:
            return text
        # Detect Greek characters
        if re.search(r'[\u0370-\u03ff\u1f00-\u1fff]', text):
            try:
                if not hasattr(self, '_translator'):
                    self._translator = Translator(from_lang="el", to_lang="en")
                if not hasattr(self, '_translation_cache'):
                    self._translation_cache = {}
                
                cleaned_text = text.strip().lower()
                if cleaned_text in self._translation_cache:
                    return self._translation_cache[cleaned_text]
                
                translated = self._translator.translate(text)
                if translated and "mymemory warning" in translated.lower():
                    logger.warning("MyMemory translation limit warning encountered for '%s': %s", text, translated)
                    return text  # fallback to original Greek text
                
                logger.info("Translated Greek ingredient '%s' to English '%s'", text, translated)
                self._translation_cache[cleaned_text] = translated
                return translated
            except Exception as exc:
                logger.warning("Translation failed for '%s': %s", text, exc)
        return text

    def _query_usda_sqlite(self, query_en: str) -> Optional[dict]:
        """Search the local USDA FoodData Central SQLite database (nutrition.db)."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "nutrition.db")
        if not os.path.exists(db_path):
            return None
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()

            # 1. Try exact description match
            row = cur.execute(
                "SELECT fdc_id, description, calories, protein_g, fat_g, carbs_g, fiber_g FROM foods WHERE description = ? LIMIT 1",
                (query_en,)
            ).fetchone()

            # 2. Try FTS match
            if not row:
                sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', query_en).strip()
                search_words = [w for w in sanitized.split() if len(w) > 1]
                if search_words:
                    fts_query = " ".join([f'"{w}"*' for w in search_words])
                    try:
                        row = cur.execute("""
                            SELECT f.fdc_id, f.description, f.calories, f.protein_g, f.fat_g, f.carbs_g, f.fiber_g 
                            FROM foods_fts fts
                            JOIN foods f ON fts.fdc_id = f.fdc_id
                            WHERE foods_fts MATCH ?
                            ORDER BY CASE WHEN f.data_type = 'foundation_food' THEN 0 ELSE 1 END, LENGTH(f.description) ASC
                            LIMIT 1
                        """, (fts_query,)).fetchone()
                    except Exception:
                        pass

            # 3. Try LIKE substring match
            if not row:
                row = cur.execute("""
                    SELECT fdc_id, description, calories, protein_g, fat_g, carbs_g, fiber_g 
                    FROM foods 
                    WHERE description LIKE ? 
                    ORDER BY CASE WHEN data_type = 'foundation_food' THEN 0 ELSE 1 END, LENGTH(description) ASC
                    LIMIT 1
                """, (f"%{query_en}%",)).fetchone()

            if not row:
                conn.close()
                return None

            fdc_id, name, kcal, p, f, c, fib = row

            if (kcal is None or kcal <= 0) and (p > 0 or f > 0 or c > 0):
                kcal = round((p * 4.0) + (c * 4.0) + (f * 9.0), 1)

            # Get portions
            portions_rows = cur.execute("SELECT portion_name, gram_weight FROM portions WHERE fdc_id = ?", (fdc_id,)).fetchall()
            conn.close()

            portions_dict = {p_name: weight for p_name, weight in portions_rows}
            return {
                "id": f"usda_{fdc_id}",
                "name": name,
                "protein_g": p,
                "fat_g": f,
                "carbs_g": c,
                "energy_kcal": kcal,
                "fiber_g": fib,
                "serving": json.dumps({"portions": portions_dict}) if portions_dict else "100g",
                "available_portions": portions_dict
            }
        except Exception as e:
            logger.debug("USDA SQLite query error: %s", e)
            return None

    @lru_cache(maxsize=2048)
    def lookup_food(self, query: str, ing_hash: str = None) -> Optional[MacroNutrients]:
        """
        Search the USDA database (nutrition.db) or PostgreSQL foods table for a food item by name or hash.

        Returns the top match's macros, or None if no match found.
        """
        # Translate Greek queries to English first so they can match the English foods DB
        query_en = self._translate_if_greek(query)

        # 1. Search USDA FoodData Central dataset first
        usda_row = self._query_usda_sqlite(query_en)
        if usda_row:
            return self._row_to_macros(usda_row, query_en, query)

        _SQL = "SELECT id, name, protein_g, carbs_g, fat_g, energy_kcal, serving FROM foods"

        # 0. Try ID exact match if hash is provided
        if ing_hash:
            rows = self._query_foods(f"{_SQL} WHERE id = %s LIMIT 1", (ing_hash,))
            if rows:
                row = rows[0]
                return self._row_to_macros(row, row["name"], query)

        sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', query_en)
        sanitized = ' '.join(sanitized.split()).strip()
        if not sanitized or not re.search(r'[a-zA-Z]', sanitized):
            return None

        # 2. Try PostgreSQL exact match
        rows = self._query_foods(f"{_SQL} WHERE name = %s LIMIT 1", (query_en,))
        if rows:
            return self._row_to_macros(rows[0], query_en, query)

        # 3. Try full-text search (PostgreSQL tsvector)
        search_words = [w for w in sanitized.split() if w]
        fts_query = " & ".join(search_words)
        rows = self._query_foods(
            f"{_SQL} WHERE to_tsvector('english', name) @@ to_tsquery('english', %s) LIMIT 1",
            (fts_query,)
        )
        if rows:
            return self._row_to_macros(rows[0], query_en, query)

        # 4. Fallback to ILIKE substring matching
        rows = self._query_foods(f"{_SQL} WHERE name ILIKE %s LIMIT 1", (f"%{sanitized}%",))
        if rows:
            return self._row_to_macros(rows[0], query_en, query)

        # 5. Fallback: try removing the first word (e.g. 'potato gnocchi' -> 'gnocchi')
        words = sanitized.split()
        if len(words) > 1:
            fallback_query = " ".join(words[1:])
            usda_fb = self._query_usda_sqlite(fallback_query)
            if usda_fb:
                return self._row_to_macros(usda_fb, fallback_query, query)

            rows = self._query_foods(f"{_SQL} WHERE name = %s LIMIT 1", (fallback_query,))
            if rows:
                return self._row_to_macros(rows[0], fallback_query, query)

        return None

    def _row_to_macros(self, row: dict, query_en: str, query_orig: str) -> MacroNutrients:
        protein = float(row.get("protein_g") or 0.0)
        carbs = float(row.get("carbs_g") or 0.0)
        fat = float(row.get("fat_g") or 0.0)
        energy = float(row.get("energy_kcal") or 0.0)
        serving = row.get("serving")
        food_id = row.get("id")
        food_name = row.get("name")
        
        macros = MacroNutrients(
            protein=protein,
            carbs=carbs,
            fats=fat,
            calories=int(round(energy)),
            serving=serving,
            food_id=food_id,
            food_name=food_name
        )
        logger.debug("Matched '%s' (translated from '%s') → P:%.1f C:%.1f F:%.1f Cal:%d",
                     query_en, query_orig, protein, carbs, fat, energy)
        return macros

    def _extract_explicit_macros(self, description: str) -> Optional[MacroNutrients]:
        """Attempt to extract explicit macro-nutrients from text using regex patterns."""
        if not description:
            return None

        desc_clean = description.replace('\xa0', ' ')

        cal_patterns = [
            r'(?:calories|cal|kcal|energy|θερμίδες|θερμιδες)[:\-\s]*(\d+)',
            r'(\d+)\s*(?:calories|cal|kcal|energy|θερμίδες|θερμιδες)'
        ]
        calories = None
        for pat in cal_patterns:
            m = re.search(pat, desc_clean, re.IGNORECASE)
            if m:
                calories = int(m.group(1))
                break

        prot_patterns = [
            r'(?:protein|prot|πρωτεΐνη|πρωτεΐνης|πρωτεινη|πρωτεινης)[:\-\s]*(\d+(?:\.\d+)?)g?\b',
            r'(\d+(?:\.\d+)?)\s*(?:g|γρ|γραμμάρια|γραμμαρια)?\s*(?:protein|prot|πρωτεΐνη|πρωτεΐνης|πρωτεινη|πρωτεινης)\b'
        ]
        protein = None
        for pat in prot_patterns:
            m = re.search(pat, desc_clean, re.IGNORECASE)
            if m:
                protein = float(m.group(1))
                break

        carb_patterns = [
            r'(?:carbs|carb|carbohydrates|carbohydrate|υδατάνθρακες|υδατανθρακες)[:\-\s]*(\d+(?:\.\d+)?)g?\b',
            r'(\d+(?:\.\d+)?)\s*(?:g|γρ|γραμμάρια|γραμμαρια)?\s*(?:carbs|carb|carbohydrates|carbohydrate|υδατάνθρακες|υδατανθρακες)\b'
        ]
        carbs = None
        for pat in carb_patterns:
            m = re.search(pat, desc_clean, re.IGNORECASE)
            if m:
                carbs = float(m.group(1))
                break

        fat_patterns = [
            r'(?:fats|fat|lipid|lipids|λίπη|λιπαρά|λιπαρα|λιπος)[:\-\s]*(\d+(?:\.\d+)?)g?\b',
            r'(\d+(?:\.\d+)?)\s*(?:g|γρ|γραμμάρια|γραμμαρια)?\s*(?:fats|fat|lipid|lipids|λίπη|λιπαρά|λιπαρα|λιπος)\b'
        ]
        fats = None
        for pat in fat_patterns:
            m = re.search(pat, desc_clean, re.IGNORECASE)
            if m:
                fats = float(m.group(1))
                break

        if calories is not None or protein is not None or carbs is not None or fats is not None:
            return MacroNutrients(
                protein=protein or 0.0,
                carbs=carbs or 0.0,
                fats=fats or 0.0,
                calories=calories or 0
            )
        return None

    def analyze_ingredients(self, ingredients: list[dict[str, str]], description_for_servings: str = "") -> MacroNutrients:
        """
        Calculate total macros for a structured list of ingredients using OpenNutrition DB.
        Each ingredient is a dict with 'name' and 'quantity'.
        """
        # First, try to extract explicit macros if they are in the description
        explicit = self._extract_explicit_macros(description_for_servings)
        if explicit:
            logger.info("Using explicit macros extracted from description/transcript.")
            return explicit

        total = MacroNutrients()
        matches = 0

        def process_ing(ing):
            name_str = (ing.get("name") or "").strip()
            qty_str = (ing.get("quantity") or "").strip()
            ing_hash = (ing.get("hash") or "").strip()
            if not name_str:
                return None

            # Parse quantity and name combined to retrieve amount object
            sentence = f"{qty_str} {name_str}".strip()
            try:
                result = parse_ingredient(sentence)
                amount_obj = result.amount[0] if result.amount else None
            except Exception:
                amount_obj = None

            grams = self._get_ingredient_grams(amount_obj, name_str)
            scale = grams / 100.0

            db_match = self.lookup_food(name_str, ing_hash if ing_hash else None)
            
            if db_match:
                if db_match.food_id:
                    ing["hash"] = db_match.food_id
                if db_match.food_name:
                    ing["name"] = db_match.food_name
                    
                ing["protein"] = db_match.protein * scale
                ing["carbs"] = db_match.carbs * scale
                ing["fats"] = db_match.fats * scale
                ing["calories"] = db_match.calories * scale
                ing["grams"] = grams

            return (name_str, grams, scale, db_match)

        # Run sequentially to avoid Windows socket exhaustion (WinError 10035) with httpx
        results = [process_ing(ing) for ing in ingredients]
        
        for res in results:
                if res is None:
                    continue
                name_str, grams, scale, db_match = res
                if db_match:
                    total.protein += db_match.protein * scale
                    total.carbs += db_match.carbs * scale
                    total.fats += db_match.fats * scale
                    total.calories += db_match.calories * scale
                    matches += 1
                    logger.debug("Matched ingredient '%s' -> P:%.1f C:%.1f F:%.1f Cal:%d (grams: %.1f)",
                                 name_str, db_match.protein * scale, db_match.carbs * scale,
                                 db_match.fats * scale, db_match.calories * scale, grams)
                else:
                    logger.debug("No match for ingredient '%s'", name_str)

        if matches > 0:
            servings = self._extract_servings(description_for_servings)
            if servings > 1:
                total.protein /= servings
                total.carbs /= servings
                total.fats /= servings
                total.calories /= servings
                logger.info("Scaled aggregated macros by %g servings", servings)

            total.protein = round(total.protein, 2)
            total.carbs = round(total.carbs, 2)
            total.fats = round(total.fats, 2)
            total.calories = int(round(total.calories))

            logger.info("Aggregated %d/%d ingredient matches: P:%.1f C:%.1f F:%.1f Cal:%d",
                        matches, len(ingredients), total.protein, total.carbs, total.fats, total.calories)
        else:
            total.calculate_calories_atwater()

        return total

    def analyze(self, description: str) -> tuple[MacroNutrients, list[dict[str, str]]]:
        """
        Analyze a free-form text description and return aggregated macros and ingredients list.

        Strategy:
        1. Clean up and normalize whitespace.
        2. Attempt direct regex macro extraction from description.
        3. If direct extraction succeeds, return those macros along with ingredients list.
        4. If not, query OpenNutrition DB for food items, scaling by the parsed gram weight.
        5. Detect the number of servings and divide the total recipe macros.
        """
        if not description or not description.strip():
            return MacroNutrients(), []

        # Normalize spaces
        desc_clean = description.replace('\xa0', ' ')

        # First, try to extract and parse the ingredients list
        ingredients_list = []
        sentences = []
        has_header = False
        ingredients_block, has_header = self._extract_ingredients_text(desc_clean)
        sentences = self._split_ingredients(ingredients_block)
        for sentence in sentences:
            try:
                result = parse_ingredient(sentence)
            except Exception as exc:
                logger.debug("NLP parse error for '%s': %s", sentence, exc)
                continue

            if not result.name:
                continue

            name_str = result.name[0].text.strip()
            amount_str = ""
            if result.amount:
                amount_str = result.amount[0].text.strip()

            # If there is no ingredients header (e.g., parsing a raw transcript),
            # ONLY keep items that have a parsed quantity. This prevents parsing
            # random narrative text sentences as ingredients.
            if not has_header and not amount_str:
                continue

            ingredients_list.append({
                "name": name_str,
                "quantity": amount_str
            })

        # 1. Try direct regex macro extraction
        explicit = self._extract_explicit_macros(desc_clean)
        if explicit:
            logger.info(
                "Extracted explicit macros: P:%s C:%s F:%s Cal:%s",
                explicit.protein, explicit.carbs, explicit.fats, explicit.calories
            )
            return explicit, ingredients_list

        # 2. Otherwise fall back to ingredient-parser-nlp and SQLite lookups
        total = MacroNutrients()
        matches = 0

        for sentence in sentences:
            try:
                result = parse_ingredient(sentence)
            except Exception as exc:
                continue

            if not result.name:
                continue

            name_str = result.name[0].text.strip()
            amount_obj = result.amount[0] if result.amount else None

            # Skip items without a parsed quantity if there's no ingredients list header
            if not has_header and not amount_obj:
                continue

            grams = self._get_ingredient_grams(amount_obj, name_str)
            scale = grams / 100.0

            db_match = self.lookup_food(name_str)
            if db_match:
                total.protein += db_match.protein * scale
                total.carbs += db_match.carbs * scale
                total.fats += db_match.fats * scale
                total.calories += db_match.calories * scale
                matches += 1

        if matches > 0:
            servings = self._extract_servings(desc_clean)
            if servings > 1:
                total.protein /= servings
                total.carbs /= servings
                total.fats /= servings
                total.calories /= servings
                logger.info("Scaled aggregated macros by %g servings", servings)

            total.protein = round(total.protein, 2)
            total.carbs = round(total.carbs, 2)
            total.fats = round(total.fats, 2)
            total.calories = int(round(total.calories))

            logger.info(
                "Aggregated %d ingredient matches: P:%.1f C:%.1f F:%.1f Cal:%d",
                matches, total.protein, total.carbs, total.fats, total.calories,
            )
        else:
            total.calculate_calories_atwater()
            logger.info("No ingredient matches - Atwater fallback: Cal=%d", total.calories)

        return total, ingredients_list

    def _analyze_basic(self, description: str) -> tuple[MacroNutrients, list[dict[str, str]]]:
        """Fallback basic token parsing when ingredient-parser-nlp is not installed."""
        ingredients_block, has_header = self._extract_ingredients_text(description)
        if not has_header:
            return MacroNutrients(), []

        phrases = self._tokenize_ingredients(ingredients_block)
        ingredients_list = [{"name": p, "quantity": ""} for p in phrases]
        total = MacroNutrients()
        matches = 0

        for phrase in phrases:
            result = self.lookup_food(phrase)
            if result:
                total.protein += result.protein
                total.carbs += result.carbs
                total.fats += result.fats
                total.calories += result.calories
                matches += 1

        if matches > 0:
            total.protein = round(total.protein, 2)
            total.carbs = round(total.carbs, 2)
            total.fats = round(total.fats, 2)
            logger.info(
                "Basic analyzed %d/%d phrases: P:%.1f C:%.1f F:%.1f Cal:%d",
                matches, len(phrases), total.protein, total.carbs, total.fats, total.calories
            )
        else:
            total.calculate_calories_atwater()

        return total, ingredients_list

    @staticmethod
    def _extract_ingredients_text(description: str) -> tuple[str, bool]:
        """
        Extract the block of text containing ingredients from the description.
        Returns a tuple of (extracted_text, has_header).
        """
        desc_lower = description.lower()
        headers = ["ingredients", "υλικά", "υλικα", "συστατικά", "συστατικα"]
        
        ing_pos = -1
        matched_header = ""
        for header in headers:
            pos = desc_lower.find(header)
            if pos != -1:
                if ing_pos == -1 or pos < ing_pos:
                    ing_pos = pos
                    matched_header = header

        if ing_pos == -1:
            return description, False

        start_pos = ing_pos + len(matched_header)
        while start_pos < len(description) and description[start_pos] in [':', ' ', '\t', '-', '•', '*']:
            start_pos += 1

        end_pos = len(description)
        terminators = [
            "instructions", "directions", "steps", "nutrition", "prep time",
            "εκτέλεση", "εκτελεση", "οδηγίες", "οδηγιες", "τρόπος παρασκευής", "τροπος παρασκευης"
        ]
        for term in terminators:
            term_pos = desc_lower.find(term, start_pos)
            if term_pos != -1 and term_pos < end_pos:
                end_pos = term_pos

        return description[start_pos:end_pos].strip(), True

    @staticmethod
    def _split_ingredients(text: str) -> list[str]:
        """Split the ingredients block into individual ingredient sentences."""
        if '*' in text or '•' in text or ' - ' in text:
            parts = re.split(r'[*•]|\s-\s', text)
        else:
            parts = re.split(r'[\n,]+', text)

        sentences = []
        for part in parts:
            cleaned = part.strip()
            cleaned = cleaned.strip(',. ')
            if cleaned and len(cleaned) >= 3:
                sentences.append(cleaned)
        return sentences

    @staticmethod
    def _extract_servings(description: str) -> float:
        """Detect the number of servings in the recipe description."""
        patterns = [
            r'(\d+)\s*servings\b',
            r'serves\s*(\d+)\b',
            r'makes\s*(\d+)\b',
            r'serving\s*size\s*[:\-]?\s*(\d+)\b',
            r'(\d+)\s*portions\b',
            r'portions\s*[:\-]?\s*(\d+)\b'
        ]
        for pat in patterns:
            m = re.search(pat, description, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                if val > 0:
                    return val
        return 1.0

    def _get_ingredient_grams(self, amount_obj, name_str: str) -> float:
        """Estimate the weight in grams for a given parsed amount and ingredient name."""
        qty = 1.0
        if hasattr(amount_obj, 'quantity') and amount_obj.quantity:
            try:
                qty = float(amount_obj.quantity)
            except Exception:
                qty = 1.0

        unit_str = ""
        if hasattr(amount_obj, 'unit') and amount_obj.unit:
            unit_str = str(amount_obj.unit).lower().strip()

        # 1. Match USDA household portion conversions from database
        db_match = self.lookup_food(name_str)
        if db_match and db_match.serving:
            try:
                serving_data = json.loads(db_match.serving) if isinstance(db_match.serving, str) else db_match.serving
                portions = serving_data.get("portions", {})
                if portions and unit_str:
                    for p_name, p_weight in portions.items():
                        p_clean = p_name.lower()
                        if unit_str in p_clean or p_clean in unit_str:
                            return qty * float(p_weight)
            except Exception:
                pass

        # 2. Check if the unit refers to default portion / serving / unit
        if unit_str in ["serving", "servings", "portion", "portions", "unit", "units", "piece", "pieces"]:
            if db_match and db_match.serving:
                try:
                    serving_data = json.loads(db_match.serving) if isinstance(db_match.serving, str) else db_match.serving
                    metric = serving_data.get("metric", {})
                    if metric:
                        m_qty = float(metric.get("quantity", 100.0))
                        m_unit = str(metric.get("unit", "g")).lower().strip()
                        if m_unit in ["g", "ml", "grams"]:
                            return qty * m_qty
                    common = serving_data.get("common", {})
                    if common:
                        c_qty = float(common.get("quantity", 1.0))
                        c_unit = str(common.get("unit", "")).lower().strip()
                        common_conversion = {
                            "tbsp": 15.0, "tablespoon": 15.0, "tablespoons": 15.0,
                            "tsp": 5.0, "teaspoon": 5.0, "teaspoons": 5.0,
                            "cup": 240.0, "cups": 240.0,
                            "oz": 28.35, "ounce": 28.35, "ounces": 28.35,
                            "egg": 50.0, "eggs": 50.0,
                            "piece": 100.0, "pieces": 100.0,
                            "g": 1.0, "grams": 1.0
                        }
                        if c_unit in common_conversion:
                            return qty * c_qty * common_conversion[c_unit]
                except Exception:
                    pass

        unit_conversion = {
            "gram": 1.0, "g": 1.0, "grams": 1.0,
            "kilogram": 1000.0, "kg": 1000.0, "kilograms": 1000.0,
            "tbsp": 15.0, "tablespoon": 15.0, "tablespoons": 15.0, "tbsp.": 15.0,
            "tsp": 5.0, "teaspoon": 5.0, "teaspoons": 5.0, "tsp.": 5.0,
            "cup": 240.0, "cups": 240.0,
            "oz": 28.35, "ounce": 28.35, "ounces": 28.35,
            "lb": 453.59, "lbs": 453.59, "pound": 453.59, "pounds": 453.59,
            "ml": 1.0, "milliliter": 1.0, "milliliters": 1.0, 
            "l": 1000.0, "liter": 1000.0, "liters": 1000.0, "litre": 1000.0, "litres": 1000.0,
            "egg": 50.0, "eggs": 50.0,
            "clove": 5.0, "cloves": 5.0,
            "can": 400.0, "cans": 400.0,
        }

        unitless_defaults = {
            "chicken": 200.0,
            "egg": 50.0,
            "onion": 150.0,
            "pepper": 150.0,
            "banana": 120.0,
            "apple": 150.0,
            "tomato": 100.0,
            "lime": 40.0,
            "lemon": 50.0,
            "handful": 30.0,
        }

        if not unit_str:
            if qty >= 15.0:
                return qty
            if db_match and db_match.serving:
                try:
                    serving_data = json.loads(db_match.serving) if isinstance(db_match.serving, str) else db_match.serving
                    metric = serving_data.get("metric", {})
                    if metric:
                        m_qty = float(metric.get("quantity", 100.0))
                        m_unit = str(metric.get("unit", "g")).lower().strip()
                        if m_unit in ["g", "ml", "grams"]:
                            return qty * m_qty
                except Exception:
                    pass
            name_lower = name_str.lower()
            for key, weight in unitless_defaults.items():
                if key in name_lower:
                    return qty * weight
            return qty * 100.0

        if unit_str in unit_conversion:
            return qty * unit_conversion[unit_str]

        return qty * 100.0

    @staticmethod
    def _tokenize_ingredients(text: str) -> list[str]:
        """
        Split a recipe description into searchable ingredient phrases.

        Handles common separators: commas, newlines, bullet points, 'and', semicolons.
        Strips quantity prefixes like '100g' or '2 cups'.
        """
        # Normalize separators
        text = re.sub(r"[•\-\*]", ",", text)
        text = re.sub(r"\band\b", ",", text, flags=re.IGNORECASE)

        # Split on commas, newlines, semicolons
        raw_phrases = re.split(r"[,;\n]+", text)

        phrases = []
        for phrase in raw_phrases:
            cleaned = phrase.strip()
            if not cleaned or len(cleaned) < 3:
                continue

            cleaned = re.sub(
                r"^\d+[\./]?\d*\s*(g|kg|oz|ml|l|cup|cups|tbsp|tsp|tablespoon|teaspoon|pound|lb|lbs)\s+",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r"^\d+[\./]?\d*\s+", "", cleaned)

            cleaned = cleaned.strip()
            if cleaned and len(cleaned) >= 3:
                phrases.append(cleaned)

        return phrases

    @staticmethod
    def atwater_fallback(protein: float, carbs: float, fats: float) -> int:
        """
        Atwater estimation formula:
            Calories = (Protein * 4) + (Carbs * 4) + (Fats * 9)
        """
        return int((protein * 4) + (carbs * 4) + (fats * 9))

    def close(self) -> None:
        pass


# ── Global Utility Functions ─────────────────────────

_global_analyzer: Optional[NutritionAnalyzer] = None

def _get_analyzer() -> NutritionAnalyzer:
    global _global_analyzer
    if _global_analyzer is None:
        _global_analyzer = NutritionAnalyzer()
    return _global_analyzer

def get_food_nutrition(food_search_term: str) -> dict | str:
    """Query USDA food database and return 100g macros & available household portions."""
    analyzer = _get_analyzer()
    usda_data = analyzer._query_usda_sqlite(food_search_term)
    if not usda_data:
        match = analyzer.lookup_food(food_search_term)
        if not match:
            return f"No food found matching '{food_search_term}'"
        return {
            "food_name": match.food_name or food_search_term,
            "base_100g": {"calories": match.calories, "protein": match.protein, "fat": match.fats, "carbs": match.carbs, "fiber": 0.0},
            "available_portions": {}
        }

    return {
        "food_name": usda_data["name"],
        "base_100g": {
            "calories": usda_data["energy_kcal"],
            "protein": usda_data["protein_g"],
            "fat": usda_data["fat_g"],
            "carbs": usda_data["carbs_g"],
            "fiber": usda_data["fiber_g"],
        },
        "available_portions": usda_data.get("available_portions", {})
    }

def calculate_recipe_item(food_search_term: str, amount: float, unit: str) -> dict | str:
    """Calculate exact grams and macros for a recipe item given amount and unit."""
    data = get_food_nutrition(food_search_term)
    if isinstance(data, str):
        return data

    # Resolve weight in grams
    if unit in ["g", "gram", "grams"]:
        weight = float(amount)
    elif unit in ["kg", "kilogram", "kilograms"]:
        weight = float(amount) * 1000.0
    else:
        # Match nearest portion (e.g. "medium", "cup", "tbsp", "slice")
        matched_weight = None
        for portion_desc, grams in data.get("available_portions", {}).items():
            if unit.lower() in portion_desc.lower():
                matched_weight = float(grams)
                break
        
        weight = float(amount) * (matched_weight if matched_weight else 100.0)

    # Scale macros
    factor = weight / 100.0
    base = data["base_100g"]

    return {
        "item": data["food_name"],
        "calculated_weight_g": round(weight, 1),
        "calories": round(base["calories"] * factor, 1),
        "protein_g": round(base["protein"] * factor, 1),
        "fat_g": round(base["fat"] * factor, 1),
        "carbs_g": round(base["carbs"] * factor, 1),
        "fiber_g": round(base["fiber"] * factor, 1),
    }

