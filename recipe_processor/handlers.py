import logging
from datetime import datetime, timedelta
from database import RecipeDatabase, Recipe
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from .base_handler import BaseHandler
from .context import RecipeContext
from .llm_parser import translate_description_if_needed, parse_recipe_with_llm, sanitize_ingredients

logger = logging.getLogger(__name__)

def is_within_7_days(date_str: str) -> bool:
    """Check if the given date string is within the past 7 days."""
    if not date_str:
        return False
    try:
        clean_str = str(date_str).replace("Z", "").split(".")[0].split("+")[0]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(clean_str, fmt)
                diff = datetime.now() - dt
                return diff.total_seconds() < 7 * 86400  # 7 days
            except ValueError:
                continue
    except Exception:
        pass
    return False

class DeltaCheckHandler(BaseHandler):
    def __init__(self, db: RecipeDatabase, not_added_db: RecipeDatabase):
        super().__init__()
        self._db = db
        self._not_added_db = not_added_db

    def handle(self, context: RecipeContext) -> None:
        if context.force_reprocess:
            logger.info("FORCE RE-PROCESS: Recipe '%s' (%s)", context.recipe_id, context.name)
            self.next(context)
            return

        existing_record = self._db.get(context.recipe_id)
        if existing_record:
            last_proc = existing_record.get("last_processed") or existing_record.get("added_on")
            if is_within_7_days(last_proc):
                logger.info("SKIP: Recipe '%s' (%s) was processed recently (%s - within 7 days)", context.recipe_id, context.name, last_proc)
                context.is_skipped = True
                context.status = False
                return  # Stop the chain
            else:
                logger.info("RE-PROCESSING: Recipe '%s' (%s) was processed >7 days ago (%s)", context.recipe_id, context.name, last_proc)
                self.next(context)
                return

        if self._not_added_db.exists(context.recipe_id):
            existing = self._not_added_db.get(context.recipe_id)
            last_proc = ""
            desc = ""
            if existing:
                last_proc = existing.get("last_processed") or existing.get("added_on") or ""
                desc = existing.get("description", "") if isinstance(existing, dict) else getattr(existing, "description", "")
            
            if is_within_7_days(last_proc) and ("[Transcript]" in desc or "Transcript fetch failed" in desc or "[Ollama]" in desc):
                logger.info("SKIP: Recipe '%s' (%s) in manual check list was processed recently (%s)", context.recipe_id, context.name, last_proc)
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
                    instructions_text = "\n".join([f"{idx+1}. {step}" for idx, step in enumerate(context.instructions)])
                    context.description = f"{desc_to_parse}\n\n[LLM Parsed Instructions]\n{instructions_text}"
                    logger.info("LLM identified recipe in description for '%s' with %d ingredients and %d instructions.", context.recipe_id, len(context.ingredients), len(context.instructions))
            else:
                logger.info("LLM determined description for '%s' is NOT a recipe", context.recipe_id)
        except Exception as exc:
            exc_str = str(exc).lower()
            if any(k in exc_str for k in ("429", "402", "rate limit", "credit", "quota", "insufficient")):
                logger.warning("Groq credits depleted / rate limit hit during description parsing for '%s': %s. Fallback: processing description without updating last_processed.", context.recipe_id, exc)
                context.groq_out_of_credits = True
                context.update_last_processed = False
            else:
                logger.error("LLM description parsing failed for '%s': %s", context.recipe_id, exc)

        self.next(context)


class TranscriptFetchHandler(BaseHandler):
    def handle(self, context: RecipeContext) -> None:
        # If Groq ran out of credits, skip transcript extraction and do not update last_processed
        if context.groq_out_of_credits:
            logger.warning("Groq credits depleted. Skipping transcript extraction for '%s'.", context.recipe_id)
            context.update_last_processed = False
            self.next(context)
            return

        # Attempt to fetch and store the full video transcript if not already populated
        if not context.transcript and context.url:
            if "youtube.com" in context.url or "youtu.be" in context.url:
                logger.info("Fetching direct YouTube transcript for '%s'...", context.recipe_id)
                try:
                    from helpers.youtube_transcript import fetch_youtube_transcript
                    transcript_text = fetch_youtube_transcript(context.url)
                    if transcript_text:
                        context.transcript = transcript_text.strip()
                        logger.info("Direct YouTube transcript fetched (%d chars) for '%s'", len(context.transcript), context.recipe_id)
                except Exception as exc:
                    logger.warning("Direct YouTube transcript fetch failed for '%s': %s", context.recipe_id, exc)
            else:
                logger.info("Fetching Groq Whisper transcript for '%s'...", context.recipe_id)
                try:
                    from helpers.whisper_extractor import fetch_groq_whisper_transcript
                    transcript_text = fetch_groq_whisper_transcript(context.url)
                    
                    if transcript_text:
                        transcript_text = transcript_text.strip()
                        context.transcript = transcript_text
                        logger.info("Groq Whisper transcript fetched (%d chars) for '%s'", len(transcript_text), context.recipe_id)
                except Exception as exc:
                    exc_str = str(exc).lower()
                    if any(k in exc_str for k in ("429", "402", "rate limit", "credit", "quota", "insufficient")):
                        logger.warning("Groq ran out of credits during Whisper transcription for '%s': %s. Processing description only and skipping last_processed update.", context.recipe_id, exc)
                        context.groq_out_of_credits = True
                        context.update_last_processed = False
                    else:
                        logger.warning("Groq Whisper transcript fetch failed for '%s': %s", context.recipe_id, exc)

        # If no ingredients were extracted from description, use the transcript for recipe parsing
        if not context.ingredients and context.transcript:
            translated_desc = translate_description_if_needed(context.transcript)
            context.description = f"[Transcript]\n{translated_desc}"
        elif not context.ingredients and not context.transcript:
            if "Transcript fetch failed" not in context.description:
                context.description = f"{context.description}\n\n[Transcript fetch failed]"

        self.next(context)


class TranscriptParseHandler(BaseHandler):
    def handle(self, context: RecipeContext) -> None:
        if context.ingredients or not context.transcript or context.groq_out_of_credits:
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
                    instructions_text = "\n".join([f"{idx+1}. {step}" for idx, step in enumerate(context.instructions)])
                    context.description = f"{context.description}\n\n[LLM Parsed Instructions]\n{instructions_text}"
                    logger.info("LLM identified recipe from transcript '%s' with %d ingredient(s) and %d instruction(s)", context.name, len(context.ingredients), len(context.instructions))
            else:
                logger.info("LLM determined transcript for '%s' is NOT a recipe. Routing to not-added.", context.recipe_id)
                context.description = f"{context.description}\n\n[LLM: not a recipe]"
        except Exception as exc:
            exc_str = str(exc).lower()
            if any(k in exc_str for k in ("429", "402", "rate limit", "credit", "quota", "insufficient")):
                logger.warning("Groq credits depleted during LLM transcript parsing for '%s': %s. Setting update_last_processed=False.", context.recipe_id, exc)
                context.groq_out_of_credits = True
                context.update_last_processed = False
            else:
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
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadata = {
            "transcript": context.transcript,
            "description": context.description,
        }
        if context.groq_out_of_credits:
            metadata["groq_quota_exceeded"] = True
        context.metadata = metadata

        recipe = Recipe(
            name=context.name,
            url=context.url,
            description=context.description,
            macros=context.macros,
            ingredients=context.ingredients,
            instructions=context.instructions,
            added_on=now_str,
            transcript=context.transcript,
            last_processed=now_str if context.update_last_processed else (context.last_processed or ""),
            metadata=metadata,
        )
        context.tags = self._tagger.tag(recipe, context.manual_tags)
        self.next(context)


class PersistenceHandler(BaseHandler):
    def __init__(self, db: RecipeDatabase, not_added_db: RecipeDatabase):
        super().__init__()
        self._db = db
        self._not_added_db = not_added_db

    def handle(self, context: RecipeContext) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadata = {
            "transcript": context.transcript,
            "description": context.description,
        }
        if context.groq_out_of_credits:
            metadata["groq_quota_exceeded"] = True
        context.metadata = metadata

        recipe = Recipe(
            name=context.name,
            url=context.url,
            description=context.description,
            macros=context.macros,
            ingredients=context.ingredients,
            instructions=context.instructions,
            tags=context.tags,
            added_on=now_str,
            transcript=context.transcript,
            last_processed=now_str if context.update_last_processed else (context.last_processed or ""),
            metadata=metadata,
        )

        is_filled = bool(
            context.ingredients and
            len(context.ingredients) >= 1 and
            not (
                recipe.macros.protein == 0.0 and
                recipe.macros.carbs == 0.0 and
                recipe.macros.fats == 0.0 and
                recipe.macros.calories == 0
            )
        )

        if is_filled:
            if self._not_added_db.exists(context.recipe_id):
                self._not_added_db.delete(context.recipe_id)
            if self._db.exists(context.recipe_id):
                self._db.update(context.recipe_id, recipe.to_dict() if hasattr(recipe, "to_dict") else recipe, update_last_processed=context.update_last_processed)
            else:
                self._db.insert(context.recipe_id, recipe, update_last_processed=context.update_last_processed)
            logger.info("ADDED/UPDATED: Recipe '%s' (%s) — %d tags (last_processed updated: %s)", context.recipe_id, context.name, len(recipe.tags), context.update_last_processed)
            context.status = True
        else:
            if self._db.exists(context.recipe_id):
                self._db.delete(context.recipe_id)
            if self._not_added_db.exists(context.recipe_id):
                self._not_added_db.delete(context.recipe_id)
            self._not_added_db.insert(context.recipe_id, recipe, update_last_processed=context.update_last_processed)
            logger.info("ROUTED TO MANUAL REVIEW: Recipe '%s' (%s) saved in manual check list (last_processed updated: %s)", context.recipe_id, context.name, context.update_last_processed)
            context.status = None

        self.next(context)
