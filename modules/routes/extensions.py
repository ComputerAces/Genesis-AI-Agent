from flask import Blueprint, request, jsonify, send_file
from flask_login import login_required, current_user
from modules.decorators import admin_required
from modules.extensions import agent
from modules.bot_config import get_bot_config, save_bot_config
from modules.permissions import grant_permission
from modules.tasks import get_scheduler
from modules.actions import ActionRegistry, ActionExecutor
from modules.actions.gplug import calculate_manifest_hash
import os
import json
import tempfile

ext_bp = Blueprint('extensions_api', __name__)

# --- BOT ---
@ext_bp.route("/api/bot", methods=["GET", "POST"])
@login_required
def manage_bot():
    if request.method == "POST":
        data = request.json
        config = get_bot_config(str(current_user.id))
        if "name" in data:
            config["name"] = data["name"]
        if "personality" in data:
            config["personality"] = data["personality"]
        
        save_bot_config(str(current_user.id), config)
        return jsonify({"status": "success", "config": config})
    
    config = get_bot_config(str(current_user.id))
    return jsonify(config)

@ext_bp.route("/api/permissions/grant", methods=["POST"])
@login_required
def grant_permission_api():
    data = request.json
    action_name = data.get("action_name")
    scope = data.get("scope")
    chat_id = data.get("chat_id")
    
    if not action_name or not scope:
        return jsonify({"error": "Missing action_name or scope"}), 400
        
    grant_permission(str(current_user.id), action_name, scope, chat_id)
    return jsonify({"status": "success"})

# --- TASKS ---
@ext_bp.route("/api/tasks", methods=["GET"])
@login_required
def list_tasks():
    scheduler = get_scheduler()
    tasks = scheduler.get_all_tasks(user_id=str(current_user.id))
    return jsonify(tasks)

@ext_bp.route("/api/tasks", methods=["POST"])
@login_required
def create_task():
    scheduler = get_scheduler()
    data = request.json
    task_id = scheduler.create_task(
        name=data.get("name", "Untitled Task"),
        action=data.get("action"),
        schedule=data.get("schedule"),
        user_id=str(current_user.id),
        args=data.get("args", {})
    )
    return jsonify({"task_id": task_id, "status": "created"})

@ext_bp.route("/api/tasks/<task_id>", methods=["PUT"])
@login_required
def update_task(task_id):
    scheduler = get_scheduler()
    data = request.json
    if scheduler.update_task(task_id, data):
        return jsonify({"status": "updated"})
    return jsonify({"error": "Task not found"}), 404

@ext_bp.route("/api/tasks/<task_id>", methods=["DELETE"])
@login_required
def delete_task_api(task_id):
    scheduler = get_scheduler()
    if scheduler.delete_task(task_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Task not found"}), 404

@ext_bp.route("/api/tasks/<task_id>/run", methods=["POST"])
@login_required
def run_task_api(task_id):
    scheduler = get_scheduler()
    registry = ActionRegistry()
    executor = ActionExecutor()
    registry.scan_plugins()
    result = scheduler.run_task(task_id, executor=executor, registry=registry)
    return jsonify(result)

# --- ACTIONS ---
@ext_bp.route("/api/actions", methods=["GET"])
@login_required
def list_actions():
    registry = ActionRegistry()
    registry.scan_plugins(user_id=str(current_user.id))
    return jsonify(registry.get_all_actions())

@ext_bp.route("/api/actions/create", methods=["POST"])
@login_required
def create_action():
    plugin_id = request.form.get('plugin_id')
    plugin_name = request.form.get('plugin_name')
    version = request.form.get('version', '1.0.0')
    action_name = request.form.get('action_name')
    description = request.form.get('description', '')
    trigger = request.form.get('trigger', 'manual')
    cache_ttl = int(request.form.get('cache_ttl', 0))
    scope = request.form.get('scope', 'user')
    params_str = request.form.get('parameters', '{}')
    script_content = request.form.get('script_content', '')
    
    if not plugin_id or not action_name:
        return jsonify({"error": "plugin_id and action_name are required"}), 400
    
    if scope == "system" and current_user.role != "admin":
        return jsonify({"error": "Only admins can create system actions"}), 403
    
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    if scope == "system":
        plugin_dir = os.path.join(base_dir, "data", "plugins", plugin_id)
    else:
        plugin_dir = os.path.join(base_dir, "bot_data", "users", str(current_user.id), "plugins", plugin_id)
    
    os.makedirs(plugin_dir, exist_ok=True)
    
    try:
        parameters = json.loads(params_str) if params_str else {}
    except:
        parameters = {}
    
    manifest = {
        "id": plugin_id,
        "name": plugin_name,
        "version": version,
        "description": description,
        "actions": [
            {
                "name": action_name,
                "script": "main.py",
                "type": "python",
                "description": description,
                "trigger": trigger,
                "cache_ttl": cache_ttl,
                "parameters": parameters
            }
        ]
    }
    
    manifest_path = os.path.join(plugin_dir, "manifest.json")
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    
    if script_content:
        script_path = os.path.join(plugin_dir, "main.py")
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
    else:
        files = request.files.getlist('files')
        for file in files:
            rel_path = file.filename
            if '/' in rel_path:
                parts = rel_path.split('/')
                rel_path = '/'.join(parts[1:]) if len(parts) > 1 else parts[0]
            
            file_path = os.path.join(plugin_dir, rel_path)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            file.save(file_path)
    
    return jsonify({"status": "created", "plugin_id": plugin_id, "scope": scope})

@ext_bp.route("/api/actions/<plugin_id>", methods=["GET"])
@login_required
def get_plugin_details(plugin_id):
    registry = ActionRegistry()
    registry.scan_plugins(user_id=str(current_user.id))
    
    plugin = registry.get_plugin(plugin_id)
    if not plugin:
        return jsonify({"error": "Plugin not found"}), 404
    
    script_path = os.path.join(plugin['_path'], 'main.py')
    script_content = ""
    if os.path.exists(script_path):
        with open(script_path, 'r', encoding='utf-8') as f:
            script_content = f.read()
    
    return jsonify({
        "plugin": plugin,
        "script_content": script_content
    })

@ext_bp.route("/api/actions/<plugin_id>", methods=["PUT"])
@login_required
def update_plugin(plugin_id):
    registry = ActionRegistry()
    registry.scan_plugins(user_id=str(current_user.id))
    plugin = registry.get_plugin(plugin_id)
    if not plugin:
        return jsonify({"error": "Plugin not found"}), 404
    
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if plugin.get('_role') == 'user':
        user_plugins_path = os.path.join(base_dir, "bot_data", "users", str(current_user.id), "plugins")
        if not plugin['_path'].startswith(os.path.abspath(user_plugins_path)):
            return jsonify({"error": "Cannot edit other users' plugins"}), 403
    elif plugin.get('_role') == 'system' and current_user.role != 'admin':
        return jsonify({"error": "Only admins can edit system plugins"}), 403
    
    data = request.json
    manifest_path = os.path.join(plugin['_path'], 'manifest.json')
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    if 'name' in data: manifest['name'] = data['name']
    if 'description' in data: manifest['description'] = data['description']
    if 'version' in data: manifest['version'] = data['version']
    if 'actions' in data: manifest['actions'] = data['actions']
    
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    
    if 'script_content' in data:
        script_path = os.path.join(plugin['_path'], 'main.py')
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(data['script_content'])
    
    return jsonify({"status": "updated"})

@ext_bp.route("/api/actions/<plugin_id>", methods=["DELETE"])
@login_required
def delete_plugin(plugin_id):
    registry = ActionRegistry()
    registry.scan_plugins(user_id=str(current_user.id))
    plugin = registry.get_plugin(plugin_id)
    if not plugin:
        return jsonify({"error": "Plugin not found"}), 404
    
    if plugin.get('_role') == 'system' and current_user.role != 'admin':
        return jsonify({"error": "Only admins can delete system plugins"}), 403
    
    if registry.delete_plugin(plugin_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Failed to delete"}), 500

@ext_bp.route("/api/actions/<plugin_id>/export", methods=["GET"])
@login_required
def export_plugin(plugin_id):
    registry = ActionRegistry()
    registry.scan_plugins(user_id=str(current_user.id))
    try:
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, f"{plugin_id}.gplug")
        gplug_path = registry.pack_plugin(plugin_id, output_path)
        
        plugin = registry.get_plugin(plugin_id)
        if plugin:
            sha = calculate_manifest_hash(plugin)
            response = send_file(gplug_path, as_attachment=True, download_name=f"{plugin_id}.gplug")
            response.headers['X-Plugin-SHA'] = sha
            return response
        return send_file(gplug_path, as_attachment=True, download_name=f"{plugin_id}.gplug")
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

@ext_bp.route("/api/actions/<plugin_id>/sha", methods=["GET"])
@login_required
def get_plugin_sha(plugin_id):
    registry = ActionRegistry()
    registry.scan_plugins(user_id=str(current_user.id))
    plugin = registry.get_plugin(plugin_id)
    if not plugin:
        return jsonify({"error": "Plugin not found"}), 404
    
    sha = calculate_manifest_hash(plugin)
    return jsonify({
        "plugin_id": plugin_id,
        "sha256": sha,
        "name": plugin.get("name", plugin_id),
        "version": plugin.get("version", "1.0.0")
    })

@ext_bp.route("/api/actions/install", methods=["POST"])
@login_required
def install_plugin_api():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    scope = request.form.get('scope', 'user')
    expected_sha = request.form.get('sha', '').strip()
    
    if scope == 'system' and current_user.role != 'admin':
        return jsonify({"error": "Only admins can install system plugins"}), 403
    
    temp_dir = tempfile.mkdtemp()
    gplug_path = os.path.join(temp_dir, file.filename)
    file.save(gplug_path)
    
    try:
        registry = ActionRegistry()
        manifest = registry.install_plugin(gplug_path, user_id=str(current_user.id), scope=scope)
        
        installed_sha = calculate_manifest_hash(manifest)
        if expected_sha and installed_sha != expected_sha:
            registry.delete_plugin(manifest['id'])
            return jsonify({
                "error": f"SHA mismatch! Expected {expected_sha[:16]}... but got {installed_sha[:16]}...",
                "expected_sha": expected_sha,
                "actual_sha": installed_sha
            }), 400
        
        return jsonify({
            "status": "installed",
            "plugin_id": manifest['id'],
            "scope": scope,
            "sha256": installed_sha
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
