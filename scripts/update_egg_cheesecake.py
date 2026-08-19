import sqlite3

conn = sqlite3.connect("data/nutrition.db")
cur = conn.cursor()

cur.execute("""
    INSERT OR REPLACE INTO foods (fdc_id, description, data_type, calories, protein_g, fat_g, carbs_g, fiber_g)
    VALUES (900036, 'Egg, whole, fresh, raw, beaten egg', 'foundation_food', 143.0, 12.6, 9.5, 0.7, 0.0)
""")
cur.execute("DELETE FROM foods_fts WHERE fdc_id = 900036")
cur.execute("INSERT INTO foods_fts (fdc_id, description) VALUES (900036, 'Egg, whole, fresh, raw, beaten egg')")

cur.execute("""
    INSERT OR REPLACE INTO foods (fdc_id, description, data_type, calories, protein_g, fat_g, carbs_g, fiber_g)
    VALUES (900037, 'Cheesecake, bark, pieces', 'foundation_food', 321.0, 5.5, 22.5, 25.5, 0.4)
""")
cur.execute("DELETE FROM foods_fts WHERE fdc_id = 900037")
cur.execute("INSERT INTO foods_fts (fdc_id, description) VALUES (900037, 'Cheesecake, bark, pieces')")

conn.commit()
conn.close()
print("Updated beaten egg & cheesecake bark!")
