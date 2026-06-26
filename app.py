import os
import config

import re
import json
import tempfile
import requests
import concurrent.futures
from flask import Flask, jsonify, request, send_from_directory, redirect
from ingredient_parser import parse_ingredient

app = Flask(__name__, static_url_path='', static_folder='interface')

from database import RecipeDatabase
import config
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
        print(f"Could not load NutritionAnalyzer: {e}")
        return {"protein": 0, "carbs": 0, "fats": 0, "calories": 0, "ingredients": []}
        
    total_protein = 0.0
    total_carbs = 0.0
    total_fats = 0.0
    total_calories = 0.0
    
    ingredients_breakdown = []
    
    def process_ingredient(ing):
        name = ing.get('name', '').strip()
        qty_str = ing.get('quantity', '').strip()
        ing_hash = ing.get('hash', '').strip()
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

    ingredients_breakdown = []
    
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
        print(f"Error saving barcode to Supabase: {e}")

@app.route('/')
def index():
    return send_from_directory('interface', 'index.html')

@app.route('/api/thumbnail')
def get_thumbnail():
    target_url = request.args.get('url')
    if not target_url:
        return jsonify({"error": "url parameter is required"}), 400
    try:
        import urllib.parse
        oembed_url = f"https://www.tiktok.com/oembed?url={urllib.parse.quote(target_url)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(oembed_url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            thumb_url = data.get('thumbnail_url')
            if thumb_url:
                return redirect(thumb_url)
    except Exception as e:
        print(f"Error fetching thumbnail from oEmbed: {e}")
    return send_from_directory('interface', 'baker.png')

@app.route('/recipes_db.json')
def get_db():
    try:
        data = db.get_all()
        # Make sure all macros are rounded to nearest int in memory/response
        for recipe in data.values():
            if 'macros' in recipe:
                m = recipe['macros']
                recipe['macros'] = {
                    "protein": int(round(m.get("protein", 0))),
                    "carbs": int(round(m.get("carbs", 0))),
                    "fats": int(round(m.get("fats", 0))),
                    "calories": int(round(m.get("calories", 0)))
                }
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/recipes/calculate_macros', methods=['POST'])
def calculate_macros():
    try:
        req_data = request.json or {}
        ingredients = req_data.get('ingredients', [])
        calculated = calculate_recipe_macros_from_ingredients(ingredients)
        return jsonify(calculated)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/recipes/update', methods=['POST'])
def update_recipe():
    try:
        req_data = request.json
        recipe_id = req_data.get('id')
        if not recipe_id:
            return jsonify({"error": "Missing recipe ID"}), 400

        # Load current data
        recipe = db.get(recipe_id)
        if not recipe:
            return jsonify({"error": "Recipe not found"}), 404

        # Update fields
        recipe['name'] = req_data.get('name', recipe.get('name'))
        recipe['ingredients'] = req_data.get('ingredients', [])
        
        # Calculate macros strictly from ingredients (block user custom updates)
        calc_result = calculate_recipe_macros_from_ingredients(recipe['ingredients'])
        recipe['macros'] = {
            "protein": calc_result["protein"],
            "carbs": calc_result["carbs"],
            "fats": calc_result["fats"],
            "calories": calc_result["calories"]
        }
        
        recipe['tags'] = req_data.get('tags', [])
        
        # Optionally update description/url if provided
        if 'description' in req_data:
            recipe['description'] = req_data['description']
        if 'url' in req_data:
            recipe['url'] = req_data['url']

        # Save via database helper
        db.update(recipe_id, recipe)

        return jsonify({"success": True, "recipe": recipe})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/recipes/delete', methods=['POST'])
def delete_recipe():
    try:
        req_data = request.json or {}
        recipe_id = req_data.get('id')
        if not recipe_id:
            return jsonify({"error": "Missing recipe ID"}), 400
        
        success = db.delete(recipe_id)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/ingredients/search', methods=['GET'])
def search_ingredients():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({"results": []})

    try:
        # Translate Greek search queries to English first
        try:
            analyzer = get_analyzer()
            q_en = analyzer._translate_if_greek(q)
        except Exception as e:
            print(f"Failed to translate autocomplete query '{q}': {e}")
            q_en = q

        # Sanitize query and prepare for full-text search
        sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', q_en)
        words = [w for w in sanitized.split() if w]
        if not words:
            return jsonify({"results": []})
        
        # Format as postgrest websearch query (e.g. "chicken & breast")
        fts_query = " & ".join(words)

        # Query Supabase foods table using full-text search
        response = analyzer._client.table("foods").select("name, protein_g, carbs_g, fat_g, energy_kcal, serving").limit(15).text_search("name", fts_query).execute()
        
        results = []
        for row in response.data:
            results.append({
                "name": row.get("name"),
                "protein": row.get("protein_g") or 0.0,
                "carbs": row.get("carbs_g") or 0.0,
                "fats": row.get("fat_g") or 0.0,
                "calories": int(round(row.get("energy_kcal") or 0)),
                "serving": row.get("serving")
            })

        # Fallback to ILIKE if no results found on FTS
        if not results:
            response = analyzer._client.table("foods").select("name, protein_g, carbs_g, fat_g, energy_kcal, serving").limit(15).ilike("name", f"%{q_en}%").execute()
            for row in response.data:
                results.append({
                    "name": row.get("name"),
                    "protein": row.get("protein_g") or 0.0,
                    "carbs": row.get("carbs_g") or 0.0,
                    "fats": row.get("fat_g") or 0.0,
                    "calories": int(round(row.get("energy_kcal") or 0)),
                    "serving": row.get("serving")
                })

        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/barcode/lookup', methods=['GET'])
def lookup_barcode():
    barcode = request.args.get('barcode', '').strip()
    if not barcode:
        return jsonify({"success": False, "error": "Missing barcode"}), 400

    # First check if barcode exists in Supabase foods table
    try:
        analyzer = get_analyzer()
        response = analyzer._client.table("foods").select("name, protein_g, carbs_g, fat_g, energy_kcal").limit(1).eq("id", barcode).execute()
        if response.data:
            row = response.data[0]
            return jsonify({
                "success": True,
                "name": row.get("name"),
                "protein": int(round(row.get("protein_g") or 0)),
                "carbs": int(round(row.get("carbs_g") or 0)),
                "fats": int(round(row.get("fat_g") or 0)),
                "calories": int(round(row.get("energy_kcal") or 0))
            })
    except Exception as e:
        print(f"Error checking Supabase for barcode: {e}")

    # Fetch from Open Food Facts
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    headers = {"User-Agent": "Grams - WebApp - Version 1.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            res_data = resp.json()
            if res_data.get("status") == 1:
                product = res_data.get("product", {})
                nutriments = product.get("nutriments", {})
                
                name = product.get("product_name") or product.get("generic_name") or "Unknown Product"
                protein = float(nutriments.get("proteins_100g") or 0)
                carbs = float(nutriments.get("carbohydrates_100g") or 0)
                fats = float(nutriments.get("fat_100g") or 0)
                calories = float(nutriments.get("energy-kcal_100g") or nutriments.get("energy_100g", 0) / 4.184)
                
                # Cache it to Supabase
                save_barcode_to_supabase(barcode, name, protein, carbs, fats, calories)
                
                return jsonify({
                    "success": True,
                    "name": name,
                    "protein": int(round(protein)),
                    "carbs": int(round(carbs)),
                    "fats": int(round(fats)),
                    "calories": int(round(calories))
                })
    except Exception as e:
        print(f"Error fetching from Open Food Facts: {e}")

    return jsonify({"success": False, "error": "Product not found"}), 404

if __name__ == '__main__':
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    app.run(host=host, port=port, debug=True)
