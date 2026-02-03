
import os
import traceback
from modules.config import load_settings
from modules.db import init_db 
import sqlite3

# Import Providers
# We use lazy imports inside get_provider to avoid circular dependency issues if any,
# though providers usually don't import core.
from .qwen_provider import QwenProvider
from .gemini_provider import GeminiProvider

_PROVIDER_CACHE = {}

def get_user_preferred_model(user_id):
    """Fetches the user's preferred model ID from the database."""
    if not user_id:
        return None
        
    try:
        # Assuming db_path is standard
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        db_path = os.path.join(base_dir, "data", "system.db")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT preferred_model FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            return row[0]
    except Exception as e:
        print(f"[ProviderFactory] Error fetching user preference: {e}")
        traceback.print_exc()
    return None

def get_provider(model_id=None):
    """
    Factory method to get the appropriate AI Provider.
    If model_id is None, finds the system default.
    """
    global _PROVIDER_CACHE
    
    settings = load_settings()
    target_cfg = None

    # 1. Resolve Model Config
    if not model_id:
        model_id = settings.get("active_model")
    
    # Search for config
    for m in settings.get("models", []):
        if m["id"] == model_id:
            target_cfg = m
            break
            
    # Fallback
    if not target_cfg:
        if settings.get("models"):
            target_cfg = settings["models"][0]
            model_id = target_cfg["id"]
        else:
            raise ValueError("No models defined in settings.json")

    # 2. Check Cache
    if model_id in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[model_id]

    # 3. Instantiate
    provider_type = target_cfg.get("type", "qwen")
    model_name = target_cfg.get("name")
    
    print(f"[ProviderFactory] Instantiating Provider: {model_id} ({provider_type})")
    
    try:
        if provider_type == "qwen":
            instance = QwenProvider(model_name=model_name, model_cfg=target_cfg)
        elif provider_type == "gemini":
            instance = GeminiProvider(model_name=model_name, model_cfg=target_cfg)
        else:
            raise ValueError(f"Unsupported provider type: {provider_type}")
            
        _PROVIDER_CACHE[model_id] = instance
        return instance
    except Exception as e:
        print(f"[ProviderFactory] Failed to instantiate {provider_type}: {e}")
        traceback.print_exc()
        raise e
