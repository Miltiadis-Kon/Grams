#!/usr/bin/env python3
"""
Comprehensive Recipe Cleaner, Multi-Meal Splitter & Extractor for Grams.
- Splits multi-meal compilation videos into standalone single-meal recipes.
- Removes duplicate ingredients and cleans quantities.
- Removes marketing boilerplate, links, and social prompts.
- Recalculates accurate macronutrients and updates PostgreSQL.
"""

import os
import sys
import re
import json
import logging
from typing import List, Dict, Tuple, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("fix_recipes")

# Multi-meal split specifications
MULTI_MEAL_RECIPES = {
    'yt_ZgXSr4NPZo8': [
        {
            'id_suffix': '_1',
            'name': 'High-Protein Egg Sandwich',
            'servings': 1,
            'ingredients': [
                {'name': 'whole eggs', 'quantity': '1'},
                {'name': 'egg whites', 'quantity': '100g'},
                {'name': 'sandwich bread', 'quantity': '2 slices'},
                {'name': 'deli chicken breast', 'quantity': '50g'},
                {'name': 'butter', 'quantity': '7g'},
                {'name': 'American cheese slice', 'quantity': '1 slice'},
                {'name': 'salt and black pepper', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Whisk 1 whole egg with 100g egg whites, salt, and black pepper.',
                'Melt 7g butter in a non-stick pan over medium heat and scramble the eggs until fluffy.',
                'Toast 2 slices of sandwich bread. Layer the cooked eggs, 50g deli chicken, and 1 slice of cheese between the warm bread.'
            ]
        },
        {
            'id_suffix': '_2',
            'name': 'Beef & Udon Noodle Bowl',
            'servings': 1,
            'ingredients': [
                {'name': 'udon noodles', 'quantity': '200g'},
                {'name': 'extra lean ground beef', 'quantity': '180g'},
                {'name': 'onion', 'quantity': '1'},
                {'name': 'pak choi (bok choy)', 'quantity': '150g'},
                {'name': 'miso paste', 'quantity': '30g'},
                {'name': 'gochujang', 'quantity': '20g'},
                {'name': 'olive oil', 'quantity': '6g'},
                {'name': 'salt', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'In a skillet with 6g oil, brown 180g extra lean ground beef over medium-high heat.',
                'Add 1 diced onion and 150g chopped pak choi to the pan and sauté for 3 minutes.',
                'Whisk 30g miso and 20g gochujang into 250g warm water; pour over the beef and vegetables.',
                'Add 200g cooked udon noodles and simmer for 2 minutes until the sauce coats the noodles.'
            ]
        },
        {
            'id_suffix': '_3',
            'name': 'Honey Mustard Chicken & Sweet Potatoes',
            'servings': 1,
            'ingredients': [
                {'name': 'sweet potatoes', 'quantity': '300g'},
                {'name': 'chicken breast', 'quantity': '200g'},
                {'name': 'light feta cheese', 'quantity': '30g'},
                {'name': 'honey', 'quantity': '10g'},
                {'name': 'mustard', 'quantity': '10g'},
                {'name': 'sriracha', 'quantity': '5g'},
                {'name': 'olive oil', 'quantity': '4g'},
                {'name': 'smoked paprika', 'quantity': '1/2 tsp'},
                {'name': 'garlic powder', 'quantity': '1/4 tsp'},
                {'name': 'cayenne pepper', 'quantity': '1/4 tsp'},
                {'name': 'salt and black pepper', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Dice 300g sweet potatoes and toss with 2g oil, smoked paprika, garlic powder, and salt. Bake at 200°C (400°F) for 30–35 minutes until tender.',
                'Season 200g chicken breast with salt, pepper, and cayenne. Sear in a hot skillet with 2g oil for 6–8 minutes until cooked through.',
                'In a small bowl, whisk 10g honey, 10g mustard, and 5g sriracha into a smooth sauce.',
                'Plate the roasted sweet potatoes and sliced chicken breast, drizzle with honey mustard sauce, and crumble 30g feta over top.'
            ]
        }
    ],
    'yt_CpU1Tqg2884': [
        {
            'id_suffix': '_1',
            'name': 'High-Protein Breakfast Quesadilla',
            'servings': 1,
            'ingredients': [
                {'name': 'tortilla wrap', 'quantity': '1'},
                {'name': 'whole eggs', 'quantity': '1'},
                {'name': 'egg whites', 'quantity': '100g'},
                {'name': 'shredded mozzarella cheese', 'quantity': '30g'},
                {'name': 'deli meat', 'quantity': '50g'},
                {'name': 'butter', 'quantity': '6g'},
                {'name': 'salt and black pepper', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Whisk 1 egg with 100g egg whites, salt, and black pepper.',
                'Scramble the eggs in a pan with 3g butter until soft.',
                'Place a tortilla in a warm pan with remaining butter, layer with cooked eggs, 50g deli meat, and 30g mozzarella.',
                'Fold tortilla in half and toast on both sides until crispy and cheese is melted.'
            ]
        },
        {
            'id_suffix': '_2',
            'name': 'Creamy Chicken Alfredo & Roasted Potatoes',
            'servings': 1,
            'ingredients': [
                {'name': 'potatoes', 'quantity': '300g'},
                {'name': 'chicken breast', 'quantity': '180g'},
                {'name': 'onion', 'quantity': '1'},
                {'name': 'cottage cheese (low fat)', 'quantity': '100g'},
                {'name': 'evaporated milk', 'quantity': '50g'},
                {'name': 'parmesan cheese', 'quantity': '20g'},
                {'name': 'olive oil', 'quantity': '7g'},
                {'name': 'garlic powder', 'quantity': '1/4 tsp'},
                {'name': 'onion powder', 'quantity': '1/4 tsp'},
                {'name': 'salt and black pepper', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Dice 300g potatoes, season with 4g oil, salt, and pepper, and roast at 200°C (400°F) for 25 minutes.',
                'Sear 180g diced chicken breast and 1 chopped onion in a skillet with 3g oil for 6–8 minutes.',
                'Blend 100g cottage cheese, 50g evaporated milk, 20g parmesan, garlic powder, and onion powder until completely smooth.',
                'Pour Alfredo sauce over the chicken in the skillet on low heat and serve with the roasted potatoes.'
            ]
        },
        {
            'id_suffix': '_3',
            'name': 'High-Protein Chocolate PB Cheesecake',
            'servings': 4,
            'ingredients': [
                {'name': 'Greek yogurt 0%', 'quantity': '340g'},
                {'name': 'light cream cheese', 'quantity': '340g'},
                {'name': 'egg whites', 'quantity': '100g'},
                {'name': 'cocoa powder', 'quantity': '30g'},
                {'name': 'all-purpose flour', 'quantity': '30g'},
                {'name': 'peanut butter', 'quantity': '50g'},
                {'name': 'sweetener', 'quantity': '50g'}
            ],
            'instructions': [
                'In a large mixing bowl, beat 340g Greek yogurt, 340g cream cheese, and 100g egg whites until smooth.',
                'Whisk in 30g cocoa powder, 30g flour, 50g peanut butter, and 50g sweetener until fully incorporated.',
                'Pour batter into a greased 7-inch springform pan.',
                'Bake at 160°C (320°F) for 35–45 minutes until the center is just set. Chill in refrigerator before slicing.'
            ]
        }
    ],
    'yt_2-tnmkCCdL4': [
        {
            'id_suffix': '_1',
            'name': 'Peanut Butter Chicken Noodle Bowl',
            'servings': 1,
            'ingredients': [
                {'name': 'chicken breast', 'quantity': '200g'},
                {'name': 'udon / ramen noodles', 'quantity': '200g'},
                {'name': 'bell pepper', 'quantity': '1'},
                {'name': 'onion', 'quantity': '1'},
                {'name': 'peanut butter', 'quantity': '20g'},
                {'name': 'rice vinegar', 'quantity': '10g'},
                {'name': 'honey', 'quantity': '5g'},
                {'name': 'lime juice', 'quantity': '1/2 lime'},
                {'name': 'olive oil', 'quantity': '6g'},
                {'name': 'garlic powder', 'quantity': '1/4 tsp'},
                {'name': 'salt and black pepper', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Dice 200g chicken breast and sear in a hot skillet with 6g oil, bell pepper, and onion for 7 minutes.',
                'In a small bowl, whisk 20g peanut butter, 10g rice vinegar, 5g honey, lime juice, and garlic powder with 2 tbsp warm water.',
                'Boil 200g noodles, drain, and toss with the cooked chicken, vegetables, and peanut sauce.'
            ]
        },
        {
            'id_suffix': '_2',
            'name': 'High-Protein Cheeseburger Bowl',
            'servings': 1,
            'ingredients': [
                {'name': 'extra lean ground beef', 'quantity': '180g'},
                {'name': 'potatoes', 'quantity': '250g'},
                {'name': 'onion', 'quantity': '1'},
                {'name': 'lettuce', 'quantity': '50g'},
                {'name': 'tomatoes', 'quantity': '100g'},
                {'name': 'pickles', 'quantity': '50g'},
                {'name': 'cheddar cheese', 'quantity': '15g'},
                {'name': 'light mayo', 'quantity': '20g'},
                {'name': 'sriracha', 'quantity': '10g'},
                {'name': 'mustard', 'quantity': '10g'},
                {'name': 'olive oil', 'quantity': '6g'},
                {'name': 'garlic powder', 'quantity': '1/4 tsp'},
                {'name': 'salt and black pepper', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Cube 250g potatoes, toss with 3g oil and salt, and air-fry at 200°C (400°F) for 20 minutes.',
                'Brown 180g ground beef in a skillet with remaining oil, garlic powder, salt, and pepper. Top with 15g cheddar to melt.',
                'Whisk 20g light mayo, 10g sriracha, and 10g mustard to make the burger sauce.',
                'Assemble bowl with chopped lettuce, sliced tomatoes, pickles, crispy potatoes, and cheesy beef; drizzle with burger sauce.'
            ]
        },
        {
            'id_suffix': '_3',
            'name': 'Panizza (Quick Skillet Pizza)',
            'servings': 1,
            'ingredients': [
                {'name': 'all-purpose flour', 'quantity': '30g'},
                {'name': 'Greek yogurt 0%', 'quantity': '70g'},
                {'name': 'egg whites', 'quantity': '70g'},
                {'name': 'tomato sauce', 'quantity': '60g'},
                {'name': 'deli meat', 'quantity': '50g'},
                {'name': 'shredded mozzarella cheese', 'quantity': '50g'},
                {'name': 'garlic powder', 'quantity': '1/4 tsp'},
                {'name': 'salt', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'In a bowl, mix 30g flour, 70g Greek yogurt, 70g egg whites, garlic powder, and a pinch of salt until smooth.',
                'Pour batter into a greased non-stick skillet over medium-low heat. Cover with a lid and cook for 4–5 minutes until the bottom sets.',
                'Spread 60g tomato sauce over the dough, add 50g deli meat, and top with 50g mozzarella.',
                'Cover and cook for another 3–4 minutes until the cheese is completely melted and bubbly.'
            ]
        }
    ],
    'yt_L-rDHDD-9I0': [
        {
            'id_suffix': '_1',
            'name': 'Crispy Air Fryer Chicken Tenders',
            'servings': 2,
            'ingredients': [
                {'name': 'chicken tenderloins', 'quantity': '400g'},
                {'name': 'all-purpose flour', 'quantity': '50g'},
                {'name': 'whole eggs', 'quantity': '2'},
                {'name': 'cornflakes (crushed)', 'quantity': '50g'},
                {'name': 'garlic powder', 'quantity': '1/2 tsp'},
                {'name': 'smoked paprika', 'quantity': '1/2 tsp'},
                {'name': 'salt and black pepper', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Remove tendons from 400g chicken tenderloins.',
                'Dredge chicken tenders in 50g seasoned flour, dip in 2 beaten eggs, and coat thoroughly in 50g crushed cornflakes.',
                'Lightly spray with cooking oil and air-fry at 190°C (375°F) for 10–12 minutes until crispy and golden brown.'
            ]
        },
        {
            'id_suffix': '_2',
            'name': '20-Minute Air Fryer Flatbread Pizza',
            'servings': 1,
            'ingredients': [
                {'name': 'pita bread / flatbread', 'quantity': '1'},
                {'name': 'tomato sauce', 'quantity': '50g'},
                {'name': 'shredded mozzarella cheese', 'quantity': '100g'},
                {'name': 'cooked chicken breast', 'quantity': '100g'},
                {'name': 'Italian oregano', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Spread 50g tomato sauce evenly over 1 flatbread or pita.',
                'Top with 100g shredded mozzarella cheese and 100g diced cooked chicken breast.',
                'Air-fry at 200°C (400°F) for 6–8 minutes until the crust is crisp and cheese is bubbling.'
            ]
        },
        {
            'id_suffix': '_3',
            'name': 'High-Protein Banana Bread',
            'servings': 2,
            'ingredients': [
                {'name': 'ripe bananas', 'quantity': '2 (200g)'},
                {'name': 'egg whites', 'quantity': '100g'},
                {'name': 'rolled oats', 'quantity': '50g'},
                {'name': 'vanilla protein powder', 'quantity': '40g'},
                {'name': 'cinnamon', 'quantity': '1/2 tsp'}
            ],
            'instructions': [
                'In a bowl, mash 2 ripe bananas with a fork.',
                'Stir in 100g egg whites, 50g oats, 40g vanilla protein powder, and 1/2 tsp cinnamon until a thick batter forms.',
                'Pour into a small parchment-lined loaf tin and air-fry at 160°C (320°F) for 20–25 minutes until firm.'
            ]
        }
    ],
    'yt_ROoLkpGxQ8E': [
        {
            'id_suffix': '',
            'name': 'Meal Prep Breakfast Burritos (10 Servings)',
            'servings': 10,
            'ingredients': [
                {'name': 'tortilla wrap', 'quantity': '10'},
                {'name': 'lean ground beef 95/5', 'quantity': '500g'},
                {'name': 'whole eggs', 'quantity': '20'},
                {'name': 'cheddar cheese', 'quantity': '150g'},
                {'name': 'potatoes', 'quantity': '500g'},
                {'name': 'onion', 'quantity': '300g'},
                {'name': 'bell pepper', 'quantity': '300g'},
                {'name': 'olive oil', 'quantity': '30g'},
                {'name': 'Greek yogurt 0%', 'quantity': '300g'},
                {'name': 'lime juice', 'quantity': '1 lime'},
                {'name': 'fresh cilantro', 'quantity': '10g'},
                {'name': 'smoked paprika', 'quantity': '2 tsp'},
                {'name': 'cayenne pepper', 'quantity': '2 tsp'},
                {'name': 'garlic powder', 'quantity': '2 tsp'},
                {'name': 'salt and black pepper', 'quantity': '1 pinch'}
            ],
            'instructions': [
                'Preheat oven to 200°C (400°F). Toss 500g diced potatoes, 300g onions, and 300g bell peppers with 15g oil and seasonings on a sheet pan; roast for 20 minutes.',
                'Brown 500g lean ground beef in a skillet with seasonings.',
                'Whisk 20 eggs with salt and pepper, pour onto a greased sheet pan, and bake for 12–15 minutes until set.',
                'Whisk 300g Greek yogurt, 15g olive oil, lime juice, cilantro, and garlic powder for the sauce.',
                'Assemble 10 burritos with tortillas, roasted potatoes, ground beef, sliced egg patty, 150g cheddar, and sauce. Wrap in foil and freeze.'
            ]
        }
    ]
}


def clean_raw_description(desc: str) -> str:
    """Pre-cleans description text, stripping links, noise, and sponsors."""
    if not desc:
        return ""

    from recipe_processor.normalization import IngestionNormalizer
    return IngestionNormalizer.clean_text(desc)


def parse_line_as_ingredient(line: str) -> Dict[str, str]:
    """Parse a single text line into clean food name & quantity."""
    line = line.strip()
    if not line or len(line) > 85:
        return None

    lower = line.lower()

    # Reject section headers & non-food lines
    if lower in ["instructions:", "directions:", "steps:", "method:", "preparation:", "ingredients:", "optional:", "optional", "sauce:", "topping:", "garnish:"]:
        return None

    if any(h in lower for h in [
        "http", "cookbook", "amzn", "click", "subscribe", "pan", "knife", "blender", "scale",
        "air fryer", "stovetop", "container", "live stream", "connect on", "socials", "macros"
    ]):
        if not any(food in lower for food in ["oil", "spray", "butter", "egg", "chicken", "beef", "flour", "milk", "cheese"]):
            return None

    from recipe_processor.validator import RecipeValidator
    from ingredient_parser import parse_ingredient
    try:
        parsed = parse_ingredient(line)
        has_amount = parsed and parsed.amount and len(parsed.amount) > 0
        has_name = parsed and parsed.name and len(parsed.name) > 0

        if has_name and has_amount:
            name = " ".join([n.text for n in parsed.name]).strip()
            qty = " ".join([a.text for a in parsed.amount]).strip()
            if RecipeValidator.is_valid_food_name(name):
                return {"name": name, "quantity": qty or "1"}
    except Exception:
        pass

    m = re.match(r'^((?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|portion|portions)?)\s*(?:of\s+)?(.*)$', line, re.IGNORECASE)
    if m:
        qty = m.group(1).strip()
        name = m.group(2).strip()
        if RecipeValidator.is_valid_food_name(name):
            return {"name": name, "quantity": qty or "1"}

    if len(line) < 40 and not line.endswith('.') and RecipeValidator.is_valid_food_name(line):
        return {"name": line, "quantity": "1"}

    return None


def clean_and_fix_all_recipes():
    """Main execution function to fix, split, and clean all recipes in database."""
    from server.services import db, calculate_recipe_macros_from_ingredients
    from helpers.tagger import AutoTagger
    from database.models import Recipe, MacroNutrients
    from recipe_processor.validator import RecipeValidator

    tagger = AutoTagger()
    fixed_count = 0

    # 1. Process all Multi-Meal Recipes first
    for recipe_id, sub_recipes in MULTI_MEAL_RECIPES.items():
        logger.info("SPLITTING multi-meal video [%s] into %d standalone recipes", recipe_id, len(sub_recipes))

        # Retrieve existing metadata if present
        existing_parent = db.get(recipe_id) or {}
        orig_desc = existing_parent.get("description", "")
        url = existing_parent.get("url", f"https://www.youtube.com/watch?v={recipe_id.replace('yt_', '')}")
        added_on = existing_parent.get("added_on", "")
        transcript = existing_parent.get("transcript", "")

        for meal_spec in sub_recipes:
            sub_id = f"{recipe_id}{meal_spec['id_suffix']}"
            sub_name = meal_spec['name']
            sub_servings = meal_spec.get('servings', 1)
            sub_raw_ings = meal_spec['ingredients']
            sub_ins = meal_spec['instructions']

            reconciled = RecipeValidator.reconcile_recipe_payload({
                "is_recipe": True,
                "title": sub_name,
                "servings": sub_servings,
                "ingredients": sub_raw_ings,
                "instructions": sub_ins
            })

            calc_result = calculate_recipe_macros_from_ingredients(reconciled["ingredients"])
            calc_ings = calc_result.get("ingredients", reconciled["ingredients"])

            tot_p = float(calc_result.get("protein", 0))
            tot_c = float(calc_result.get("carbs", 0))
            tot_f = float(calc_result.get("fats", 0))
            tot_cal = int(calc_result.get("calories", 0))

            if sub_servings > 1:
                serv_p = round(tot_p / sub_servings, 1)
                serv_c = round(tot_c / sub_servings, 1)
                serv_f = round(tot_f / sub_servings, 1)
                serv_cal = int(round(tot_cal / sub_servings))
            else:
                serv_p, serv_c, serv_f, serv_cal = tot_p, tot_c, tot_f, tot_cal

            sub_recipe_obj = Recipe(
                name=sub_name,
                url=url,
                description=orig_desc,
                macros=MacroNutrients(protein=serv_p, carbs=serv_c, fats=serv_f, calories=serv_cal),
                ingredients=calc_ings,
                instructions=sub_ins,
                tags=[],
                added_on=added_on,
                transcript=transcript
            )
            sub_recipe_obj.tags = tagger.tag(sub_recipe_obj)

            if db.exists(sub_id):
                db.update(sub_id, sub_recipe_obj.to_dict())
            else:
                db.insert(sub_id, sub_recipe_obj)
            fixed_count += 1
            logger.info("Saved sub-recipe '%s': %s (P:%.0fg, C:%.0fg, F:%.0fg, %d kcal)", sub_id, sub_name, serv_p, serv_c, serv_f, serv_cal)

        if any(m['id_suffix'] != '' for m in sub_recipes):
            if db.exists(recipe_id):
                db.delete(recipe_id)
                logger.info("Deleted monolithic composite record '%s'", recipe_id)

    # 2. Process all remaining recipes
    recipes = db.get_all()
    total = len(recipes)
    logger.info("Processing %d recipes in database for cleaning...", total)

    for recipe_id, r in recipes.items():
        if recipe_id in MULTI_MEAL_RECIPES or any(recipe_id.startswith(f"{m}_") for m in MULTI_MEAL_RECIPES):
            continue

        name = r.get("name", "Untitled")
        orig_desc = r.get("description", "")
        transcript = r.get("transcript", "")
        url = r.get("url", "")
        added_on = r.get("added_on", "")

        # 2. Standard Single Recipe Processing
        cleaned_desc = clean_raw_description(orig_desc)
        paragraphs = [p.strip() for p in cleaned_desc.split('\n\n') if p.strip()]

        ingredients = []
        instructions = []

        qty_regex = re.compile(
            r'^(?:(?:\d+(?:[./]\d+)?|\u00bc|\u00bd|\u00be|\u2153|\u2154|\d+\s*-\s*\d+)\s*(?:g|gram|grams|kg|ml|l|liter|liters|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|cup|cups|scoop|scoops|oz|ounce|ounces|clove|cloves|slice|slices|can|cans|piece|pieces|pinch|pinches|serving|servings|portion|portions)?\b|salt\b|pepper\b|black pepper\b|seasonings?\b)',
            re.IGNORECASE
        )

        for p in paragraphs:
            p_lines = [pl.strip() for pl in p.splitlines() if pl.strip()]
            has_qty = sum(1 for pl in p_lines if qty_regex.match(pl) or (len(pl) < 55 and not pl.endswith('.')))

            if has_qty >= len(p_lines) * 0.5 and len(p_lines) > 0 and len(p) < 700:
                for pl in p_lines:
                    if re.match(r'^(?:macros|nutrition|calories|servings|serving size)[:\s]', pl.lower()):
                        continue
                    if len(pl) > 85:
                        continue
                    # Split plus lines (e.g. 10g honey + 10g mustard)
                    if "+" in pl and not any(k in pl.lower() for k in ["flour", "powder"]):
                        for sub_item in pl.split("+"):
                            parsed_ing = parse_line_as_ingredient(sub_item)
                            if parsed_ing:
                                ingredients.append(parsed_ing)
                    else:
                        parsed_ing = parse_line_as_ingredient(pl)
                        if parsed_ing:
                            ingredients.append(parsed_ing)
            else:
                if len(p) > 20 and not instructions:
                    clean_p = re.sub(r'^instructions:?\s*', '', p, flags=re.IGNORECASE).strip()
                    if clean_p and not any(j in clean_p.lower() for j in ["disclaimer:", "amazon links", "cookbook"]):
                        instructions.append(clean_p)

        if not instructions:
            instructions = ["Follow video instructions for preparation and cooking."]

        # Reconcile through validator to deduplicate stems & clean quantities
        reconciled = RecipeValidator.reconcile_recipe_payload({
            "is_recipe": True,
            "title": name,
            "servings": 1,
            "ingredients": ingredients,
            "instructions": instructions
        })

        calc_result = calculate_recipe_macros_from_ingredients(reconciled["ingredients"])
        calc_ings = calc_result.get("ingredients", reconciled["ingredients"])

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
            instructions=reconciled["instructions"] or instructions,
            tags=[],
            added_on=added_on,
            transcript=transcript
        )
        recipe_obj.tags = tagger.tag(recipe_obj)

        if not calc_ings or not reconciled.get("is_recipe") or (calc_result.get("protein", 0) == 0 and calc_result.get("carbs", 0) == 0 and calc_result.get("calories", 0) == 0):
            if db.exists(recipe_id):
                db.delete(recipe_id)
            from server.services import not_added_db
            if not_added_db.exists(recipe_id):
                not_added_db.delete(recipe_id)
            not_added_db.insert(recipe_id, recipe_obj)
            logger.info("ROUTED TO MANUAL REVIEW: Recipe '%s' (%s) saved in manual check list", recipe_id, name)
            continue

        db.update(recipe_id, recipe_obj.to_dict())
        fixed_count += 1

    logger.info("SUCCESS! Cleaned, split, and updated %d recipes in database.", fixed_count)


if __name__ == "__main__":
    clean_and_fix_all_recipes()
