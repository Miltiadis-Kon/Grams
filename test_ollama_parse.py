#!/usr/bin/env python
"""
test_ollama_parse.py
====================
Standalone test: supply a transcript (from a file or a built-in sample) and
call the local Ollama API to extract recipe data.

This does NOT modify any database and does NOT call Supadata.
Ollama must be running locally on the configured port (default: 11434).

Usage:
    # Use the built-in sample recipe transcript
    python test_ollama_parse.py

    # Use a specific transcript file
    python test_ollama_parse.py --transcript-file path/to/transcript.txt

    # Pass transcript inline
    python test_ollama_parse.py --transcript "your raw transcript text here"

    # Test with a non-recipe transcript to verify rejection logic
    python test_ollama_parse.py --non-recipe
"""

import argparse
import json
import re
import sys
import logging
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_ollama_parse")

# ── Built-in sample transcripts ───────────────────────────────────────────────

SAMPLE_RECIPE_TRANSCRIPT = """
Hey guys, welcome back! Today I'm making my go-to high protein chicken bowl.
You'll need about 200 grams of chicken breast, diced. Season it with salt,
pepper, one teaspoon of garlic powder and paprika. Cook it in a pan with
one tablespoon of olive oil for about 8 minutes until golden.

Meanwhile, cook 150 grams of white rice. For the sauce, mix together
two tablespoons of Greek yogurt, one tablespoon of lemon juice, half a
teaspoon of cumin and a pinch of chilli flakes.

In a bowl, layer the rice, top with the chicken, drizzle the sauce and
add some cherry tomatoes and cucumber slices on the side. This meal gives
you around 45 grams of protein, 60 grams of carbs and only 8 grams of fat.
About 480 calories total. Perfect for meal prep — store in the fridge for
up to 4 days. Enjoy!
"""

SAMPLE_NON_RECIPE_TRANSCRIPT = """
What's up everyone, it's me again. So today I wanted to talk about my
morning routine and how I've been optimising my productivity. I wake up at
5 AM, do 20 minutes of stretching, then I journal for 10 minutes. After that
I check my emails and plan my day. I've been doing this for 3 months and my
output has literally doubled. Let me know in the comments if you want a full
breakdown of my productivity system. Don't forget to like and subscribe!
"""

# ─────────────────────────────────────────────────────────────────────────────


def call_ollama(text: str, base_url: str, model: str) -> dict:
    """Send text to local Ollama and return parsed JSON dict."""

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
        '  "macros": {\n'
        '    "protein": 0.0,\n'
        '    "carbs": 0.0,\n'
        '    "fats": 0.0,\n'
        '    "calories": 0\n'
        '  }\n'
        "}\n\n"
        "If it is NOT a recipe (e.g. fitness tips, general talking, product review, travel), respond with:\n"
        "{\n"
        '  "is_recipe": false,\n'
        '  "title": "",\n'
        '  "ingredients": [],\n'
        '  "macros": {\n'
        '    "protein": 0.0,\n'
        '    "carbs": 0.0,\n'
        '    "fats": 0.0,\n'
        '    "calories": 0\n'
        '  }\n'
        "}\n\n"
        "IMPORTANT instructions for macros calculation:\n"
        "- If the macro-nutrients (protein, carbs, fats, calories) are explicitly mentioned in the text, extract them.\n"
        "- If they are not mentioned, estimate the macronutrients and calories as accurately as possible based on the ingredients list and quantities.\n"
        "- The values for protein, carbs, fats must be numbers in grams. calories must be an integer representing kcal.\n"
        "- Output ONLY the raw JSON block. Do not include markdown code blocks, do not include any preamble, introduction, or explanation.\n\n"
        f"Text:\n{text[:6000]}"
    )

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode("utf-8")

    endpoint = f"{base_url.rstrip('/')}/api/generate"
    logger.info("Calling Ollama at %s  model=%s", endpoint, model)

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {endpoint}. "
            "Make sure Ollama is running: `ollama serve`"
        ) from exc

    raw_text = response_data.get("response", "").strip()
    logger.info("Raw Ollama response (%d chars): %s...", len(raw_text), raw_text[:120])

    # Find the JSON object starting with { and ending with }
    match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if match:
        raw_text = match.group(1)

    return json.loads(raw_text)


def main():
    parser = argparse.ArgumentParser(description="Test Ollama recipe parsing (no DB write)")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Ollama base URL (default: read from config.OLLAMA_BASE_URL or http://localhost:11434)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model to use (default: read from config.OLLAMA_MODEL or llama3.1)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--transcript-file",
        metavar="FILE",
        help="Path to a plain-text file containing the transcript",
    )
    group.add_argument(
        "--transcript",
        metavar="TEXT",
        help="Raw transcript text string",
    )
    group.add_argument(
        "--non-recipe",
        action="store_true",
        help="Use the built-in non-recipe sample to test rejection logic",
    )
    args = parser.parse_args()

    # ── Resolve config ──────────────────────────────────────────────────────
    try:
        import config
        base_url = args.base_url or getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
        model = args.model or getattr(config, "OLLAMA_MODEL", "llama3.1")
    except ImportError:
        base_url = args.base_url or "http://localhost:11434"
        model = args.model or "llama3.1"

    logger.info("Ollama base URL : %s", base_url)
    logger.info("Model           : %s", model)

    # ── Resolve transcript text ──────────────────────────────────────────────
    if args.transcript_file:
        with open(args.transcript_file, "r", encoding="utf-8") as f:
            transcript = f.read().strip()
        logger.info("Loaded transcript from file: %s (%d chars)", args.transcript_file, len(transcript))
    elif args.transcript:
        transcript = args.transcript.strip()
        logger.info("Using transcript from --transcript flag (%d chars)", len(transcript))
    elif args.non_recipe:
        transcript = SAMPLE_NON_RECIPE_TRANSCRIPT.strip()
        logger.info("Using built-in NON-RECIPE sample transcript")
    else:
        transcript = SAMPLE_RECIPE_TRANSCRIPT.strip()
        logger.info("Using built-in RECIPE sample transcript")

    print("\n" + "=" * 70)
    print("TRANSCRIPT PREVIEW (first 300 chars):")
    print("=" * 70)
    print(transcript[:300])
    if len(transcript) > 300:
        print(f"... ({len(transcript)} total chars)")

    print("\n" + "=" * 70)
    print(f"CALLING OLLAMA  [{model}]")
    print("=" * 70)

    try:
        result = call_ollama(transcript, base_url, model)
    except json.JSONDecodeError as exc:
        print(f"\n❌  Failed to parse Ollama output as JSON: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌  Ollama call failed: {exc}")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("OLLAMA RESULT:")
    print("=" * 70)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    is_recipe = result.get("is_recipe", False)
    title = result.get("title", "")
    ingredients = result.get("ingredients", [])
    macros = result.get("macros", {})

    print()
    if is_recipe:
        print("✅  IS RECIPE : Yes")
        print(f"📋  Title     : {title}")
        print(f"🥦  Ingredients ({len(ingredients)}):")
        for ing in ingredients:
            print(f"      - {ing.get('quantity', '')} {ing.get('name', '')}")
        print(f"📊  Macros:")
        print(f"      Protein  : {macros.get('protein', 0.0)}g")
        print(f"      Carbs    : {macros.get('carbs', 0.0)}g")
        print(f"      Fats     : {macros.get('fats', 0.0)}g")
        print(f"      Calories : {macros.get('calories', 0)} kcal")
    else:
        print("🚫  IS RECIPE : No — Ollama identified this as non-recipe content.")
        print("     → This video would be routed to not_added_recipes.json")


if __name__ == "__main__":
    main()
