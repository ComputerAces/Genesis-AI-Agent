import sys
import json
import os

def main():
    # Read args from stdin
    try:
        input_data = sys.stdin.read()
        if not input_data:
            args = {}
        else:
            args = json.loads(input_data)
        
        name = args.get("name", "World")
        
        # Access GENESIS_HOME to prove isolation
        genesis_home = os.environ.get("GENESIS_HOME", "UNKNOWN")
        
        response = {
            "message": f"Hello, {name}!",
            "genesis_home": genesis_home
        }
        
        # Write response to stdout
        print(json.dumps(response))
        
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
