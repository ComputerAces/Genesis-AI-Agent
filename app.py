from flask import Flask, redirect, url_for
from flask_login import LoginManager
from modules.extensions import agent
from modules.db import init_db
from modules.config import load_settings
from modules.routes.auth import auth_bp, load_user_from_db
from modules.routes.main import main_bp
from modules.routes.chat import chat_bp
from modules.routes.admin import admin_bp
from modules.routes.extensions import ext_bp
import os
import sys
import signal

# Ensure database is initialized
init_db()

if "--help" in sys.argv or "-h" in sys.argv:
    print("Usage: python app.py [options]")
    print("Options:")
    print("  -h, --help    Show this help message and exit")
    print("  /gui          Launch in GUI mode (handled by run.bat)")
    sys.exit(0)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "genesis_secret_key_123")

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login" # Updated view name

@login_manager.user_loader
def load_user(user_id):
    return load_user_from_db(user_id)

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(ext_bp)

# Start Task Scheduler
from modules.tasks import get_scheduler
get_scheduler().start()

# Signal Handler
def signal_handler(sig, frame):
    print("\n[System] Shutdown signal received. Cleaning up...")
    if agent:
        agent.shutdown()
    get_scheduler().stop()
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    settings = load_settings()
    server_cfg = settings.get("server", {})
    host = server_cfg.get("host", "127.0.0.1")
    port = server_cfg.get("port", 5000)
    debug = server_cfg.get("debug", False)
    
    print(f"Starting Genesis AI on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)
