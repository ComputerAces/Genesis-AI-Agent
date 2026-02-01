import os
import json
import random

# Default bot names
DEFAULT_NAMES = [
    "Atlas", "Nova", "Echo", "Sage", "Oracle", 
    "Nimbus", "Zenith", "Cipher", "Aether", "Prism"
]

DEFAULT_PERSONALITY = """I am a helpful, friendly AI assistant. I aim to be clear, concise, and accurate in my responses. I enjoy helping users accomplish their goals and learning new things along the way."""

def get_bot_config(user_id: str) -> dict:
    """
    Gets or creates bot.json for a user.
    Returns dict with 'name' and 'personality' keys.
    """
    bot_data_dir = os.path.join("bot_data", "users", str(user_id))
    bot_json_path = os.path.join(bot_data_dir, "bot.json")
    
    # Ensure directory exists
    os.makedirs(bot_data_dir, exist_ok=True)
    
    if os.path.exists(bot_json_path):
        try:
            with open(bot_json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    
    # Create default config
    config = {
        "name": random.choice(DEFAULT_NAMES),
        "personality": DEFAULT_PERSONALITY
    }
    
    with open(bot_json_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
    
    return config

def save_bot_config(user_id: str, config: dict):
    """Saves bot configuration for a user."""
    bot_data_dir = os.path.join("bot_data", "users", str(user_id))
    bot_json_path = os.path.join(bot_data_dir, "bot.json")
    
    os.makedirs(bot_data_dir, exist_ok=True)
    
    with open(bot_json_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
