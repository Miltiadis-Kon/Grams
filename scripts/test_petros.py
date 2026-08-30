import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recipe_processor.llm_parser import parse_recipe_with_llm
from database.postgres_db import RecipeDatabase
from server.services import calculate_recipe_macros_from_ingredients

db = RecipeDatabase(table_name='recipes')
r = db.get('7251946119909952795') or db.get('tt_7251946119909952795')
if r:
    res = parse_recipe_with_llm(r.get('description'))
    print("IS_RECIPE:", res.get('is_recipe'))
    calc = calculate_recipe_macros_from_ingredients(res.get('ingredients', []))
    print(f"MACROS: {calc.get('protein')}g P | {calc.get('carbs')}g C | {calc.get('fats')}g F | {calc.get('calories')} kcal")
    for i in calc.get('ingredients', []):
        print(f"  * {i.get('name')}: {i.get('quantity')} ({i.get('protein')}g P, {i.get('calories')} kcal, {i.get('grams')}g)")
