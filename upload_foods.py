import os
import sys
import sqlite3
import time
from supabase import create_client, Client

# Load environment variables from .env file if it exists
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_KEY environment variables are required in your .env or environment!")
    sys.exit(1)

db_path = os.path.join(BASE_DIR, "data", "opennutrition.db")
if not os.path.exists(db_path):
    print(f"Error: Local SQLite database not found at {db_path}!")
    sys.exit(1)

print(f"Initializing Supabase client targeting {supabase_url}...")
client: Client = create_client(supabase_url, supabase_key)

print(f"Connecting to local SQLite database at {db_path}...")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Get total row count
cur.execute("SELECT COUNT(*) FROM foods")
total_rows = cur.fetchone()[0]
print(f"Found {total_rows} total rows to migrate to Supabase.")

cur.execute("SELECT id, name, protein_g, carbs_g, fat_g, energy_kcal, serving FROM foods")

BATCH_SIZE = 1000
batch = []
uploaded = 0
errors = 0

start_time = time.time()

# Verify connection to foods table first by querying count
try:
    client.table("foods").select("id", count="exact").limit(1).execute()
    print("Successfully connected to Supabase 'foods' table.")
except Exception as e:
    print(f"Error: Could not access 'foods' table in Supabase. Make sure you run database/schema.sql first!\nDetails: {e}")
    conn.close()
    sys.exit(1)

while True:
    rows = cur.fetchmany(BATCH_SIZE)
    if not rows:
        break
        
    batch_data = []
    for row in rows:
        batch_data.append({
            "id": row[0],
            "name": row[1],
            "protein_g": float(row[2] or 0.0),
            "carbs_g": float(row[3] or 0.0),
            "fat_g": float(row[4] or 0.0),
            "energy_kcal": float(row[5] or 0.0),
            "serving": row[6]
        })
        
    retry_attempts = 3
    success = False
    for attempt in range(1, retry_attempts + 1):
        try:
            client.table("foods").upsert(batch_data).execute()
            uploaded += len(batch_data)
            success = True
            break
        except Exception as e:
            print(f"Attempt {attempt}/{retry_attempts} failed to upload batch: {e}")
            if attempt < retry_attempts:
                time.sleep(2)
                
    if not success:
        print(f"Skipping batch starting with ID '{batch_data[0]['id']}' after {retry_attempts} failed attempts.")
        errors += len(batch_data)
        
    elapsed = time.time() - start_time
    rate = uploaded / elapsed if elapsed > 0 else 0
    percent = (uploaded + errors) / total_rows * 100
    print(f"Progress: {uploaded + errors}/{total_rows} ({percent:.1f}%) | Uploaded: {uploaded} | Rate: {rate:.1f} rows/sec | Elapsed: {elapsed:.1f}s")

conn.close()
print(f"\nMigration complete. Total uploaded: {uploaded} | Errors: {errors} | Time taken: {time.time() - start_time:.1f} seconds")
