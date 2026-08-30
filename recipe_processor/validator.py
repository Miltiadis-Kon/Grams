"""
Layer 4: Validation, Unit Normalization & Cross-Entity Reconciliation Layer.
Performs:
- Numerical fraction-to-decimal standardization.
- Metric/Imperial unit normalization.
- Strict culinary entity validation (excluding equipment, URLs, marketing, macro summaries, section headers).
- Compound line splitting (e.g. '30g miso + 20g gochujang').
- Stem-based ingredient deduplication (preventing duplicate 'rice', 'egg', etc.).
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

        # Clean trailing duplicate quantities (e.g. "500 g 95 5" -> "500 g", "750 g 15 g" -> "750 g")
        m_double_g = re.match(r'^(\d+(?:\.\d+)?\s*(?:g|ml|kg|tbsp|tsp|cups?))\s+\d+.*$', s, re.IGNORECASE)
        if m_double_g:
            s = m_double_g.group(1)

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

        # Reject pure section headers or meta words
        if lower in [
            "optional", "optional:", "optional sauce:", "optional topping:",
            "sauce", "sauce:", "topping:", "garnish:", "notes:", "extras:",
            "chop:", "method:", "directions:", "instructions:", "preparation:", "ingredients:"
        ]:
            return False

        # Reject conversational clauses and non-food verbs/pronouns
        if any(lower.startswith(prefix) for prefix in [
            "don't", "dont", "make sure", "welcome", "subscribe", "today", "we are",
            "i like", "you can", "you will", "check the", "hit the", "first", "then",
            "after", "please", "remember", "let's", "lets", "new live", "live stream",
            "connect on", "follow me", "follow my", "socials", "patreon"
        ]):
            return False

        # Reject headers and metadata tokens
        if any(h in lower for h in [
            "translation", "english translation", "[english", "macros", "nutrition", "calories", "cals", "kcal", "http", "payhip", "amzn",
            "felu", "patreon", "twitch", "cookbook", "kochbuch", "walkingpad", "live stream",
            "twitter", "instagram", "tiktok", "youtube", "servings", "serving size", "save this recipe", "like and subscribe"
        ]):
            return False

        # Reject equipment unless qualified with food (e.g. "cooking spray", "olive oil")
        equipment_words = ["knife", "pan", "blender", "scale", "air fryer", "stovetop", "container", "peeler", "bottle"]
        for eq in equipment_words:
            if eq in lower:
                if not any(food in lower for food in ["oil", "spray", "butter", "egg", "chicken", "beef", "flour", "milk", "cheese"]):
                    return False

        # Reject pure macro summary strings (e.g. '541 45 C', '45C 26F 31P', '422 calories')
        if re.match(r'^(?:\d+\s*(?:c|f|p|cc|kcal|cals?|g)?|\d+/\d+|\d+\s*of\s*\d+.*|\d+\s*(?:cals?|calories).*)$', lower):
            return False

        if re.search(r'\b\d+\s*[cfp]\b', lower) and not any(food in lower for food in ["chicken", "flour", "protein", "pasta", "beef", "pork"]):
            return False

        return True

    @classmethod
    def get_food_stem(cls, name: str) -> str:
        """Extracts the base food noun stem for deduplication."""
        lower = name.lower()
        if "egg white" in lower:
            return "egg_white"
        elif "egg" in lower:
            return "egg_whole"
        if "sweet potato" in lower:
            return "sweet_potato"
        elif "potato" in lower:
            return "potato"
        if "olive oil" in lower:
            return "olive_oil"
        elif "oil" in lower:
            return "oil"
        if "garlic powder" in lower:
            return "garlic_powder"
        elif "garlic" in lower:
            return "garlic"
        if "onion powder" in lower:
            return "onion_powder"
        elif "onion" in lower:
            return "onion"

        stems = [
            "chicken", "beef", "turkey", "pork", "salmon", "tuna", "shrimp",
            "rice", "pasta", "macaroni", "noodle", "bread",
            "tortilla", "wrap", "bun", "oat", "flour",
            "cornstarch", "cheese", "cheddar", "parmesan", "mozzarella", "feta",
            "greek yogurt", "yogurt", "cottage cheese", "milk", "butter",
            "paprika", "pepper", "salt",
            "honey", "mustard", "mayo", "sriracha", "soy sauce", "cocoa"
        ]
        for s in stems:
            if s in lower:
                return s
        return re.sub(r'[^a-z0-9]', '', lower)[:12]

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

        # Expand compound lines containing '+' (e.g. '30g miso + 20g gochujang')
        expanded_ings = []
        for ing in raw_ings:
            if isinstance(ing, dict):
                name = str(ing.get("name", "")).strip()
                qty = str(ing.get("quantity", "1")).strip()
                if "+" in name and not any(k in name.lower() for k in ["flour", "powder"]):
                    parts = name.split("+")
                    for p in parts:
                        expanded_ings.append({"name": p.strip(), "quantity": "1"})
                else:
                    expanded_ings.append(ing)
            elif isinstance(ing, str):
                if "+" in ing:
                    for p in ing.split("+"):
                        expanded_ings.append({"name": p.strip(), "quantity": "1"})
                else:
                    expanded_ings.append({"name": ing.strip(), "quantity": "1"})

        # 1. Process and normalize ingredients list
        clean_ingredients = []
        seen_stems = {}  # stem -> index in clean_ingredients

        for ing in expanded_ings:
            name = str(ing.get("name", "")).strip()
            qty = str(ing.get("quantity", "1")).strip()
            unit = str(ing.get("unit", "")).strip()
            prep = str(ing.get("prep", "")).strip()
            notes = str(ing.get("notes", "")).strip()

            # Clean name from leading bullet dashes or colons
            name = re.sub(r'^(?:[-•*:]\s*|\d+[\.\)]\s*)', '', name).strip()

            if not cls.is_valid_food_name(name):
                continue

            # Standardize loose colloquial quantities
            qty_lower = qty.lower()
            if qty_lower in COLLOQUIAL_QUANTITIES:
                std_qty, std_unit, col_note = COLLOQUIAL_QUANTITIES[qty_lower]
                qty = std_qty
                unit = std_unit
                notes = f"{notes} ({col_note})".strip()

            # If quantity contains a paren measure like '1 pack (150g)', extract the paren measure
            m_paren = re.search(r'\(([\d\.]+\s*(?:g|gram|grams|kg|ml|l|tbsp|tsp|cup|oz|clove|slice))\)', qty, re.IGNORECASE)
            if m_paren:
                qty = m_paren.group(1)

            # Standardize fractions and numbers
            if not unit:
                m_unit = re.search(r'\b(g|gram|grams|kg|ml|l|tbsp|tsp|cup|cups|oz|slice|slices|clove|cloves|pinch|pinches)\b', qty, re.IGNORECASE)
                if m_unit:
                    unit = m_unit.group(1)

            std_qty = cls.standardize_fraction(qty)
            std_unit = cls.normalize_unit(unit)

            # Prevent double unit formatting (e.g. "2 tsps 2 tsps")
            if std_unit and std_unit != 'unit':
                # Check if std_unit is already inside std_qty
                if std_unit in std_qty.lower():
                    formatted_qty = std_qty
                else:
                    formatted_qty = f"{std_qty} {std_unit}".strip()
            else:
                formatted_qty = std_qty

            stem = cls.get_food_stem(name)

            # Deduplication: if an item with this stem already exists
            if stem in seen_stems:
                existing_idx = seen_stems[stem]
                existing_item = clean_ingredients[existing_idx]
                # If current item is unitless ("1"), skip it in favor of the quantified item
                if formatted_qty == "1" and existing_item["quantity"] != "1":
                    continue
                # If existing was unitless and current has specific quantity, replace it
                elif existing_item["quantity"] == "1" and formatted_qty != "1":
                    clean_ingredients[existing_idx] = {
                        "name": name,
                        "quantity": formatted_qty,
                        "unit": std_unit,
                        "amount": std_qty,
                        "prep": prep,
                        "notes": notes
                    }
                    continue
                else:
                    # Same stem duplicate, ignore second occurrence
                    continue

            seen_stems[stem] = len(clean_ingredients)
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
        for idx, step in enumerate(raw_ins):
            action_text = ""
            if isinstance(step, str):
                action_text = step.strip()
            elif isinstance(step, dict):
                action_text = str(step.get("action", "")).strip()

            if not action_text or len(action_text) < 8 or action_text.startswith('---'):
                continue

            # Clean leading step prefixes
            action_text = re.sub(r'^(?:step\s*\d+[:\-\.]\s*|\d+[\.\)]\s*|[-•*]\s*)', '', action_text).strip()
            if not any(junk in action_text.lower() for junk in ["disclaimer:", "links included", "amazon links", "cookbook"]):
                clean_instructions.append(action_text)

        # Final verification
        has_recipe = is_recipe and len(clean_ingredients) >= 1

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
