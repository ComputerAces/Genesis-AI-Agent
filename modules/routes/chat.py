from flask import Blueprint, request, jsonify, Response, stream_with_context
from flask_login import login_required, current_user
from modules.extensions import agent
from modules.config import get_startup_thinking_mode
from modules.db import get_chats_for_user, create_chat, delete_chat, clear_chat_history
import json
import uuid

chat_bp = Blueprint('chat_api', __name__)

@chat_bp.route("/api/chats", methods=["GET", "POST"])
@login_required
def manage_chats():
    if request.method == "POST":
        chat_id = uuid.uuid4().hex
        title = request.json.get("title", "New Chat")
        create_chat(chat_id, current_user.id, title)
        return jsonify({"status": "success", "chat_id": chat_id})
    
    chats = get_chats_for_user(current_user.id)
    return jsonify(chats)

@chat_bp.route("/api/chats/<chat_id>", methods=["DELETE"])
@login_required
def delete_chat_api(chat_id):
    delete_chat(chat_id)
    return jsonify({"status": "success"})

@chat_bp.route("/api/chats/<chat_id>/clear", methods=["POST"])
@login_required
def clear_chat_api(chat_id):
    clear_chat_history(chat_id)
    return jsonify({"status": "success"})

@chat_bp.route("/api/chat", methods=["POST"])
@login_required
def chat():
    data = request.json
    message = data.get("message")
    
    default_use_thinking = get_startup_thinking_mode()
    use_thinking = data.get("use_thinking", default_use_thinking)
    priority = data.get("priority", "normal")
    return_json = data.get("return_json", True) 
    prompt_id = data.get("prompt_id", "user_chat")
    tab_id = data.get("tab_id", "general")
    chat_id = data.get("chat_id")
    resume_action = data.get("resume_action", False)
    
    # Check if we are just resubscribing
    is_resubscribe = False
    with agent.active_tasks_lock:
        if not message and not resume_action and chat_id in agent.active_tasks:
            is_resubscribe = True
    
    if not message and not resume_action and not is_resubscribe:
        return jsonify({"status": "no_active_stream", "message": "No active stream to join"}), 200
    
    # Ensure chat exists in DB
    if message or resume_action:
        create_chat(chat_id, current_user.id)

    def generate():
        try:
            for chunk in agent.ask_stream(message, use_thinking=use_thinking, priority=priority, return_json=return_json, prompt_id=prompt_id, chat_id=chat_id, resume_action=resume_action):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
            
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@chat_bp.route("/api/history/clear", methods=["POST"])
@login_required
def clear_history():
    data = request.json or {}
    chat_id = data.get("chat_id")
    if chat_id:
        clear_chat_history(chat_id)
    return jsonify({"status": "success"})

@chat_bp.route("/api/history", methods=["GET"])
@login_required
def get_history():
    chat_id = request.args.get("chat_id")
    history = agent.get_history(chat_id=chat_id)
    return jsonify(history)
