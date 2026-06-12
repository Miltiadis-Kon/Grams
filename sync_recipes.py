#!/usr/bin/env python
"""
Grams - CLI TikTok Sync Utility
==============================
Performs continuous, rate-limited ingestion of recipe videos from a TikTok playlist.
Ensures we do not hit the network or request details for videos already in the database.
"""

import argparse
import sys
import logging
from helpers.engine import RecipeEngine
from config import TIKTOK_INGEST_DELAY_SEC

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
    parser = argparse.ArgumentParser(
        description="Grams CLI Tool: Sync a TikTok recipe playlist slowly & incrementally."
    )
    parser.add_argument(
        "playlist_url", 
        help="The full TikTok playlist URL to scrape/sync."
    )
    parser.add_argument(
        "--delay", 
        type=float, 
        default=TIKTOK_INGEST_DELAY_SEC,
        help=f"Delay in seconds between newly ingested video pages (default: {TIKTOK_INGEST_DELAY_SEC}s)"
    )

    args = parser.parse_args()

    logger.info("Starting Grams Sync Engine...")
    try:
        engine = RecipeEngine()
    except Exception as e:
        logger.error("Failed to initialize RecipeEngine: %s", e)
        sys.exit(1)

    logger.info("Playlist URL: %s", args.playlist_url)
    logger.info("Configured Ingestion Delay: %.1fs", args.delay)
    
    try:
        stats = engine.ingest_tiktok_playlist_detailed(args.playlist_url, delay_seconds=args.delay)
        
        logger.info("==========================================")
        logger.info("Sync completed successfully!")
        logger.info("Added   : %d new recipe(s)", stats.get("added", 0))
        logger.info("Skipped : %d already existing recipe(s)", stats.get("skipped", 0))
        logger.info("Errors  : %d occurred", stats.get("errors", 0))
        logger.info("==========================================")
    except KeyboardInterrupt:
        logger.warning("\nSync interrupted by user. Exiting safely.")
    except Exception as e:
        logger.error("Error during playlist sync: %s", e)
    finally:
        engine.close()

if __name__ == "__main__":
    main()
