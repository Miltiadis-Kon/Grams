import sqlite3
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect("data/recipes.db")
cur = conn.cursor()

print("=" * 125)
print(f"  RECIPES TABLE ({cur.execute('SELECT COUNT(*) FROM recipes').fetchone()[0]} entries)")
print("=" * 125)
for r in cur.execute("SELECT recipe_id, name, macros, last_processed, length(transcript), tags FROM recipes").fetchall():
    m = json.loads(r[2]) if r[2] else {}
    cal = m.get("calories", 0)
    p = m.get("protein", 0)
    c = m.get("carbs", 0)
    f = m.get("fats", 0)
    ts_len = r[4] if r[4] is not None else 0
    proc = r[3][:19] if r[3] else "N/A"
    tags = r[5] or "[]"
    print(f"ID: {r[0]} | {cal:>4} kcal | P: {p:>5.1f}g | C: {c:>5.1f}g | F: {f:>5.1f}g | Transcript: {ts_len:>4} chars | {proc} | {r[1][:30]}")

print("\n" + "=" * 125)
print(f"  NOT_ADDED_RECIPES TABLE ({cur.execute('SELECT COUNT(*) FROM not_added_recipes').fetchone()[0]} entries)")
print("=" * 125)
for r in cur.execute("SELECT recipe_id, name, last_processed, length(transcript) FROM not_added_recipes").fetchall():
    proc = r[2][:19] if r[2] else "N/A"
    ts_len = r[3] if r[3] is not None else 0
    print(f"ID: {r[0]} | Transcript: {ts_len:>4} chars | {proc} | {r[1][:50]}")
print("=" * 125)
