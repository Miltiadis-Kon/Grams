#!/usr/bin/env python
"""
test_transcript_parse.py
========================
Standalone test: fetch the Supadata transcript for a video that is in the
not_added_recipes.json file and print the raw result.

This does NOT modify any database and does NOT call Gemini.

Usage:
    python test_transcript_parse.py [--video-id VIDEO_ID]

If --video-id is omitted, the first entry in not_added_recipes.json that has
a real TikTok URL and no existing "Transcript:" marker is used.
"""

import argparse
import json
import sys
import logging

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_transcript_parse")


def load_not_added(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_candidate(not_added: dict, preferred_id: str = None) -> tuple[str, str, str]:
    """
    Return (video_id, url, name) for the test video.

    Preference order:
      1. explicitly supplied preferred_id
      2. first entry whose description does NOT start with '[Transcript'
         (i.e. one that hasn't been tried yet / limit was the issue, not unavailability)
    """
    if preferred_id and preferred_id in not_added:
        entry = not_added[preferred_id]
        return preferred_id, entry["url"], entry.get("name", f"TikTok Video {preferred_id}")

    for vid_id, entry in not_added.items():
        desc = entry.get("description", "")
        url = entry.get("url", "")
        if not url or "tiktok.com" not in url:
            continue
        # Skip videos where transcript is confirmed unavailable
        if "transcript-unavailable" in desc.lower():
            continue
        return vid_id, url, entry.get("name", f"TikTok Video {vid_id}")

    raise RuntimeError("No suitable candidate found in not_added_recipes.json")


def fetch_transcript(url: str) -> str | None:
    """Call Supadata and return the plain-text transcript, or None on failure."""
    import config
    from supadata import Supadata

    api_key = config.SUPADATA_API_KEY
    logger.info("Fetching transcript for: %s", url)
    client = Supadata(api_key=api_key)
    result = client.transcript(url=url, text=True, mode="auto")
    if hasattr(result, "content") and result.content:
        return result.content.strip()
    return None


def main():
    parser = argparse.ArgumentParser(description="Test Supadata transcript fetch (no DB write)")
    parser.add_argument(
        "--video-id",
        default=None,
        help="Specific video ID from not_added_recipes.json to test (optional)",
    )
    args = parser.parse_args()

    from config import NOT_ADDED_FILE_PATH

    not_added = load_not_added(NOT_ADDED_FILE_PATH)
    logger.info("Loaded %d entries from not_added_recipes.json", len(not_added))

    video_id, url, name = pick_candidate(not_added, args.video_id)
    logger.info("Selected video  : %s", video_id)
    logger.info("Name            : %s", name)
    logger.info("URL             : %s", url)
    logger.info("Stored desc     : %.120s ...", not_added[video_id].get("description", ""))

    print("\n" + "=" * 70)
    print("FETCHING TRANSCRIPT VIA SUPADATA")
    print("=" * 70)

    try:
        transcript = fetch_transcript(url)
        if transcript:
            print(f"\n✅  Transcript retrieved ({len(transcript)} chars):\n")
            print(transcript[:2000])
            if len(transcript) > 2000:
                print(f"\n... (truncated, full length: {len(transcript)} chars)")
        else:
            print("\n⚠️  Supadata returned empty content for this video.")
    except Exception as exc:
        print(f"\n❌  Supadata call failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
