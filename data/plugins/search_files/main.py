import sys
import json
import os
import glob

def main():
    try:
        # 1. Parse Input
        if len(sys.argv) < 2:
            print(json.dumps({"error": "No input provided"}))
            return
        
        input_data = json.loads(sys.argv[1])
        query = input_data.get("query", "")
        if not query:
            query = input_data.get("path", "")
        
        if not query:
             print(json.dumps({"matches": []}))
             return

        # 2. Search Logic
        # We search from GENESIS_HOME down
        try:
            base_dir = os.environ.get("GENESIS_HOME")
            if not base_dir:
                # Fallback to current working directory or relative
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        except:
             base_dir = os.getcwd()
             
        # Normalize slashes
        base_dir = base_dir.replace("\\", "/")
        
        matches = []
        # Recursive walk to find partial matches
        # Using os.walk for robust partial matching
        for root, dirs, files in os.walk(base_dir):
            # Skip hidden/virtual envs if possible?
            if "venv" in root or "__pycache__" in root or ".git" in root:
                continue
                
            for file in files:
                if query.lower() in file.lower():
                    full_path = os.path.join(root, file)
                    matches.append(full_path)
                    
            if len(matches) > 50: # Limit results
                break
        
        # 3. Output
        print(json.dumps({
            "matches": matches,
            "count": len(matches),
            "base_dir": base_dir
        }))
        
    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
