import os
import json
import urllib.request
import urllib.error
import config  # imports and runs .env loading

groq_api_key = os.environ.get("GROQ_API_KEY")
print(f"GROQ_API_KEY found in env: {bool(groq_api_key)}")

prompt = "Analyze the text: 'Today we are making chicken and rice. High protein.' and output JSON {\"is_recipe\": true}"

payload = json.dumps({
    "model": "llama-3.3-70b-versatile",
    "messages": [
        {"role": "user", "content": prompt}
    ],
    "temperature": 0.1,
    "response_format": {"type": "json_object"}
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.groq.com/openai/v1/chat/completions",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {groq_api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    },
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        response_data = json.loads(resp.read().decode("utf-8"))
    choices = response_data.get("choices", [])
    if choices:
        print("Success! Groq response:")
        print(choices[0].get("message", {}).get("content", "").strip())
    else:
        print("Empty choices list in response:", response_data)
except urllib.error.HTTPError as e:
    try:
        err_body = e.read().decode("utf-8")
    except Exception:
        err_body = "(could not read body)"
    print(f"HTTPError: {e.code} {e.reason}\nBody: {err_body}")
except Exception as e:
    print("Error calling Groq:", e)
