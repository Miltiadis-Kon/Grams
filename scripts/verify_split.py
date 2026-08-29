import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.nutrition import _get_pg_connection
import json

conn = _get_pg_connection()
with conn.cursor() as cur:
    for vid_id in ['yt_ZgXSr4NPZo8_1', 'yt_ZgXSr4NPZo8_2', 'yt_ZgXSr4NPZo8_3', 'yt_CpU1Tqg2884_1', 'yt_2-tnmkCCdL4_1', 'yt_L-rDHDD-9I0_1', 'yt_ROoLkpGxQ8E']:
        cur.execute('SELECT recipe_id, name, macros, ingredients FROM recipes WHERE recipe_id = %s', (vid_id,))
        row = cur.fetchone()
        if row:
            print("========================================")
            print(f"Recipe [{row[0]}]: {row[1]}")
            macs = json.loads(row[2]) if isinstance(row[2], str) else row[2]
            print(f"Total Macros: {macs.get('protein')}g Protein | {macs.get('carbs')}g Carbs | {macs.get('fats')}g Fats | {macs.get('calories')} kcal")
            ings = json.loads(row[3]) if isinstance(row[3], str) else row[3]
            print("Ingredients:")
            for ing in ings:
                print(f"  * {ing.get('name')}: {ing.get('quantity')} ({ing.get('protein', 0)}g P, {ing.get('calories', 0)} kcal, {ing.get('grams', 0)}g)")
            print()
conn.close()
