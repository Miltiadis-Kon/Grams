import io
import sys
import os
import re
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.nutrition import NutritionAnalyzer

analyzer = NutritionAnalyzer()

# Test Video 1 and Video 2 ingredients
vid1_ingredients = [
    {"name": "Low Fat Cottage Cheese", "quantity": "6 Cups"},
    {"name": "Whole Eggs", "quantity": "12"},
    {"name": "Vanilla Extract", "quantity": "3 Tsp"},
    {"name": "SF Maple Syrup", "quantity": "12 Tbsp"},
    {"name": "Self Rising Flour", "quantity": "3.75 Cups"},
    {"name": "Stevia Chocolate Chips", "quantity": "180g"}
]

vid2_ingredients = [
    {"name": "Plain or Vanilla Nonfat Greek Yogurt (cookie batter)", "quantity": "40g (3 tbsp)"},
    {"name": "Egg Whites (cookie batter)", "quantity": "25mL (1 tbsp + 2 tsp)"},
    {"name": "Vanilla Extract (optional)", "quantity": "2.1mL (1/2 tsp)"},
    {"name": "All Purpose Flour (cookie batter)", "quantity": "10g (1 tbsp + 1 tsp)"},
    {"name": "Casein Protein Powder", "quantity": "10g (1/3 Scoop)"},
    {"name": "Oat Flour", "quantity": "5g (2 tsp)"},
    {"name": "Granulated Sugar Substitute (cookie batter)", "quantity": "24g (2 tbsp)"},
    {"name": "Baking Soda (cookie batter)", "quantity": "1g (1/4 tsp)"},
    {"name": "Salt (cookie batter)", "quantity": "1"},
    {"name": "Egg Whites (brownie batter)", "quantity": "120mL (1/2 Cup)"},
    {"name": "Plain or Vanilla Nonfat Greek Yogurt (brownie batter)", "quantity": "80g (1/3 Cup)"},
    {"name": "Pumpkin Purée", "quantity": "120g (1/2 Cup)"},
    {"name": "Almond Milk", "quantity": "120mL (1/2 Cup)"},
    {"name": "All Purpose Flour (brownie batter)", "quantity": "35g (1/4 Cup)"},
    {"name": "Granulated Sugar Substitute (brownie batter)", "quantity": "72-96g (6-8 tbsp)"},
    {"name": "Whey/Casein Blend Protein Powder", "quantity": "20g (2/3 Scoop)"},
    {"name": "Black or Dark Cocoa Powder", "quantity": "25g (1/4 Cup)"},
    {"name": "Baking Soda (brownie batter)", "quantity": "2g (1/3 tsp)"},
    {"name": "Baking Powder", "quantity": "2g (1/2 tsp)"},
    {"name": "Salt (brownie batter)", "quantity": "1"},
    {"name": "Chocolate Chips", "quantity": "10g"}
]

for label, ingrs in [("VIDEO 1: Protein Pancakes", vid1_ingredients), ("VIDEO 2: Brownies", vid2_ingredients)]:
    print("\n" + "=" * 110)
    print(" ", label)
    print("=" * 110)
    for ing in ingrs:
        name_raw = ing["name"]
        qty_raw = ing["quantity"]
        cleaned_name = re.sub(r'\(.*?\)', ' ', name_raw)
        cleaned_name = re.sub(r'\b(?:plain|black|white|unbleached)\s+or\s+', ' ', cleaned_name, flags=re.IGNORECASE)
        cleaned_name = re.sub(r'\bSF\b', 'sugar free', cleaned_name, flags=re.IGNORECASE)
        cleaned_name = ' '.join(cleaned_name.split()).strip()

        db_match = analyzer.lookup_food(cleaned_name)
        if db_match:
            # Estimate grams
            grams = 100.0
            range_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*g', qty_raw, re.IGNORECASE)
            if range_match:
                grams = (float(range_match.group(1)) + float(range_match.group(2))) / 2.0
            else:
                gm_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:g|ml|grams)', qty_raw, re.IGNORECASE)
                if gm_match:
                    grams = float(gm_match.group(1))
                else:
                    cup_match = re.search(r'(\d+(?:\.\d+)?)\s*cups?', qty_raw, re.IGNORECASE)
                    if cup_match:
                        cups = float(cup_match.group(1))
                        grams = cups * 125.0 if "flour" in cleaned_name.lower() else (cups * 226.0 if "cheese" in cleaned_name.lower() else cups * 240.0)
                    else:
                        tbsp_match = re.search(r'(\d+(?:\.\d+)?)\s*tbsp', qty_raw, re.IGNORECASE)
                        if tbsp_match:
                            grams = float(tbsp_match.group(1)) * 15.0
                        else:
                            tsp_match = re.search(r'(\d+(?:\.\d+)?)\s*tsp', qty_raw, re.IGNORECASE)
                            if tsp_match:
                                grams = float(tsp_match.group(1)) * 5.0
                            else:
                                count_match = re.search(r'^(\d+(?:\.\d+)?)$', qty_raw.strip())
                                if count_match:
                                    cnt = float(count_match.group(1))
                                    grams = cnt * 50.0 if "egg" in cleaned_name.lower() else (cnt * 0.5 if "salt" in cleaned_name.lower() else cnt * 100.0)

            scale = grams / 100.0
            p = db_match.protein * scale
            c = db_match.carbs * scale
            f = db_match.fats * scale
            cal = db_match.calories * scale
            print(f"{name_raw:<48} | {qty_raw:<15} | {grams:>6.1f}g | {cal:>6.1f} kcal | P:{p:>5.1f}g C:{c:>5.1f}g F:{f:>5.1f}g | -> {db_match.food_name[:25]}")
        else:
            print(f"{name_raw:<48} | {qty_raw:<15} | NO MATCH")
