import logging
import concurrent.futures
from functools import lru_cache
import requests

from database import RecipeDatabase
import config
from ingredient_parser import parse_ingredient

logger = logging.getLogger(__name__)

RECIPES_TABLE = getattr(config, "RECIPES_TABLE", "recipes")
db = RecipeDatabase(RECIPES_TABLE)

_analyzer = None

def get_analyzer():
    global _analyzer
    if _analyzer is None:
        from helpers.nutrition import NutritionAnalyzer
        _analyzer = NutritionAnalyzer()
    return _analyzer

def calculate_recipe_macros_from_ingredients(ingredients):
    try:
        analyzer = get_analyzer()
    except Exception as e:
        logger.error(f"Could not load NutritionAnalyzer: {e}")
        return {"protein": 0, "carbs": 0, "fats": 0, "calories": 0, "ingredients": []}
        
    total_protein = 0.0
    total_carbs = 0.0
    total_fats = 0.0
    total_calories = 0.0
    
    ingredients_breakdown = []
    
    def process_ingredient(ing):
        name = (ing.get('name') or '').strip()
        qty_str = (ing.get('quantity') or '').strip()
        ing_hash = (ing.get('hash') or '').strip()
        if not name:
            return None
            
        grams = 100.0
        amount_obj = None
        try:
            sentence = f"{qty_str} {name}" if qty_str else name
            result = parse_ingredient(sentence)
            amount_obj = result.amount[0] if result.amount else None
        except Exception:
            pass
            
        grams = analyzer._get_ingredient_grams(amount_obj, name)
        scale = grams / 100.0
        
        db_match = analyzer.lookup_food(name, ing_hash if ing_hash else None)
        ing_protein = 0.0
        ing_carbs = 0.0
        ing_fats = 0.0
        ing_calories = 0.0
        
        if db_match:
            if db_match.food_id:
                ing["hash"] = db_match.food_id
            if db_match.food_name:
                ing["name"] = db_match.food_name
                name = db_match.food_name
                
            ing_protein = db_match.protein * scale
            ing_carbs = db_match.carbs * scale
            ing_fats = db_match.fats * scale
            ing_calories = db_match.calories * scale
            
            ing["protein"] = ing_protein
            ing["carbs"] = ing_carbs
            ing["fats"] = ing_fats
            ing["calories"] = ing_calories
            ing["grams"] = grams
            
        return {
            "name": name,
            "quantity": qty_str,
            "hash": db_match.food_id if db_match else None,
            "protein": int(round(ing_protein)),
            "carbs": int(round(ing_carbs)),
            "fats": int(round(ing_fats)),
            "calories": int(round(ing_calories)),
            "serving": db_match.serving if db_match else None,
            "grams": int(round(grams)),
            "_raw_p": ing_protein,
            "_raw_c": ing_carbs,
            "_raw_f": ing_fats,
            "_raw_cal": ing_calories
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for res in executor.map(process_ingredient, ingredients):
            if res:
                total_protein += res.pop("_raw_p")
                total_carbs += res.pop("_raw_c")
                total_fats += res.pop("_raw_f")
                total_calories += res.pop("_raw_cal")
                ingredients_breakdown.append(res)
            
    return {
        "protein": int(round(total_protein)),
        "carbs": int(round(total_carbs)),
        "fats": int(round(total_fats)),
        "calories": int(round(total_calories)),
        "ingredients": ingredients_breakdown
    }

def save_barcode_to_supabase(barcode, name, protein, carbs, fats, calories):
    try:
        analyzer = get_analyzer()
        data = {
            "id": barcode,
            "name": name,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fats,
            "energy_kcal": calories,
            "serving": None
        }
        analyzer._client.table("foods").upsert(data).execute()
    except Exception as e:
        logger.error(f"Error saving barcode to Supabase: {e}")

@lru_cache(maxsize=512)
def fetch_tiktok_thumbnail(target_url: str):
    try:
        import urllib.parse
        oembed_url = f"https://www.tiktok.com/oembed?url={urllib.parse.quote(target_url)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(oembed_url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return data.get('thumbnail_url')
    except Exception as e:
        logger.error(f"Error fetching thumbnail from oEmbed: {e}")
    return None
