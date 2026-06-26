"""
Nutritional analysis module using the OpenNutrition dataset in Supabase.

Zero API keys required for OpenNutrition dataset itself, but requires
SUPABASE_URL and SUPABASE_KEY to be configured in the environment.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional
from functools import lru_cache

from translate import Translator
from ingredient_parser import parse_ingredient
from supabase import create_client, Client

from database import MacroNutrients

logger = logging.getLogger(__name__)


class NutritionAnalyzer:
    """
    Nutritional analysis engine backed by the OpenNutrition dataset in Supabase.
    """

    def __init__(self) -> None:
        # Detect environment database configuration
        self._supabase_url = os.environ.get("SUPABASE_URL")
        self._supabase_key = os.environ.get("SUPABASE_KEY")
        if not self._supabase_url or not self._supabase_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY environment variables are required!\n"
                "Please specify them in your .env file or environment variables."
            )
        self._client: Client = create_client(self._supabase_url, self._supabase_key)

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

    @lru_cache(maxsize=2048)
    def lookup_food(self, query: str) -> Optional[MacroNutrients]:
        """
        Search the Supabase foods table for a food item by name.

        Returns the top match's macros, or None if no match found.
        """
        # Translate Greek queries to English first so they can match the English foods DB
        query_en = self._translate_if_greek(query)

        sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', query_en)
        sanitized = ' '.join(sanitized.split()).strip()
        if not sanitized or not re.search(r'[a-zA-Z]', sanitized):
            return None

        try:
            # 1. Try exact match first
            response = self._client.table("foods").select("protein_g, carbs_g, fat_g, energy_kcal, serving").limit(1).eq("name", query_en).execute()
            if response.data:
                row = response.data[0]
                return self._row_to_macros(row, query_en, query)

            # 2. Try text search (FTS)
            search_words = [w for w in sanitized.split() if w]
            fts_query = " & ".join(search_words)
            
            response = self._client.table("foods").select("protein_g, carbs_g, fat_g, energy_kcal, serving").limit(1).text_search("name", fts_query).execute()
            if response.data:
                row = response.data[0]
                return self._row_to_macros(row, query_en, query)

            # 3. Fallback to ILIKE substring matching
            response = self._client.table("foods").select("protein_g, carbs_g, fat_g, energy_kcal, serving").limit(1).ilike("name", f"%{sanitized}%").execute()
            if response.data:
                row = response.data[0]
                return self._row_to_macros(row, query_en, query)

        except Exception as exc:
            logger.warning("Supabase foods lookup failed for '%s': %s", query_en, exc)

        return None

    def _row_to_macros(self, row: dict, query_en: str, query_orig: str) -> MacroNutrients:
        protein = float(row.get("protein_g") or 0.0)
        carbs = float(row.get("carbs_g") or 0.0)
        fat = float(row.get("fat_g") or 0.0)
        energy = float(row.get("energy_kcal") or 0.0)
        serving = row.get("serving")
        
        macros = MacroNutrients(
            protein=protein,
            carbs=carbs,
            fats=fat,
            calories=int(round(energy)),
            serving=serving
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
        """No-op as Supabase client is connectionless HTTP."""
        pass

