import json
import os

def load_settings():
    """
    Loads settings from data/settings.json relative to the project root.
    """
    # Assuming this file is in project_root/modules/config.py
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings_path = os.path.join(base_dir, "data", "settings.json")
    
    if not os.path.exists(settings_path):
        # Fallback default if file is missing (though our flow should ensure it exists)
        return {
            "server": {"host": "127.0.0.1", "port": 5000, "debug": True},
            "models": [],
            "active_model": None
        }
        
    with open(settings_path, "r") as f:
        return json.load(f)

def load_prompts():
    """
    Loads custom prompts from data/prompts.json.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompts_path = os.path.join(base_dir, "data", "prompts.json")
    
    if not os.path.exists(prompts_path):
        return {"general_chat": "You are a helpful AI assistant."}
        
    with open(prompts_path, "r") as f:
        return json.load(f)

def save_prompts(prompts):
    """
    Saves prompts to data/prompts.json.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompts_path = os.path.join(base_dir, "data", "prompts.json")
    
    with open(prompts_path, "w") as f:
        json.dump(prompts, f, indent=2)

def get_active_model_settings(settings=None):
    """
    Retrieves the settings for the currently active model.
    """
    if settings is None:
        settings = load_settings()
        
    active_id = settings.get("active_model")
    for model in settings.get("models", []):
        if model.get("id") == active_id:
            return model
    return None

def get_startup_thinking_mode():
    """
    Parses sys.argv for /think on/off
    """
    import sys
    use_thinking = True
    if "/think" in sys.argv:
        try:
            idx = sys.argv.index("/think")
            if idx + 1 < len(sys.argv):
                state = sys.argv[idx + 1].lower()
                if state == "off":
                    use_thinking = False
                elif state == "on":
                    use_thinking = True
        except ValueError:
            pass
    return use_thinking

def update_token_usage(model_id, prompt_tokens, generated_tokens):
    """
    Updates the token usage stats for a specific model in settings.json.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings_path = os.path.join(base_dir, "data", "settings.json")
    
    # Load raw, modify, save to avoid race conditions (simple file lock would be better but KISS)
    if not os.path.exists(settings_path):
        return

    try:
        with open(settings_path, "r") as f:
            settings = json.load(f)

        for model in settings.get("models", []):
            if model["id"] == model_id:
                if "token_usage" not in model:
                    model["token_usage"] = {"input": 0, "output": 0}
                
                model["token_usage"]["input"] += prompt_tokens
                model["token_usage"]["output"] += generated_tokens
                break
        
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"[Error] Failed to update token usage: {e}")
