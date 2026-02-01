from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from modules.decorators import admin_required
from modules.config import load_settings, load_prompts, save_prompts
from werkzeug.security import generate_password_hash
import os
import json
import sys
import sqlite3
from threading import Thread

admin_bp = Blueprint('admin_api', __name__)

@admin_bp.route("/api/settings", methods=["GET", "POST"])
@admin_required
def manage_settings():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    settings_path = os.path.join(base_dir, "data", "settings.json")
    
    if request.method == "POST":
        new_settings = request.json
        with open(settings_path, "w") as f:
            json.dump(new_settings, f, indent=2)
        return jsonify({"status": "success"})
    
    return jsonify(load_settings())

@admin_bp.route("/api/models", methods=["GET"])
@login_required
def list_models():
    settings = load_settings()
    return jsonify(settings.get("models", []))

@admin_bp.route("/api/prompts", methods=["GET", "POST"])
@admin_required
def manage_prompts():
    if request.method == "POST":
        new_prompts = request.json
        save_prompts(new_prompts)
        return jsonify({"status": "success"})
    return jsonify(load_prompts())

@admin_bp.route("/api/reload", methods=["POST"])
@admin_required
def reload_server():
    print("[System] Restarting server...")
    def restart():
        import time
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    
    Thread(target=restart).start()
    return jsonify({"status": "restarting"})

@admin_bp.route("/api/admin/users", methods=["GET", "POST"])
@admin_required
def manage_users():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        if request.method == "POST":
            data = request.json
            action = data.get("action")
            if action == "add":
                pwd_hash = generate_password_hash(data.get("password"))
                try:
                    cursor.execute("INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
                                 (data.get("username"), pwd_hash, data.get("email"), data.get("role", "user")))
                    conn.commit()
                except sqlite3.IntegrityError:
                    return jsonify({"status": "error", "message": "User already exists"}), 400
            elif action == "delete":
                cursor.execute("DELETE FROM users WHERE id = ?", (data.get("id"),))
                conn.commit()
            return jsonify({"status": "success"})
        
        cursor.execute("SELECT id, username, email, role FROM users")
        users = [{"id": r[0], "username": r[1], "email": r[2], "role": r[3]} for r in cursor.fetchall()]
        return jsonify(users)
    finally:
        conn.close()

@admin_bp.route("/api/admin/history", methods=["GET"])
@admin_required
def admin_history_api():
    query = request.args.get("q")
    from modules.db import get_all_history_items
    items = get_all_history_items(query)
    return jsonify(items)

@admin_bp.route("/api/admin/global_history", methods=["GET"])
@admin_required
def get_global_history():
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        history_dir = os.path.join(base_dir, "data", "history")
        
        if not os.path.exists(history_dir):
            return jsonify({"items": [], "total": 0, "page": page, "pages": 0})
            
        all_files = []
        for root, dirs, files in os.walk(history_dir):
            for file in files:
                if file.endswith(".json"):
                    all_files.append(os.path.join(root, file))
        
        all_files.sort(key=os.path.getmtime, reverse=True)
        
        total_items = len(all_files)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        page_files = all_files[start_idx:end_idx]
        
        items = []
        for fpath in page_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    user_input = ""
                    history = data.get("history_context", [])
                    for m in reversed(history):
                        if m.get("role") == "user":
                            user_input = m.get("content", "")
                            break
                    truncated_input = (user_input[:100] + '...') if len(user_input) > 100 else user_input
                    response_content = data.get("response", {}).get("content", "")
                    truncated_response = (response_content[:100] + '...') if len(response_content) > 100 else response_content
                    
                    items.append({
                        "file_path": fpath,
                        "timestamp": data.get("timestamp"),
                        "chat_id": data.get("chat_id"),
                        "model": data.get("model_config", {}).get("id", "Unknown"),
                        "user_input": truncated_input,
                        "response": truncated_response,
                        "full_log": data
                    })
            except Exception as e:
                continue
                
        return jsonify({
            "items": items,
            "total": total_items,
            "page": page,
            "pages": (total_items + per_page - 1) // per_page
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
