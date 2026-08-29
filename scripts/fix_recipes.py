#!/usr/bin/env python3
"""
Comprehensive Recipe Cleaner & Extractor for Grams.
Cleans marketing boilerplate, extracts clean ingredients & step-by-step instructions,
recalculates accurate macronutrients, and updates PostgreSQL database.
"""

import os
import sys
import re
import json
import logging
from typing import List, Dict, Tuple, Any

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("fix_recipes")

# Curated recipe enrichments for videos with minimal text descriptions
CURATED_RECIPE_DATA = {
    'yt_pdis-Pvlp_0': {
        'instructions': [
            'In a pot, whisk 25g cocoa powder, 25g sweetener, 4g cornstarch, 1g salt, and 400g 1% milk. Heat on medium-low and simmer for 60 seconds.',
            'Transfer to a heatproof bowl set inside an ice-water bath, stirring every minute to cool down quickly.',
            'Add 20g 70% dark chocolate to the warm mixture and stir continuously until silky and completely melted.',
            'Pour mixture into a Ninja Creami pint, freeze for 24 hours, and process on the Lite Ice Cream setting.'
        ]
    },
    'yt_I96tVxRC6JY': {
        'instructions': [
            'Boil pasta in salted water until al dente; reserve 1/2 cup starchy pasta water before draining.',
            'In a hot skillet, brown lean ground beef with minced garlic, Italian herbs, salt, and black pepper.',
            'Stir in tomato marinara and blended cottage cheese / Greek yogurt along with pasta water to create a creamy high-protein sauce.',
            'Toss cooked pasta in the sauce, divide evenly across meal prep containers, and top with mozzarella.'
        ]
    },
    'yt_kRwMYvuUR4s': {
        'instructions': [
            'Cook 400g pasta in salted boiling water until al dente; drain and set aside.',
            'In a large pan, cook 1000g lean ground beef (95/5) with diced onions, garlic, and seasoning until fully browned.',
            'Pour in tomato sauce and blend with light cream cheese or Greek yogurt, simmering for 5 minutes.',
            'Combine pasta with the meat sauce, divide across 5 containers, and top with grated parmesan.'
        ]
    },
    'yt_-oK73-9-7pQ': {
        'instructions': [
            'In a bowl, mix 900g ground chicken with garlic powder, onion powder, rosemary, salt, and black pepper.',
            'Shape into 5 burger patties and place on a tray in the freezer for 30 minutes to firm up.',
            'Dredge patties in flour, dip in beaten eggs, and coat with crushed seasoned cornflakes.',
            'Bake at 180°C (355°F) for 15–20 minutes until crispy and internal temp reaches 74°C (165°F). Assemble with buns and sauce.'
        ]
    },
    'yt_8HVQ091Y00I': {
        'instructions': [
            'Cube potatoes and toss with olive oil, paprika, garlic powder, salt, and pepper.',
            'Roast or air-fry potatoes at 200°C (400°F) for 20–25 minutes until crispy on the edges.',
            'Cut chicken breast into bite-sized pieces, season, and sear in a skillet over medium-high heat until golden (8–10 min).',
            'Whisk Greek yogurt with garlic, lemon, and herbs for the sauce. Divide chicken and potatoes into meal prep containers.'
        ]
    },
    'yt_CpU1Tqg2884': {
        'instructions': [
            'Meal 1: Scramble egg whites with spinach, mushrooms, and lean turkey bacon; serve with high-fiber toast.',
            'Meal 2: High-volume chicken salad with shredded chicken breast, mixed greens, cucumbers, and Greek yogurt dressing.',
            'Meal 3: Low-calorie chocolate protein fluff / pudding topped with fresh berries.'
        ]
    },
    'yt_6v_YEkp8QyI': {
        'instructions': [
            'Season 300g lean ground beef with salt and black pepper, then shape into 2 or 3 smash burger patties.',
            'Whisk 15g light mayo, 15g ketchup, 5g mustard, 50g chopped dill pickles, and garlic powder to create the special burger sauce.',
            'Sear the beef patties in a hot skillet with oil for 2–3 minutes per side until deeply browned. Top with American cheese slices to melt.',
            'Toast the brioche bun, spread burger sauce on both halves, and assemble with the cheesy beef patties, sliced onion, tomato, and fresh lettuce.'
        ]
    },
    'yt_td7pHnZRQFk': {
        'instructions': [
            'Dice 500g potatoes and deli meat into bite-sized cubes.',
            'In a large bowl, whisk 10 eggs with 250g cottage cheese, 100g milk, olive oil, garlic powder, cayenne pepper, salt, and black pepper.',
            'Add the diced potatoes, deli meat, and half the cheddar cheese into the egg mixture and mix well.',
            'Pour into a baking dish, top with the remaining cheddar cheese, and bake at 200°C (400°F) for 25 minutes until set and golden brown.'
        ]
    },
    'yt_vPlWIUH-mLU': {
        'instructions': [
            'In a large mixing bowl, combine 250g oats, 75g vanilla protein powder, 50g cocoa powder, 50g sweetener, and a pinch of salt.',
            'Whisk in 250g Greek yogurt, 5 eggs, 250g milk, 250g brewed coffee, and 50g melted butter until a smooth batter forms.',
            'Fold in 30g chocolate chips and transfer the mixture into a greased baking pan.',
            'Bake at 180°C (350°F) for 35 minutes. Allow to cool, then slice into 5 meal prep portions (keeps refrigerated up to 5 days).'
        ]
    },
    'yt_x3VcBI_cCYk': {
        'instructions': [
            'Slice 600g chicken breast into strips and season with salt, pepper, garlic powder, and paprika.',
            'Cook the chicken in a hot pan with a little oil for 6–8 minutes until fully cooked through and juicy.',
            'Shred 200g cabbage and prepare your favorite light wrap sauce (Greek yogurt, mayo, and herbs).',
            'Assemble wraps with warm tortillas, shredded cabbage, seasoned chicken, and sauce. Wrap tightly and store in meal prep foil.'
        ]
    },
    'yt_X_hrPeT6HmU': {
        'instructions': [
            'Cook the ground meat / eggs in a pan with butter and seasonings until cooked and fluffy.',
            'Prepare the breakfast burrito filling by combining the scrambled eggs, cheese, and salsa.',
            'Warm the tortillas, distribute the filling evenly across burritos, roll tightly, and wrap in foil for freezer storage.'
        ]
    },
    'yt_r0cZ0tqelhM': {
        'instructions': [
            'Cut 1000g chicken breast into bite-sized cubes and marinate with soy sauce, garlic, ginger, and honey.',
            'Cook 300g rice according to package directions.',
            'Sear the marinated chicken in a hot pan over medium-high heat until caramelized and cooked through (8–10 minutes).',
            'Divide cooked rice and chicken across meal prep containers and top with sesame seeds and green onions.'
        ]
    },
    'yt_otmNsCNR6Wg': {
        'instructions': [
            'Meal 1: French toast using 4 slices bread dipped in 200g egg whites with cinnamon, cooked in a pan until golden.',
            'Meal 2: High-protein chicken bowl with lean chicken breast, steamed rice, and vegetables.',
            'Meal 3: Evening protein snack with Greek yogurt or casein pudding.'
        ]
    },
    'yt_XyZgMmThYGk': {
        'instructions': [
            'In a bowl, mix 300g pumpkin puree, 100g egg whites, protein powder, oat flour, and pumpkin pie spice until smooth.',
            'Pour batter into a silicone cake mold or loaf pan.',
            'Bake at 175°C (350°F) for 25–30 minutes until a toothpick inserted comes out clean. Cool before frosting with light cream cheese.'
        ]
    },
    'yt_a_E-P5xMCMo': {
        'instructions': [
            'In a bowl, combine 60g cornmeal, 60g all-purpose flour, protein powder, sweetener, and baking powder.',
            'Mix in wet ingredients (egg whites, milk, and vanilla extract) until a thick dough forms.',
            'Press into a baking tin and bake at 180°C (350°F) for 15–18 minutes. Slice into high-protein bars.'
        ]
    },
    'yt_ILJrZfJ0vwg': {
        'instructions': [
            'Mix dry ingredients (flour, protein powder, baking powder, and sweetener) in a large bowl.',
            'Add Greek yogurt, eggs, and milk, stirring until a smooth cake batter is achieved.',
            'Pour into a cake pan and bake at 180°C (350°F) for 25 minutes. Store in the fridge for easy breakfast slices.'
        ]
    },
    'yt_2pAV3-lCzg0': {
        'instructions': [
            'Shape lean ground beef into burger patties and season with salt and pepper.',
            'Mix light mayo, yellow mustard, ketchup, and diced pickles to recreate the iconic sauce.',
            'Sear patties in a pan, add American cheese to melt, and assemble on toasted burger buns with shredded lettuce and sauce.'
        ]
    },
    'yt_eWUltLms1AA': {
        'instructions': [
            'Distribute high-protein meals across the day focusing on lean chicken, egg whites, Greek yogurt, and protein shakes.',
            'Pre-portion your meals in airtight containers to hit 186g protein consistently.'
        ]
    },
    'yt_ROoLkpGxQ8E': {
        'instructions': [
            'Brown 500g ground beef with Mexican seasonings in a skillet.',
            'Whisk eggs with milk and scramble lightly on a sheet pan in the oven until set.',
            'Distribute beef, eggs, and shredded cheddar across 10 large tortillas, roll tightly, and freeze in foil.'
        ]
    },
    'yt_2-tnmkCCdL4': {
        'instructions': [
            'Meal 1: High-protein savory breakfast skillet with eggs, potatoes, and lean meat.',
            'Meal 2: Teriyaki chicken meal prep bowl with steamed jasmine rice.',
            'Meal 3: Low-calorie creamy protein dessert bowl.'
        ]
    },
    'yt_BYMbBDOPOEg': {
        'instructions': [
            'Combine oats, whey protein, peanut butter, and honey in a bowl.',
            'Press the mixture firmly into a lined tray and refrigerate for 2 hours until set.',
            'Cut into chewy protein bars and wrap individually.'
        ]
    },
    'yt_He7mi4joxrs': {
        'instructions': [
            'In a blender, combine bananas / pumpkin, eggs, cocoa powder, protein powder, and sweetener.',
            'Blend until completely smooth, then fold in dark chocolate chips.',
            'Pour into a square baking dish and bake at 175°C (350°F) for 20 minutes for fudgy weight-loss brownies.'
        ]
    },
    'yt_4e39CMTc9kw': {
        'instructions': [
            'Dice 200g turkey breast and season with cumin, garlic powder, and paprika.',
            'Air-fry or pan-sear the turkey with mixed vegetables until tender and cooked through (10 min).',
            'Serve over 110g pre-cooked white rice with aioli sauce drizzled on top.'
        ]
    }
}


def clean_raw_description(desc: str) -> str:
    """Strip marketing links, affiliate sections, and disclaimers from description."""
    if not desc:
        return ""

    lines = desc.splitlines()
    clean_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append("")
            continue

        lower = stripped.lower()

        # Stop parsing if we hit bottom disclaimer
        if "disclaimer:" in lower:
            break

        # Check if line matches known marketing header
        if any(h in lower for h in [
            "follow my live streams", "my patreon", "socials:", "everything i cook with",
            "amazon links:", "diet cookbook", "kochbuch", "knife:", "walkingpad:",
            "midea flexify", "check the link in my description"
        ]):
            continue

        # Skip URLs and affiliate product lines
        if "http://" in lower or "https://" in lower or "amzn.to" in lower or "payhip.com" in lower or "felu.co" in lower:
            continue

        if re.match(r'^(?:[-=_*~]{3,})$', stripped):
            continue

        clean_lines.append(stripped)

    return "\n".join(clean_lines).strip()


def parse_line_as_ingredient(line: str) -> Dict[str, str]:
    """Parse a single text line into name & quantity."""
    line = line.strip()
    if not line or len(line) > 85:
        return None

    # Check for junk keywords
    lower = line.lower()
    if lower in ["instructions:", "directions:", "steps:", "method:", "preparation:", "ingredients:"]:
        return None

    if any(j in lower for j in ["http", "cookbook", "amzn", "click", "subscribe", "pan", "knife", "blender", "scale", "air fryer", "stovetop", "container"]):
        if not any(food in lower for food in ["oil", "spray", "butter", "egg", "chicken", "beef", "flour", "milk", "cheese"]):
            return None

    from ingredient_parser import parse_ingredient
    try:
        parsed = parse_ingredient(line)
        has_amount = parsed and parsed.amount and len(parsed.amount) > 0
        has_name = parsed and parsed.name and len(parsed.name) > 0

        if has_name and has_amount:
            name = " ".join([n.text for n in parsed.name]).strip()
            qty = " ".join([a.text for a in parsed.amount]).strip()
            if name and qty and name.lower() not in ["instructions:", "directions:", "steps:"]:
                return {"name": name, "quantity": qty}
    except Exception:
        pass

    # Regex fallback
    m = re.match(r'^((?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|portion|portions)?)\s*(?:of\s+)?(.*)$', line, re.IGNORECASE)
    if m:
        qty = m.group(1).strip()
        name = m.group(2).strip()
        if name and len(name) > 1 and name.lower() not in ["instructions:", "directions:", "steps:"]:
            return {"name": name, "quantity": qty or "1"}

    if len(line) < 40 and not line.endswith('.') and lower not in ["instructions:", "directions:", "steps:"]:
        return {"name": line, "quantity": "1"}

    return None


def extract_recipe_details(id: str, r: dict) -> Tuple[List[Dict[str, str]], List[str]]:
    desc = r.get('description', '')
    transcript = r.get('transcript', '')

    curated = CURATED_RECIPE_DATA.get(id)

    # Step 1: Check LLM Parsed Instructions
    llm_steps = []
    if '[LLM Parsed Instructions]' in desc:
        m = re.search(r'\[LLM Parsed Instructions\]\s*(.*?)(?:\n\n|\Z)', desc, re.DOTALL)
        if m:
            lines = [l.strip() for l in m.group(1).splitlines() if len(l.strip()) > 8 and not '---' in l]
            llm_steps = [re.sub(r'^\d+[\.\)]\s*', '', l) for l in lines]

    # Step 2: Cut description at DISCLAIMER or [LLM Parsed
    clean_desc = desc
    if 'DISCLAIMER:' in clean_desc:
        clean_desc = clean_desc.split('DISCLAIMER:')[0]
    if '[LLM Parsed' in clean_desc:
        clean_desc = clean_desc.split('[LLM Parsed')[0]

    cleaned_desc = clean_raw_description(clean_desc)
    paragraphs = [p.strip() for p in cleaned_desc.split('\n\n') if p.strip()]

    ingredients = []
    instructions = []

    if len(llm_steps) >= 2:
        instructions = llm_steps

    qty_regex = re.compile(
        r'^(?:(?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|portion|portions)?\b|salt\b|pepper\b|black pepper\b|seasonings?\b)',
        re.IGNORECASE
    )

    for p in paragraphs:
        p_lines = [pl.strip() for pl in p.splitlines() if pl.strip()]
        has_qty = sum(1 for pl in p_lines if qty_regex.match(pl) or (len(pl) < 55 and not pl.endswith('.')))

        if has_qty >= len(p_lines) * 0.6 and len(p_lines) > 0 and len(p) < 600:
            for pl in p_lines:
                if re.match(r'^(?:macros|nutrition|calories|servings|serving size)[:\s]', pl.lower()):
                    continue
                if len(pl) > 85:
                    continue
                parsed_ing = parse_line_as_ingredient(pl)
                if parsed_ing:
                    ingredients.append(parsed_ing)
        else:
            # Instructional paragraph
            if len(p) > 20 and not instructions:
                clean_p = re.sub(r'^instructions:?\s*', '', p, flags=re.IGNORECASE).strip()
                if clean_p:
                    instructions.append(clean_p)

    # Special handling for transcript-only videos
    if id == 'yt_4Y1BV1UZTQY' or (len(ingredients) == 0 and 'ground chicken' in desc.lower()):
        ingredients = [
            {'name': 'ground chicken (or ground turkey)', 'quantity': '900g'},
            {'name': 'salt', 'quantity': '2 pinches'},
            {'name': 'garlic powder', 'quantity': '2 tsp (6g)'},
            {'name': 'onion powder', 'quantity': '2 tsp (6g)'},
            {'name': 'rosemary', 'quantity': '1 tsp (3g)'},
            {'name': 'black pepper', 'quantity': '20g'},
            {'name': 'all-purpose flour', 'quantity': '50g'},
            {'name': 'eggs', 'quantity': '2'},
            {'name': 'cornflakes (crushed)', 'quantity': '75g'},
            {'name': 'brioche burger buns', 'quantity': '5'},
            {'name': 'light mayo', 'quantity': '75g'},
            {'name': 'sriracha', 'quantity': '40g'},
            {'name': 'dijon mustard', 'quantity': '30g'},
            {'name': 'iceberg lettuce', 'quantity': '100g'}
        ]
        instructions = [
            'In a large bowl, combine 900g ground chicken with salt, garlic powder, onion powder, rosemary, and black pepper. Mix thoroughly for 1 minute.',
            'Portion into five 180g patties, shape into rounds matching the bun size, and place on a tray in the freezer for 30–45 minutes to firm up.',
            'Set up 3 dredging plates: one with 50g flour, one with 2 beaten eggs, and one with 75g crushed cornflakes seasoned with a pinch of salt.',
            'Coat each patty in flour, dip in beaten eggs, and press firmly into crushed cornflakes to coat all sides.',
            'Place patties on a baking sheet, lightly spray with oil, and bake/air-fry at 180°C (355°F) for 15–20 minutes until internal temp reaches 74°C (165°F).',
            'Whisk 75g light mayo, 40g sriracha, and 30g dijon mustard to make the burger sauce.',
            'Assemble burgers with warm brioche buns, a crispy chicken patty, spicy mayo sauce, and fresh shredded iceberg lettuce.'
        ]

    if id == 'yt_L-rDHDD-9I0':
        ingredients = [
            {'name': 'chicken tenderloins', 'quantity': '400g'},
            {'name': 'all-purpose flour', 'quantity': '50g'},
            {'name': 'eggs', 'quantity': '2'},
            {'name': 'cornflakes (crushed)', 'quantity': '50g'},
            {'name': 'pita bread / flatbread', 'quantity': '1'},
            {'name': 'tomato sauce', 'quantity': '50g'},
            {'name': 'mozzarella cheese', 'quantity': '100g'},
            {'name': 'cooked chicken breast', 'quantity': '100g'},
            {'name': 'ripe bananas', 'quantity': '2 (200g)'},
            {'name': 'egg whites', 'quantity': '100g'},
            {'name': 'oats', 'quantity': '50g'},
            {'name': 'vanilla protein powder', 'quantity': '40g'}
        ]
        instructions = [
            'Meal 1 (Chicken Tenders): Remove tendons from 400g chicken tenderloins. Dredge in flour, dip in beaten eggs, coat in crushed seasoned cornflakes, spray with oil, and air-fry at 190°C (375°F) for 10–12 minutes.',
            'Meal 2 (20-Min Air Fryer Pizza): Top a flatbread with 50g tomato sauce, 100g mozzarella, and 100g shredded chicken breast. Air-fry at 200°C (400°F) for 6–8 minutes until bubbly and golden.',
            'Meal 3 (High-Protein Banana Bread): Mash 2 ripe bananas with 100g egg whites, 50g oats, 40g protein powder, and cinnamon. Pour into a loaf tin and air-fry at 160°C (320°F) for 20–25 minutes.'
        ]

    # Apply curated instructions override
    if curated:
        instructions = curated.get('instructions', instructions)

    # Clean instructions: split long paragraphs into multiple numbered sentences
    cleaned_steps = []
    for step in instructions:
        if len(step) > 140:
            s_list = [s.strip() for s in re.split(r'(?<=[.!?])\s+', step) if len(s.strip()) > 15]
            if len(s_list) > 1:
                cleaned_steps.extend(s_list)
            else:
                cleaned_steps.append(step)
        else:
            cleaned_steps.append(step)

    if not cleaned_steps:
        cleaned_steps = ["Follow video instructions for preparation and cooking."]

    return ingredients, cleaned_steps


def clean_and_fix_all_recipes():
    """Main execution function to fix all recipes in database."""
    from server.services import db, calculate_recipe_macros_from_ingredients
    from helpers.tagger import AutoTagger
    from database.models import Recipe, MacroNutrients

    tagger = AutoTagger()

    recipes = db.get_all()
    total = len(recipes)
    logger.info("Found %d recipes in database. Beginning cleanup & re-extraction...", total)

    fixed_count = 0

    for recipe_id, r in recipes.items():
        name = r.get("name", "Untitled")
        orig_desc = r.get("description", "")
        transcript = r.get("transcript", "")
        url = r.get("url", "")
        added_on = r.get("added_on", "")

        clean_ings, clean_ins = extract_recipe_details(recipe_id, r)

        # Sanitize ingredients
        final_ings = []
        for ing in clean_ings:
            ing_name = ing.get("name", "").strip()
            ing_qty = ing.get("quantity", "1").strip()
            lower_name = ing_name.lower()
            if lower_name in ["instructions:", "directions:", "steps:", "method:", "preparation:"]:
                continue
            if any(junk in lower_name for junk in ["http", "cookbook", "amzn.to", "payhip", "felu.co", "walkingpad", "twitch", "patreon", "subscriber", "knife"]):
                continue
            if len(ing_name) < 2:
                continue
            final_ings.append({"name": ing_name, "quantity": ing_qty or "1"})

        # Sanitize instructions
        final_ins = []
        for step in clean_ins:
            s_clean = re.sub(r'^(?:[-=_*~]{2,}|\d+[\.\)]\s*)', '', step).strip()
            if len(s_clean) > 8 and not s_clean.startswith('---') and "disclaimer" not in s_clean.lower():
                final_ins.append(s_clean)

        if not final_ins:
            final_ins = ["Follow video instructions for preparation and cooking."]

        logger.info("Fixing [%s] '%s' -> %d ingredients, %d instructions", recipe_id, name, len(final_ings), len(final_ins))

        # Recalculate accurate macros from ingredients
        calc_result = calculate_recipe_macros_from_ingredients(final_ings)
        calc_ings = calc_result.get("ingredients", final_ings)

        # Create updated Recipe object
        recipe_obj = Recipe(
            name=name,
            url=url,
            description=orig_desc,
            macros=MacroNutrients(
                protein=float(calc_result.get("protein", 0)),
                carbs=float(calc_result.get("carbs", 0)),
                fats=float(calc_result.get("fats", 0)),
                calories=int(calc_result.get("calories", 0))
            ),
            ingredients=calc_ings,
            instructions=final_ins,
            tags=[],
            added_on=added_on,
            transcript=transcript
        )

        # Auto-tag recipe
        recipe_obj.tags = tagger.tag(recipe_obj)

        # Save to database
        db.update(recipe_id, recipe_obj.to_dict())
        fixed_count += 1

    logger.info("SUCCESS! Cleaned and updated %d/%d recipes in database.", fixed_count, total)


if __name__ == "__main__":
    clean_and_fix_all_recipes()
