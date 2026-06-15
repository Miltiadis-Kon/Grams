"""
Incremental sync pipeline with delta handling.

Before calling the nutrition analyzer or tagger, cross-references each
incoming recipe ID against the existing database. If the ID already exists,
all processing is skipped entirely — achieving O(1) deduplication.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

from database import RecipeDatabase, MacroNutrients, Recipe
from .nutrition import NutritionAnalyzer
from .tagger import AutoTagger

logger = logging.getLogger(__name__)


class SyncPipeline:
    """
    Orchestrates the ingestion flow for individual recipe payloads:
    1. Delta check (skip if exists in main or not-added database)
    2. Try to parse ingredients from description/title
    3. If ingredients found → save the recipe
    4. If not → fetch transcript via Supadata API
    5. Use Gemini API to parse the transcript and extract recipe data
    6. Build Recipe object and auto-tag
    7. Database insertion (route to main if filled, otherwise to not-added)
    """

    def __init__(
        self,
        database: RecipeDatabase,
        not_added_database: RecipeDatabase,
        nutrition_analyzer: NutritionAnalyzer,
        tagger: AutoTagger,
    ) -> None:
        self._db = database
        self._not_added_db = not_added_database
        self._nutrition = nutrition_analyzer
        self._tagger = tagger

    @staticmethod
    def _translate_description_if_needed(text: str) -> str:
        """
        Detect if the text is predominantly non-English (e.g. Greek) and, if so,
        translate the entire block to English so the ingredient parser can work on it.
        The original text is preserved and the translation is appended.
        """
        if not text:
            return text

        # Detect Greek (or other non-Latin) characters
        has_greek = bool(re.search(r'[\u0370-\u03ff\u1f00-\u1fff]', text))
        # Also detect if the bulk of alphabetic chars are non-ASCII (covers Italian, etc.)
        alpha_chars = [c for c in text if c.isalpha()]
        non_ascii_ratio = sum(1 for c in alpha_chars if ord(c) > 127) / max(len(alpha_chars), 1)

        if not has_greek and non_ascii_ratio < 0.3:
            return text  # Already mostly English, no translation needed

        try:
            from translate import Translator
            # Chunk into pieces ≤ 500 chars to stay within MyMemory free limit
            MAX_CHUNK = 450
            chunks = []
            # Split by sentences first to avoid breaking mid-word
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
                    # MyMemory returns "MYMEMORY WARNING" when limit is hit
                    if translated and "MYMEMORY WARNING" not in translated:
                        translated_parts.append(translated)
                    else:
                        translated_parts.append(chunk)  # keep original on error
                except Exception:
                    translated_parts.append(chunk)

            translated_text = " ".join(translated_parts)
            logger.info("Translated description to English (%d chars)", len(translated_text))
            # Append the English translation after the original so both are stored
            return f"{text}\n\n[English Translation]\n{translated_text}"
        except Exception as exc:
            logger.warning("Description translation failed: %s", exc)
            return text

    @staticmethod
    def _parse_recipe_with_ollama(text: str) -> dict:
        """
        Call the Ollama API (or Groq API if GROQ_API_KEY is in environment) to parse a text block (description or transcript)
        into structured recipe data, including ingredients and estimated macros.

        Returns a dict with keys: 'is_recipe' (bool), 'title' (str), 'ingredients' (list of dicts),
        and 'macros' (dict with protein, carbs, fats, calories).
        """
        import os
        import json as _json
        import urllib.request
        import urllib.error

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
            "- If they are not mentioned, set all macro values to 0.0 / 0. DO NOT estimate them under any circumstances.\n"
            "- The values for protein, carbs, fats must be numbers in grams. calories must be an integer representing kcal.\n"
            "- Output ONLY the raw JSON block. Do not include markdown code blocks, do not include any preamble, introduction, or explanation.\n\n"
            f"Text:\n{text[:6000]}"
        )

        raw_text = ""
        if groq_api_key:
            logger.info("GROQ_API_KEY detected. Directing parsing request to Groq API.")
            payload = _json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
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

        # Find the JSON object starting with { and ending with }
        match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)

        return _json.loads(raw_text)

    # ── Processing ────────────────────────────────────────────────────────────

    def process(
        self,
        recipe_id: str,
        name: str,
        url: str,
        description: str,
        manual_tags: Optional[list[str]] = None,
    ) -> bool | None:
        """
        Process a single recipe payload through the full pipeline.

        New flow:
          1. Delta check — skip if already processed.
          2. Try to parse ingredients and macros from the description/title using Ollama.
          3. If recipe/ingredients found → save the recipe.
          4. If not → fetch transcript via Supadata.
          5. Parse transcript with Ollama.
             If Ollama confirms it's a recipe → save; otherwise → not-added.

        Returns:
          True: Recipe was newly added to recipes_db.json
          False: Recipe already processed (skipped)
          None: Recipe had no data and was saved to not_added_recipes.json for manual check
        """
        # ── Step 1: Delta check ──────────────────────
        if self._db.exists(recipe_id):
            logger.info("SKIP: Recipe '%s' (%s) already in main database", recipe_id, name)
            return False

        if self._not_added_db.exists(recipe_id):
            existing = self._not_added_db.get(recipe_id)
            desc = ""
            if existing:
                if isinstance(existing, dict):
                    desc = existing.get("description", "")
                else:
                    desc = getattr(existing, "description", "")
            if "[Transcript]" in desc or "Transcript fetch failed" in desc or "[Ollama]" in desc:
                logger.info("SKIP: Recipe '%s' (%s) already processed and fallback attempted", recipe_id, name)
                return False
            else:
                logger.info("RE-PROCESSING: Recipe '%s' (%s) from manual check list", recipe_id, name)

        # ── Step 2: Try to parse ingredients from description using Ollama ───
        description = self._translate_description_if_needed(description)

        macros = MacroNutrients()
        ingredients = []
        has_ingredients = False

        logger.info("Parsing description with Ollama for '%s'...", recipe_id)
        try:
            llm_result = self._parse_recipe_with_ollama(description)
            if llm_result.get("is_recipe"):
                llm_title = llm_result.get("title", "").strip()
                llm_ingredients = llm_result.get("ingredients", [])
                if llm_title and llm_title != name and "TikTok Video" in name:
                    name = llm_title
                
                if llm_ingredients:
                    ingredients = llm_ingredients
                    has_ingredients = True
                    macros = self._nutrition.analyze_ingredients(ingredients, description_for_servings=description)
                    logger.info("Ollama identified recipe in description for '%s' with %d ingredients. Calculated macros: P:%.1f C:%.1f F:%.1f Cal:%d",
                                recipe_id, len(ingredients), macros.protein, macros.carbs, macros.fats, macros.calories)
                    description = f"{description}\n\n[Ollama Parsed Ingredients & Macros]"
            else:
                logger.info("Ollama determined description for '%s' is NOT a recipe", recipe_id)
        except Exception as exc:
            logger.error("Ollama description parsing failed for '%s': %s", recipe_id, exc)

        # ── Step 3: If ingredients found → save ──────────────────────────────
        if has_ingredients:
            logger.info("Ingredients found in description for '%s'. Proceeding to save.", recipe_id)
        else:
            # ── Step 4: Fetch transcript from Supadata ───────────────────────
            logger.info("No ingredients in description for '%s'. Fetching Supadata transcript...", recipe_id)
            transcript_text = None
            try:
                import config as _config
                supadata_key = getattr(_config, "SUPADATA_API_KEY", None)
                if not supadata_key:
                    raise ValueError("SUPADATA_API_KEY is not defined in config.py")
                from supadata import Supadata

                client = Supadata(api_key=supadata_key)
                transcript = client.transcript(url=url, text=True, mode="auto")
                if hasattr(transcript, 'content') and transcript.content:
                    transcript_text = transcript.content.strip()
                    logger.info("Supadata transcript fetched (%d chars): %s...", len(transcript_text), transcript_text[:80])
                    # Translate transcript text first before prepending label
                    translated_desc = self._translate_description_if_needed(transcript_text)
                    description = f"[Transcript]\n{translated_desc}"
                else:
                    logger.warning("Supadata returned empty transcript for: %s", url)
                    if description and "Transcript fetch failed" not in description:
                        description = f"{description}\n\n[Transcript fetch failed: empty content]"
                    else:
                        description = "[Transcript fetch failed: empty content]"
            except Exception as supadata_exc:
                logger.error("Supadata transcript fetch failed: %s", supadata_exc)
                if description:
                    description = f"{description}\n\n[Transcript fetch failed: {supadata_exc}]"
                else:
                    description = f"[Transcript fetch failed: {supadata_exc}]"

            # ── Step 5: Parse transcript with Ollama ─────────────────────────
            if transcript_text:
                logger.info("Parsing transcript with Ollama for '%s'...", recipe_id)
                try:
                    # We should parse the translated description so Ollama has the English context
                    llm_result = self._parse_recipe_with_ollama(description)
                    if llm_result.get("is_recipe"):
                        llm_title = llm_result.get("title", "").strip()
                        llm_ingredients = llm_result.get("ingredients", [])
                        if llm_title and llm_title != name and "TikTok Video" in name:
                            name = llm_title
                        logger.info(
                            "Ollama identified recipe from transcript '%s' with %d ingredient(s)",
                            name, len(llm_ingredients),
                        )
                        ingredients = llm_ingredients
                        # Always compute macros using OpenNutrition
                        macros = self._nutrition.analyze_ingredients(ingredients, description_for_servings=description)
                        description = f"{description}\n\n[Ollama Parsed Ingredients & Macros]"
                    else:
                        logger.info("Ollama determined transcript for '%s' is NOT a recipe. Routing to not-added.", recipe_id)
                        description = f"{description}\n\n[Ollama: not a recipe]"
                except Exception as llm_exc:
                    logger.error("Ollama parsing failed for '%s': %s", recipe_id, llm_exc)
                    description = f"{description}\n\n[Ollama parse failed: {llm_exc}]"


        # ── Step 6: Build Recipe object ──────────────────────────────────────
        recipe = Recipe(
            name=name,
            url=url,
            description=description,
            macros=macros,
            ingredients=ingredients,
            added_on=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # ── Step 7: Auto-tag ─────────────────────────────────────────────────
        recipe.tags = self._tagger.tag(recipe, manual_tags)

        # ── Step 8: Persist / Route ──────────────────────────────────────────
        is_filled = not (
            recipe.macros.protein == 0.0 and
            recipe.macros.carbs == 0.0 and
            recipe.macros.fats == 0.0 and
            recipe.macros.calories == 0
        )

        if is_filled:
            if self._not_added_db.exists(recipe_id):
                self._not_added_db.delete(recipe_id)
            self._db.insert(recipe_id, recipe)
            logger.info("ADDED: Recipe '%s' (%s) — %d tags", recipe_id, name, len(recipe.tags))
            return True
        else:
            if self._not_added_db.exists(recipe_id):
                self._not_added_db.delete(recipe_id)
            self._not_added_db.insert(recipe_id, recipe)
            logger.info("NOT ADDED (Unfilled): Recipe '%s' (%s) saved/updated in manual check list", recipe_id, name)
            return None

    def process_batch(self, items: list[dict[str, Any]]) -> dict[str, int]:
        """
        Process a batch of recipe payloads.

        Each item must have keys: 'id', 'name', 'url', 'description'.
        Optional key: 'manual_tags' (list of strings).

        Returns stats: {"added": N, "skipped": M, "errors": K, "not_added": L}
        """
        stats = {"added": 0, "skipped": 0, "errors": 0, "not_added": 0}

        for item in items:
            try:
                recipe_id = item["id"]
                name = item.get("name", "Untitled")
                url = item.get("url", "")
                description = item.get("description", "")
                manual_tags = item.get("manual_tags")

                added = self.process(recipe_id, name, url, description, manual_tags)
                if added is True:
                    stats["added"] += 1
                elif added is None:
                    stats["not_added"] += 1
                else:
                    stats["skipped"] += 1

            except KeyError as exc:
                logger.error("Batch item missing required field: %s — item: %s", exc, item)
                stats["errors"] += 1
            except Exception as exc:
                logger.error("Unexpected error processing item: %s — %s", item, exc)
                stats["errors"] += 1

        logger.info(
            "Batch complete: %d added, %d skipped, %d not added, %d errors",
            stats["added"], stats["skipped"], stats["not_added"], stats["errors"],
        )
        return stats
