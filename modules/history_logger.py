import os
import json
import datetime

class HistoryLogger:
    def __init__(self, base_dir=None):
        if base_dir:
            self.base_dir = base_dir
        else:
            # Default to genesis_home/data/history
            genesis_home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.base_dir = os.path.join(genesis_home, "data", "history")

    def log_interaction(self, chat_id, system_prompt, history_context, assistant_output, thinking_trace, model_config=None, user_id=None):
        """
        Logs a full interaction to a JSON file.
        """
        try:
            # 1. Create Directory for Today
            now = datetime.datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            daily_dir = os.path.join(self.base_dir, date_str)
            
            if not os.path.exists(daily_dir):
                os.makedirs(daily_dir)
            
            # 2. Construct Filename
            # timestamp_chatid.json
            time_str = now.strftime("%H-%M-%S")
            filename = f"{time_str}_{chat_id[:8]}.json"
            filepath = os.path.join(daily_dir, filename)
            
            # 3. Prepare Data
            data = {
                "timestamp": now.isoformat(),
                "user_id": user_id,
                "chat_id": chat_id,
                "model_config": model_config or {},
                "system_prompt": system_prompt,
                "history_context": history_context, # The full list of messages sent to the model
                "response": {
                    "role": "assistant",
                    "content": assistant_output,
                    "thinking": thinking_trace
                }
            }
            
            # 4. Write File
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            print(f"[HistoryLogger] Saved interaction to {filepath}")
            return filepath
            
        except Exception as e:
            print(f"[HistoryLogger] Error saving log: {e}")
            return None

# Singleton instance for easy import
_logger = HistoryLogger()

def log_interaction(*args, **kwargs):
    return _logger.log_interaction(*args, **kwargs)
