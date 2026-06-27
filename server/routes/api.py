import re
import requests
from flask import Blueprint, jsonify, request, send_from_directory, redirect
from server.services import (
    db, 
    get_analyzer, 
    calculate_recipe_macros_from_ingredients, 
    save_barcode_to_supabase, 
    fetch_tiktok_thumbnail
)

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/thumbnail')
def get_thumbnail():
    target_url = request.args.get('url')
    if not target_url:
        return jsonify({"error": "url parameter is required"}), 400
        
    thumb_url = fetch_tiktok_thumbnail(target_url)
    if thumb_url:
        return redirect(thumb_url)
        
    # Assuming 'interface' is served correctly or handle relative path
    return send_from_directory('../interface', 'baker.png')

@api_bp.route('/recipes/calculate_macros', methods=['POST'])
def calculate_macros():
    try:
        req_data = request.json or {}
        ingredients = req_data.get('ingredients', [])
        calculated = calculate_recipe_macros_from_ingredients(ingredients)
        return jsonify(calculated)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/recipes/update', methods=['POST'])
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

@api_bp.route('/recipes/delete', methods=['POST'])
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

@api_bp.route('/ingredients/search', methods=['GET'])
def search_ingredients():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({"results": []})

    try:
        try:
            analyzer = get_analyzer()
            q_en = analyzer._translate_if_greek(q)
        except Exception as e:
            print(f"Failed to translate autocomplete query '{q}': {e}")
            q_en = q

        sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', q_en)
        words = [w for w in sanitized.split() if w]
        if not words:
            return jsonify({"results": []})
        
        fts_query = " & ".join(words)
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

@api_bp.route('/barcode/lookup', methods=['GET'])
def lookup_barcode():
    barcode = request.args.get('barcode', '').strip()
    if not barcode:
        return jsonify({"success": False, "error": "Missing barcode"}), 400

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
