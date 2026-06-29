import os
import csv
import json
import re
from dotenv import load_dotenv
from supabase import create_client

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    env_path = os.path.join(root_dir, ".env")
    load_dotenv(env_path)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_KEY")
        return

    client = create_client(url, key)
    
    print("Clearing the foods table...")
    while True:
        res = client.table('foods').select('id').limit(1000).execute()
        if not res.data:
            break
        ids = [r['id'] for r in res.data]
        client.table('foods').delete().in_('id', ids).execute()
        print(f"Deleted {len(ids)} rows...")
        
    print("Foods table cleared.")
    
    csv.field_size_limit(10**7)
    tsv_path = os.path.join(root_dir, 'data', 'opennutrition_foods.tsv')
    
    batch = []
    batch_size = 500
    total_imported = 0
    
    print("Reading TSV and importing 'everyday' items...")
    with open(tsv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            if row.get('type', '').lower() != 'everyday':
                continue
                
            name = row.get('name', '')
            # Strip " by [Brand]" case-insensitively
            name = re.sub(r'(?i)\s+by\s+.*$', '', name).strip()
            
            nutrition_str = row.get('nutrition_100g', '{}')
            try:
                nut_data = json.loads(nutrition_str)
            except:
                nut_data = {}
            
            record = {
                "id": row.get('id'),
                "name": name,
                "protein_g": float(nut_data.get('protein', 0.0) or 0.0),
                "carbs_g": float(nut_data.get('carbohydrates', 0.0) or 0.0),
                "fat_g": float(nut_data.get('total_fat', 0.0) or 0.0),
                "energy_kcal": float(nut_data.get('calories', 0.0) or 0.0),
                "serving": row.get('serving')  # Upload serving JSON exactly as-is
            }
            batch.append(record)
            
            if len(batch) >= batch_size:
                client.table('foods').upsert(batch).execute()
                total_imported += len(batch)
                print(f"Inserted {total_imported} everyday foods...")
                batch = []
                
        if batch:
            client.table('foods').upsert(batch).execute()
            total_imported += len(batch)
            print(f"Inserted {total_imported} everyday foods...")

    print("Import complete.")

if __name__ == "__main__":
    main()
