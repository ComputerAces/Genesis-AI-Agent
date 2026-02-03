from flask import Blueprint, request, jsonify
from flask_login import login_required
from modules.db import save_api_key, get_api_key
from modules.decorators import admin_required

keys_bp = Blueprint('keys', __name__)

@keys_bp.route("/api/keys", methods=["POST"])
@login_required
@admin_required
def save_key():
    data = request.json
    provider = data.get("provider")
    key = data.get("key")
    
    if not provider or not key:
        return jsonify({"error": "Missing provider or key"}), 400
        
    if save_api_key(provider, key):
        return jsonify({"status": "success", "message": f"Key for {provider} saved."})
    else:
        return jsonify({"error": "Failed to save key"}), 500

@keys_bp.route("/api/keys/<provider>", methods=["GET"])
@login_required
def check_key(provider):
    # Return whether a key exists, but not the key itself
    key = get_api_key(provider)
    return jsonify({"exists": bool(key)})
