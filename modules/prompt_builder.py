import json
import os
from typing import Dict, List, Optional

def load_prompts() -> Dict:
    """Load prompt templates from prompts.json"""
    # Get Genesis root: from modules/prompt_builder.py go up one level
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompts_path = os.path.join(base_dir, "data", "prompts.json")
    
    with open(prompts_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_system_prompt(
    user_id: str,
    available_actions: List[Dict],
    action_data: str = "",
    bot_config: Dict = None,
    prompt_id: str = "user_chat",
    user_message: str = ""
) -> str:
    """
    Build a complete system prompt with bot personality and available actions.
    
    Args:
        user_id: The user's ID
        available_actions: List of action definitions from registry
        action_data: Pre-request plugin output to inject
        bot_config: Bot configuration (name, personality)
        prompt_id: The ID of the prompt template to use from prompts.json
        user_message: The original user message (for action_formater)
    """
    prompts = load_prompts()
    template = prompts.get(prompt_id, prompts.get("user_chat", ""))
    
    # Inject bot personality
    if bot_config:
        bot_name = bot_config.get("name", "Genesis AI")
        bot_personality = bot_config.get("personality", "")
    else:
        bot_name = "Genesis AI"
        bot_personality = ""
    
    template = template.replace("[bot_name]", bot_name)
    template = template.replace("[bot_personality]", bot_personality)
    
    # Inject User Message (if present in template)
    if user_message:
        template = template.replace("[user_message]", user_message)

    # Remove [history] placeholder - history is injected separately via format_history_for_prompt
    template = template.replace("Context history: [history]", "")
    template = template.replace("[history]", "")
    
    # Inject action data (Content only, headers in prompt template)
    if action_data:
        template = template.replace("[action_data]", action_data)
    else:
        template = template.replace("[action_data]", "")
    
    # Build available actions list (exclude pre_request actions - those run automatically)
    if available_actions:
        actions_text = ""
        for action in available_actions:
            # Skip pre_request actions - they run automatically before each request
            if action.get("trigger") == "pre_request":
                continue
                
            spec = action.get("spec")
            if not spec:
                # Fallback: assume the action itself is the spec (flat structure)
                spec = action
            name = spec.get("name", "unknown")
            description = spec.get("description", "No description")
            params = spec.get("parameters", {})
            
            params_text = ", ".join([f'"{k}": <{v}>' for k, v in params.items()])
            actions_text += f"- **{name}**: {description}\n"
            if params_text:
                actions_text += f"  Parameters: {{{params_text}}}\n"
            else:
                actions_text += f"  Parameters: None\n"
        
        if actions_text:
            template = template.replace("[actions]", actions_text)
            # Cleanup old tag if present (legacy support/safety)
            template = template.replace("[available_actions]", actions_text)
        else:
            template = template.replace("[actions]", "No actions currently available.")
            template = template.replace("[available_actions]", "No actions currently available.")
    else:
        template = template.replace("[actions]", "No actions currently available.")
        template = template.replace("[available_actions]", "No actions currently available.")

    # 4. Final Sanitization: Remove any remaining [tag] placeholders
    # We use a regex to find any remaining bracketed identifiers that look like tags
    import re
    # Remove tags like [some_tag] but try to avoid removing standard brackets if possible.
    # We assume valid tags are alphanumeric + underscore.
    template = re.sub(r'\[[a-z_0-9]+\]', '', template)
    
    # Clean up any double newlines from removed placeholders
    while "\n\n\n" in template:
        template = template.replace("\n\n\n", "\n\n")
    
    return template.strip()

def format_history_for_prompt(history: List[Dict], system_prompt: str) -> List[Dict]:
    """
    Format history for the prompt.
    NOTE: We now pass system_prompt out-of-band to the provider, so we DO NOT prepend it here.
    This prevents it from being trimmed or duplicated.
    """
    # formatted = [{"role": "system", "content": system_prompt}]
    # formatted.extend(history)
    return list(history) # Return a copy
