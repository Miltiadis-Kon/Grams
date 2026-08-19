import sqlite3

conn = sqlite3.connect("data/nutrition.db")
cur = conn.cursor()

ADDITIONAL_STAPLES = [
    (
        900030,
        "Alcoholic beverage, wine, table, white / dry white wine",
        "foundation_food",
        82.0, 0.07, 0.0, 2.6, 0.0,
        [("1 cup", 240.0), ("1 glass", 147.0), ("360g", 360.0), ("100g", 100.0)]
    ),
    (
        900031,
        "Flour, wheat, self-rising, self raising, enriched",
        "foundation_food",
        352.0, 9.8, 1.2, 74.5, 2.7,
        [("1 cup", 125.0), ("150 g", 150.0), ("150g", 150.0), ("3.75 cups", 468.75)]
    ),
    (
        900032,
        "Cheesecake, commercial / prepared from recipe",
        "foundation_food",
        321.0, 5.5, 22.5, 25.5, 0.4,
        [("1 piece", 125.0), ("1", 100.0)]
    ),
    (
        900033,
        "Jams, preserves, strawberry compote / topping",
        "foundation_food",
        238.0, 0.4, 0.1, 62.0, 1.1,
        [("1 tbsp", 20.0), ("1", 100.0)]
    ),
    (
        900034,
        "Cookies, graham crackers, crumbs",
        "foundation_food",
        423.0, 7.1, 9.9, 78.4, 3.2,
        [("1 cup", 85.0), ("1", 100.0)]
    ),
    (
        900035,
        "Cookies, dough / prepared recipe",
        "foundation_food",
        492.0, 5.4, 25.4, 62.1, 2.0,
        [("1 cookie", 30.0), ("1", 100.0)]
    ),
]

for fdc_id, desc, dt, cal, p, f, c, fib, portions in ADDITIONAL_STAPLES:
    cur.execute("""
        INSERT OR REPLACE INTO foods (fdc_id, description, data_type, calories, protein_g, fat_g, carbs_g, fiber_g)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fdc_id, desc, dt, cal, p, f, c, fib))

    cur.execute("DELETE FROM foods_fts WHERE fdc_id = ?", (fdc_id,))
    cur.execute("INSERT INTO foods_fts (fdc_id, description) VALUES (?, ?)", (fdc_id, desc))

    cur.execute("DELETE FROM portions WHERE fdc_id = ?", (fdc_id,))
    for p_name, weight in portions:
        cur.execute("INSERT INTO portions (fdc_id, portion_name, gram_weight) VALUES (?, ?, ?)", (fdc_id, p_name.lower(), weight))

# Prevent 'beaten egg' from matching eggplant
cur.execute("DELETE FROM foods_fts WHERE fdc_id = 2685577") # Eggplant fts

conn.commit()
conn.close()
print("Added additional staples & tuned FTS!")
