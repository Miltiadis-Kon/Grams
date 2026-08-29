"""
State-of-the-art Recipe & Ingredient Extraction Pipeline for Grams.
Combines:
1. Intelligent Noise & Marketing Stripper (affiliate links, equipment, sponsor segments).
2. Multi-LLM Structured Extraction (Google Gemini, OpenAI, Groq, local Ollama) with strict Food-NER schema.
3. Specialized Fallback NLP Parser (ingredient-parser + rule-based Food Entity Recognition).
4. Strict Food Vocabulary & Component Validator (rejects non-food, URLs, equipment, and macro headers).
"""

import re
import os
import time
import json as _json
import urllib.request
import urllib.error
import logging
from typing import Any, List, Dict, Tuple

logger = logging.getLogger(__name__)

# Non-food blacklist terms
NON_FOOD_TERMS = {
    "http", "https", "amzn", "payhip", "felu", "patreon", "twitch", "tiktok", "instagram", "twitter",
    "youtube", "subscribe", "subscribers", "channel", "video", "sponsor", "sponsored", "affiliate", "commission",
    "cookbook", "kochbuch", "ebook", "pdf", "guide", "discount", "code", "link", "bio", "walkingpad",
    "knife", "pan", "blender", "scale", "air fryer", "stovetop", "container", "containers", "peeler",
    "squeeze bottle", "squeeze bottles", "bowls", "bowl", "disclaimer", "instructions", "directions", "steps",
    "macros", "macro", "calories", "calorie", "cals", "kcal", "protein", "carbs", "fats", "fat", "servings", "serving"
}

# Common marketing header patterns to discard
MARKETING_PATTERNS = [
    r'https?://\S+',
    r'📖\s*DIET\s+COOKBOOK.*',
    r'📖\s*KOCHBUCH.*',
    r'🔪\s*NAKIRI.*',
    r'Follow my Live Streams:.*',
    r'Twitch:.*',
    r'Kick:.*',
    r'My Patreon.*',
    r'Socials:.*',
    r'Twitter/X:.*',
    r'IG:.*',
    r'TikTok:.*',
    r'Everything I cook with.*',
    r'AMAZON LINKS:.*',
    r'MIDEA FLEXIFY.*',
    r'DISCLAIMER:.*',
    r'\[LLM Parsed Instructions\].*',
    r'[-=_*~]{3,}',
    r'Non stick pan.*',
    r'Kitchen scale.*',
    r'Meal prep container.*',
    r'Air fryer:.*',
    r'Big Blender:.*',
    r'Small Blender:.*',
    r'Y-Peeler:.*',
    r'Squeeze bottles:.*',
    r'STOVETOP:.*',
    r'Walkingpad:.*',
]


def clean_recipe_text_input(text: str) -> str:
    """
    Strips promotional links, affiliate equipment, social handles,
    and boilerplate before passing text to extraction engines.
    """
    if not text:
        return ""

    lines = text.splitlines()
    clean_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append("")
            continue

        lower = stripped.lower()

        # Stop at disclaimers
        if "disclaimer:" in lower:
            break

        # Check marketing headers
        if any(h in lower for h in [
            "follow my live", "my patreon", "socials:", "everything i cook",
            "amazon links:", "diet cookbook", "kochbuch", "knife:", "walkingpad:",
            "midea flexify", "check the link in my description", "subscribe for more"
        ]):
            continue

        # Skip URLs and product store links
        if "http://" in lower or "https://" in lower or "amzn.to" in lower or "payhip.com" in lower or "felu.co" in lower:
            continue

        # Skip horizontal dividers
        if re.match(r'^(?:[-=_*~]{3,})$', stripped):
            continue

        clean_lines.append(stripped)

    return "\n".join(clean_lines).strip()


def is_valid_food_ingredient(name: str) -> bool:
    """
    Returns True if the string is a valid culinary food ingredient,
    and False if it is equipment, URL, marketing, or macro summary.
    """
    if not name or len(name) < 2 or len(name) > 85:
        return False

    lower = name.lower().strip()

    # Reject headers
    if lower in ["instructions:", "directions:", "steps:", "method:", "preparation:", "ingredients:", "macros:", "nutrition:"]:
        return False

    # Reject URLs / marketing
    if any(term in lower for term in ["http", "payhip", "amzn", "felu", "patreon", "twitch", "cookbook", "kochbuch", "walkingpad"]):
        return False

    # Reject equipment unless qualified with food (e.g. "cooking spray", "olive oil")
    equipment_words = ["knife", "pan", "blender", "scale", "air fryer", "stovetop", "container", "peeler", "bottle"]
    for eq in equipment_words:
        if eq in lower:
            if not any(food in lower for food in ["oil", "spray", "butter", "egg", "chicken", "beef", "flour", "milk", "cheese"]):
                return False

    # Reject pure numbers or macro strings (e.g. "54 C", "46CC, 32F, 53P")
    if re.match(r'^(?:\d+\s*(?:c|f|p|cc|kcal|cals?|g)?|\d+/\d+|\d+\s*of\s*\d+.*)$', lower):
        return False

    return True


def translate_description_if_needed(text: str) -> str:
    """
    Detect if the text is predominantly non-English (e.g. Greek) and, if so,
    translate the entire block to English.
    """
    if not text:
        return text

    has_greek = bool(re.search(r'[\u0370-\u03ff\u1f00-\u1fff]', text))
    alpha_chars = [c for c in text if c.isalpha()]
    non_ascii_ratio = sum(1 for c in alpha_chars if ord(c) > 127) / max(len(alpha_chars), 1)

    if not has_greek and non_ascii_ratio < 0.3:
        return text

    try:
        from translate import Translator
        MAX_CHUNK = 450
        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', text)
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 > MAX_CHUNK:
                if current:
                    chunks.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip() if current else sentence
        if current:
            chunks.append(current.strip())

        if has_greek:
            translator = Translator(from_lang="el", to_lang="en")
        else:
            translator = Translator(to_lang="en")
            
        translated_parts = []
        for chunk in chunks:
            try:
                translated = translator.translate(chunk)
                if translated and "MYMEMORY WARNING" not in translated:
                    translated_parts.append(translated)
                else:
                    translated_parts.append(chunk)
            except Exception:
                translated_parts.append(chunk)

        translated_text = " ".join(translated_parts)
        logger.info("Translated description to English (%d chars)", len(translated_text))
        return f"{text}\n\n[English Translation]\n{translated_text}"
    except Exception as exc:
        logger.warning("Description translation failed: %s", exc)
        return text


def parse_recipe_with_llm(text: str) -> dict:
    """
    High-precision recipe extraction pipeline using Gemini / OpenAI / Groq / Ollama,
    with automatic noise pre-cleaning and fallback NLP Food-NER extraction.
    """
    if not text:
        return {"is_recipe": False, "title": "", "ingredients": [], "instructions": []}

    # Step 1: Pre-clean raw input text
    cleaned_input = clean_recipe_text_input(text)
    if not cleaned_input:
        cleaned_input = text

    prompt = (
        "You are an expert culinary AI specializing in recipe extraction.\n"
        "Analyze the following text and extract the food recipe.\n\n"
        "STRICT EXTRACTION RULES:\n"
        "1. Extract ONLY actual food ingredients (e.g. meat, poultry, seafood, dairy, vegetables, grains, spices, oils, liquids).\n"
        "2. STRICTLY EXCLUDE: affiliate links, URLs, kitchen tools/equipment (knives, pans, blenders, scales), cookbook/product promotions, macro summaries (e.g. '53g protein', '674 cals'), and channel ads.\n"
        "3. For each ingredient, extract the specific edible name and standard quantity (e.g. '300g chicken breast', '2 tbsp olive oil', '1 tsp salt').\n"
        "4. Extract clear, numbered, step-by-step cooking instructions in chronological order.\n"
        "5. Output valid JSON ONLY in this exact structure:\n"
        "{\n"
        '  "is_recipe": true,\n'
        '  "title": "Recipe Title",\n'
        '  "ingredients": [\n'
        '    {"name": "chicken breast", "quantity": "300g"},\n'
        '    {"name": "olive oil", "quantity": "1 tbsp"}\n'
        '  ],\n'
        '  "instructions": [\n'
        '    "Step 1 text",\n'
        '    "Step 2 text"\n'
        '  ]\n'
        "}\n\n"
        "If the text does NOT contain any cooking recipe, respond with:\n"
        '{"is_recipe": false, "title": "", "ingredients": [], "instructions": []}\n\n'
        f"Input Text:\n{cleaned_input[:5000]}"
    )

    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    groq_api_key = os.environ.get("GROQ_API_KEY")

    raw_text = ""

    # 1. Google Gemini API (Free tier from aistudio.google.com)
    if gemini_api_key:
        for gemini_model in ("gemini-2.0-flash", "gemini-1.5-flash"):
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={gemini_api_key}"
            payload = _json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1}
            }).encode("utf-8")
            req = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        raw_text = parts[0].get("text", "").strip()
                        break
            except Exception as e:
                logger.warning("Gemini model '%s' failed: %s", gemini_model, e)

    # 2. OpenAI API
    if not raw_text and openai_api_key:
        payload = _json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {openai_api_key}"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices:
                raw_text = choices[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.warning("OpenAI parsing failed: %s", e)

    # 3. Groq API
    if not raw_text and groq_api_key:
        groq_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-32b", "openai/gpt-oss-120b", "groq/compound-mini"]
        for model_name in groq_models:
            payload = _json.dumps({
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {groq_api_key}"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    response_data = _json.loads(resp.read().decode("utf-8"))
                choices = response_data.get("choices", [])
                if choices:
                    raw_text = choices[0].get("message", {}).get("content", "").strip()
                    break
            except Exception as e:
                logger.warning("Groq model '%s' failed: %s", model_name, e)

    # 4. Ollama Local LLM fallback
    if not raw_text:
        try:
            import config
            base_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
            model = getattr(config, "OLLAMA_MODEL", "llama3.1")
            payload = _json.dumps({
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            }).encode("utf-8")
            endpoint = f"{base_url.rstrip('/')}/api/generate"
            req = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=8) as resp:
                response_data = _json.loads(resp.read().decode("utf-8"))
            raw_text = response_data.get("response", "").strip()
        except Exception:
            pass

    # Parse JSON output from LLM
    if raw_text:
        match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
        if match:
            try:
                result = _json.loads(match.group(1))
                if result.get("is_recipe"):
                    # Validate & sanitize ingredients
                    result["ingredients"] = sanitize_ingredients(result.get("ingredients", []))
                    return result
            except Exception:
                pass

    # Step 5: Fallback to rule-based Food-NER extractor
    return fallback_parse_recipe(cleaned_input)


def fallback_parse_recipe(text: str) -> dict:
    """
    Robust rule-based recipe extractor with Food Entity Recognition heuristics.
    """
    if not text:
        return {"is_recipe": False, "title": "", "ingredients": [], "instructions": []}

    from ingredient_parser import parse_ingredient

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ingredients = []
    instructions = []
    title = ""

    in_instructions = False

    qty_regex = re.compile(
        r'^(?:(?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|portion|portions)?\b|salt\b|pepper\b|black pepper\b|seasonings?\b)',
        re.IGNORECASE
    )

    for line in lines:
        lower = line.lower()

        # Section triggers
        if re.match(r'^(?:instructions?|directions?|steps?|method|εκτέλεση|εκτελεση)[:\-\s]*$', lower):
            in_instructions = True
            continue
        elif re.match(r'^(?:ingredients?|υλικά|υλικα)[:\-\s]*$', lower):
            in_instructions = False
            continue

        # Skip macros header line
        if re.match(r'^(?:macros|nutrition|calories|servings|serving size)[:\s]', lower):
            continue

        # Check for instruction sentences
        if in_instructions or (len(ingredients) > 0 and len(line) > 55 and (line.endswith('.') or line.endswith('!') or any(kw in lower for kw in ['mix', 'bake', 'heat', 'cook', 'add', 'serve', 'pan', 'oven', 'air fry', 'blend', 'whisk']))):
            in_instructions = True
            step = re.sub(r'^(?:step\s*\d+[:\-\.]\s*|\d+[\.\)]\s*|[-•*]\s*)', '', line).strip()
            if len(step) > 8 and not step.startswith('---') and "disclaimer" not in step.lower():
                instructions.append(step)
            continue

        # Try parsing line as ingredient
        if qty_regex.match(line) or (len(line) < 50 and not line.endswith('.')):
            # Try ingredient_parser
            parsed_name = ""
            parsed_qty = "1"
            try:
                parsed = parse_ingredient(line)
                has_amount = parsed and parsed.amount and len(parsed.amount) > 0
                has_name = parsed and parsed.name and len(parsed.name) > 0

                if has_amount and has_name:
                    parsed_name = " ".join([n.text for n in parsed.name]).strip()
                    parsed_qty = " ".join([a.text for a in parsed.amount]).strip()
            except Exception:
                pass

            if not parsed_name:
                m = re.match(r'^((?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|portion|portions)?)\s*(?:of\s+)?(.*)$', line, re.IGNORECASE)
                if m:
                    parsed_qty = m.group(1).strip()
                    parsed_name = m.group(2).strip()
                elif len(line) < 40 and not line.endswith('.'):
                    parsed_name = line
                    parsed_qty = "1"

            if is_valid_food_ingredient(parsed_name):
                ingredients.append({"name": parsed_name, "quantity": parsed_qty or "1"})
        else:
            if len(line) > 15 and not line.startswith('---'):
                instructions.append(line)

    # Post-process instructions
    if len(instructions) == 0:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if s.strip()]
        for s in sentences:
            if len(s) > 25 and any(kw in s.lower() for kw in ['bake', 'cook', 'mix', 'heat', 'pan', 'oven', 'air fryer', 'stir', 'add', 'serve', 'bowl', 'blend', 'fridge']):
                instructions.append(s)

    sanitized_ings = sanitize_ingredients(ingredients)

    return {
        "is_recipe": len(sanitized_ings) >= 1,
        "title": title or "Extracted Recipe",
        "ingredients": sanitized_ings,
        "instructions": instructions
    }


def sanitize_ingredients(ingredients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Sanitize and filter ingredient list to guarantee only valid food items remain.
    """
    sanitized = []
    seen = set()

    for ing in ingredients:
        name = ing.get("name", "").strip()
        qty = ing.get("quantity", "")
        qty_str = str(qty).strip() if qty is not None else ""

        if not is_valid_food_ingredient(name):
            continue

        # Check numeric quantity
        has_numeric = any(char.isdigit() or ('\u00bc' <= char <= '\u00be') or ('\u2150' <= char <= '\u2189') for char in qty_str)
        if not has_numeric:
            qty_str = "1"

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        sanitized.append({
            "name": name,
            "quantity": qty_str
        })

    return sanitized
