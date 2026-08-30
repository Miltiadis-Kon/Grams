import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from helpers.nutrition import NutritionAnalyzer
from recipe_processor.validator import RecipeValidator
from server.services import calculate_recipe_macros_from_ingredients

analyzer = NutritionAnalyzer()

desc = '''Πατατο-Ομελετο-Κατάσταση! Σίγουρα καλοκαιρινό φαγητό και φυσικά εύκολο και νόστιμο. Υλικά  3 μεγάλες Πατάτες 5 Αυγά 1 Πιπεριά Φλωρίνης 100γρ Ντοματίνια Αλάτι Πιπέρι 200γρ Τυρί φέτα Ελαιόλαδο Δοκίμασε το και περιμένω εντυπώσεις!'''

norm = re.sub(r'(\d+)\s*(γρ|γρ\.|κιλά|κ\.σ\.|κ\.γ\.|κουταλιές|τεμ|τεμάχια|ml|g|kg)', r'\1 \2', desc, flags=re.IGNORECASE)
if 'υλικά' in norm.lower():
    parts = re.split(r'(?i)υλικά[:\s]*', norm, maxsplit=1)
    body = parts[1]
    body = re.sub(r'\s+(\d+\s*(?:μεγάλες|μικρές|φέτες|κ\.σ\.|κ\.γ\.|γρ|κιλά|κουταλιές|αυγά)?\s*[Α-Ωα-ωά-ώ]+)', r'\n- \1', body)
    body = re.sub(r'\s+(Αλάτι|Πιπέρι|Ελαιόλαδο|Ρίγανη|Σκόρδο)', r'\n- \1', body)
    norm = f"{parts[0]}\n\n{body}"

lines = [l.strip() for l in norm.splitlines() if l.strip()]
ings = []
for line in lines:
    clean = re.sub(r'^(?:[-•*:]\s*|\d+[\.\)]\s*)', '', line).strip()
    if not clean or clean.startswith('Πατατο') or 'δοκίμασε' in clean.lower() or clean.lower() in ['υλικά', 'υλικα', 'materials', 'ingredients']:
        continue
    m = re.match(r'^((?:\d+(?:[./]\d+)?|\d+\s*-\s*\d+)?\s*(?:μεγάλες|μικρές|φέτες|γρ|κιλά|κ\.σ\.|κ\.γ\.|κουταλιές|τεμ|τεμάχια)?)\s*(.*)$', clean, re.IGNORECASE)
    if m:
        raw_qty = m.group(1).strip()
        raw_name = m.group(2).strip()
        if not raw_name and raw_qty:
            raw_name = raw_qty
            raw_qty = '1'
        
        en_name = analyzer._translate_if_greek(raw_name)
        
        std_qty = re.sub(r'\bγρ\.?\b', 'g', raw_qty)
        std_qty = re.sub(r'\bκιλά\b', 'kg', std_qty)
        std_qty = re.sub(r'\bκ\.σ\.?\b', 'tbsp', std_qty)
        std_qty = re.sub(r'\bκ\.γ\.?\b', 'tsp', std_qty)
        std_qty = re.sub(r'\bκουταλιές?\b', 'tbsp', std_qty)
        std_qty = re.sub(r'\b(?:μεγάλες|μικρές|φέτες)\b', '', std_qty).strip()
        
        if RecipeValidator.is_valid_food_name(en_name):
            ings.append({'name': en_name, 'quantity': std_qty or '1'})

print("PARSED GREEK INGREDIENTS:")
for i in ings:
    print(f"  * {i['name']}: {i['quantity']}")

rec = RecipeValidator.reconcile_recipe_payload({'is_recipe': True, 'title': 'Potato Omelet', 'ingredients': ings, 'instructions': []})
calc = calculate_recipe_macros_from_ingredients(rec['ingredients'])
print(f"\nCALCULATED MACROS: {calc.get('protein')}g Protein | {calc.get('carbs')}g Carbs | {calc.get('fats')}g Fats | {calc.get('calories')} kcal")
for i in calc['ingredients']:
    print(f"  -> {i['name']}: {i['quantity']} ({i.get('protein')}g P, {i.get('calories')} kcal, {i.get('grams')}g)")
