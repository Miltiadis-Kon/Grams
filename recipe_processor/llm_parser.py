import re
import os
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

    raw_text = ""
    if groq_api_key:
        logger.info("GROQ_API_KEY detected. Directing parsing request to Groq API.")
        payload = _json.dumps({
            "model": "llama-3.3-70b-versatile",
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

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                response_data = _json.loads(resp.read().decode("utf-8"))
            choices = response_data.get("choices", [])
            if not choices:
                raise ValueError("Groq returned an empty choice list")
            raw_text = choices[0].get("message", {}).get("content", "").strip()
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                err_body = "(could not read body)"
            logger.warning("Groq API parsing failed with HTTP Error %d (%s): %s. Falling back to local Ollama if available.", e.code, e.reason, err_body)
            groq_api_key = None
        except Exception as e:
            logger.warning("Groq API parsing failed: %s. Falling back to local Ollama if available.", e)
            groq_api_key = None

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

        with urllib.request.urlopen(req, timeout=300) as resp:
            response_data = _json.loads(resp.read().decode("utf-8"))

        raw_text = response_data.get("response", "").strip()

    match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if match:
        raw_text = match.group(1)

    return _json.loads(raw_text)


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
