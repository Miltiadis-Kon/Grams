import logging
from typing import Any, Optional
from database import RecipeDatabase
from helpers.nutrition import NutritionAnalyzer
from helpers.tagger import AutoTagger
from .context import RecipeContext
from .handlers import (
    DeltaCheckHandler,
    DescriptionParseHandler,
    TranscriptFetchHandler,
    TranscriptParseHandler,
    NutritionAnalysisHandler,
    AutoTaggingHandler,
    PersistenceHandler
)

logger = logging.getLogger(__name__)

class RecipePipeline:
    """
    Orchestrates the ingestion flow for individual recipe payloads using the
    Chain of Responsibility design pattern.
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
        
        # Build the chain
        self._head = DeltaCheckHandler(self._db, self._not_added_db)
        
        description_parser = DescriptionParseHandler()
        transcript_fetcher = TranscriptFetchHandler()
        transcript_parser = TranscriptParseHandler()
        nutrition_analyzer_handler = NutritionAnalysisHandler(self._nutrition)
        tagger_handler = AutoTaggingHandler(self._tagger)
        persistence_handler = PersistenceHandler(self._db, self._not_added_db)
        
        self._head.set_next(description_parser) \
                  .set_next(transcript_fetcher) \
                  .set_next(transcript_parser) \
                  .set_next(nutrition_analyzer_handler) \
                  .set_next(tagger_handler) \
                  .set_next(persistence_handler)

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
        
        Returns:
          True: Recipe was newly added to recipes DB
          False: Recipe already processed (skipped)
          None: Recipe had no data and was saved to not_added_recipes DB for manual check
        """
        context = RecipeContext(
            recipe_id=recipe_id,
            name=name,
            url=url,
            description=description,
            manual_tags=manual_tags
        )
        
        try:
            self._head.handle(context)
        except Exception as e:
            logger.error("Error processing recipe '%s': %s", recipe_id, e, exc_info=True)
            return False
            
        return context.status

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
            "Batch complete — Added: %d | Skipped: %d | Not Added: %d | Errors: %d",
            stats["added"], stats["skipped"], stats["not_added"], stats["errors"]
        )
        return stats
