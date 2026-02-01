# Adding Actions (Plugins)

Genesis AI Action System allows you to extend the capabilities of the bot.

## 1. Creating a Plugin

You can create actions directly from the UI (`/actions`) or manually in the `data/plugins/` folder.

### File Structure

A plugin folder (e.g., `my_action`) requires:

1. `manifest.json`: Configuration.
2. `main.py`: The python script to execute.

### Manifest Format

```json
{
  "id": "my_action",
  "name": "My Custom Action",
  "version": "1.0.0",
  "description": "Does something cool.",
  "actions": [
    {
      "name": "cool_action",
      "script": "main.py",
      "type": "python",
      "description": "Executes the cool logic.",
      "parameters": {
        "target": "String: what to target"
      }
    }
  ]
}
```

### Script Format (`main.py`)

The script receives input as a JSON string in `sys.argv[1]`.
It MUST print a JSON object to `stdout`.

```python
import sys
import json

def main():
    try:
        # Read args
        args = json.loads(sys.argv[1])
        target = args.get("target", "World")
        
        # Do work...
        result = f"Hello, {target}!"
        
        # Output JSON
        print(json.dumps({
            "status": "success",
            "message": result
        }))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
```

## 2. Importing/Exporting

- **Export**: Go to the Actions page and click the "Export" button to get a `.gplug` file.
- **Install**: Upload the `.gplug` file on the Actions page.
