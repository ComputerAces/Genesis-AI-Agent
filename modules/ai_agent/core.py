from .providers.qwen_provider import QwenProvider
from .providers.gemini_provider import GeminiProvider
import threading
from concurrent.futures import wait, FIRST_COMPLETED
import queue
import datetime
import psutil
import os
import re
import uuid
import json
from modules.config import get_active_model_settings
from modules.db import save_chat_item, load_chat_items, update_history_entry, get_chat_owner, save_raw_history
from modules.actions.registry import ActionRegistry
from modules.actions.executor import ActionExecutor

from .utils import GetTokenLength, clean_content, shrink_history

class AIAgent:
    def __init__(self, **kwargs):
        self.model_cfg = get_active_model_settings()
        if not self.model_cfg:
            print("[WARN] No active model setting found. Will load on demand.")
            
        # Provider Cache: model_id -> provider_instance
        self.providers = {}
        
    def _get_provider(self, model_id=None):
        """
        Retrieves or instantiates a provider for the given model_id.
        If model_id is None, uses the global default from settings.
        """
        from modules.config import get_active_model_settings, load_settings
        
        # 1. Resolve Model Configuration
        target_cfg = None
        settings = load_settings()
        
        if not model_id:
             model_id = settings.get("active_model")
        
        # Find config for this ID
        for m in settings.get("models", []):
            if m["id"] == model_id:
                target_cfg = m
                break
        
        if not target_cfg:
            # Fallback to first if still failing
            if settings.get("models"):
                target_cfg = settings["models"][0]
                model_id = target_cfg["id"]
        
        if not target_cfg:
            raise ValueError("No model configuration found.")

        # 2. Check Cache
        if model_id in self.providers:
            return self.providers[model_id]

        # 3. Instantiate
        provider_type = target_cfg.get("type", "qwen")
        model_name = target_cfg.get("name")
        
        print(f"[Core] Loading Provider for {model_id} ({provider_type})...")
        
        if provider_type == "qwen":
            instance = QwenProvider(model_name=model_name, model_cfg=target_cfg)
        elif provider_type == "gemini":
            instance = GeminiProvider(model_name=model_name, model_cfg=target_cfg)
        else:
            raise ValueError(f"Unsupported provider: {provider_type}")
            
        self.providers[model_id] = instance
        return instance
    
    @property
    def provider(self):
        # Legacy property for backward compatibility, returns default active
        return self._get_provider()

    def __init__(self, **kwargs):
        self.model_cfg = get_active_model_settings()
        self.providers = {} 
        
        # Legacy: Check for specific forced init
        # if self.model_cfg:
        #      self._get_provider(self.model_cfg["id"])
        
        self.priority_map = {
            "low": psutil.IDLE_PRIORITY_CLASS if os.name == 'nt' else 19,
            "normal": psutil.NORMAL_PRIORITY_CLASS if os.name == 'nt' else 0,
            "high": psutil.HIGH_PRIORITY_CLASS if os.name == 'nt' else -10
        }
        self.stop_event = threading.Event()
        self.request_queue = queue.Queue()
        
        # Action System Initialization
        self.action_registry = ActionRegistry.get_instance()
        self.action_registry.scan_plugins() # Load system plugins
        self.action_executor = ActionExecutor()
        
        # EXECUTOR for Parallel Actions
        from concurrent.futures import ThreadPoolExecutor
        self.thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ActionWorker")

        # Track active tasks for resubscription: chat_id -> list of queues
        self.active_tasks = {}
        self.active_tasks_lock = threading.Lock()
        
        # Track Active Execution IDs for Cancellation: chat_id -> execution_id
        self.active_action_ids = {} 
        self.active_action_ids_lock = threading.Lock()
        
        self.processor_thread = threading.Thread(target=self._main_processor, daemon=True)
        self.processor_thread.start()

    def cancel_current_action(self, chat_id):
        """Cancels the currently running action for a specific chat."""
        with self.active_action_ids_lock:
            execution_id = self.active_action_ids.get(chat_id)
            if execution_id:
                return self.action_executor.cancel_action(execution_id)
        return False

    def _broadcast(self, chat_id, data):
        with self.active_tasks_lock:
            if chat_id in self.active_tasks:
                for q in self.active_tasks[chat_id]:
                    try:
                        q.put(data)
                    except:
                        pass

    def _main_processor(self):
        """
        Background worker thread logic.
        Delegates to modules.ai_agent.scheduler_worker.run_worker_loop
        """
        from .scheduler_worker import run_worker_loop
        run_worker_loop(self)

    def ask_stream(self, prompt, use_thinking=True, priority="normal", return_json=False, prompt_id="general_chat", parent_id=None, chat_id=None, resume_action=False, system_prompt=None, history_override=None, stop_event=None):
        """
        Main entry point for Chat Generation with Action Loop.
        Supports:
        - Priority Queueing (via niceness)
        - Action Loop (max 5)
        - ASYNC/PARALLEL Action Execution
        - Stop Event
        - Resuming from Permission
        """
        # Ensure ID if not provided
        if not chat_id:
             chat_id = f"ephemeral_{uuid.uuid4().hex[:8]}"

        # Load System Prompt if not provided or empty
        from modules.config import load_prompts
        if not system_prompt:
             prompts = load_prompts()
             system_prompt = prompts.get(prompt_id, "")


        if not system_prompt:
             prompts = load_prompts()
             system_prompt = prompts.get(prompt_id, "")

        # --- RESOLVE PROVIDER ---
        user_id = get_chat_owner(chat_id)
        current_provider = None
        
        # Try to get User's preferred model
        preferred_model = None
        if user_id:
            from modules.db import init_db # Ensure db
            import sqlite3
            # We need a direct DB read here. 
            # Ideally this should be a helper in db.py: get_user_preference(user_id)
            try:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                db_path = os.path.join(base_dir, "data", "system.db")
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT preferred_model FROM users WHERE id = ?", (user_id,))
                row = cursor.fetchone()
                conn.close()
                if row and row[0]:
                    preferred_model = row[0]
            except Exception as e:
                print(f"[Core] Error fetching user preference: {e}")

        try:
             current_provider = self._get_provider(preferred_model) 
        except Exception as e:
             print(f"[Core] Error loading preferred provider '{preferred_model}': {e}. Falling back.")
             current_provider = self._get_provider(None)

        # --- GEMINI KEY CHECK (Context Aware) ---
        if isinstance(current_provider, GeminiProvider) and not current_provider.api_key:
             print("[Core] Gemini Key Required. Requesting from UI...", flush=True)
             yield {
                 "status": "request_key",
                 "provider": "gemini",
                 "message": "Gemini API Key is missing. Please enter it to continue."
             }
             
             # Polling Loop (Wait for Key)
             import time
             for _ in range(60): # Wait 60 seconds max
                 time.sleep(1)
                 from modules.db import get_api_key
                 if get_api_key("gemini"):
                     current_provider.api_key = get_api_key("gemini")
                     import google.generativeai as genai
                     genai.configure(api_key=current_provider.api_key)
                     current_provider.model = genai.GenerativeModel(current_provider.model_name)
                     yield {"status": "info", "message": "Key received. Resuming..."}
                     break
             else:
                 yield {"status": "error", "error": "Timed out waiting for API Key."}
                 return
        
        # Priority Handling
        p = psutil.Process(os.getpid())
        original_priority = p.nice()
        try:
            if os.name == 'nt':
                 p.nice(self.priority_map.get(priority.lower(), psutil.NORMAL_PRIORITY_CLASS))
            else:
                p.nice(self.priority_map.get(priority.lower(), 0))
        except:
            pass

        # ENTRY SAVING LOGIC
        db_entry_id = None
        
        try:
            db_entry_id = save_chat_item(chat_id, "assistant", "", thinking="")
            if prompt and not resume_action:
                 save_chat_item(chat_id, "user", prompt)
        except Exception as e:
            print(f"[Error:History] Failed to save chat items for {chat_id}: {e}")

        try:
            # --- ACTION LOOP START ---
            max_loops = 5
            current_loop = 0
            
            # Helper Import
            from modules.prompt_builder import format_history_for_prompt, build_system_prompt
            
            # Prepare History
            if history_override:
                loop_history = history_override.copy()
            else:
                loop_history = load_chat_items(chat_id)
            
            # --- 0. Pre-Request Actions (System Info, RAG, etc.) ---
            # Scan plugins to ensure we have the latest
            self.action_registry.scan_plugins(user_id=user_id)
            all_actions = self.action_registry.get_all_actions()
            
            pre_request_outputs = []
            
            # Execute all actions with trigger="pre_request"
            for act_name, act_meta in all_actions.items():
                if act_meta.get("trigger") == "pre_request":
                    try:
                        # Execute silently
                        ctx = {"user_id": user_id, "chat_id": chat_id}
                        print(f"[Core] Running pre-request action: {act_name}", flush=True)
                        res = self.action_executor.execute(act_meta, {}, ctx)
                        if res["status"] == "success":
                            output_str = json.dumps(res["output"], indent=2) if isinstance(res["output"], (dict, list)) else str(res["output"])
                            
                            # [DEBUG:Action]
                            print(f"[DEBUG:Action] Pre-request '{act_name}' returned: {output_str}", flush=True)

                            pre_request_outputs.append(f"### {act_name}\n{output_str}")
                    except Exception as e:
                        print(f"[Core] Pre-request action {act_name} failed: {e}")
            
            action_data_str = "\n\n".join(pre_request_outputs)
            
            # Build System Prompt
            from modules.bot_config import get_bot_config
            bot_config = get_bot_config(str(user_id)) if user_id else {"name": "Genesis AI", "personality": ""}
            
            available_actions_list = list(all_actions.values())

            system_prompt = build_system_prompt(
                user_id=user_id,
                available_actions=available_actions_list,
                action_data=action_data_str,
                bot_config=bot_config
            )

            # Inject system prompt at the beginning of history logic
            loop_history = format_history_for_prompt(loop_history, system_prompt)
            
            current_prompt = prompt # Default initialization
            json_data = None # Ensure defined for loop scope
            found_resume_actions = [] # Ensure defined for loop scope
            accumulated_thinking = "" # Capture thinking output

            # RESUME LOGIC
            if resume_action:
                print(f"[DEBUG:Resume] Starting Resume Logic for chat_id={chat_id}", flush=True)
                # Scan history for the last action request
                last_msg = ""
                if loop_history:
                     pass

                for m in reversed(loop_history):
                     # Skip empty messages
                     if m.get('role') == 'assistant' and m.get('content', '').strip():
                         last_msg = m.get('content', '')
                         break
                
                print(f"[DEBUG:Resume] Last Msg (First 500 chars): {last_msg[:500]}", flush=True)
                
                found_resume_actions = []
                from modules.utils import extract_json
                json_data = extract_json(last_msg)
                
                if json_data:
                    # Check for single action object
                    if isinstance(json_data, dict) and "action" in json_data:
                        found_resume_actions.append(json_data)
                    # Check for list of actions
                    elif isinstance(json_data, list):
                        for item in json_data:
                            if isinstance(item, dict) and "action" in item:
                                found_resume_actions.append(item)
                    # Check for old format (actions wrapper)
                    elif isinstance(json_data, dict) and "actions" in json_data:
                        acts = json_data["actions"]
                        if isinstance(acts, list):
                            found_resume_actions.extend(acts)

                if found_resume_actions:
                    print(f"[DEBUG:Resume] Found {len(found_resume_actions)} actions to resume.", flush=True)
                    # We have actions to execute. Jump directly to action execution phase.
                    # We simulate the model having just outputted this.
                    full_content = last_msg
                    # Skip generation, go to processing
                    # We need to ensure we are in the loop context
                    current_loop = 1 
                else:
                     print("[DEBUG:Resume] No actions found to resume.", flush=True)
                     resume_action = False # Fallback to normal generation

            # --- GENERATION LOOP ---
            while current_loop <= max_loops:
                full_content = ""
                # Reset thinking for this turn if we want to capture it freshly, 
                # OR keep it accumulating? Usually per-turn thinking.
                # If we accumulate across loops (Action -> Think -> Action), we might want a list?
                # For now, let's reset it per generation to avoid duplicates.
                # BUT the variable MUST be available for the += operation.
                # If I defined it outside, it should be fine.
                # However, if I define it HERE, it shadows the outer one, which is fine for the loop.
                # But I need it available for the specific `save_raw_history` at the END of the function.
                # So I should use a different variable name locally or ensure the outer one is used.
                # Actually, `accumulated_thinking` at the end wants the LAST thinking? Or all of it?
                # Probably the last one.
                pass
                
                # If we are NOT resuming, we generate text
                if not resume_action:
                    # 1. Prepare Prompt
                    if current_loop == 0:
                        prompt_for_model = current_prompt
                        if not prompt_for_model:
                             prompt_for_model = "Continue processing based on the previous context."
                    else:
                        prompt_for_model = "Continue processing based on the action output."

                    # Ensure variable is ready for +=
                    if 'accumulated_thinking' not in locals():
                        accumulated_thinking = ""

                    # 2. History Handling
                    # History for provider: deeply copy looped history
                    history_for_provider = [
                        {"role": m["role"], "content": m["content"]} 
                        for m in loop_history 
                        if m.get("role") != "system"
                    ]
                    
                    # Current System Prompt
                    current_sys_prompt = system_prompt 
                    
                    # Generate Response
                    # Use thinking only if requested AND it's the first loop (or user wants it always?)
                    # For now, let's respect the flag passed to ask_stream.
                    # Qwen provider checks if it supports it.
                    try:
                        generator = current_provider.generate(
                            prompt=prompt_for_model, 
                            use_thinking=use_thinking, 
                            stop_event=stop_event,
                            history_override=history_for_provider,
                            system_prompt=current_sys_prompt
                        )
                        
                        # Stream it
                        for chunk in generator:
                            # Check for dict (status update) or string (content)
                            if isinstance(chunk, dict):
                                if chunk.get("status") == "thinking":
                                    accumulated_thinking += chunk.get("chunk", "")
                                elif chunk.get("status") == "thinking_finished":
                                    # Ensure we captured everything
                                    if chunk.get("thinking"): 
                                        accumulated_thinking = chunk.get("thinking")
                                
                                yield chunk
                            else:
                                full_content += chunk
                                yield {
                                    "status": "stream",
                                    "content": chunk,
                                    "chat_id": chat_id
                                }
                                
                    except Exception as e:
                        print(f"[Core] Generation Error: {e}")
                        yield {"status": "error", "error": str(e)}
                        return
                
                # Reset resume flag after first pass check
                resume_action = False
                
                # [Optimization] Update History Immediately with Assistant Response
                # This ensures if we crash or stop, the response is saved.
                # However, for actions, we might want to append AFTER we confirm? 
                # No, standard flow is: User -> Assistant (Call) -> Tool (Result) -> Assistant (Answer)
                
                if full_content.strip():
                     loop_history.append({"role": "assistant", "content": full_content})
                     # Save to DB? We usually save at the end of the turn, but for safety:
                     # save_chat_item(... assistant ...) - omitting for speed, we save below.

                # --- 3. RESPONSE ANALYSIS & ACTION EXTRACTION ---
                # ... (Next block handles this)
                
                if json_data and isinstance(json_data, dict) and "actions" in json_data:
                    raw_actions = json_data["actions"]
                    if isinstance(raw_actions, list):
                        for ra in raw_actions:
                            if "name" in ra:
                                args = {}
                                if "parameters" in ra:
                                    params = ra["parameters"]
                                    if isinstance(params, dict):
                                        args = params
                                    elif isinstance(params, list):
                                        for p in params:
                                            if "name" in p:
                                                args[p["name"]] = p.get("value", "")
                                
                                found_resume_actions.append({
                                    "name": ra["name"],
                                    "args": args
                                })
                
                print(f"[DEBUG:Resume] Found {len(found_resume_actions)} actions to resume.", flush=True)
                
                if found_resume_actions:
                     if db_entry_id: update_history_entry(db_entry_id, thinking=f"[Resuming Actions...]")
                     yield {"status": "content", "chunk": "\n\n[System] Resuming Actions...\n", "chat_id": chat_id}
                     
                     futures = []
                     future_map = {}
                     pending = []
                     progress_q = queue.Queue()
                     
                     def make_cb(name):
                         return lambda d: progress_q.put({"name": name, "data": d})
                     
                     for act in found_resume_actions:
                         action_name = act["name"]
                         try:
                             action_args = act["args"]
                             print(f"[DEBUG:Resume] preparing action: {action_name} Args: {action_args}", flush=True)
                             
                             action_def = self.action_registry.get_action(action_name)
                             
                             if action_def:
                                 # Generate and Track Execution ID
                                 execution_id = str(uuid.uuid4())
                                 with self.active_action_ids_lock:
                                     self.active_action_ids[chat_id] = execution_id
                                 
                                 ctx = {"user_id": user_id, "chat_id": chat_id, "execution_id": execution_id}
                                 
                                 f = self.thread_pool.submit(self.action_executor.execute, action_def, action_args, ctx, make_cb(action_name))
                                 future_map[f] = action_name
                                 pending.append(f)
                                 
                                 yield {"status": "content", "chunk": f"[Executing {action_name}...]\n", "chat_id": chat_id}
                             else:
                                 print(f"[DEBUG:Resume] Action definition not found for {action_name}", flush=True)
                         except Exception as e:
                             print(f"[DEBUG:Resume] Error preparing {action_name}: {e}", flush=True)
                             pass

                     # Streaming Wait Loop
                     observations = []
                     
                     while pending or not progress_q.empty():
                         # 1. Drain Queue (Non-blocking)
                         while not progress_q.empty():
                             try:
                                 msg = progress_q.get_nowait()
                                 status_msg = ""
                                 # Parse known progress fields
                                 if "scanned" in msg["data"]:
                                     status_msg = f"Scanned {msg['data']['scanned']} items..."
                                 elif "message" in msg["data"]:
                                     status_msg = msg["data"]["message"]
                                 
                                 if status_msg:
                                    # Yield progress chunk directly to chat stream
                                    yield {"status": "content", "chunk": f"[{msg['name']} Progress]: {status_msg}\n", "chat_id": chat_id}
                                 
                                 # Handle Action Update (Match Found)
                                 if "status" in msg["data"] and msg["data"]["status"] == "match":
                                     yield {
                                         "status": "action_update",
                                         "type": "match",
                                         "data": msg["data"],
                                         "chat_id": chat_id
                                     }
                                     
                             except:
                                 break
                         
                         if not pending:
                             break
                             
                         # 2. Wait for Futures
                         done, not_done = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                         
                         for future in done:
                             pending.remove(future)
                             if future in future_map:
                                 name = future_map[future]
                                 
                                 # Cleanup Execution ID
                                 with self.active_action_ids_lock:
                                     if self.active_action_ids.get(chat_id):
                                         # Only remove if it belongs to this action 
                                         # (Wait, if we run multiple parallel, this logic is shaky for multiple, but user usually runs one)
                                         # We'll assume the last one started is the "active" one for UI purposes.
                                         pass 
                                         # Actually executor cleans up internal map. We just track for UI cancel.
                                         del self.active_action_ids[chat_id]

                                 try:
                                     exec_result = future.result()
                                     obs_text = json.dumps(exec_result.get("output", {})) if exec_result["status"] == "success" else f"Error: {exec_result.get('error')}"
                                     
                                     # [DEBUG:Action]
                                     print(f"[DEBUG:Action] Action '{name}' returned: {obs_text}", flush=True)
                                     
                                     observations.append(f"Action '{name}' Result: {obs_text}")
                                     
                                     # Log to Database for History/Web UI
                                     try:
                                         # save_chat_item is imported globally
                                         save_chat_item(chat_id, "system", f"[Action Output: {name}] {obs_text}")
                                     except Exception as e:
                                         print(f"[DEBUG:Resume] Failed to log action result: {e}")
                                     
                                     action_status = "success" if exec_result["status"] == "success" else "error"
                                     yield {
                                         "status": "action_output",
                                         "action_name": name,
                                         "action_status": action_status,
                                         "output": obs_text[:500],
                                         "chat_id": chat_id
                                     }
                                 except Exception as e:
                                     observations.append(f"Action '{name}' Failed: {str(e)}")


                     # Update System Prompt to "action_formater" mode
                     observations_str = "\n".join(observations)
                     
                     new_sys_prompt = build_system_prompt(
                         user_id=user_id,
                         available_actions=available_actions_list,
                         action_data=observations_str, 
                         bot_config=bot_config,
                         prompt_id="action_formater",
                         user_message=prompt
                     )
                     
                     # Update System Message in History
                     if loop_history and loop_history[0].get('role') == 'system':
                         loop_history[0]['content'] = new_sys_prompt
                         # CRITICAL FIX: Update the variable used by the provider!
                         system_prompt = new_sys_prompt
                     
                     # Set current prompt to trigger summary
                     current_prompt = "Actions executed. Please formulate the response."
                     current_loop = 1
                else:
                     print(f"[DEBUG:Resume] No actions found to resume!", flush=True)
                     current_prompt = prompt # Fallback
            


            full_content_raw = ""
            accumulated_thinking = ""
            
            while current_loop < max_loops:
                if current_loop > 0:
                    yield {"status": "action_loop", "loop": current_loop + 1, "max_loops": max_loops, "chat_id": chat_id}
                
                full_content_raw = ""
                accumulated_thinking = ""
                
                # Use loop_history which has system prompt + context
                # history_override is usually None from api
                active_history = loop_history
                
                # Used for System Prompt + Context logging
                # We log the 'User' side of the raw history here, capturing the full context fed to the model.
                try:
                    from modules.db import save_raw_history
                    
                    # 1. Log System Prompt (Populated)
                    save_raw_history(chat_id, {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "chat_id": chat_id,
                        "model_config": self.provider.model_cfg if hasattr(self.provider, 'model_cfg') else {},
                        "system_prompt": system_prompt, 
                        "history_context": [], # System prompt stands alone? Or is part of context.
                        "response": {
                            "role": "system",
                            "content": system_prompt,
                            "thinking": None
                        },
                        "user_id": user_id
                    })

                    # 2. Log User Prompt
                    save_raw_history(chat_id, {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "chat_id": chat_id,
                        "model_config": self.provider.model_cfg if hasattr(self.provider, 'model_cfg') else {},
                        "system_prompt": system_prompt, 
                        "history_context": loop_history, # Full context at start of turn
                        "response": {
                            "role": "user",
                            "content": prompt if prompt else "Action Loop Continuation",
                            "thinking": None
                        },
                        "user_id": user_id
                    })
                except Exception as log_err:
                     print(f"[Core] User/System History Logging Failed: {log_err}")

                # Provider Generate
                count = 0
                for result in self.provider.generate(current_prompt, use_thinking=use_thinking, stop_event=stop_event or self.stop_event, return_json=return_json, parent_id=chat_id, history_override=active_history, system_prompt=system_prompt):
                    result['chat_id'] = chat_id
                    count += 1
                    
                    if result.get("status") == "thinking":
                        chunk = result.get("chunk", "")
                        if chunk:
                            accumulated_thinking += chunk
                            if db_entry_id: update_history_entry(db_entry_id, thinking=accumulated_thinking + ("\n[Action Processing...]" if current_loop > 0 else ""))
                            yield result
                    
                    elif result.get("status") == "thinking_finished":
                        if result.get("thinking"):
                            accumulated_thinking = result.get("thinking", "")
                        if db_entry_id: update_history_entry(db_entry_id, thinking=accumulated_thinking)
                        yield result

                    else:
                        if result.get("status") == "content" or result.get("status") == "json_content":
                            chunk = result.get("chunk", "")
                            if result.get("status") == "json_content" and "raw" in result:
                                full_content_raw = result["raw"]
                            else:
                                full_content_raw += chunk
                            
                            if db_entry_id: update_history_entry(db_entry_id, content=full_content_raw)
                            yield result
                            yield result
                
                # --- DETECT ACTIONS (PARALLEL) ---
                # --- DETECT ACTIONS (JSON) ---
                from modules.utils import extract_json
                
                found_actions = []
                json_data = extract_json(full_content_raw)
                
                print(f"[DEBUG:Core] AI Response Content: {full_content_raw[:200]}...", flush=True)
                
                if json_data and isinstance(json_data, dict) and "actions" in json_data:
                    raw_actions = json_data["actions"]
                    print(f"[DEBUG:Core] Extracted JSON Actions: {raw_actions}", flush=True)
                    
                    if isinstance(raw_actions, list):
                        for ra in raw_actions:
                            if "name" in ra:
                                # Convert params to dict (handle both Dict and List formats)
                                args = {}
                                if "parameters" in ra:
                                    params = ra["parameters"]
                                    if isinstance(params, dict):
                                        args = params
                                    elif isinstance(params, list):
                                        for p in params:
                                            if "name" in p:
                                                args[p["name"]] = p.get("value", "")
                                
                                found_actions.append({
                                    "name": ra["name"],
                                    "args": args
                                })
                
                if found_actions:
                    if db_entry_id: update_history_entry(db_entry_id, thinking=accumulated_thinking + f"\n[Executing {len(found_actions)} Action(s)...]")
                    
                    # Notify UI about specific actions
                    yield {
                        "status": "action_detected",
                        "actions": [a['name'] for a in found_actions],
                        "chat_id": chat_id
                    }

                    yield {"status": "content", "chunk": f"\n\n[System] Executing {len(found_actions)} actions...\n", "chat_id": chat_id}
                    
                    # CHECK PERMISSIONS
                    from modules.permissions import check_permission, init_permissions_db
                    init_permissions_db()
                    
                    
                    # CHECK PERMISSIONS
                    from modules.permissions import check_permission, init_permissions_db
                    init_permissions_db()
                    
                    # DB functions are already imported globally

                    
                    paused = False
                    for act in found_actions:
                        action_name = act["name"]
                        if not check_permission(str(user_id), action_name, chat_id=chat_id):
                            yield {
                                "status": "permission_required",
                                "action_name": action_name,
                                "action_args": act["args"],
                                "chat_id": chat_id
                            }
                            paused = True
                            print(f"[DEBUG:Core] Permission required for {action_name}", flush=True)
                            break # Only one permission request at a time
                    
                    if paused:
                        # Force update the chat_item with the full content we have so far
                        if db_entry_id:
                            print(f"[DEBUG:Core] Perm Pause: Updating DB Entry {db_entry_id} with {len(full_content_raw)} chars", flush=True)
                            update_history_entry(db_entry_id, content=full_content_raw)
                        
                        # Ensure we save the history before exiting, so Resume can find the action request!
                        # The incremental update_history_entry handles the chat display, but let's be safe.
                        print(f"[DEBUG:Core] Pausing for Permission. Saving history...", flush=True)
                        try:
                            # save_raw_history is imported globally now
                            save_raw_history(chat_id, {
                                "timestamp": datetime.datetime.now().isoformat(),
                                "chat_id": chat_id,
                                "model_config": self.provider.model_cfg if hasattr(self.provider, 'model_cfg') else {},
                                "system_prompt": system_prompt, 
                                "history_context": active_history,
                                "response": {
                                    "role": "assistant",
                                    "content": full_content_raw,
                                    "thinking": accumulated_thinking
                                },
                                "user_id": user_id
                            })
                        except Exception as log_err:
                            print(f"[Core] History Logging Failed (Permission Pause): {log_err}")

                        return # Stop generator

                    # PARALLEL EXECUTION
                    futures = []
                    future_map = {}
                    pending = []
                    progress_q = queue.Queue()
                    
                    def make_cb(name):
                        return lambda d: progress_q.put({"name": name, "data": d})
                    
                    for act in found_actions:
                        action_name = act["name"]
                        action_args = act["args"]
                        try:
                            print(f"[DEBUG:Core] Executing Action: {action_name} Args: {action_args}", flush=True)
                            action_def = self.action_registry.get_action(action_name)
                            if action_def:
                                # Generate and Track Execution ID
                                execution_id = str(uuid.uuid4())
                                with self.active_action_ids_lock:
                                    self.active_action_ids[chat_id] = execution_id
                                
                                ctx = {"user_id": user_id, "chat_id": chat_id, "execution_id": execution_id}
                                
                                f = self.thread_pool.submit(self.action_executor.execute, action_def, action_args, ctx, make_cb(action_name))
                                future_map[f] = action_name
                                pending.append(f)
                            else:
                                print(f"[DEBUG:Core] Action {action_name} not found in registry", flush=True)
                        except Exception as e:
                            print(f"[DEBUG:Core] Error preparing action {action_name}: {e}", flush=True)

                    # Streaming Wait Loop (Main)
                    while pending or not progress_q.empty():
                         # 1. Drain Queue (Non-blocking)
                         while not progress_q.empty():
                             try:
                                 msg = progress_q.get_nowait()
                                 status_msg = ""
                                 # Parse known progress fields
                                 if "scanned" in msg["data"]:
                                     status_msg = f"Scanned {msg['data']['scanned']} items..."
                                 elif "message" in msg["data"]:
                                     status_msg = msg["data"]["message"]
                                 
                                 if status_msg:
                                    # Yield progress chunk directly to chat stream
                                    yield {"status": "content", "chunk": f"[{msg['name']} Progress]: {status_msg}\n", "chat_id": chat_id}
                                 
                                 # Handle Action Update (Match Found)
                                 if "status" in msg["data"] and msg["data"]["status"] == "match":
                                     yield {
                                         "status": "action_update",
                                         "type": "match",
                                         "data": msg["data"],
                                         "chat_id": chat_id
                                     }
                             except:
                                 break
                         
                         if not pending:
                             break
                             
                         # 2. Wait for Futures
                         done, not_done = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                         
                         for future in done:
                             pending.remove(future)
                             if future in future_map:
                                 name = future_map[future]
                                 
                                 # Cleanup Execution ID
                                 with self.active_action_ids_lock:
                                     if self.active_action_ids.get(chat_id):
                                         del self.active_action_ids[chat_id]

                                 try:
                                     exec_result = future.result()
                                     
                                     # Smart Output Unwrap
                                     output_val = exec_result.get("output", {})
                                     if exec_result["status"] == "success":
                                         if isinstance(output_val, str):
                                             obs = output_val
                                         elif isinstance(output_val, dict) and len(output_val) == 1 and "output" in output_val and isinstance(output_val["output"], str):
                                             obs = output_val["output"]
                                         else:
                                             obs = json.dumps(output_val)
                                     else:
                                         obs = f"Error: {exec_result.get('error')}"
                                         # Check for partial output
                                         if "partial_output" in exec_result:
                                              obs += f"\n[Partial Output]: {exec_result['partial_output']}"
                                     
                                     # [DEBUG:Action]
                                     print(f"[DEBUG:Action] Action '{name}' returned: {obs}", flush=True)
      
                                     observations.append(f"Action '{name}' Result: {obs}")
                                     
                                     # Log to Database for History/Web UI
                                     try:
                                         # save_chat_item is imported globally
                                         save_chat_item(chat_id, "system", f"[Action Output: {name}] {obs}")
                                     except Exception as e:
                                         print(f"[DEBUG:Core] Failed to log action result: {e}")
                                     
                                     action_status = "success" if exec_result["status"] == "success" else "error"
                                     yield {
                                          "status": "action_output",
                                          "action_name": name,
                                          "action_status": action_status,
                                          "output": obs[:500],
                                          "chat_id": chat_id
                                     }
                                 except Exception as e:
                                     observations.append(f"Action '{name}' Failed: {str(e)}")




                    # Prepare Action Data for System Prompt
                    observations_str = "\n".join(observations)
                    
                    # Switch to "action_formater" System Prompt
                    new_sys_prompt = build_system_prompt(
                         user_id=user_id,
                         available_actions=available_actions_list,
                         action_data=observations_str, 
                         bot_config=bot_config,
                         prompt_id="action_formater",
                         user_message=prompt
                    )
                     
                    # Update System Message in History Loop
                    if loop_history and loop_history[0].get('role') == 'system':
                         loop_history[0]['content'] = new_sys_prompt

                    # Commit the previous turn to history
                    if current_loop == 0:
                        loop_history.append({"role": "user", "content": prompt or "Action Request"}) 
                    loop_history.append({"role": "assistant", "content": full_content_raw})
                    
                    # Set trigger for next generation
                    current_prompt = "Actions executed. Please formulate the response."
                        
                    current_loop += 1
                    continue
                else:
                    break # No valid actions 
                
                # NO ACTIONS FOUND - Final Response Analysis
                # If we are expecting JSON, and we have a full buffer, let's try to parse it.
                if return_json and (current_loop == max_loops or not found_actions):
                    from modules.utils import extract_json
                    parsed = extract_json(full_content_raw)
                    
                    if parsed:
                        yield {
                             "status": "json_content",
                             "message": parsed.get("message", full_content_raw),
                             "json": parsed,
                             "chat_id": chat_id,
                             "reason": parsed.get("reason", "") # Optional reason field
                        }
                    else:
                        # FALLBACK: If we couldn't parse JSON, treat the whole thing as the message
                        # This prevents the UI from hanging on "Building..."
                        yield {
                             "status": "json_content",
                             "message": full_content_raw,
                             "json": {},
                             "chat_id": chat_id
                        }
                    # If parsing fails, we falls through (raw content was already yielded)
                
                # --- RAW HISTORY LOGGING (DB) ---
                # --- RAW HISTORY LOGGING (ASSISTANT DB) ---
                print(f"[DEBUG:Core] About to save raw history for chat {chat_id}", flush=True)
                try:
                    from modules.db import save_raw_history
                    save_raw_history(chat_id, {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "chat_id": chat_id,
                        "model_config": self.provider.model_cfg if hasattr(self.provider, 'model_cfg') else {},
                        "system_prompt": system_prompt, 
                        "history_context": active_history,
                        "response": {
                            "role": "assistant",
                            "content": full_content_raw,
                            "thinking": accumulated_thinking
                        },
                        "user_id": user_id
                    })
                except Exception as log_err:
                    print(f"[Core] History Logging Failed: {log_err}")

                break # No matches
                
        except Exception as e:
            print(f"Error in ask_stream: {e}")
            yield {"status": "error", "error": str(e), "chat_id": chat_id}
        finally:
             p.nice(original_priority)

    def _yield_from_queue(self, q):
        while True:
            res = q.get()
            if res is None:
                break
            if isinstance(res, Exception):
                raise res
            yield res

    def shutdown(self):
        self.stop_event.set()
        self.request_queue.put(None)

    def get_history(self, parent_id, chat_id=None):
        return load_history_entries(parent_id, chat_id=chat_id)

    def clear_history(self, parent_id=None):
        # ... existing implementation ...
        pass
        clear_history_entries(parent_id)
        self.provider.clear_history(parent_id=parent_id)

    def get_history(self, chat_id=None):
        if chat_id:
            raw = load_chat_items(chat_id)
            return [{
                "role": m["role"], 
                "content": clean_content(m["content"]), 
                "thinking": m.get("thinking", ""),
                "timestamp": m.get("timestamp")
            } for m in raw if m["role"] != "system"]
        return []


    def ask(self, prompt, use_thinking=True, priority="normal", return_json=False, prompt_id="general_chat", chat_id=None):
        final_thinking = ""
        final_content = ""
        # Create ephemeral chat ID for single-shot asks if not provided
        if not chat_id:
            chat_id = f"ask_{uuid.uuid4().hex[:8]}"
            
        for chunk in self.ask_stream(prompt, use_thinking=use_thinking, priority=priority, return_json=return_json, prompt_id=prompt_id, chat_id=chat_id):
            if chunk["status"] == "thinking_finished":
                final_thinking = chunk["thinking"]
            elif chunk["status"] == "json_content":
                final_content = chunk.get("message", "")
            elif chunk["status"] == "content":
                final_content += chunk.get("chunk", "")
        return {"thinking": final_thinking, "content": final_content}
