import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.postgres_db import RecipeDatabase
from database.models import Recipe, MacroNutrients
from helpers.tagger import AutoTagger
from recipe_processor.llm_parser import parse_recipe_with_llm
from recipe_processor.validator import RecipeValidator
from server.services import calculate_recipe_macros_from_ingredients

db_recipes = RecipeDatabase('recipes')
db_not = RecipeDatabase('not_added_recipes')
tagger = AutoTagger()

item = db_not.get('7251946119909952795') or db_not.get('tt_7251946119909952795')
if item:
    print("Found in not_added_recipes. Reprocessing...")
    desc = item.get('description', '')
    parsed = parse_recipe_with_llm(desc)
    print("PARSED:", parsed)
    if parsed.get('is_recipe') and parsed.get('ingredients'):
        reconciled = RecipeValidator.reconcile_recipe_payload(parsed)
        calc = calculate_recipe_macros_from_ingredients(reconciled['ingredients'])
        
        recipe_obj = Recipe(
            name=item.get('name', 'Potato Omelet'),
            url=item.get('url', 'https://www.tiktok.com/@petros_maounatzis/video/7251946119909952795'),
            description=desc,
            macros=MacroNutrients(
                protein=float(calc.get('protein', 0)),
                carbs=float(calc.get('carbs', 0)),
                fats=float(calc.get('fats', 0)),
                calories=int(calc.get('calories', 0))
            ),
            ingredients=calc.get('ingredients', []),
            instructions=reconciled.get('instructions', []),
            tags=[],
            added_on=item.get('added_on', '')
        )
        recipe_obj.tags = tagger.tag(recipe_obj)
        
        # Delete from not_added_recipes and insert into recipes
        db_not.delete('7251946119909952795')
        db_not.delete('tt_7251946119909952795')
        db_recipes.insert('tt_7251946119909952795', recipe_obj)
        print("SUCCESS! Inserted to recipes:")
        print("  Macros:", recipe_obj.macros)
        for ing in recipe_obj.ingredients:
            print(f"  * {ing.get('name')}: {ing.get('quantity')} ({ing.get('protein')}g P, {ing.get('calories')} kcal)")
