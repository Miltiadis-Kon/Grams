import sqlite3
import os

db_path = os.path.join("data", "nutrition.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Standard USDA reference foods for common recipe & baking staples
PANTRY_FOODS = [
    # (fdc_id, description, data_type, calories, protein_g, fat_g, carbs_g, fiber_g, [(portion_name, gram_weight)])
    (
        900001,
        "Vanilla extract",
        "foundation_food",
        288.0, 0.1, 0.1, 12.7, 0.0,
        [("1 tsp", 4.2), ("1 tbsp", 13.0), ("1/2 tsp", 2.1), ("2 tsp", 8.4), ("3 tsp", 12.6)]
    ),
    (
        900002,
        "Syrup, maple, sugar free",
        "foundation_food",
        20.0, 0.0, 0.0, 5.0, 0.0,
        [("1 tbsp", 15.0), ("1 cup", 240.0), ("12 tbsp", 180.0), ("2 tbsp", 30.0)]
    ),
    (
        900003,
        "Syrup, maple, pure",
        "foundation_food",
        260.0, 0.04, 0.06, 67.0, 0.0,
        [("1 tbsp", 20.0), ("1 cup", 322.0), ("12 tbsp", 240.0)]
    ),
    (
        900004,
        "Chocolate chips, stevia sweetened, dark",
        "foundation_food",
        350.0, 6.0, 26.0, 48.0, 22.0,
        [("1 tbsp", 15.0), ("1 cup", 170.0), ("180g", 180.0)]
    ),
    (
        900005,
        "Chocolate chips, semi-sweet / dark",
        "foundation_food",
        479.0, 4.2, 29.7, 63.4, 5.9,
        [("1 tbsp", 15.0), ("1 cup", 170.0), ("10g", 10.0)]
    ),
    (
        900006,
        "Flour, wheat, self-rising, enriched",
        "foundation_food",
        352.0, 9.8, 1.2, 74.5, 2.7,
        [("1 cup", 125.0), ("3.75 cup", 468.75), ("3.75 cups", 468.75), ("1 tbsp", 8.0)]
    ),
    (
        900007,
        "Flour, wheat, all-purpose, enriched, unbleached",
        "foundation_food",
        364.0, 10.3, 1.0, 76.3, 2.7,
        [("1 cup", 125.0), ("1/4 cup", 31.25), ("1 tbsp", 8.0), ("10g", 10.0), ("35g", 35.0)]
    ),
    (
        900008,
        "Flour, oat, whole grain",
        "foundation_food",
        404.0, 14.7, 9.1, 65.7, 6.5,
        [("1 cup", 120.0), ("1 tsp", 2.5), ("2 tsp", 5.0), ("1 tbsp", 7.5)]
    ),
    (
        900009,
        "Protein powder, casein / whey blend",
        "foundation_food",
        370.0, 78.0, 3.5, 7.0, 1.0,
        [("1 scoop", 30.0), ("1/3 scoop", 10.0), ("2/3 scoop", 20.0), ("10g", 10.0), ("20g", 20.0)]
    ),
    (
        900010,
        "Protein powder, casein",
        "foundation_food",
        360.0, 80.0, 1.5, 4.0, 0.5,
        [("1 scoop", 30.0), ("1/3 scoop", 10.0), ("2/3 scoop", 20.0), ("10g", 10.0)]
    ),
    (
        900011,
        "Protein powder, whey isolate",
        "foundation_food",
        380.0, 82.0, 3.0, 5.0, 0.5,
        [("1 scoop", 30.0), ("1/3 scoop", 10.0), ("2/3 scoop", 20.0), ("20g", 20.0)]
    ),
    (
        900012,
        "Sweetener, sugar substitute, granulated (erythritol/stevia/allulose)",
        "foundation_food",
        0.0, 0.0, 0.0, 0.0, 0.0,
        [("1 tbsp", 12.0), ("2 tbsp", 24.0), ("1 tsp", 4.0), ("1 cup", 190.0), ("6-8 tbsp", 84.0)]
    ),
    (
        900013,
        "Leavening agents, baking soda (sodium bicarbonate)",
        "foundation_food",
        0.0, 0.0, 0.0, 0.0, 0.0,
        [("1 tsp", 4.6), ("1/4 tsp", 1.2), ("1/3 tsp", 1.5), ("1g", 1.0), ("2g", 2.0)]
    ),
    (
        900014,
        "Leavening agents, baking powder, double-acting",
        "foundation_food",
        53.0, 0.0, 0.0, 27.7, 0.0,
        [("1 tsp", 4.6), ("1/2 tsp", 2.3), ("1g", 1.0), ("2g", 2.0)]
    ),
    (
        900015,
        "Salt, table, iodized",
        "foundation_food",
        0.0, 0.0, 0.0, 0.0, 0.0,
        [("1 pinch", 0.5), ("1 tsp", 6.0), ("1", 0.5), ("20g", 20.0)]
    ),
    (
        900016,
        "Pumpkin, canned, puree, without salt",
        "foundation_food",
        34.0, 1.1, 0.3, 8.1, 2.9,
        [("1 cup", 245.0), ("1/2 cup", 122.5), ("120g", 120.0), ("1 tbsp", 15.0)]
    ),
    (
        900017,
        "Cocoa, dry powder, unsweetened, dark / black",
        "foundation_food",
        228.0, 19.6, 13.7, 57.9, 33.2,
        [("1 cup", 86.0), ("1/4 cup", 21.5), ("25g", 25.0), ("1 tbsp", 5.4)]
    ),
    (
        900018,
        "Egg, white, raw, fresh, liquid",
        "foundation_food",
        52.0, 10.9, 0.2, 0.7, 0.0,
        [("1 large", 33.0), ("1 cup", 243.0), ("1/2 cup", 121.5), ("1 tbsp", 15.0), ("25ml", 25.0), ("120ml", 120.0)]
    ),
    (
        900019,
        "Eggs, Grade A, Large, egg whole",
        "foundation_food",
        143.0, 12.6, 9.5, 0.7, 0.0,
        [("1 large", 50.0), ("1 whole egg", 50.0), ("1 egg", 50.0), ("12", 600.0), ("2", 100.0), ("4", 200.0)]
    ),
    (
        900020,
        "Yogurt, Greek, plain / vanilla, nonfat",
        "foundation_food",
        59.0, 10.2, 0.4, 3.6, 0.0,
        [("1 cup", 245.0), ("1/3 cup", 81.6), ("3 tbsp", 45.0), ("40g", 40.0), ("80g", 80.0)]
    ),
    (
        900021,
        "Cottage cheese, lowfat, 1% / 2% milkfat",
        "foundation_food",
        72.0, 12.4, 1.0, 2.7, 0.0,
        [("1 cup", 226.0), ("6 cups", 1356.0), ("6 cup", 1356.0), ("1/2 cup", 113.0)]
    ),
    (
        900022,
        "Almond milk, unsweetened, plain, shelf stable",
        "foundation_food",
        15.0, 0.55, 1.22, 0.34, 0.2,
        [("1 cup", 240.0), ("1/2 cup", 120.0), ("120ml", 120.0), ("1 tbsp", 15.0)]
    ),
    (
        900023,
        "Spices, cinnamon, ground",
        "foundation_food",
        247.0, 4.0, 1.2, 80.6, 53.1,
        [("1 tsp", 2.6), ("1 tbsp", 7.8)]
    ),
    (
        900024,
        "Butter, unsalted",
        "foundation_food",
        717.0, 0.9, 81.1, 0.1, 0.0,
        [("1 tbsp", 14.2), ("1 stick", 113.0), ("1 cup", 227.0), ("10g", 10.0), ("40g", 40.0), ("50g", 50.0)]
    ),
    (
        900025,
        "Water, tap / lukewarm drinking water",
        "foundation_food",
        0.0, 0.0, 0.0, 0.0, 0.0,
        [("1 cup", 237.0), ("1 ml", 1.0), ("220 ml", 220.0)]
    ),
    (
        900026,
        "Yeast, dry active / instant yeast",
        "foundation_food",
        325.0, 40.4, 7.6, 41.2, 27.0,
        [("1 packet", 7.0), ("1 tsp", 3.0), ("3g", 3.0)]
    ),
]

for fdc_id, desc, dt, cal, p, f, c, fib, portions in PANTRY_FOODS:
    cur.execute("""
        INSERT OR REPLACE INTO foods (fdc_id, description, data_type, calories, protein_g, fat_g, carbs_g, fiber_g)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fdc_id, desc, dt, cal, p, f, c, fib))

    # Update FTS
    cur.execute("DELETE FROM foods_fts WHERE fdc_id = ?", (fdc_id,))
    cur.execute("INSERT INTO foods_fts (fdc_id, description) VALUES (?, ?)", (fdc_id, desc))

    # Insert portions
    cur.execute("DELETE FROM portions WHERE fdc_id = ?", (fdc_id,))
    for p_name, weight in portions:
        cur.execute("INSERT INTO portions (fdc_id, portion_name, gram_weight) VALUES (?, ?, ?)", (fdc_id, p_name.lower(), weight))

conn.commit()
conn.close()
print("Successfully seeded USDA pantry staples into nutrition.db!")
