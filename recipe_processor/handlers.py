import logging
from datetime import datetime
from database import RecipeDatabase, Recipe
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from .base_handler import BaseHandler
from .context import RecipeContext
from .llm_parser import translate_description_if_needed, parse_recipe_with_llm, sanitize_ingredients

logger = logging.getLogger(__name__)

class DeltaCheckHandler(BaseHandler):
    def __init__(self, db: RecipeDatabase, not_added_db: RecipeDatabase):
        super().__init__()
        self._db = db
        self._not_added_db = not_added_db

    def handle(self, context: RecipeContext) -> None:
        if self._db.exists(context.recipe_id):
            logger.info("SKIP: Recipe '%s' (%s) already in main database", context.recipe_id, context.name)
            context.is_skipped = True
            context.status = False
            return  # Stop the chain

        if self._not_added_db.exists(context.recipe_id):
            existing = self._not_added_db.get(context.recipe_id)
            desc = ""
            if existing:
                desc = existing.get("description", "") if isinstance(existing, dict) else getattr(existing, "description", "")
            
            if "[Transcript]" in desc or "Transcript fetch failed" in desc or "[Ollama]" in desc:
                logger.info("SKIP: Recipe '%s' (%s) already processed and fallback attempted", context.recipe_id, context.name)
                context.is_skipped = True
                context.status = False
                return  # Stop the chain
            else:
                logger.info("RE-PROCESSING: Recipe '%s' (%s) from manual check list", context.recipe_id, context.name)

        self.next(context)


class DescriptionParseHandler(BaseHandler):
    def handle(self, context: RecipeContext) -> None:
        logger.info("Parsing description with LLM for '%s'...", context.recipe_id)
        desc_to_parse = translate_description_if_needed(context.description)
        
        try:
            llm_result = parse_recipe_with_llm(desc_to_parse)
            if llm_result.get("is_recipe"):
                llm_title = llm_result.get("title", "").strip()
                if llm_title and llm_title != context.name and "TikTok Video" in context.name:
                    context.name = llm_title
                
                llm_ingredients = llm_result.get("ingredients", [])
                if llm_ingredients:
                    context.ingredients = sanitize_ingredients(llm_ingredients)
                    context.instructions = llm_result.get("instructions", [])
                    context.description = f"{desc_to_parse}\n\n[LLM Parsed Ingredients & Instructions]"
                    logger.info("LLM identified recipe in description for '%s' with %d ingredients.", context.recipe_id, len(context.ingredients))
            else:
                logger.info("LLM determined description for '%s' is NOT a recipe", context.recipe_id)
        except Exception as exc:
            logger.error("LLM description parsing failed for '%s': %s", context.recipe_id, exc)

        self.next(context)


class TranscriptFetchHandler(BaseHandler):
    def handle(self, context: RecipeContext) -> None:
        if context.ingredients:
            logger.info("Ingredients found. Skipping transcript fetch.")
            self.next(context)
            return

        logger.info("No ingredients in description for '%s'. Fetching Groq Whisper transcript...", context.recipe_id)
        try:
            from helpers.whisper_extractor import fetch_groq_whisper_transcript
            transcript_text = fetch_groq_whisper_transcript(context.url)
            
            if transcript_text:
                transcript_text = transcript_text.strip()
                logger.info("Groq Whisper transcript fetched (%d chars): %s...", len(transcript_text), transcript_text[:80])
                translated_desc = translate_description_if_needed(transcript_text)
                context.description = f"[Transcript]\n{translated_desc}"
                context.transcript = translated_desc
            else:
                logger.warning("Groq Whisper returned empty transcript for: %s", context.url)
                if "Transcript fetch failed" not in context.description:
                    context.description = f"{context.description}\n\n[Transcript fetch failed: empty content]"
        except Exception as exc:
            logger.error("Groq Whisper transcript fetch failed: %s", exc)
            if "Transcript fetch failed" not in context.description:
                context.description = f"{context.description}\n\n[Transcript fetch failed: {exc}]"

        self.next(context)


class TranscriptParseHandler(BaseHandler):
    def handle(self, context: RecipeContext) -> None:
        if context.ingredients or not context.transcript:
            self.next(context)
            return

        logger.info("Parsing transcript with LLM for '%s'...", context.recipe_id)
        try:
            llm_result = parse_recipe_with_llm(context.description)
            if llm_result.get("is_recipe"):
                llm_title = llm_result.get("title", "").strip()
                if llm_title and llm_title != context.name and "TikTok Video" in context.name:
                    context.name = llm_title
                
                llm_ingredients = llm_result.get("ingredients", [])
                if llm_ingredients:
                    context.ingredients = sanitize_ingredients(llm_ingredients)
                    context.instructions = llm_result.get("instructions", [])
                    context.description = f"{context.description}\n\n[LLM Parsed Ingredients & Instructions]"
                    logger.info("LLM identified recipe from transcript '%s' with %d ingredient(s)", context.name, len(context.ingredients))
            else:
                logger.info("LLM determined transcript for '%s' is NOT a recipe. Routing to not-added.", context.recipe_id)
                context.description = f"{context.description}\n\n[LLM: not a recipe]"
        except Exception as exc:
            logger.error("LLM transcript parsing failed for '%s': %s", context.recipe_id, exc)
            context.description = f"{context.description}\n\n[LLM parse failed: {exc}]"

        self.next(context)


class NutritionAnalysisHandler(BaseHandler):
    def __init__(self, analyzer: NutritionAnalyzer):
        super().__init__()
        self._analyzer = analyzer

    def handle(self, context: RecipeContext) -> None:
        if context.ingredients:
            context.macros = self._analyzer.analyze_ingredients(context.ingredients, description_for_servings=context.description)
            logger.info("Calculated macros for '%s': P:%.1f C:%.1f F:%.1f Cal:%d", 
                        context.recipe_id, context.macros.protein, context.macros.carbs, context.macros.fats, context.macros.calories)
        self.next(context)


class AutoTaggingHandler(BaseHandler):
    def __init__(self, tagger: AutoTagger):
        super().__init__()
        self._tagger = tagger

    def handle(self, context: RecipeContext) -> None:
        # We need a temporary Recipe object to pass to the tagger
        recipe = Recipe(
            name=context.name,
            url=context.url,
            description=context.description,
            macros=context.macros,
            ingredients=context.ingredients,
            instructions=context.instructions,
            added_on=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        context.tags = self._tagger.tag(recipe, context.manual_tags)
        self.next(context)


class PersistenceHandler(BaseHandler):
    def __init__(self, db: RecipeDatabase, not_added_db: RecipeDatabase):
        super().__init__()
        self._db = db
        self._not_added_db = not_added_db

    def handle(self, context: RecipeContext) -> None:
        recipe = Recipe(
            name=context.name,
            url=context.url,
            description=context.description,
            macros=context.macros,
            ingredients=context.ingredients,
            instructions=context.instructions,
            tags=context.tags,
            added_on=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        is_filled = not (
            recipe.macros.protein == 0.0 and
            recipe.macros.carbs == 0.0 and
            recipe.macros.fats == 0.0 and
            recipe.macros.calories == 0
        )

        if is_filled:
            if self._not_added_db.exists(context.recipe_id):
                self._not_added_db.delete(context.recipe_id)
            self._db.insert(context.recipe_id, recipe)
            logger.info("ADDED: Recipe '%s' (%s) — %d tags", context.recipe_id, context.name, len(recipe.tags))
            context.status = True
        else:
            if self._not_added_db.exists(context.recipe_id):
                self._not_added_db.delete(context.recipe_id)
            self._not_added_db.insert(context.recipe_id, recipe)
            logger.info("NOT ADDED (Unfilled): Recipe '%s' (%s) saved/updated in manual check list", context.recipe_id, context.name)
            context.status = None

        self.next(context)
