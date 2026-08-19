import sqlite3

conn = sqlite3.connect("data/nutrition.db")
cur = conn.cursor()

GREEK_SPECIALTIES = [
    (
        900038,
        "Cheese, kefalotyri, hard yellow cheese",
        "foundation_food",
        380.0, 26.0, 30.0, 1.0, 0.0,
        [("150 g", 150.0), ("100 g", 100.0), ("1 slice", 30.0)]
    ),
    (
        900039,
        "Cheese, anthotyro, fresh whey cheese",
        "foundation_food",
        175.0, 11.0, 13.0, 3.0, 0.0,
        [("100 g", 100.0), ("1 cup", 200.0)]
    ),
    (
        900040,
        "Spearmint, fresh / dried herbs",
        "foundation_food",
        44.0, 3.3, 0.9, 8.4, 6.8,
        [("1 bunch", 15.0), ("1", 5.0), ("1 tsp", 1.5), ("1 tbsp", 4.0)]
    ),
]

for fdc_id, desc, dt, cal, p, f, c, fib, portions in GREEK_SPECIALTIES:
    cur.execute("""
        INSERT OR REPLACE INTO foods (fdc_id, description, data_type, calories, protein_g, fat_g, carbs_g, fiber_g)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fdc_id, desc, dt, cal, p, f, c, fib))

    cur.execute("DELETE FROM foods_fts WHERE fdc_id = ?", (fdc_id,))
    cur.execute("INSERT INTO foods_fts (fdc_id, description) VALUES (?, ?)", (fdc_id, desc))

    cur.execute("DELETE FROM portions WHERE fdc_id = ?", (fdc_id,))
    for p_name, weight in portions:
        cur.execute("INSERT INTO portions (fdc_id, portion_name, gram_weight) VALUES (?, ?, ?)", (fdc_id, p_name.lower(), weight))

conn.commit()
conn.close()
print("Added Greek specialty ingredients!")
