"""
Nutritional analysis module using the OpenNutrition local database.

Downloads the OpenNutrition Foods TSV dataset on first use, indexes it into
a local SQLite database with FTS5 full-text search, and provides ingredient-level
macro lookups. Falls back to the Atwater formula when no match is found.

Zero API keys required. Fully offline after initial dataset download.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import sqlite3
import zipfile
from typing import Optional

import requests

from config import (
    DATA_DIR,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT_SECONDS,
    OPENNUTRITION_DB_PATH,
    OPENNUTRITION_TSV_PATH,
    OPENNUTRITION_ZIP_URL,
)
from database import MacroNutrients

logger = logging.getLogger(__name__)


class NutritionAnalyzer:
    """
    Local nutritional analysis engine backed by the OpenNutrition dataset.

    On first instantiation the dataset is downloaded (~50 MB zipped) and
    indexed into a SQLite database with FTS5 for fast fuzzy lookups.
    Subsequent runs reuse the existing SQLite index.
    """

    def __init__(self, data_dir: str = DATA_DIR) -> None:
        self._data_dir = data_dir
        self._db_path = OPENNUTRITION_DB_PATH
        self._tsv_path = OPENNUTRITION_TSV_PATH
        self._conn: Optional[sqlite3.Connection] = None

        os.makedirs(self._data_dir, exist_ok=True)
        self._ensure_database()

    # ── Setup / Indexing ─────────────────────────────

    def _ensure_database(self) -> None:
        """Download and index the dataset if the SQLite DB doesn't exist."""
        if os.path.exists(self._db_path):
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            logger.info("OpenNutrition SQLite index loaded from %s", self._db_path)
            return

        # Download the dataset if TSV is missing
        if not os.path.exists(self._tsv_path):
            self._download_dataset()

        # Build the SQLite index from the TSV
        self._build_sqlite_index()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)

    def _download_dataset(self) -> None:
        """Download and extract the OpenNutrition Foods ZIP archive."""
        logger.info("Downloading OpenNutrition dataset from %s ...", OPENNUTRITION_ZIP_URL)

        for attempt in range(1, HTTP_MAX_RETRIES + 1):
            try:
                resp = requests.get(
                    OPENNUTRITION_ZIP_URL,
                    timeout=HTTP_TIMEOUT_SECONDS * 4,  # larger timeout for big file
                    stream=True,
                )
                resp.raise_for_status()

                zip_path = os.path.join(self._data_dir, "opennutrition.zip")
                with open(zip_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=8192):
                        fh.write(chunk)

                # Extract the TSV from the ZIP
                with zipfile.ZipFile(zip_path, "r") as zf:
                    tsv_names = [n for n in zf.namelist() if n.endswith(".tsv")]
                    if not tsv_names:
                        raise FileNotFoundError("No TSV file found inside ZIP archive")
                    # Extract the TSV to our expected path
                    with zf.open(tsv_names[0]) as src, open(self._tsv_path, "wb") as dst:
                        dst.write(src.read())

                # Clean up the ZIP
                os.remove(zip_path)
                logger.info("Dataset extracted to %s", self._tsv_path)
                return

            except (requests.RequestException, IOError) as exc:
                logger.warning(
                    "Download attempt %d/%d failed: %s",
                    attempt, HTTP_MAX_RETRIES, exc,
                )

        logger.error(
            "Failed to download OpenNutrition dataset after %d attempts. "
            "Nutrition lookups will fall back to Atwater estimation.",
            HTTP_MAX_RETRIES,
        )

    def _build_sqlite_index(self) -> None:
        """
        Parse the OpenNutrition TSV and build a SQLite database with FTS5 index.

        The TSV schema has columns: id, name, alternate_names, description, type,
        source, serving, nutrition_100g, ean_13, labels, ...

        The `nutrition_100g` column contains a JSON object with keys like:
        protein, carbohydrates, total_fat, calories, etc. (values per 100g).
        """
        if not os.path.exists(self._tsv_path):
            logger.warning("TSV file not found at %s - skipping index build", self._tsv_path)
            return

        temp_db_path = self._db_path + ".tmp"
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except OSError:
                pass

        logger.info("Building SQLite index from %s into temporary file %s ...", self._tsv_path, temp_db_path)
        conn = sqlite3.connect(temp_db_path)
        cur = conn.cursor()

        # Main table for nutritional data
        cur.execute("""
            CREATE TABLE IF NOT EXISTS foods (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protein_g REAL DEFAULT 0,
                carbs_g REAL DEFAULT 0,
                fat_g REAL DEFAULT 0,
                energy_kcal REAL DEFAULT 0,
                serving TEXT
            )
        """)

        # FTS5 virtual table for fast text search
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS foods_fts
            USING fts5(name, content=foods, content_rowid=rowid)
        """)

        rows_inserted = 0
        parse_errors = 0

        with open(self._tsv_path, "r", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            if reader.fieldnames is None:
                logger.error("TSV file has no header row")
                conn.close()
                return

            batch = []
            for row in reader:
                food_id = (row.get("id") or "").strip()
                food_name = (row.get("name") or "").strip()
                if not food_name:
                    continue
                if not food_id:
                    food_id = f"auto_{rows_inserted}"

                serving_str = (row.get("serving") or "").strip()

                # Parse the nutrition_100g JSON blob
                nutrition_json = row.get("nutrition_100g", "{}")
                protein = 0.0
                carbs = 0.0
                fat = 0.0
                calories = 0.0

                try:
                    nutrition = json.loads(nutrition_json) if nutrition_json else {}
                    protein = float(nutrition.get("protein", 0) or 0)
                    carbs = float(nutrition.get("carbohydrates", 0) or 0)
                    fat = float(nutrition.get("total_fat", 0) or 0)
                    calories = float(nutrition.get("calories", 0) or 0)
                except (json.JSONDecodeError, ValueError, TypeError):
                    parse_errors += 1

                batch.append((food_id, food_name, protein, carbs, fat, calories, serving_str))
                rows_inserted += 1

                if len(batch) >= 5000:
                    cur.executemany(
                        "INSERT OR IGNORE INTO foods VALUES (?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                    batch.clear()

            # Insert remaining
            if batch:
                cur.executemany(
                    "INSERT OR IGNORE INTO foods VALUES (?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )

        # Populate the FTS index
        cur.execute("INSERT INTO foods_fts(foods_fts) VALUES('rebuild')")
        conn.commit()
        conn.close()

        # Atomically replace the final DB file
        os.replace(temp_db_path, self._db_path)

        if parse_errors:
            logger.warning("Encountered %d JSON parse errors during indexing", parse_errors)
        logger.info(
            "SQLite index built: %d foods indexed at %s", rows_inserted, self._db_path
        )

    # ── Public API ───────────────────────────────────

    def _translate_if_greek(self, text: str) -> str:
        """Translate text to English if it contains Greek characters."""
        if not text:
            return text
        # Detect Greek characters
        if re.search(r'[\u0370-\u03ff\u1f00-\u1fff]', text):
            try:
                from translate import Translator
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

    def lookup_food(self, query: str) -> Optional[MacroNutrients]:
        """
        Search the OpenNutrition database for a food item by name.

        Returns the top match's macros, or None if no match found.
        """
        if self._conn is None:
            return None

        # Translate Greek queries to English first so they can match the English foods DB
        query_en = self._translate_if_greek(query)

        try:
            cur = self._conn.cursor()
            # Clean and sanitize the FTS5 query to avoid punctuation errors
            sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', query_en)
            sanitized = ' '.join(sanitized.split()).strip()
            if not sanitized or not re.search(r'[a-zA-Z]', sanitized):
                return None

            # Try exact phrase match first, then token match
            for fts_query in [f'"{sanitized}"', sanitized]:
                cur.execute(
                    """
                    SELECT f.protein_g, f.carbs_g, f.fat_g, f.energy_kcal, f.serving
                    FROM foods_fts fts
                    JOIN foods f ON f.rowid = fts.rowid
                    WHERE foods_fts MATCH ?
                    ORDER BY rank
                    LIMIT 1
                    """,
                    (fts_query,),
                )
                row = cur.fetchone()
                if row:
                    protein, carbs, fat, energy, serving = row
                    macros = MacroNutrients(
                        protein=protein,
                        carbs=carbs,
                        fats=fat,
                        calories=int(energy) if energy else 0,
                        serving=serving
                    )
                    logger.debug("Matched '%s' (translated from '%s') → P:%.1f C:%.1f F:%.1f Cal:%d",
                                 query_en, query, protein, carbs, fat, energy)
                    return macros

        except sqlite3.OperationalError as exc:
            logger.warning("FTS query failed for '%s': %s", query, exc)

        return None

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

        # Import parse_ingredient here to ensure dependency is loaded
        try:
            from ingredient_parser import parse_ingredient
        except ImportError:
            logger.warning("ingredient-parser-nlp is not installed, unable to parse quantity structure")
            return total

        for ing in ingredients:
            name_str = ing.get("name", "").strip()
            qty_str = ing.get("quantity", "").strip()
            if not name_str:
                continue

            # Parse quantity and name combined to retrieve amount object
            sentence = f"{qty_str} {name_str}".strip()
            try:
                result = parse_ingredient(sentence)
                amount_obj = result.amount[0] if result.amount else None
            except Exception:
                amount_obj = None

            grams = self._get_ingredient_grams(amount_obj, name_str)
            scale = grams / 100.0

            db_match = self.lookup_food(name_str)
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
        try:
            from ingredient_parser import parse_ingredient
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
        except ImportError:
            logger.warning("ingredient-parser-nlp is not installed, using basic parser")
            return self._analyze_basic(desc_clean)

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

        # Check if the unit refers to default portion / serving / unit
        if unit_str in ["serving", "servings", "portion", "portions", "unit", "units", "piece", "pieces"]:
            db_match = self.lookup_food(name_str)
            if db_match and db_match.serving:
                try:
                    import json
                    serving_data = json.loads(db_match.serving)
                    # Try metric first (grams / ml)
                    metric = serving_data.get("metric", {})
                    if metric:
                        m_qty = float(metric.get("quantity", 100.0))
                        m_unit = str(metric.get("unit", "g")).lower().strip()
                        if m_unit in ["g", "ml", "grams"]:
                            return qty * m_qty
                    # Try common unit conversion
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
            "ml": 1.0, "l": 1000.0,
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
            # If the quantity is large (e.g. >= 15) and unit is empty, it's almost certainly grams/ml
            if qty >= 15.0:
                return qty
            # Check if there is a default serving in DB even for unitless input
            db_match = self.lookup_food(name_str)
            if db_match and db_match.serving:
                try:
                    import json
                    serving_data = json.loads(db_match.serving)
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

            # Strip leading quantities: "100g chicken" → "chicken"
            # "2 cups rice" → "rice", "1/2 cup oats" → "oats"
            cleaned = re.sub(
                r"^\d+[\./]?\d*\s*(g|kg|oz|ml|l|cup|cups|tbsp|tsp|tablespoon|teaspoon|pound|lb|lbs)\s+",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            # Strip standalone leading numbers: "2 chicken breast" → "chicken breast"
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
        """Close the SQLite connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

