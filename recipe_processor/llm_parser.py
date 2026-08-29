import re
import os
import time
import json as _json
import urllib.request
import urllib.error
import logging
from typing import Any

logger = logging.getLogger(__name__)

def translate_description_if_needed(text: str) -> str:
    """
    Detect if the text is predominantly non-English (e.g. Greek) and, if so,
    translate the entire block to English so the ingredient parser can work on it.
    The original text is preserved and the translation is appended.
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
    Call the Groq API (or Ollama API fallback) to parse a text block
    into structured recipe data, including ingredients and instructions.
    """
    groq_api_key = os.environ.get("GROQ_API_KEY")

    prompt = (
        "You are a recipe extraction assistant.\n"
        "Analyse the following text and determine if it contains a food recipe.\n\n"
        "If it IS a recipe, respond with valid JSON only (no markdown, no explanation) "
        "in this exact format:\n"
        "{\n"
        '  "is_recipe": true,\n'
        '  "title": "Recipe Title",\n'
        '  "ingredients": [\n'
        '    {"name": "ingredient 1 name", "quantity": "quantity 1"},\n'
        '    {"name": "ingredient 2 name", "quantity": "quantity 2"}\n'
        '  ],\n'
        '  "instructions": [\n'
        '    "Step 1 text",\n'
        '    "Step 2 text"\n'
        '  ]\n'
        "}\n\n"
        "If it is NOT a recipe (e.g. fitness tips, general talking, product review, travel), respond with:\n"
        "{\n"
        '  "is_recipe": false,\n'
        '  "title": "",\n'
        '  "ingredients": [],\n'
        '  "instructions": []\n'
        "}\n\n"
        "IMPORTANT instructions:\n"
        "- Output ONLY the raw JSON block. Do not include markdown code blocks, do not include any preamble, introduction, or explanation.\n"
        "- The 'instructions' field should be a list of strings, each representing a step in the recipe. Provide them in chronological order.\n\n"
        f"Text:\n{text[:6000]}"
    )

    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    groq_api_key = os.environ.get("GROQ_API_KEY")

    raw_text = ""

    # 1. Google Gemini API (Free tier from aistudio.google.com, VPN-friendly)
    if gemini_api_key:
        logger.info("GEMINI_API_KEY detected. Directing parsing request to Google Gemini.")
        for gemini_model in ("gemini-2.0-flash", "gemini-1.5-flash"):
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={gemini_api_key}"
            payload = _json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1}
            }).encode("utf-8")
            req = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
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
        logger.info("OPENAI_API_KEY detected. Directing parsing request to OpenAI.")
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
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices:
                raw_text = choices[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.warning("OpenAI parsing failed: %s", e)

    # 3. Groq API
    if not raw_text and groq_api_key:
        logger.info("GROQ_API_KEY detected. Directing parsing request to Groq API.")
        groq_models = ["openai/gpt-oss-120b", "groq/compound-mini", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b", "groq/compound"]
        
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
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {groq_api_key}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
                method="POST"
            )

            success = False
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        response_data = _json.loads(resp.read().decode("utf-8"))
                    choices = response_data.get("choices", [])
                    if not choices:
                        raise ValueError("Groq returned an empty choice list")
                    raw_text = choices[0].get("message", {}).get("content", "").strip()
                    success = True
                    break # Success
                except urllib.error.HTTPError as e:
                    try:
                        err_body = e.read().decode("utf-8")
                    except Exception:
                        err_body = "(could not read body)"
                    
                    if e.code == 429:
                        match = re.search(r'try again in (?:(\d+)m)?([\d\.]+)s', err_body)
                        if match:
                            mins = int(match.group(1)) if match.group(1) else 0
                            secs = float(match.group(2))
                            sleep_time = mins * 60 + secs + 1.0
                            logger.warning("Groq API Rate Limit 429 hit for %s. Sleeping for %.1f seconds...", model_name, sleep_time)
                            time.sleep(sleep_time)
                            continue
                    
                    logger.warning("Groq model '%s' failed (%d %s): %s", model_name, e.code, e.reason, err_body)
                    break
                except Exception as e:
                    logger.warning("Groq model '%s' failed: %s", model_name, e)
                    break
            
            if success and raw_text:
                break

    if not groq_api_key:
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

        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                response_data = _json.loads(resp.read().decode("utf-8"))
            raw_text = response_data.get("response", "").strip()
        except Exception as exc:
            logger.info("Ollama LLM unavailable (%s); using rule-based ingredient parser fallback.", exc)
            return fallback_parse_recipe(text)

    match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if match:
        raw_text = match.group(1)

    try:
        return _json.loads(raw_text)
    except Exception:
        return fallback_parse_recipe(text)


def fallback_parse_recipe(text: str) -> dict:
    """
    Rule-based recipe extractor using ingredient-parser and regex heuristics
    when external LLM APIs (Groq/Ollama) are unavailable.
    """
    if not text:
        return {"is_recipe": False, "title": "", "ingredients": [], "instructions": []}

    from ingredient_parser import parse_ingredient

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ingredients = []
    instructions = []
    title = ""

    in_ingredients = False
    in_instructions = False

    for line in lines:
        lower = line.lower()
        if re.match(r'^(?:ingredients?|υλικά|υλικα)[:\-\s]*$', lower):
            in_ingredients = True
            in_instructions = False
            continue
        elif re.match(r'^(?:instructions?|directions?|steps?|method|εκτέλεση|εκτελεση)[:\-\s]*$', lower):
            in_instructions = True
            in_ingredients = False
            continue

        # Check if line looks like an ingredient
        try:
            parsed = parse_ingredient(line)
            has_amount = parsed and parsed.amount and len(parsed.amount) > 0
            has_name = parsed and parsed.name and len(parsed.name) > 0

            if has_amount and has_name:
                ing_name = " ".join([n.text for n in parsed.name]).strip()
                ing_qty = " ".join([a.text for a in parsed.amount]).strip()
                if ing_name:
                    ingredients.append({"name": ing_name, "quantity": ing_qty or "1"})
                    continue
        except Exception:
            pass

        # Check for numbered instruction step
        m_step = re.match(r'^(?:\d+[\.\)]\s*|[-•*]\s*)(.+)$', line)
        if m_step and (in_instructions or len(ingredients) > 0):
            step_text = m_step.group(1).strip()
            if len(step_text) > 10:
                instructions.append(step_text)
                continue

        if not title and not in_ingredients and not in_instructions and len(line) < 80 and not line.startswith('#'):
            title = line

    if len(ingredients) == 0:
        # Fallback for continuous text / spoken transcripts without line breaks
        NON_FOOD_TERMS = {
            "protein", "carbs", "fats", "fat", "calories", "calorie", "kcal", "minutes", "minute", "seconds", "second",
            "hours", "hour", "degrees", "celsius", "fahrenheit", "views", "likes", "subscribers", "video", "recipe",
            "macros", "macro", "portion", "portions", "servings", "serving", "taste", "flavor", "step", "steps"
        }
        phrase_pattern = r'\b(\d+(?:[./]\d+)?\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces)?)\s+(?:of\s+)?([a-zA-Z\s]{3,35}?)(?=\band\b|\bthen\b|\bto\b|\bwith\b|\bfor\b|\bin\b|\binto\b|[,\.\n\(\)]|$)'

        seen_ing_names = set()
        for match in re.finditer(phrase_pattern, text, re.IGNORECASE):
            qty = match.group(1).strip()
            raw_name = match.group(2).strip()
            clean_name = re.sub(r'^(?:fresh|chopped|diced|sliced|ground|low\s+fat|fat\s+free|boneless|skinless)\s+', '', raw_name, flags=re.IGNORECASE).strip()
            name_words = set(clean_name.lower().split())
            if not name_words or name_words.issubset(NON_FOOD_TERMS):
                continue
            if any(term in name_words for term in ["protein", "carbs", "calories", "kcal", "minutes", "seconds", "hours", "degrees"]):
                continue
            if len(clean_name) < 3:
                continue
            if clean_name.lower() not in seen_ing_names:
                seen_ing_names.add(clean_name.lower())
                ingredients.append({"name": raw_name, "quantity": qty or "1"})

    is_recipe = len(ingredients) >= 1
    return {
        "is_recipe": is_recipe,
        "title": title or "Extracted Recipe",
        "ingredients": ingredients,
        "instructions": instructions
    }


def sanitize_ingredients(ingredients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized = []
    for ing in ingredients:
        name = ing.get("name", "").strip()
        qty = ing.get("quantity", "")
        qty_str = str(qty).strip() if qty is not None else ""
        
        has_numeric = False
        for char in qty_str:
            if char.isdigit():
                has_numeric = True
                break
            if '\u00bc' <= char <= '\u00be' or '\u2150' <= char <= '\u2189':
                has_numeric = True
                break
        
        if not has_numeric:
            qty_str = "1"
        
        sanitized.append({
            "name": name,
            "quantity": qty_str
        })
    return sanitized
