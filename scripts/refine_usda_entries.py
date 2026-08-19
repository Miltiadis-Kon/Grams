import sqlite3

conn = sqlite3.connect("data/nutrition.db")
cur = conn.cursor()

# 1. Ensure Egg whites points to full nutrient profile (52 kcal/100g, 10.9g protein)
cur.execute("DELETE FROM foods_fts WHERE fdc_id = 323608 OR fdc_id = 323614 OR fdc_id = 323620 OR fdc_id = 323625")
cur.execute("UPDATE foods SET description = 'Egg whites, analytical fraction' WHERE fdc_id IN (323608, 323614, 323620, 323625)")
cur.execute("""
    INSERT OR REPLACE INTO foods (fdc_id, description, data_type, calories, protein_g, fat_g, carbs_g, fiber_g)
    VALUES (900018, 'Egg whites, raw, fresh', 'foundation_food', 52.0, 10.9, 0.2, 0.7, 0.0)
""")
cur.execute("DELETE FROM foods_fts WHERE fdc_id = 900018")
cur.execute("INSERT INTO foods_fts (fdc_id, description) VALUES (900018, 'Egg whites, raw, fresh')")

# 2. Ensure Low fat cottage cheese points to fdc_id 900021
cur.execute("""
    INSERT OR REPLACE INTO foods (fdc_id, description, data_type, calories, protein_g, fat_g, carbs_g, fiber_g)
    VALUES (900021, 'Low Fat Cottage cheese, 1% / 2% milkfat', 'foundation_food', 72.0, 12.4, 1.0, 2.7, 0.0)
""")
cur.execute("DELETE FROM foods_fts WHERE fdc_id = 900021")
cur.execute("INSERT INTO foods_fts (fdc_id, description) VALUES (900021, 'Low Fat Cottage cheese, 1% / 2% milkfat')")

conn.commit()
conn.close()
print("Refined nutrition.db entries successfully!")
