import os
import re
import json
import sqlite3
import tempfile
import requests
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_url_path='', static_folder='interface')

DB_FILE_PATH = os.path.join(os.path.dirname(__abspath__ := os.path.abspath(__file__)), "database", "recipes_db.json")
NUTRITION_DB_PATH = os.path.join(os.path.dirname(__abspath__), "data", "opennutrition.db")

def calculate_recipe_macros_from_ingredients(ingredients):
    try:
        from helpers.nutrition import NutritionAnalyzer
        analyzer = NutritionAnalyzer()
    except Exception as e:
        print(f"Could not load NutritionAnalyzer: {e}")
        return {"protein": 0, "carbs": 0, "fats": 0, "calories": 0, "ingredients": []}
        
    total_protein = 0.0
    total_carbs = 0.0
    total_fats = 0.0
    total_calories = 0.0
    
    ingredients_breakdown = []
    
    for ing in ingredients:
        name = ing.get('name', '').strip()
        qty_str = ing.get('quantity', '').strip()
        if not name:
            continue
            
        grams = 100.0
        amount_obj = None
        try:
            from ingredient_parser import parse_ingredient
            sentence = f"{qty_str} {name}" if qty_str else name
            result = parse_ingredient(sentence)
            amount_obj = result.amount[0] if result.amount else None
        except Exception:
            pass
            
        grams = analyzer._get_ingredient_grams(amount_obj, name)
        scale = grams / 100.0
        
        db_match = analyzer.lookup_food(name)
        ing_protein = 0.0
        ing_carbs = 0.0
        ing_fats = 0.0
        ing_calories = 0.0
        
        if db_match:
            ing_protein = db_match.protein * scale
            ing_carbs = db_match.carbs * scale
            ing_fats = db_match.fats * scale
            ing_calories = db_match.calories * scale
            
            total_protein += ing_protein
            total_carbs += ing_carbs
            total_fats += ing_fats
            total_calories += ing_calories
            
        ingredients_breakdown.append({
            "name": name,
            "quantity": qty_str,
            "protein": int(round(ing_protein)),
            "carbs": int(round(ing_carbs)),
            "fats": int(round(ing_fats)),
            "calories": int(round(ing_calories))
        })
            
    return {
        "protein": int(round(total_protein)),
        "carbs": int(round(total_carbs)),
        "fats": int(round(total_fats)),
        "calories": int(round(total_calories)),
        "ingredients": ingredients_breakdown
    }

def save_barcode_to_local_db(barcode, name, protein, carbs, fats, calories):
    try:
        conn = sqlite3.connect(NUTRITION_DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO foods (id, name, protein_g, carbs_g, fat_g, energy_kcal) VALUES (?, ?, ?, ?, ?, ?)",
            (barcode, name, protein, carbs, fats, calories)
        )
        cur.execute("SELECT rowid FROM foods WHERE id=?", (barcode,))
        row = cur.fetchone()
        if row:
            rowid = row[0]
            cur.execute("INSERT OR REPLACE INTO foods_fts (rowid, name) VALUES (?, ?)", (rowid, name))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving barcode to DB: {e}")

@app.route('/')
def index():
    return send_from_directory('interface', 'index.html')

@app.route('/recipes_db.json')
def get_db():
    if os.path.exists(DB_FILE_PATH):
        try:
            with open(DB_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
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
    return jsonify({})

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
        data = {}
        if os.path.exists(DB_FILE_PATH):
            with open(DB_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)

        if recipe_id not in data:
            return jsonify({"error": "Recipe not found"}), 404

        # Update fields
        data[recipe_id]['name'] = req_data.get('name', data[recipe_id].get('name'))
        data[recipe_id]['ingredients'] = req_data.get('ingredients', [])
        
        # Calculate macros strictly from ingredients (block user custom updates)
        calc_result = calculate_recipe_macros_from_ingredients(data[recipe_id]['ingredients'])
        data[recipe_id]['macros'] = {
            "protein": calc_result["protein"],
            "carbs": calc_result["carbs"],
            "fats": calc_result["fats"],
            "calories": calc_result["calories"]
        }
        
        data[recipe_id]['tags'] = req_data.get('tags', [])
        
        # Optionally update description/url if provided
        if 'description' in req_data:
            data[recipe_id]['description'] = req_data['description']
        if 'url' in req_data:
            data[recipe_id]['url'] = req_data['url']

        # Save atomically
        dir_name = os.path.dirname(DB_FILE_PATH) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, DB_FILE_PATH)
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise e

        return jsonify({"success": True, "recipe": data[recipe_id]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/ingredients/search', methods=['GET'])
def search_ingredients():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({"results": []})

    if not os.path.exists(NUTRITION_DB_PATH):
        return jsonify({"results": [], "warning": "Nutrition database not initialized"}), 200

    try:
        conn = sqlite3.connect(NUTRITION_DB_PATH)
        cur = conn.cursor()

        # Sanitize query and prepare for prefix match
        sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', q)
        words = [w for w in sanitized.split() if w]
        if not words:
            return jsonify({"results": []})
        
        words[-1] = words[-1] + '*'
        fts_query = ' '.join(words)

        cur.execute(
            """
            SELECT f.name, f.protein_g, f.carbs_g, f.fat_g, f.energy_kcal, f.serving
            FROM foods_fts fts
            JOIN foods f ON f.rowid = fts.rowid
            WHERE foods_fts MATCH ?
            LIMIT 15
            """,
            (fts_query,),
        )
        rows = cur.fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append({
                "name": row[0],
                "protein": row[1],
                "carbs": row[2],
                "fats": row[3],
                "calories": int(round(row[4])) if row[4] else 0,
                "serving": row[5]
            })

        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/barcode/lookup', methods=['GET'])
def lookup_barcode():
    barcode = request.args.get('barcode', '').strip()
    if not barcode:
        return jsonify({"success": False, "error": "Missing barcode"}), 400

    # First check if barcode exists in local DB
    try:
        conn = sqlite3.connect(NUTRITION_DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT name, protein_g, carbs_g, fat_g, energy_kcal FROM foods WHERE id = ?",
            (barcode,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return jsonify({
                "success": True,
                "name": row[0],
                "protein": int(round(row[1])),
                "carbs": int(round(row[2])),
                "fats": int(round(row[3])),
                "calories": int(round(row[4]))
            })
    except Exception as e:
        print(f"Error checking local DB for barcode: {e}")

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
                
                # Cache it to local SQLite
                save_barcode_to_local_db(barcode, name, protein, carbs, fats, calories)
                
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
    app.run(host='127.0.0.1', port=5000, debug=True)
