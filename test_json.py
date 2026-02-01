from modules.utils import extract_json
import json

test_str = """{
  "message": "Searching for system.ini in the current directory.",
  "reason": "Checking file",
  "actions": [{"name": "search_files", "parameters": [{"name": "path", "value": "system.ini"}] }]
}<|im_end|>"""

print("Input:", test_str)
result = extract_json(test_str)
print("Result:", json.dumps(result, indent=2))

if result and "actions" in result:
    print("Actions found:", len(result["actions"]))
else:
    print("No actions found.")
