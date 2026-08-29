"""
Layer 4: Validation, Unit Normalization & Cross-Entity Reconciliation Layer.
Performs:
- Numerical fraction-to-decimal standardization.
- Metric/Imperial unit normalization.
- Strict culinary entity validation (excluding equipment, URLs, marketing, macro summaries).
- Cross-entity reconciliation (ensuring every ingredient used in instruction steps exists in the master roster).
"""

import re
import logging
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# Unicode vulgar fraction mappings
FRACTION_MAP = {
    '\u00bd': '0.5',   # 1/2
    '\u00bc': '0.25',  # 1/4
    '\u00be': '0.75',  # 3/4
    '\u2153': '0.33',  # 1/3
    '\u2154': '0.67',  # 2/3
    '\u2155': '0.2',   # 1/5
    '\u2156': '0.4',   # 2/5
    '\u2157': '0.6',   # 3/5
    '\u2158': '0.8',   # 4/5
    '\u2159': '0.17',  # 1/6
    '\u215a': '0.83',  # 5/6
    '\u215b': '0.125', # 1/8
    '\u215c': '0.375', # 3/8
    '\u215d': '0.625', # 5/8
    '\u215e': '0.875', # 7/8
}

# Standardized unit aliases
UNIT_NORMALIZATION_MAP = {
    # Weight
    'g': 'g', 'gram': 'g', 'grams': 'g', 'gr': 'g', 'g.': 'g',
    'kg': 'kg', 'kilogram': 'kg', 'kilograms': 'kg', 'kgs': 'kg',
    'oz': 'oz', 'ounce': 'oz', 'ounces': 'oz',
    'lb': 'lb', 'lbs': 'lb', 'pound': 'lb', 'pounds': 'lb',
    # Volume
    'ml': 'ml', 'milliliter': 'ml', 'milliliters': 'ml', 'millilitre': 'ml',
    'l': 'l', 'liter': 'l', 'liters': 'l', 'litre': 'l', 'litres': 'l',
    'tbsp': 'tbsp', 'tablespoon': 'tbsp', 'tablespoons': 'tbsp', 'tbs': 'tbsp', 'tb': 'tbsp',
    'tsp': 'tsp', 'teaspoon': 'tsp', 'teaspoons': 'tsp', 'ts': 'tsp',
    'cup': 'cup', 'cups': 'cup',
    'scoop': 'scoop', 'scoops': 'scoop',
    # Count / Portion
    'pinch': 'pinch', 'pinches': 'pinch',
    'slice': 'slice', 'slices': 'slice',
    'clove': 'clove', 'cloves': 'clove',
    'can': 'can', 'cans': 'can',
    'piece': 'piece', 'pieces': 'piece',
    'unit': 'unit', 'serving': 'serving', 'servings': 'serving',
}

# Loose colloquial quantity expressions
COLLOQUIAL_QUANTITIES = {
    'a splash': ('15', 'ml', 'splash'),
    'splash': ('15', 'ml', 'splash'),
    'a glug': ('15', 'ml', 'glug'),
    'glug': ('15', 'ml', 'glug'),
    'a drizzle': ('10', 'ml', 'drizzle'),
    'drizzle': ('10', 'ml', 'drizzle'),
    'a handful': ('30', 'g', 'handful'),
    'handful': ('30', 'g', 'handful'),
    'pinch': ('1', 'pinch', 'pinch'),
    'a pinch': ('1', 'pinch', 'pinch'),
    'to taste': ('1', 'pinch', 'to taste'),
    'as needed': ('1', 'unit', 'as needed'),
    'optional': ('1', 'unit', 'optional'),
}


class RecipeValidator:
    """
    Validates, normalizes, and reconciles recipe payloads.
    """

    @classmethod
    def standardize_fraction(cls, qty_str: str) -> str:
        """Converts vulgar unicode fractions and slash fractions (1 1/2) into clean decimals."""
        if not qty_str:
            return "1"

        s = str(qty_str).strip()

        # Handle mixed fractions with slash (e.g. "1 1/2" -> 1.5)
        m_mixed = re.match(r'^(\d+)\s+(\d+)/(\d+)$', s)
        if m_mixed:
            whole = float(m_mixed.group(1))
            num = float(m_mixed.group(2))
            den = float(m_mixed.group(3))
            res = round(whole + (num / den), 2)
            return str(int(res)) if res.is_integer() else str(res)

        # Handle simple slash fractions (e.g. "1/2" -> 0.5)
        m_simple = re.match(r'^(\d+)/(\d+)$', s)
        if m_simple:
            num = float(m_simple.group(1))
            den = float(m_simple.group(2))
            res = round(num / den, 2)
            return str(int(res)) if res.is_integer() else str(res)

        # Handle range (e.g. "2-3" -> 2.5)
        m_range = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$', s)
        if m_range:
            low = float(m_range.group(1))
            high = float(m_range.group(2))
            res = round((low + high) / 2.0, 2)
            return str(int(res)) if res.is_integer() else str(res)

        # Handle mixed with unicode fraction (e.g. "1 ½" or "1½")
        for frac, dec in FRACTION_MAP.items():
            if frac in s:
                m_u_mixed = re.match(rf'^(\d+)\s*{re.escape(frac)}$', s)
                if m_u_mixed:
                    whole = float(m_u_mixed.group(1))
                    res = round(whole + float(dec), 2)
                    return str(int(res)) if res.is_integer() else str(res)
                if s == frac:
                    return dec
                s = s.replace(frac, f" {dec} ")

        s = re.sub(r'\s+', ' ', s).strip()
        m_sum = re.match(r'^(\d+)\s+(\d+(?:\.\d+)?)$', s)
        if m_sum:
            res = round(float(m_sum.group(1)) + float(m_sum.group(2)), 2)
            return str(int(res)) if res.is_integer() else str(res)

        m_num = re.search(r'^\d+(?:\.\d+)?', s)
        if m_num:
            return m_num.group(0)

        return s

    @classmethod
    def normalize_unit(cls, unit_str: str) -> str:
        """Normalizes unit string to standard unit name or 'unit'."""
        if not unit_str:
            return "unit"
        clean = unit_str.lower().strip().rstrip('.')
        return UNIT_NORMALIZATION_MAP.get(clean, clean)

    @classmethod
    def is_valid_food_name(cls, name: str) -> bool:
        """Strictly checks whether name is an edible food ingredient."""
        if not name or len(name) < 2 or len(name) > 85:
            return False

        lower = name.lower().strip()

        # Reject conversational clauses and non-food verbs/pronouns
        if any(lower.startswith(prefix) for prefix in [
            "don't", "dont", "make sure", "welcome", "subscribe", "today", "we are",
            "i like", "you can", "you will", "check the", "hit the", "first", "then",
            "after", "please", "remember", "let's", "lets"
        ]):
            return False

        # Reject headers and metadata tokens
        if any(h in lower for h in [
            "macros", "nutrition", "calories", "cals", "kcal", "http", "payhip", "amzn",
            "felu", "patreon", "twitch", "cookbook", "kochbuch", "walkingpad",
            "instructions:", "directions:", "servings", "serving size"
        ]):
            return False

        # Reject equipment unless qualified with food (e.g. "cooking spray", "olive oil")
        equipment_words = ["knife", "pan", "blender", "scale", "air fryer", "stovetop", "container", "peeler", "bottle"]
        for eq in equipment_words:
            if eq in lower:
                if not any(food in lower for food in ["oil", "spray", "butter", "egg", "chicken", "beef", "flour", "milk", "cheese"]):
                    return False

        # Reject pure macro summary strings or loose numbers
        if re.match(r'^(?:\d+\s*(?:c|f|p|cc|kcal|cals?|g)?|\d+/\d+|\d+\s*of\s*\d+.*)$', lower):
            return False

        return True

    @classmethod
    def reconcile_recipe_payload(cls, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates, normalizes, and reconciles the extracted recipe payload.
        Ensures cross-entity consistency between instructions and ingredients list.
        """
        if not isinstance(raw_payload, dict):
            return {"is_recipe": False, "title": "", "ingredients": [], "instructions": []}

        is_recipe = bool(raw_payload.get("is_recipe", False))
        title = str(raw_payload.get("title", "Extracted Recipe")).strip()
        servings = raw_payload.get("servings")

        raw_ings = raw_payload.get("ingredients", [])
        raw_ins = raw_payload.get("instructions", [])

        # 1. Process and normalize ingredients list
        clean_ingredients = []
        seen_names = set()

        for ing in raw_ings:
            if isinstance(ing, str):
                name = ing.strip()
                qty = "1"
                unit = "unit"
                prep = ""
                notes = ""
            elif isinstance(ing, dict):
                name = str(ing.get("name", "")).strip()
                qty = str(ing.get("quantity", "1")).strip()
                unit = str(ing.get("unit", "")).strip()
                prep = str(ing.get("prep", "")).strip()
                notes = str(ing.get("notes", "")).strip()
            else:
                continue

            if not cls.is_valid_food_name(name):
                continue

            # Standardize loose colloquial quantities
            qty_lower = qty.lower()
            if qty_lower in COLLOQUIAL_QUANTITIES:
                std_qty, std_unit, col_note = COLLOQUIAL_QUANTITIES[qty_lower]
                qty = std_qty
                unit = std_unit
                notes = f"{notes} ({col_note})".strip()

            # Standardize fractions and numbers
            std_qty = cls.standardize_fraction(qty)
            std_unit = cls.normalize_unit(unit)

            # Combine formatted quantity string for backward compatibility
            formatted_qty = f"{std_qty} {std_unit}".strip() if std_unit and std_unit != 'unit' else std_qty

            norm_key = name.lower()
            if norm_key in seen_names:
                continue
            seen_names.add(norm_key)

            clean_ingredients.append({
                "name": name,
                "quantity": formatted_qty,
                "unit": std_unit,
                "amount": std_qty,
                "prep": prep,
                "notes": notes
            })

        # 2. Process and normalize instruction steps
        clean_instructions = []
        in_step_ingredients = set()

        for idx, step in enumerate(raw_ins):
            action_text = ""
            timer_min = None
            used_ings = []

            if isinstance(step, str):
                action_text = step.strip()
            elif isinstance(step, dict):
                action_text = str(step.get("action", "")).strip()
                timer_min = step.get("timer_minutes")
                used_ings = step.get("ingredients_used", [])

            if not action_text or len(action_text) < 8 or action_text.startswith('---'):
                continue

            # Clean leading step prefixes
            action_text = re.sub(r'^(?:step\s*\d+[:\-\.]\s*|\d+[\.\)]\s*|[-•*]\s*)', '', action_text).strip()

            # Track mentioned ingredients
            for item in used_ings:
                if isinstance(item, str) and cls.is_valid_food_name(item):
                    in_step_ingredients.add(item.lower())

            clean_instructions.append(action_text)

        # 3. Cross-Entity Reconciliation:
        # If an ingredient was explicitly named in instructions but omitted from master list, reconcile it
        for step_ing in in_step_ingredients:
            if not any(step_ing in ing_item["name"].lower() or ing_item["name"].lower() in step_ing for ing_item in clean_ingredients):
                clean_ingredients.append({
                    "name": step_ing.capitalize(),
                    "quantity": "1 to taste",
                    "unit": "to taste",
                    "amount": "1",
                    "prep": "",
                    "notes": "detected in preparation steps"
                })

        # Final verification
        has_recipe = is_recipe and len(clean_ingredients) >= 1

        # Format legacy-compatible ingredients list
        final_ings = [
            {"name": ing["name"], "quantity": ing["quantity"]}
            for ing in clean_ingredients
        ]

        return {
            "is_recipe": has_recipe,
            "title": title if has_recipe else "",
            "servings": servings,
            "ingredients": final_ings,
            "instructions": clean_instructions
        }
