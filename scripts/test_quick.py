import io
import sys
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.nutrition import NutritionAnalyzer
a = NutritionAnalyzer()

queries = [
    'self-raising flour',
    'dry white wine',
    'beaten egg',
    'cheesecake bark',
    'graham cracker crumbs',
    'cookie dough',
    'strawberry compote'
]

for q in queries:
    cleaned = a._clean_ingredient_name(q)
    m = a.lookup_food(cleaned)
    name = m.food_name if m else "NO MATCH"
    cal = m.calories if m else 0
    print(f"{q:<25} -> {name} ({cal} kcal/100g)")
