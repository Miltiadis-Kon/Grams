import json
import os

files = [
    "database/recipes_db.json",
    "database/gemini-code-1781532108130.json",
    "database/gemini-code-1781532128064.json"
]

merged_data = {}

def load_and_repair_json(fpath):
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read().strip()
    
    # Strip any trailing garbage first
    if "I seem to be encountering an error" in content:
        content = content.split("I seem to be encountering an error")[0].strip()
        
    try:
        # Try loading directly
        return json.loads(content)
    except json.JSONDecodeError:
        print(f"File {fpath} is malformed. Attempting repair...")
        
    # Repair strategy: find the last occurrence of '    },' at the start of a line
    # which demarcates a successfully closed recipe dictionary block in pretty JSON.
    idx = content.rfind("\n    },")
    if idx != -1:
        repaired = content[:idx + 6]  # include the '    },'
        # Strip the trailing comma if it's the new end of the dictionary
        repaired = repaired.rstrip().rstrip(",")
        repaired += "\n}"  # close the main dictionary
        try:
            data = json.loads(repaired)
            print(f"Successfully repaired {fpath}! Recovered {len(data)} recipes.")
            return data
        except json.JSONDecodeError as repair_err:
            print(f"Repair attempt failed for {fpath}: {repair_err}")
            
    # Alternative repair strategy: just find the last closed brace '}' that is matched
    # But usually the '\n    },' is very reliable for these specific dumps.
    return None

for fpath in files:
    if not os.path.exists(fpath):
        print(f"File {fpath} does not exist. Skipping.")
        continue
    
    data = load_and_repair_json(fpath)
    if data:
        for recipe_id, recipe_val in data.items():
            if recipe_id in merged_data:
                existing = merged_data[recipe_id]
                existing_ings = len(existing.get("ingredients", []))
                new_ings = len(recipe_val.get("ingredients", []))
                # Keep the one with more ingredients
                if new_ings > existing_ings:
                    merged_data[recipe_id] = recipe_val
            else:
                merged_data[recipe_id] = recipe_val

print(f"Total merged unique recipes: {len(merged_data)}")

# Write to database/recipes_db.json
try:
    with open("database/recipes_db.json", "w", encoding="utf-8") as f:
        json.dump(merged_data, f, indent=4, ensure_ascii=False)
    print("Successfully wrote consolidated database to database/recipes_db.json")
except Exception as write_err:
    print(f"Error writing merged database: {write_err}")
