"""
Transcript-to-Recipe Extraction Pipeline for Grams.

Architecture:
1. Ingestion & Text Normalization Layer (IngestionNormalizer)
2. Prompt & Schema Orchestration Layer (PromptOrchestrator)
3. Groq LPU Inference Routing & Cloud/Local Fallbacks (InferenceRouter)
4. Validation, Unit Normalization & Cross-Entity Reconciliation (RecipeValidator)
"""

import re
import os
import logging
from typing import Any, List, Dict

from .normalization import IngestionNormalizer
from .inference_router import InferenceRouter
from .validator import RecipeValidator

logger = logging.getLogger(__name__)


def clean_recipe_text_input(text: str) -> str:
    """Wrapper for IngestionNormalizer."""
    return IngestionNormalizer.clean_text(text)


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
        logger.info("Translated text to English (%d chars)", len(translated_text))
        return f"{text}\n\n[English Translation]\n{translated_text}"
    except Exception as exc:
        logger.warning("Description translation failed: %s", exc)
        return text


def parse_recipe_with_llm(text: str) -> Dict[str, Any]:
    """
    Complete 4-Layer Transcript-to-Recipe Extraction Pipeline:
    1. Layer 1: Ingestion & Text Normalization (De-noising, disfluency cleaning, sponsor stripping).
    2. Layer 2 & 3: Prompt & Schema Orchestration + Groq LPU Inference (T=0.0, llama-3.3-70b / llama-3.1-8b).
    3. Layer 4: Validation, Unit Normalization & Cross-Entity Reconciliation.
    """
    if not text:
        return {"is_recipe": False, "title": "", "ingredients": [], "instructions": []}

    # ── Layer 1: Ingestion & Normalization ─────────────────────
    cleaned_text = IngestionNormalizer.clean_text(text)
    if not cleaned_text:
        cleaned_text = text

    # ── Layer 2 & 3: Prompt Orchestration & Groq LPU Inference ──
    raw_payload = InferenceRouter.extract_recipe_json(cleaned_text)

    if raw_payload and raw_payload.get("is_recipe"):
        # ── Layer 4: Validation & Reconciliation ───────────────
        reconciled = RecipeValidator.reconcile_recipe_payload(raw_payload)
        if reconciled.get("is_recipe") and reconciled.get("ingredients"):
            return reconciled

    # Fallback to specialized NLP Food-NER parser if LLM offline
    logger.info("Using Food-NER NLP fallback extractor for recipe parsing.")
    fallback_raw = fallback_parse_recipe(cleaned_text)
    return RecipeValidator.reconcile_recipe_payload(fallback_raw)


def fallback_parse_recipe(text: str) -> Dict[str, Any]:
    """
    Specialized Fallback Food Entity Recognition & Recipe Extractor
    using ingredient-parser and regex heuristics.
    """
    if not text:
        return {"is_recipe": False, "title": "", "ingredients": [], "instructions": []}

    from ingredient_parser import parse_ingredient

    # Pre-process and normalize delimiters often found in TikTok / Instagram posts
    norm_text = text
    # Convert inline bullets (' - ', ' • ', ' * ') to newlines
    norm_text = re.sub(r'\s*[\-•*]\s+', '\n- ', norm_text)
    # Split section headers into separate lines
    norm_text = re.sub(r'(?i)\b(ingredients?|υλικά|υλικα|instructions?|directions?|method|steps?|εκτέλεση|εκτελεση|key points?|notes?|servings?|portion)[:\s]+', r'\n\1:\n', norm_text)
    # Split numbered steps (e.g. "1. Cut the chicken... 2. Heat oil...")
    norm_text = re.sub(r'(?<=[.!?])\s+(?=\d+[\.\)]\s+[A-Z0-9])', '\n', norm_text)

    lines = [line.strip() for line in norm_text.splitlines() if line.strip()]
    ingredients = []
    instructions = []
    title = ""

    in_instructions = False

    qty_regex = re.compile(
        r'^(?:(?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|portion|portions|splash|glug|handful)?\b|salt\b|pepper\b|black pepper\b|seasonings?\b)',
        re.IGNORECASE
    )

    for line in lines:
        lower = line.lower()

        # Skip translation and transcript metadata headers
        if line.startswith('[') and line.endswith(']'):
            continue

        # Skip call-to-action / engagement prompts
        if any(cta in lower for cta in [
            "save this recipe", "like and subscribe", "leave a heart", "follow for more",
            "αν σου άρεσε", "κάνε 1", "αποθήκευσε", "subscribe", "follow me", "link in bio"
        ]):
            continue

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

        # Clean leading bullet or numbering markers
        clean_line = re.sub(r'^(?:[-•*:]\s*|\d+[\.\)]\s*)', '', line).strip()
        clean_lower = clean_line.lower()

        # Check for instruction sentences
        if in_instructions or (len(ingredients) > 0 and len(clean_line) > 55 and (clean_line.endswith('.') or clean_line.endswith('!') or any(kw in clean_lower for kw in ['mix', 'bake', 'heat', 'cook', 'add', 'serve', 'pan', 'oven', 'air fry', 'blend', 'whisk']))):
            in_instructions = True
            step = clean_line
            if len(step) > 8 and not step.startswith('---') and "disclaimer" not in step.lower():
                instructions.append(step)
            continue

        # Handle 'Name: Quantity' pattern (e.g. 'Chicken thighs: 120g', 'Udon noodles: 1 pack (150g)', 'Salt: a pinch')
        if ":" in clean_line and not any(k in clean_lower for k in ["http", "servings", "method", "ingredients", "instructions", "notes", "disclaimer"]):
            parts = clean_line.split(":", 1)
            p_name = parts[0].strip()
            p_qty = parts[1].strip()
            # Clean trailing brackets/emojis from qty
            p_qty = re.sub(r'\[.*?\]|[^\x00-\x7F]+', '', p_qty).strip()
            if RecipeValidator.is_valid_food_name(p_name):
                ingredients.append({"name": p_name, "quantity": p_qty or "1"})
                continue

        # Try parsing line as ingredient
        if qty_regex.match(clean_line) or (len(clean_line) < 50 and not clean_line.endswith('.')):
            parsed_name = ""
            parsed_qty = "1"
            try:
                parsed = parse_ingredient(clean_line)
                has_amount = parsed and parsed.amount and len(parsed.amount) > 0
                has_name = parsed and parsed.name and len(parsed.name) > 0

                if has_amount and has_name:
                    parsed_name = " ".join([n.text for n in parsed.name]).strip()
                    parsed_qty = " ".join([a.text for a in parsed.amount]).strip()
            except Exception:
                pass

            if not parsed_name:
                m = re.match(r'^((?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|portion|portions|splash|glug|handful)?)\s*(?:of\s+)?(.*)$', clean_line, re.IGNORECASE)
                if m:
                    parsed_qty = m.group(1).strip()
                    parsed_name = m.group(2).strip()
                elif len(clean_line) < 40 and not clean_line.endswith('.'):
                    parsed_name = clean_line
                    parsed_qty = "1"

            if RecipeValidator.is_valid_food_name(parsed_name):
                ingredients.append({"name": parsed_name, "quantity": parsed_qty or "1"})
        else:
            if len(clean_line) > 15 and not clean_line.startswith('---'):
                instructions.append(clean_line)

    # In-line entity hunting for narrative transcripts where ingredients are spoken within sentences
    if len(ingredients) < 3:
        phrase_pattern = r'\b((?:(?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|splash|glug|handful)?|a\s+(?:pinch|splash|glug|handful|drizzle|dash))\s+(?:of\s+)?)([a-zA-Z\s]{3,35}?)(?=\band\b|\bthen\b|\bto\b|\bwith\b|\bfor\b|\bin\b|\binto\b|[,\.\n\(\)]|$)'
        seen_names = {i["name"].lower() for i in ingredients}
        for match in re.finditer(phrase_pattern, text, re.IGNORECASE):
            qty = match.group(1).strip()
            raw_name = match.group(2).strip()
            clean_name = re.sub(r'^(?:fresh|chopped|diced|sliced|ground|extra\s+lean|lean|low\s+fat|fat\s+free|boneless|skinless|grated|melted)\s+', '', raw_name, flags=re.IGNORECASE).strip()
            if RecipeValidator.is_valid_food_name(clean_name) and clean_name.lower() not in seen_names:
                # Avoid non-food verbal verbs (e.g. "minutes until", "seconds to")
                if any(kw in clean_name.lower() for kw in ["minute", "second", "hour", "degree", "oven", "pan", "channel", "video", "bowl", "plate"]):
                    continue
                seen_names.add(clean_name.lower())
                ingredients.append({"name": raw_name, "quantity": qty or "1"})

    # Post-process instructions
    if len(instructions) == 0:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if s.strip()]
        for s in sentences:
            if len(s) > 25 and any(kw in s.lower() for kw in ['bake', 'cook', 'mix', 'heat', 'pan', 'oven', 'air fryer', 'stir', 'add', 'serve', 'bowl', 'blend', 'fridge']):
                instructions.append(s)

    valid_ingredients = [
        i for i in ingredients
        if RecipeValidator.is_valid_food_name(i.get("name", ""))
    ]

    has_valid_recipe = (
        len(valid_ingredients) >= 2 or
        (len(valid_ingredients) == 1 and valid_ingredients[0].get("quantity") != "1")
    )

    return {
        "is_recipe": has_valid_recipe,
        "title": title or "Extracted Recipe",
        "ingredients": valid_ingredients,
        "instructions": instructions
    }


def sanitize_ingredients(ingredients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Backward compatibility helper."""
    dummy_payload = {
        "is_recipe": True,
        "title": "",
        "ingredients": ingredients,
        "instructions": []
    }
    reconciled = RecipeValidator.reconcile_recipe_payload(dummy_payload)
    return reconciled.get("ingredients", [])
