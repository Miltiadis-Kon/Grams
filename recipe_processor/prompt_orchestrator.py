"""
Layer 2: Prompt & Schema Orchestration Layer.
Defines system directives, imperative instruction conversion rules,
chronological reordering directives, in-line entity hunting prompts,
and constrained JSON schemas for LLM inference.
"""

import json
from typing import Dict, Any


RECIPE_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_recipe": {
            "type": "boolean",
            "description": "True if the text contains a culinary cooking or preparation recipe, False otherwise."
        },
        "title": {
            "type": "string",
            "description": "Concise, descriptive recipe title."
        },
        "servings": {
            "type": ["integer", "null"],
            "description": "Number of servings / portions yielded by this recipe, or null if unspecified."
        },
        "ingredients": {
            "type": "array",
            "description": "Exhaustive list of all edible food ingredients required for the recipe.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Standard culinary food name without prep or brand modifiers (e.g. 'chicken breast', 'olive oil', 'cheddar cheese', 'garlic')."
                    },
                    "quantity": {
                        "type": "string",
                        "description": "Numeric quantity or standardized range (e.g. '300', '2', '0.5', '1.5', '1-2')."
                    },
                    "unit": {
                        "type": "string",
                        "description": "Measurement unit: 'g', 'ml', 'tbsp', 'tsp', 'cup', 'oz', 'kg', 'slice', 'pinch', 'can', 'unit', or 'to taste'."
                    },
                    "prep": {
                        "type": "string",
                        "description": "Preparation state or cut (e.g. 'diced', 'minced', 'boneless skinless', 'crushed', 'melted', 'grated')."
                    },
                    "notes": {
                        "type": "string",
                        "description": "Substitutions, optional status, or notes (e.g. 'or regular milk', 'optional for garnish', '0% fat')."
                    }
                },
                "required": ["name", "quantity", "unit"]
            }
        },
        "instructions": {
            "type": "array",
            "description": "Chronologically ordered, imperative cooking steps.",
            "items": {
                "type": "object",
                "properties": {
                    "step_number": {
                        "type": "integer",
                        "description": "Sequential step index starting at 1."
                    },
                    "action": {
                        "type": "string",
                        "description": "Clear imperative instruction sentence (e.g. 'Preheat the air fryer to 200°C (400°F).', 'Mix ground beef with salt and seasonings.')."
                    },
                    "timer_minutes": {
                        "type": ["number", "null"],
                        "description": "Baking, simmering, or resting duration in minutes if specified, else null."
                    },
                    "ingredients_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of ingredients used or manipulated in this specific step."
                    }
                },
                "required": ["step_number", "action"]
            }
        }
    },
    "required": ["is_recipe", "title", "ingredients", "instructions"]
}


SYSTEM_PROMPT = """You are an expert culinary AI information extractor.
Your task is to transform conversational speech transcripts or recipe descriptions into structured culinary recipe data conforming strictly to the provided JSON schema.

### CRITICAL EXTRACTION DIRECTIVES:

1. **Imperative Action Conversion**:
   - Convert passive conversational narrative ("and then what I do is toss the chicken into the hot pan with a bit of oil") into direct, professional imperative cooking commands ("Add olive oil to a hot skillet and sear the chicken breast for 6–8 minutes until golden brown.").

2. **Chronological Re-ordering & Temporal Dependency Tracking**:
   - Spoken speech often contains real-time corrections ("Oh wait, make sure you preheat your oven first before mixing the batter").
   - Place pre-heating, marinade chilling, and ingredient prep steps at their chronologically correct position in the execution flow.

3. **In-Line & Implicit Entity Hunting (Dual-Pass Extraction)**:
   - Carefully inspect the narrative for ingredients added casually or on-the-fly (e.g. "a pinch of salt", "cooking spray", "oil for frying", "reserved pasta water", "fresh cracked pepper").
   - Every edible ingredient manipulated in the instructions MUST be cataloged in the master `ingredients` list.

4. **Strict Negative Constraints**:
   - DO NOT include cookware, kitchen equipment, tools, or appliances (e.g. "knife", "pan", "air fryer", "blender", "scale", "food thermometer") as ingredients.
   - DO NOT include affiliate URLs, website links, social media handles, sponsor promotions, or cookbook ads.
   - DO NOT include macro summaries (e.g. "53g protein", "674 cals") as ingredients.

5. **JSON Schema Adherence**:
   - Output ONLY the raw JSON object conforming to the schema. No markdown backticks, no explanations.
"""


class PromptOrchestrator:
    """
    Builds optimized system prompts and user payloads for various LLM backends.
    """

    @staticmethod
    def get_system_prompt() -> str:
        return SYSTEM_PROMPT

    @staticmethod
    def get_json_schema() -> Dict[str, Any]:
        return RECIPE_JSON_SCHEMA

    @staticmethod
    def format_user_prompt(cleaned_text: str) -> str:
        return (
            "Analyze the following text and extract the recipe according to the system instructions.\n"
            "Return JSON matching the schema.\n\n"
            f"Input Text:\n{cleaned_text}"
        )
