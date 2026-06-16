#!/usr/bin/env python
"""
Grams - CLI TikTok Sync Utility
==============================
Performs continuous, rate-limited ingestion of recipe videos from a TikTok playlist.
Ensures we do not hit the network or request details for videos already in the database.
"""

import sys
import logging

# Reconfigure standard output streams to use UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

from helpers.engine import RecipeEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("sync_recipes")

def main():

    import os
    given_url = os.environ.get("TIKTOK_PLAYLIST_URL", "https://vm.tiktok.com/ZN9jNUVd4qWnw-0AhXA/")
    delay = 0

    # Resolve redirect to get the actual URL
    resolved_url = given_url
    if "tiktok.com" in given_url:
        try:
            import requests
            # Standard browser-like user agent to avoid blocking
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            r = requests.get(given_url, headers=headers, allow_redirects=True, timeout=10)
            resolved_url = r.url
            logger.info("Resolved URL: %s", resolved_url)
        except Exception as e:
            logger.warning("Failed to resolve redirect for %s: %s. Using original URL.", given_url, e)

    logger.info("Starting Grams Sync Engine...")
    try:
        engine = RecipeEngine()
    except Exception as e:
        logger.error("Failed to initialize RecipeEngine: %s", e)
        sys.exit(1)

    logger.info("Configured Ingestion Delay: %.1fs", delay)
    
    try:
        if "/video/" in resolved_url:
            logger.info("Processing single video: %s", resolved_url)
            res = engine.ingest_tiktok_video(resolved_url)
            logger.info("==========================================")
            if res is True:
                logger.info("Sync completed successfully: Recipe was added to database!")
            elif res is False:
                logger.info("Sync completed successfully: Recipe already exists (skipped)!")
            else:
                logger.info("Sync complete: Recipe had no data or failed parsing, saved/updated in manual check list.")
            logger.info("==========================================")
        else:
            logger.info("Processing playlist/collection: %s", resolved_url)
            stats = engine.ingest_tiktok_playlist_detailed(resolved_url, delay_seconds=delay)
            
            logger.info("==========================================")
            logger.info("Sync completed successfully!")
            logger.info("Added to DB : %d new recipe(s)", stats.get("added", 0))
            logger.info("Manual Check: %d recipe(s) with no data", stats.get("not_added", 0))
            logger.info("Skipped     : %d already processed recipe(s)", stats.get("skipped", 0))
            logger.info("Errors      : %d occurred", stats.get("errors", 0))
            logger.info("==========================================")
    except KeyboardInterrupt:
        logger.warning("\nSync interrupted by user. Exiting safely.")
    except Exception as e:
        logger.error("Error during sync: %s", e)
    finally:
        engine.close()

if __name__ == "__main__":
    main()
