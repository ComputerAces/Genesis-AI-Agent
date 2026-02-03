import sys
import json
import os
import re
import time
import platform

def main():
    try:
        input_data = {}
        # 1. Parse Input
        if len(sys.argv) >= 2:
            try:
                input_data = json.loads(sys.argv[1])
            except json.JSONDecodeError:
                pass 
        
        if not input_data:
            # Try reading from stdin
            try:
                stdin_content = sys.stdin.read().strip()
                if stdin_content:
                    input_data = json.loads(stdin_content)
            except Exception:
                pass
        
        if not input_data:
            print(json.dumps({"error": "No input provided"}))
            return

        input_data = input_data or {}
        query = input_data.get("query", "")
        raw_path = input_data.get("path") or ""

        # Linux-to-Windows Path Conversion
        if platform.system() == "Windows" and raw_path:
            raw_path = raw_path.replace("/", "\\") # basic slash fix first
            
            # 1. Home Directory (~ or /home/user)
            if raw_path.startswith("~"):
                raw_path = os.path.expanduser("~") + raw_path[1:]
            elif raw_path.startswith("\\home\\"):
                # Suggests someone typed /home/user on windows
                parts = raw_path.split("\\")
                if len(parts) > 2:
                    username = parts[2]
                    # Map to C:\Users\username
                    # Note: We can't guarantee drive letter is C, but it's 99% likely for Users
                    raw_path = os.path.join(os.environ.get("SystemDrive", "C:"), "Users", username, *parts[3:])
            
            # 2. Temp Directory (/tmp)
            elif raw_path == "\\tmp" or raw_path.startswith("\\tmp\\"):
                temp_dir = os.environ.get("TEMP", os.path.join(os.environ.get("SystemDrive", "C:"), "Temp"))
                raw_path = temp_dir + raw_path[4:]
            
            # 3. System Config (/etc -> C:\Windows\System32\drivers\etc for hosts, or just System32?)
            # Usually users mean 'config' area. Let's map to System32/drivers/etc just in case
            elif raw_path == "\\etc" or raw_path.startswith("\\etc\\"):
                raw_path = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "drivers", "etc") + raw_path[4:]

            # 4. Logs (/var/log -> C:\ProgramData)
            elif raw_path.startswith("\\var\\log"):
                raw_path = os.environ.get("ProgramData", "C:\\ProgramData") + raw_path[8:]
        
        # Determine Search Roots
        search_roots = []
        
        # Check if path is effectively root "/" or empty
        is_root_request = raw_path.strip() in ['/', '\\', '']
        
        if is_root_request and platform.system() == "Windows":
            # Enumerate all available drives
            import string
            from ctypes import windll
            
            drives = []
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(f"{letter}:\\")
                bitmask >>= 1
            search_roots = drives
        else:
            # Single path
            if raw_path:
                search_roots = [os.path.abspath(raw_path)]
            else:
                # Fallback to current drive root if not specified and not clearly root request (though handled above)
                search_roots = [os.path.abspath(os.sep)]

        # Validate inputs
        if not query:
             print(json.dumps({"error": "No query provided"}))
             return
             
        # Compile Regex
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            print(json.dumps({"error": f"Invalid Regex: {e}"}))
            return

        matches = []
        scanned_count = 0
        total_folders = 0
        start_time = time.time()
        
        # Directories to skip
        SKIP_DIRS = {
            '$RECYCLE.BIN', 'System Volume Information', 'Windows', 'ProgramData', 
            '.git', '__pycache__', 'node_modules', 'venv', 'env'
        }

        # 2. Walk
        for root_path in search_roots:
            if not os.path.exists(root_path):
                continue
                
            try:
                for root, dirs, files in os.walk(root_path, topdown=True):
                    total_folders += 1
                    
                    # Modify dirs in-place to skip
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
                    
                    # Progress Update every 10 folders
                    if total_folders % 10 == 0:
                        # Send specific 'action_update' message for UI
                         print(json.dumps({
                            "status": "progress", 
                            "message": f"Scanning {root}...",
                            "scanned": scanned_count,
                            "found": len(matches)
                        }), flush=True)

                    last_update_time = time.time()
                    
                    for file in files:
                        scanned_count += 1
                        
                        # Time-Based Update (Every 1.5s)
                        current_time = time.time()
                        elapsed = current_time - start_time
                        if current_time - last_update_time >= 1.5:
                            speed = round(scanned_count / elapsed, 1) if elapsed > 0 else 0
                            print(json.dumps({
                                "status": "progress", 
                                "message": f"Scanning {root}...",
                                "scanned": scanned_count,
                                "found": len(matches),
                                "elapsed": round(elapsed, 1),
                                "speed": speed
                            }), flush=True)
                            last_update_time = current_time

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
                            
                            # Real-time Match Emission
                            elapsed = current_time - start_time
                            speed = round(scanned_count / elapsed, 1) if elapsed > 0 else 0
                            print(json.dumps({
                                "status": "match",
                                "file": matches[-1],
                                "scanned": scanned_count,
                                "found": len(matches),
                                "elapsed": round(elapsed, 1),
                                "speed": speed
                            }), flush=True)
                            try:
                                size = os.path.getsize(full_path)
                            except:
                                size = 0
                                
                            matches.append({
                                "name": file,
                                "path": full_path.replace("\\", "/"),
                                "size": size
                            })
                            
                            # Real-time Match Emission
                            print(json.dumps({
                                "status": "match",
                                "file": matches[-1],
                                "scanned": scanned_count,
                                "found": len(matches)
                            }), flush=True)
                            
                    if len(matches) >= 100:
                        break
                
            except Exception as e:
                # Handle drive access errors (e.g. empty card reader, permission denied)
                # print(f"Error scanning {root_path}: {e}", file=sys.stderr)
                continue
                
            if len(matches) >= 100:
                break
        
        if len(matches) >= 100:
             print(json.dumps({
                "status": "progress", 
                "message": "Match limit reached (100). Stopping."
            }), flush=True)

        # 3. Final Output
        result = {
            "matches": matches,
            "count": len(matches),
            "scanned": scanned_count,
            "folders_scanned": total_folders,
            "duration_seconds": round(time.time() - start_time, 2)
        }
        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
