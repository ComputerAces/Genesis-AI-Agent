import google.generativeai as genai
from modules.config import update_token_usage
from modules.db import get_api_key
import os

class GeminiProvider:
    def __init__(self, model_name="gemini-flash-latest", model_cfg=None, **kwargs):
        self.model_cfg = model_cfg or {}
        self.model_name = model_name
        self.api_key = get_api_key("gemini")
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(model_name)
        else:
            print("[WARN] Gemini API Key not found in database.")
            self.model = None

    def generate(self, prompt, use_thinking=True, stop_event=None, return_json=False, parent_id="default", history_override=None, system_prompt=None):
        if not self.model:
            # Re-check key (maybe added just now)
            self.api_key = get_api_key("gemini")
            if self.api_key:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(self.model_name)
            else:
                yield {"status": "error", "error": "Gemini API Key missing. Please set it in Settings."}
                return

        # Prepare History
        history = list(history_override) if history_override else []
        
        # Gemini expects a specific format: "user", "model" roles
        # And strict alternating.
        # But we can just use `generate_content` with the full prompt context + system instruction.
        
        # Build System Config
        gen_config = genai.types.GenerationConfig(
            candidate_count=1,
            max_output_tokens=self.model_cfg.get("output_size", 8192),
            temperature=0.7 if not use_thinking else 0.8,
            top_p=0.95
        )
        
        # Construct the full chat history for the prompt
        # Newer Gemini SDK supports `system_instruction` in GenerativeModel constructor, 
        # but since we reuse the model instance, we might need to recreate it or pass it differently.
        # Actually, `generate_content` is stateless.
        # However, `start_chat` manages history.
        
        # Let's map our history to Gemini history
        gemini_history = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [msg["content"]]})
        
        # If the last message in history is the current prompt, we should remove it 
        # because `send_message` takes the new prompt.
        current_msg = prompt
        if gemini_history and gemini_history[-1]["role"] == "user" and gemini_history[-1]["parts"][0] == prompt:
            gemini_history.pop()
        
        # Handle System Prompt via 'system_instruction' if supported, or prepend to first message
        # For Flash 1.5+, system_instruction is supported.
        # We will re-instantiate the model with system instruction for this turn to be safe.
        
        model_instance = genai.GenerativeModel(
            self.model_name,
            system_instruction=system_prompt if system_prompt else None
        )
        
        chat = model_instance.start_chat(history=gemini_history)
        
        try:
            response = chat.send_message(current_msg, stream=True, generation_config=gen_config)
            
            full_text = ""
            for chunk in response:
                if stop_event and stop_event.is_set():
                    break
                
                text_chunk = chunk.text
                full_text += text_chunk
                yield {"status": "content", "chunk": text_chunk}
                
            # Update Usage
            # Gemini usage metadata is in response.usage_metadata but tricky with streaming
            # Approximate for now
            input_tokens = len(prompt) // 4  # Rough estimate
            output_tokens = len(full_text) // 4
            update_token_usage(self.model_cfg.get("id", "gemini"), input_tokens, output_tokens)
            
        except Exception as e:
            yield {"status": "error", "error": f"Gemini Error: {str(e)}"}

    def clear_history(self, parent_id=None):
        pass

    def get_history(self, parent_id=None):
        return []
