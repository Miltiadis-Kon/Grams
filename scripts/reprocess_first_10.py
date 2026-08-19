#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reprocess_first_10.py — Reprocess the first 10 videos of the TikTok playlist with extensive logging.
"""

import os
import sys
import time
import json
import logging

# Ensure UTF-8 output on Windows terminal
sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

# Configure extensive logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("reprocess_first_10")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from helpers.engine import RecipeEngine

def main():
    logger.info("================================================================================")
    logger.info("  STARTING BATCH REPROCESS: FIRST 10 VIDEOS OF PLAYLIST WITH EXTENSIVE LOGS")
    logger.info("================================================================================")

    given_url = os.environ.get("TIKTOK_PLAYLIST_URL", "https://vm.tiktok.com/ZN9jNUVd4qWnw-0AhXA/")
    resolved_url = given_url

    if "tiktok.com" in given_url:
        try:
            import requests
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            r = requests.get(given_url, headers=headers, allow_redirects=True, timeout=10)
            resolved_url = r.url
            logger.info("Playlist URL resolved: %s -> %s", given_url, resolved_url)
        except Exception as e:
            logger.warning("Could not resolve redirect for playlist: %s", e)

    try:
        engine = RecipeEngine()
        logger.info("Initialized RecipeEngine successfully.")
    except Exception as e:
        logger.error("Failed to initialize RecipeEngine: %s", e)
        sys.exit(1)

    # The first 10 video links from the user playlist
    FIRST_10_VIDEOS = [
        {"id": "7660019682480508191", "url": "https://www.tiktok.com/@noahperlofit/video/7660019682480508191"},
        {"id": "7664529268256427284", "url": "https://www.tiktok.com/@benmoore_coach/video/7664529268256427284"},
        {"id": "7672763431329565983", "url": "https://www.tiktok.com/@giovannisiracusaa/video/7672763431329565983"},
        {"id": "7641582274529594632", "url": "https://www.tiktok.com/@tabemono.bygrace/video/7641582274529594632"},
        {"id": "7659367329381322006", "url": "https://www.tiktok.com/@dinnerbyben/video/7659367329381322006"},
        {"id": "7660218141707980054", "url": "https://www.tiktok.com/@g.cooks_/video/7660218141707980054"},
        {"id": "7661273482776284436", "url": "https://www.tiktok.com/@thepurplecupcake_/video/7661273482776284436"},
        {"id": "7659485638449794326", "url": "https://www.tiktok.com/@livekitchen/video/7659485638449794326"},
        {"id": "7659022462377577750", "url": "https://www.tiktok.com/@argiskitchen/video/7659022462377577750"},
        {"id": "7659071858679106838", "url": "https://www.tiktok.com/@the_hungry_kat/video/7659071858679106838"},
    ]

    target_videos = FIRST_10_VIDEOS
    logger.info("Targeting %d videos for full forced reprocessing.", len(target_videos))

    for i, v in enumerate(target_videos):
        logger.info("  Target [%d/%d]: Video ID: %s | %s", i + 1, len(target_videos), v["id"], v["url"])

    logger.info("\n" + "=" * 80)
    logger.info("  BEGINNING REPROCESSING PIPELINE")
    logger.info("=" * 80 + "\n")

    summary_stats = {
        "total": len(target_videos),
        "success_added": 0,
        "manual_check": 0,
        "failed": 0,
        "recipes": []
    }

    for idx, item in enumerate(target_videos):
        v_id = item["id"]
        v_url = item["url"]

        logger.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        logger.info("VIDEO [%d/%d] ID: %s", idx + 1, len(target_videos), v_id)
        logger.info("URL: %s", v_url)
        logger.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")

        start_time = time.time()
        try:
            # Force reprocess ignores 7-day rate limit and fetches fresh Whisper transcript + LLM parse
            result = engine.ingest_tiktok_video(v_url, force=True)
            elapsed = time.time() - start_time

            # Check database for the saved result
            saved_recipe = engine._database.get(v_id) or engine._not_added_database.get(v_id)

            if result is True:
                summary_stats["success_added"] += 1
                logger.info("RESULT: [SUCCESS - ADDED TO RECIPES] (took %.2fs)", elapsed)
            elif result is None:
                summary_stats["manual_check"] += 1
                logger.info("RESULT: [ROUTED TO MANUAL REVIEW] (took %.2fs)", elapsed)
            else:
                summary_stats["failed"] += 1
                logger.info("RESULT: [SKIPPED / UNCHANGED] (took %.2fs)", elapsed)

            if saved_recipe:
                name = saved_recipe.get("name", "Untitled")
                macros = saved_recipe.get("macros", {})
                ingredients = saved_recipe.get("ingredients", [])
                instructions = saved_recipe.get("instructions", [])
                tags = saved_recipe.get("tags", [])
                transcript = saved_recipe.get("transcript", "")
                last_proc = saved_recipe.get("last_processed", "")

                logger.info("--- SAVED RECIPE SUMMARY ---")
                logger.info("Name: %s", name)
                logger.info("Macros: Protein: %sg | Carbs: %sg | Fat: %sg | Calories: %s kcal",
                            macros.get("protein", 0), macros.get("carbs", 0), macros.get("fats", 0), macros.get("calories", 0))
                logger.info("Ingredients (%d items):", len(ingredients))
                for ing in ingredients:
                    ing_name = ing.get("name") if isinstance(ing, dict) else str(ing)
                    ing_qty = ing.get("quantity", "") if isinstance(ing, dict) else ""
                    logger.info("  • %s %s", ing_qty, ing_name)

                logger.info("Instructions (%d steps):", len(instructions))
                for s_idx, step in enumerate(instructions[:3]):
                    logger.info("  %d. %s", s_idx + 1, step)
                if len(instructions) > 3:
                    logger.info("  ... and %d more steps", len(instructions) - 3)

                logger.info("Tags: %s", tags)
                logger.info("Last Processed: %s", last_proc)
                logger.info("Transcript Length: %d characters", len(transcript))
                if transcript:
                    preview = transcript[:250].replace("\n", " ")
                    logger.info("Transcript Preview: \"%s...\"", preview)

                summary_stats["recipes"].append({
                    "id": v_id,
                    "name": name,
                    "macros": macros,
                    "ingredient_count": len(ingredients),
                    "status": "added" if result is True else "manual_review"
                })
            else:
                logger.warning("No recipe record found in database for video ID %s", v_id)

        except Exception as exc:
            logger.error("Exception during video %s reprocessing: %s", v_id, exc, exc_info=True)
            summary_stats["failed"] += 1

        logger.info("--------------------------------------------------------------------------------\n")
        time.sleep(2.0)

    logger.info("================================================================================")
    logger.info("  BATCH REPROCESSING COMPLETE")
    logger.info("================================================================================")
    logger.info("Total Videos Targeted: %d", summary_stats["total"])
    logger.info("Successfully Added/Updated: %d", summary_stats["success_added"])
    logger.info("Sent to Manual Review: %d", summary_stats["manual_check"])
    logger.info("Errors/Skipped: %d", summary_stats["failed"])
    logger.info("================================================================================")

    engine.close()

if __name__ == "__main__":
    main()
