from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from modules.decorators import admin_required
from modules.config import get_startup_thinking_mode

main_bp = Blueprint('main', __name__)

@main_bp.route("/")
@login_required
def index():
    default_use_thinking = get_startup_thinking_mode()
    return render_template("index.html", default_thinking=default_use_thinking, user=current_user)

@main_bp.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html", user=current_user)

@main_bp.route("/manage-chats")
@login_required
def manage_chats_page():
    return render_template("chats.html", user=current_user)

@main_bp.route("/settings")
@admin_required
def settings_page():
    return render_template("settings.html", user=current_user)

@main_bp.route("/tasks")
@login_required
def tasks_page():
    return render_template("tasks.html", user=current_user)

@main_bp.route("/actions")
@login_required
def actions_page():
    return render_template("actions.html", user=current_user)

@main_bp.route("/bot")
@login_required
def bot_page():
    return render_template("bot.html", user=current_user)

@main_bp.route("/admin/history")
@admin_required
def admin_history_page():
    return render_template("manage_history.html", user=current_user)
