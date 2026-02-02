import sys
import json
import os
import re
import time

def main():
    try:
        # 1. Parse Input
        if len(sys.argv) < 2:
            print(json.dumps({"error": "No input provided"}))
            return
        
        try:
            input_data = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON input"}))
            return

        query = input_data.get("query", "")
        # Default to System Root if not provided
        root_path = input_data.get("path", os.path.abspath(os.sep))
        
        # Validate inputs
        if not query:
             print(json.dumps({"error": "No query provided"}))
             return
             
        if not os.path.exists(root_path):
            print(json.dumps({"error": f"Path not found: {root_path}"}))
            return

        # Compile Regex
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            print(json.dumps({"error": f"Invalid Regex: {e}"}))
            return

        matches = []
        scanned_count = 0
        start_time = time.time()
        
        # Directories to skip to prevent hanging/permission errors
        SKIP_DIRS = {
            '$RECYCLE.BIN', 'System Volume Information', 'Windows', 'ProgramData', 
            '.git', '__pycache__', 'node_modules', 'venv', 'env'
        }

        # 2. Walk
        for root, dirs, files in os.walk(root_path, topdown=True):
            # Modify dirs in-place to skip
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
            
            for file in files:
                scanned_count += 1
                
                # Progress every 1000 files
                if scanned_count % 1000 == 0:
                    print(json.dumps({
                        "status": "progress", 
                        "scanned": scanned_count, 
                        "found": len(matches),
                        "current_dir": root
                    }), flush=True)

                if pattern.search(file):
                    full_path = os.path.join(root, file)
                    try:
                        size = os.path.getsize(full_path)
                    except:
                        size = 0
                        
                    matches.append({
                        "name": file,
                        "path": full_path.replace("\\", "/"),
                        "size": size
                    })
                    
            # Safety break for massive searches? 
            # User asked for "whole computer", so maybe we don't break early, 
            # but we should definitely cap results return.
            if len(matches) >= 100:
                print(json.dumps({
                    "status": "progress", 
                    "message": "Match limit reached (100). Stopping."
                }), flush=True)
                break
        
        # 3. Final Output
        # Ensure we print a single JSON object at the end that assumes success
        # The executor might only parse the last line, or we need to separate structure.
        # We'll rely on the standard "last line is result" or "collect JSONs".
        
        result = {
            "matches": matches,
            "count": len(matches),
            "scanned": scanned_count,
            "duration_seconds": round(time.time() - start_time, 2)
        }
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
