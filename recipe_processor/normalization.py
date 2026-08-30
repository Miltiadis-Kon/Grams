"""
Layer 1: Ingestion & Text Normalization Layer.
Handles conversational de-noising, disfluency cleaning, sponsor stripping,
speaker turn aggregation, multi-meal semantic chunking, and context window budgeting.
"""

import re
import logging
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# Common speech disfluencies and fillers
DISFLUENCY_PATTERNS = [
    r'\b(?:um+|uh+|er+|ah+|eh+)\b',
    r'\b(?:you\s+know|like\s+literally|sort\s+of|kind\s+of|basically)\b(?!\s+(?:like|of)\s+[a-z])',
    r'\[(?:music|applause|laughter|screaming|cheering|silence|audio)\]',
    r'\((?:music|applause|laughter|audio)\)',
]

SPONSOR_AND_NOISE_PATTERNS = [
    r'https?://\S+',
    r'📖\s*DIET\s+COOKBOOK.*',
    r'📖\s*KOCHBUCH.*',
    r'🔪\s*NAKIRI.*',
    r'🫒\s*PREMIUM.*',
    r'\bNEW\s+LIVE\s+STREAMS:?.*',
    r'\bFollow\s+my\s+Live\s+Streams:?.*',
    r'\bLive\s+Streams:?.*',
    r'\bConnect\s+on\s+(?:Twitter|X|IG|TikTok|Instagram|YouTube|Facebook|Discord):?.*',
    r'\bFollow\s+me\s+on\s+[A-Za-z/]+:?.*',
    r'\b(?:Twitch|Kick|Patreon|Socials)\s*:\s*\S+',
    r'\b(?:Twitter|Twitter/X|Instagram|IG|TikTok)\s*:\s*@?\S+',
    r'Everything\s+I\s+cook\s+with.*',
    r'\bAMAZON\s+LINKS:?.*',
    r'MIDEA\s+FLEXIFY.*',
    r'\bDISCLAIMER:?.*',
    r'\[LLM\s+Parsed\s+Instructions\].*',
    r'[-=_*~]{3,}',
    r'\bNon\s+stick\s+pan:?.*',
    r'\bKitchen\s+scale:?.*',
    r'\bMeal\s+prep\s+container:?.*',
    r'\bBig\s+Blender:?.*',
    r'\bSmall\s+Blender:?.*',
    r'\bY-Peeler:?.*',
    r'\bSqueeze\s+bottles:?.*',
    r'\bWalkingpad:?.*',
    r'\bLife[\s\-]?changing\s+Cookbook.*',
    r'\bAd\s*\([^\)]*\)',
]

# Sponsor verbal triggers in spoken transcripts
VERBAL_SPONSOR_TRIGGERS = [
    r'(?:thank\s+you\s+to\s+today\'?s?\s+sponsor|sponsored\s+by|use\s+my\s+code\s+[A-Z0-9]+|check\s+the\s+link\s+in\s+(?:the\s+)?description|link\s+is\s+in\s+my\s+bio|don\'?t\s+forget\s+to\s+(?:like|subscribe|check)|hit\s+the\s+bell\s+icon|use\s+code\s+[a-zA-Z0-9_\-]+\s+for\s+\d+%\s+off).*?(?=(?:\.|\n|$))',
]


class IngestionNormalizer:
    """
    Ingests raw transcripts or recipe descriptions, cleans conversational noise,
    removes marketing boilerplate, and prepares structured text for inference.
    """

    @staticmethod
    def clean_text(text: str, is_transcript: bool = False) -> str:
        """
        Main entry point to clean and de-noise conversational text or description.
        """
        if not text:
            return ""

        # Step 1: Remove full timestamp ranges (e.g. [00:12.400 --> 00:15.200] or 00:12 --> 00:15 or 00:00 Intro)
        cleaned = re.sub(r'\[?\b\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\b\s*(?:-->|–|-)\s*\b\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\b\]?', ' ', text)
        cleaned = re.sub(r'^\s*\d{1,2}:\d{2}(?::\d{2})?\s+.*$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\[?\b\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\b\]?', ' ', cleaned)

        # Step 2: Remove speaker diarization markers (e.g. "Speaker 1:", "[Speaker 1]:", "Host:", "Chef:")
        cleaned = re.sub(r'(?:^|\n)\s*\[?(?:Speaker\s*\d+|Host|Chef|Narrator|Person\s*[A-Z])\]?[:\-]\s*', '\n', cleaned, flags=re.IGNORECASE)

        # Step 3: Remove marketing boilerplate & affiliate URLs
        for pattern in SPONSOR_AND_NOISE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        # Step 4: Remove verbal sponsor call-to-actions in transcripts
        for pattern in VERBAL_SPONSOR_TRIGGERS:
            cleaned = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)

        # Step 5: Clean speech disfluencies & sound bracket tags
        for pattern in DISFLUENCY_PATTERNS:
            cleaned = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)

        # Step 6: Normalize whitespace and redundant line breaks
        lines = [line.strip() for line in cleaned.splitlines()]
        clean_lines = []
        for line in lines:
            if not line:
                if clean_lines and clean_lines[-1] != "":
                    clean_lines.append("")
                continue

            # Strip leading bullet dashes or arrows
            l_clean = re.sub(r'^(?:[•\-\*>]|-->)\s*', '', line).strip()
            # Strip remaining speaker tags if any
            l_clean = re.sub(r'^\[?(?:Speaker\s*\d+|Host|Chef|Narrator)\]?[:\-]\s*', '', l_clean, flags=re.IGNORECASE)
            if l_clean:
                clean_lines.append(l_clean)

        result = "\n".join(clean_lines).strip()
        result = re.sub(r'[ \t]{2,}', ' ', result)
        return result

    @classmethod
    def split_multi_meal_sections(cls, text: str) -> List[Tuple[str, str]]:
        """
        Detects if text contains multiple standalone meals/recipes
        (e.g., 'Macros egg sandwich:', 'Macros Noodle Bowl:', 'Meal 1:', 'Recipe 1:').
        Returns list of (title, section_text) tuples. If single recipe, returns [("", text)].
        """
        if not text:
            return []

        # Check for 'Macros <Meal Name>:' sections
        macro_split = re.split(r'(?=(?:^|\n)\s*Macros\s+(?:for\s+)?([A-Za-z0-9\s/&\-]+)[:\-])', text, flags=re.IGNORECASE)
        if len(macro_split) > 2:
            results = []
            for i in range(1, len(macro_split), 2):
                meal_title = macro_split[i].strip()
                meal_body = macro_split[i+1].strip() if i+1 < len(macro_split) else ""
                # Skip if body is too small or just numbers
                if len(meal_body.splitlines()) >= 2:
                    clean_title = re.sub(r'^(?:for\s+)?', '', meal_title, flags=re.IGNORECASE).strip()
                    results.append((clean_title, meal_body))
            if results:
                return results

        # Check for 'Meal 1:', 'Meal 2:', 'Recipe 1:' sections
        meal_num_split = re.split(r'(?=(?:^|\n)\s*(?:Meal|Recipe|Dish)\s*(\d+)[:\-\s]+([^\n]+)?)', text, flags=re.IGNORECASE)
        if len(meal_num_split) > 3:
            results = []
            for i in range(1, len(meal_num_split), 3):
                m_num = meal_num_split[i]
                m_title = meal_num_split[i+1] if i+1 < len(meal_num_split) and meal_num_split[i+1] else f"Meal {m_num}"
                m_body = meal_num_split[i+2] if i+2 < len(meal_num_split) else ""
                if len(m_body.splitlines()) >= 2:
                    results.append((m_title.strip(), m_body.strip()))
            if results:
                return results

        return [("", text)]

    @staticmethod
    def chunk_if_needed(text: str, max_words: int = 2500) -> List[str]:
        """
        Context manager & semantic chunker:
        If text is excessively long (e.g. a 30-minute compilation video),
        splits by meal boundaries or semantic sections.
        """
        words = text.split()
        if len(words) <= max_words:
            return [text]

        meal_split_pattern = r'(?=(?:Meal\s*\d+|Recipe\s*\d+|Dish\s*\d+|First\s+recipe|Second\s+recipe|Third\s+recipe|For\s+the\s+(?:breakfast|lunch|dinner|dessert|snack))[:\-])'
        sections = re.split(meal_split_pattern, text, flags=re.IGNORECASE)
        sections = [s.strip() for s in sections if s.strip()]

        if len(sections) > 1:
            return sections

        paragraphs = text.split('\n\n')
        chunks = []
        curr_chunk = []
        curr_len = 0

        for p in paragraphs:
            p_len = len(p.split())
            if curr_len + p_len > max_words and curr_chunk:
                chunks.append("\n\n".join(curr_chunk))
                curr_chunk = [p]
                curr_len = p_len
            else:
                curr_chunk.append(p)
                curr_len += p_len

        if curr_chunk:
            chunks.append("\n\n".join(curr_chunk))

        return chunks
