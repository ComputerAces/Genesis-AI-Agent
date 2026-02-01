from .providers.qwen_provider import QwenProvider
import threading
import queue
import datetime
import psutil
import os
import re
import uuid
import json
from modules.config import get_active_model_settings
from modules.db import save_chat_item, load_chat_items, update_history_entry, get_chat_owner
from modules.actions.registry import ActionRegistry
from modules.actions.executor import ActionExecutor

def GetTokenLength(text):
    if not text:
        return 0
    # Heuristic: count words + symbols
    words = text.split()
    symbols = re.findall(r'[^a-zA-Z0-9\s]', text)
    return len(words) + len(symbols)

def clean_content(content):
    """
    If content is a JSON string from our system, extract only the message.
    Otherwise return as is.
    """
    if not content:
        return ""
    if content.strip().startswith('{') and content.strip().endswith('}'):
        try:
            from modules.utils import extract_json
            data = extract_json(content)
            if data and isinstance(data, dict):
                return data.get("message", content)
        except:
            pass
    return content

def shrink_history(history, max_tokens):
    """
    Trims history using Semantic Trimming strategy:
    1. Always keep System Prompt (index 0 if system).
    2. Always keep last 4 messages (immediate context).
    3. Prune older 'assistant' thoughts or large blocks, prioritizing 'user' intents.
    """
    if not history:
        return []
        
    # Always preserve system prompt if present
    start_idx = 0
    preserved = []
    if history and history[0].get('role') == 'system':
        preserved.append(history[0])
        start_idx = 1
    
    # Analyze remaining
    remaining = history[start_idx:]
    if not remaining:
        return preserved
        
    # If total length is fine, return as is
    total_tokens = sum(GetTokenLength(m['content']) for m in remaining) + sum(GetTokenLength(m['content']) for m in preserved)
    if total_tokens <= max_tokens:
        return preserved + remaining

    # Strategy: Keep last N (e.g. 4) intact
    KEEP_LAST_N = 4
    if len(remaining) <= KEEP_LAST_N:
         # Can't trim much if we only have few messages
         return preserved + remaining

    recent = remaining[-KEEP_LAST_N:]
    older = remaining[:-KEEP_LAST_N]
    
    # Filter older messages
    # Prioritize keeping USER messages, drop ASSISTANT thoughts/verbose replies
    filtered_older = []
    
    # Budget for older: max - preserved - recent
    current_usage = sum(GetTokenLength(m['content']) for m in preserved) + sum(GetTokenLength(m['content']) for m in recent)
    budget = max_tokens - current_usage
    
    if budget <= 0:
        # We are already over budget with just recent + system.
        # Just return system + recent (soft fail on budget to keep context)
        return preserved + recent
        
    # Greedy fill from NEWEST of "older" to OLDEST
    for msg in reversed(older):
        l = GetTokenLength(msg['content'])
        
        # Heuristic: If it's a huge assistant message (likely code or thought), skip it or truncate
        # For now, we skip if > 500 tokens and it's assistant
        if msg['role'] == 'assistant' and l > 500:
             continue
             
        if l <= budget:
            filtered_older.insert(0, msg)
            budget -= l
        else:
            # If it's a user message, we really want it. Maybe truncate?
            pass
            
    return preserved + filtered_older + recent

class AIAgent:
    def __init__(self, **kwargs):
        self.model_cfg = get_active_model_settings()
        if not self.model_cfg:
            raise ValueError("No active model found in settings.")
            
        provider_type = self.model_cfg.get("type", "qwen")
        model_name = self.model_cfg.get("name")
        
        if provider_type == "qwen":
            self.provider = QwenProvider(model_name=model_name, model_cfg=self.model_cfg, **kwargs)
        else:
            raise ValueError(f"Unsupported provider: {provider_type}")
        
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
        
        self.processor_thread = threading.Thread(target=self._main_processor, daemon=True)
        self.processor_thread.start()

    def _broadcast(self, chat_id, data):
        with self.active_tasks_lock:
            if chat_id in self.active_tasks:
                for q in self.active_tasks[chat_id]:
                    try:
                        q.put(data)
                    except:
                        pass

    def _main_processor(self):
        while not self.stop_event.is_set():
            try:
                request = self.request_queue.get(timeout=1)
                if request is None:
                    break
                
                prompt = request['prompt']
                history_override = request.get('history_override')
                use_thinking = request['use_thinking']
                priority = request['priority']
                return_json = request['return_json']
                chat_id = request.get('chat_id', 'unknown')
                system_prompt = request.get('system_prompt', '') # Added for new ask_stream
                resume_action = request.get('resume_action', False) # Added for new ask_stream
                
                # The original _main_processor logic is now largely moved into ask_stream
                # This queue processing part needs to be adapted or removed if ask_stream is direct.
                # For now, I'll assume the new ask_stream will be called directly and this _main_processor
                # might become obsolete or handle different types of requests.
                # Given the instruction is to replace ask_stream, I'll keep this as is, but it might not be fully compatible
                # with the new ask_stream's direct processing approach.
                
                # If the new ask_stream is meant to be called directly, then this _main_processor
                # would only be used for requests that still go through the queue.
                # The provided new ask_stream code suggests it will be called directly and yield.
                # So, this _main_processor might need to be refactored or removed if its purpose changes.
                # For now, I'll leave it as is, as the instruction only specified changes to ask_stream and init.
                
                # Log raw user input to history table (Admin Debug Log)
                from modules.db import log_raw_event
                log_raw_event(chat_id, "user_raw", prompt)
                
                # Fetch User ID for Action Security (needed for GENESIS_HOME isolation)
                user_id = get_chat_owner(chat_id)
                if user_id:
                     self.action_registry.scan_plugins(user_id) # Ensure user plugins loaded

                # Build dynamic system prompt with available actions
                from modules.prompt_builder import build_system_prompt, format_history_for_prompt
                from modules.bot_config import get_bot_config
                
                bot_config = get_bot_config(user_id) if user_id else None
                available_actions = list(self.action_registry.get_all_actions().values())
                system_prompt_for_build = build_system_prompt( # Renamed to avoid conflict
                    user_id=user_id or "default",
                    available_actions=available_actions,
                    action_data="",  # TODO: pre_request plugin output goes here
                    bot_config=bot_config
                )

                # Auto-generate chat title if still "New Chat" or "New Conversation"
                from modules.db import get_chat_title, update_chat_title, save_system_prompt
                current_title = get_chat_title(chat_id)
                if current_title and current_title.lower() in ("new chat", "new conversation"):
                    # Generate title from first 50 chars of user message
                    title_text = prompt[:50].strip()
                    if len(prompt) > 50:
                        title_text += "..."
                    update_chat_title(chat_id, title_text)

                # Save the populated system prompt to history (first message only)
                # Check if we already have a system entry
                existing_items = load_chat_items(chat_id)
                has_system = any(item.get('role') == 'system' for item in existing_items)
                if not has_system:
                    save_system_prompt(chat_id, system_prompt_for_build) # Use the built system prompt

                p = psutil.Process(os.getpid())
                original_priority = p.nice()
                
                # PRE-CREATE ASSISTANT ENTRY for live updates
                db_entry_id = save_chat_item(chat_id, "assistant", "", thinking="")
                
                try:
                    if os.name == 'nt':
                         p.nice(self.priority_map.get(priority.lower(), psutil.NORMAL_PRIORITY_CLASS))
                    else:
                         p.nice(self.priority_map.get(priority.lower(), 0))
                    
                    # --- ACTION LOOP START ---
                    max_loops = 5
                    current_loop = 0
                    
                    # We need to maintain a running history context for the loop
                    # If history_override provided, use it. Else fetch from DB.
                    if history_override:
                        loop_history = history_override.copy()
                    else:
                        loop_history = load_chat_items(chat_id)
                    
                    # FIX: Inject system prompt variables BEFORE formatting history
                    # This ensures the history/prompt sent to the model (and saved) has [bot_name] populated
                    from modules.bot_config import get_bot_config
                    bot_config = get_bot_config(str(user_id)) if user_id else {"name": "Genesis AI", "personality": ""}
                    
                    system_prompt_for_build = system_prompt_for_build.replace("[bot_name]", bot_config.get("name", "Genesis AI"))
                    system_prompt_for_build = system_prompt_for_build.replace("[bot_personality]", bot_config.get("personality", ""))
                    
                    # Inject system prompt at the beginning of history
                    loop_history = format_history_for_prompt(loop_history, system_prompt_for_build)

                    # RESUME LOGIC
                    # If resuming, we need to find the pending action from the LAST assistant message
                    # and execute it immediately, treating it as "approved".
                    if resume_action:
                        # Scan history for the last action request
                        # This is a simplification; we assume the last message contains the action to resume.
                        last_msg = ""
                        # Locate last assistant message in loop_history
                        for m in reversed(loop_history):
                             if m['role'] == 'assistant':
                                 last_msg = m['content']
                                 break
                        
                        pattern = r'\[ACTION:\s*([a-zA-Z0-9_]+)\s*,\s*({.*?})\]'
                        import re
                        match = re.search(pattern, last_msg, re.DOTALL)
                        if match:
                             # Jump straight to Execution
                             action_name = match.group(1)
                             action_args_str = match.group(2)
                             try:
                                 action_args = json.loads(action_args_str)
                                 # Execute immediately
                                 self._broadcast(chat_id, {"status": "content", "chunk": "\n\n[System] Resuming Action: " + action_name + "...\n", "chat_id": chat_id})
                                 update_history_entry(db_entry_id, thinking=f"[Resuming Action {action_name}...]")
                                 
                                 action_def = self.action_registry.get_action(action_name)
                                 if action_def:
                                     ctx = {"user_id": user_id, "chat_id": chat_id}
                                     exec_result = self.action_executor.execute(action_def, action_args, ctx)
                                     observation = json.dumps(exec_result.get("output", {})) if exec_result["status"] == "success" else f"Error: {exec_result.get('error')}"
                                     
                                     action_status = "success" if exec_result["status"] == "success" else "error"
                                     self._broadcast(chat_id, {
                                         "status": "action_output",
                                         "action_name": action_name,
                                         "action_status": action_status,
                                         "output": observation[:500] if len(observation) > 500 else observation,
                                         "truncated": len(observation) > 500,
                                         "chat_id": chat_id
                                     })
                                 else:
                                     observation = f"Error: Action '{action_name}' not found."
                                 
                                 current_prompt = f"Observation: {observation}"
                                 current_loop = 1 # We did one "action", so now we are in loop 1
                                 # loop_history is already set up, we just proceed to generation
                             except:
                                 pass
                    
                    current_prompt = prompt if not resume_action else current_prompt
                    full_content_raw = ""
                    final_content = ""
                    accumulated_thinking = ""
                    
                    while current_loop < max_loops:
                        # Broadcast loop status if we're in a multi-step action loop
                        if current_loop > 0:
                            self._broadcast(chat_id, {
                                "status": "action_loop",
                                "loop": current_loop + 1,
                                "max_loops": max_loops,
                                "chat_id": chat_id
                            })
                        
                        # Reset for this loop
                        full_content_raw = ""
                        accumulated_thinking = ""
                        
                        # Call Provider
                        active_history = loop_history if current_loop > 0 else history_override
                        
                        for result in self.provider.generate(current_prompt, use_thinking=use_thinking, stop_event=self.stop_event, return_json=return_json, parent_id=chat_id, history_override=active_history):
                            result['chat_id'] = chat_id
                            
                            # Thinking Handling
                            if result.get("status") == "thinking":
                                chunk = result.get("chunk", "")
                                if chunk:
                                    accumulated_thinking += chunk
                                    update_history_entry(db_entry_id, thinking=accumulated_thinking + ("\n[Action Processing...]" if current_loop > 0 else ""))
                                    self._broadcast(chat_id, result)
                            
                            elif result.get("status") == "thinking_finished":
                                if result.get("thinking"):
                                    accumulated_thinking = result.get("thinking", "")
                                update_history_entry(db_entry_id, thinking=accumulated_thinking)
                                self._broadcast(chat_id, result)

                            # Content Handling
                            else:
                                if result.get("status") == "content" or result.get("status") == "json_content":
                                    chunk = result.get("chunk", "")
                                    if result.get("status") == "json_content" and "raw" in result:
                                        full_content_raw = result["raw"]
                                    else:
                                        full_content_raw += chunk
                                    
                                    update_history_entry(db_entry_id, content=full_content_raw)
                                    self._broadcast(chat_id, result)

                        # Generation Complete for this Step
                        
                        # --- DETECT ACTION ---
                        # New Logic: Actions are in JSON "actions" array
                        # Schema: [{"name": "act_name", "parameters": [{"name": "p", "value": "v"}]}]
                        
                        found_actions = []
                        json_data = extract_json(full_content_raw)
                        
                        # print(f"[DEBUG:Core] Full Content: {full_content_raw[:100]}...") 
                        # print(f"[DEBUG:Core] Extracted JSON: {json_data.keys() if json_data else 'None'}")

                        if json_data and isinstance(json_data, dict) and "actions" in json_data:
                            raw_actions = json_data["actions"]
                            # print(f"[DEBUG:Core] Raw Actions: {raw_actions}")
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
                                        
                                        print(f"[DEBUG:Core] Found Action: {ra['name']} with Args: {args}")
                                        
                                        found_actions.append({
                                            "name": ra["name"],
                                            "args": args
                                        })
                        
                        if found_actions:
                            observations = []
                            has_permission_block = False
                            
                            # 1. Check Permissions for ALL actions first (Atomic-ish)
                            from modules.permissions import check_permission, init_permissions_db
                            init_permissions_db()
                            
                            for act in found_actions:
                                nm = act["name"]
                                if not check_permission(user_id, nm, chat_id=chat_id):
                                    # Request Permission
                                    self._broadcast(chat_id, {
                                        "status": "permission_required",
                                        "action_name": nm,
                                        "action_args": act["args"],
                                        "chat_id": chat_id
                                    })
                                    return # Stop execution (Wait for user)

                            # 2. Execute Actions
                            self._broadcast(chat_id, {"status": "content", "chunk": "\n\n", "chat_id": chat_id})
                            update_history_entry(db_entry_id, thinking=accumulated_thinking + f"\n[Processing {len(found_actions)} Actions...]")

                            for act in found_actions:
                                action_name = act["name"]
                                action_args = act["args"]
                                
                                self._broadcast(chat_id, {"status": "content", "chunk": f"[Executing {action_name}...]\n", "chat_id": chat_id})
                                
                                action_def = self.action_registry.get_action(action_name)
                                if action_def:
                                    ctx = {"user_id": user_id, "chat_id": chat_id}
                                    exec_result = self.action_executor.execute(action_def, action_args, ctx)
                                    
                                    out_str = json.dumps(exec_result.get("output", {})) if exec_result["status"] == "success" else f"Error: {exec_result.get('error')}"
                                    observations.append(f"Action '{action_name}' Output: {out_str}")

                                    # Broadcast output
                                    action_status = "success" if exec_result["status"] == "success" else "error"
                                    self._broadcast(chat_id, {
                                        "status": "action_output",
                                        "action_name": action_name,
                                        "action_status": action_status,
                                        "output": out_str[:500] if len(out_str) > 500 else out_str,
                                        "truncated": len(out_str) > 500,
                                        "chat_id": chat_id
                                    })
                                else:
                                    observations.append(f"Error: Action '{action_name}' not found.")
                            
                            # 3. Prepare Next Loop
                            if current_loop == 0:
                                loop_history.append({"role": "user", "content": current_prompt})
                            
                            loop_history.append({"role": "assistant", "content": full_content_raw})
                            
                            # Combine observations
                            current_prompt = "Observations:\n" + "\n".join(observations)
                            
                            current_loop += 1
                            full_content_raw = "" 
                            continue # NEXT LOOP
                        
                        # If No Action -> Break Loop (Final Answer)
                        final_content = full_content_raw
                        final_thinking = accumulated_thinking
                        break 
                    
                    # --- LOOP END ---

                    # Final Save Logic (Same as before)
                    if return_json:
                        json_data = extract_json(final_content)
                        final_res = {
                            "status": "json_content",
                            "chat_id": chat_id,
                            "raw": final_content
                        }
                        if json_data and isinstance(json_data, dict):
                            final_res["message"] = json_data.get("message", final_content)
                            final_res["reason"] = json_data.get("reason", "N/A")
                            final_res["json"] = json_data
                            
                            if "chat_title" in json_data:
                                from modules.db import update_chat_title
                                if chat_id:
                                    update_chat_title(chat_id, json_data["chat_title"])
                        else:
                            final_res["message"] = final_content.replace("<|im_end|>", "")
                            final_res["reason"] = "Failed to parse JSON"
                        
                        self._broadcast(chat_id, final_res)
                        update_history_entry(db_entry_id, content=final_res["message"])
                        log_raw_event(chat_id, "assistant_raw", final_content, thinking=final_thinking)
                    else:
                        update_history_entry(db_entry_id, content=final_content)
                        log_raw_event(chat_id, "assistant_raw", final_content, thinking=final_thinking)

                except Exception as e:
                    self._broadcast(chat_id, e)
                finally:
                    p.nice(original_priority)
                    self._broadcast(chat_id, None)
                    with self.active_tasks_lock:
                        if chat_id in self.active_tasks:
                            del self.active_tasks[chat_id]
                    self.request_queue.task_done()
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Error] Processor error: {str(e)}")

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


        user_id = get_chat_owner(chat_id)
        
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
        # We save if chat_id is not ephemeral.
        # We don't strictly require user_id to be found (failed lookup shouldn't block logging if chat exists)
        is_ephemeral = chat_id.startswith("ephemeral_")
        db_entry_id = None
        
        if not is_ephemeral:
            try:
                # print(f"[DEBUG:History] Attempting to save assistant entry for chat {chat_id}")
                db_entry_id = save_chat_item(chat_id, "assistant", "", thinking="")
                # print(f"[DEBUG:History] Created assistant entry: {db_entry_id}")
                if prompt and not resume_action:
                     # print(f"[DEBUG:History] Attempting to save user entry for chat {chat_id}")
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
            
            # RESUME LOGIC

            # RESUME LOGIC
            if resume_action:
                # Scan history for the last action request
                last_msg = ""
                for m in reversed(loop_history):
                     if m['role'] == 'assistant':
                         last_msg = m['content']
                         break
                
                pattern = r'\[ACTION:\s*([a-zA-Z0-9_]+)\s*,\s*({.*?})\]'
                matches = list(re.finditer(pattern, last_msg, re.DOTALL))
                
                if matches:
                     if db_entry_id: update_history_entry(db_entry_id, thinking=f"[Resuming Actions...]")
                     yield {"status": "content", "chunk": "\n\n[System] Resuming Actions...\n", "chat_id": chat_id}
                     
                     futures = []
                     future_map = {}
                     
                     for match in matches:
                         action_name = match.group(1)
                         try:
                             action_args = json.loads(match.group(2))
                             action_def = self.action_registry.get_action(action_name)
                             
                             if action_def:
                                 ctx = {"user_id": user_id, "chat_id": chat_id}
                                 f = self.thread_pool.submit(self.action_executor.execute, action_def, action_args, ctx)
                                 future_map[f] = action_name
                                 yield {"status": "content", "chunk": f"[Executing {action_name}...]\n", "chat_id": chat_id}
                         except:
                             pass

                     # Wait for results
                     from concurrent.futures import as_completed
                     observations = []
                     
                     if future_map:
                         for future in as_completed(future_map):
                             name = future_map[future]
                             try:
                                 exec_result = future.result()
                                 obs_text = json.dumps(exec_result.get("output", {})) if exec_result["status"] == "success" else f"Error: {exec_result.get('error')}"
                                 observations.append(f"Action '{name}' Result: {obs_text}")
                                 
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
                         
                         # Set current prompt to trigger summary
                         current_prompt = "Actions executed. Please formulate the response."
                         current_loop = 1
                     else:
                         current_prompt = "Observation: No actions found to resume."
            
            else:
                current_prompt = prompt

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
                matches = list(re.finditer(r'\[ACTION:\s*([a-zA-Z0-9_]+)\s*,\s*({.*?})\]', full_content_raw, re.DOTALL))
                
                if matches:
                    if db_entry_id: update_history_entry(db_entry_id, thinking=accumulated_thinking + f"\n[Executing {len(matches)} Action(s)...]")
                    yield {"status": "content", "chunk": f"\n\n[System] Executing {len(matches)} actions...\n", "chat_id": chat_id}
                    
                    # CHECK PERMISSIONS
                    from modules.permissions import check_permission, init_permissions_db
                    init_permissions_db()
                    
                    paused = False
                    for match in matches:
                        action_name = match.group(1)
                        if not check_permission(str(user_id), action_name, chat_id=chat_id):
                            try:
                                args = json.loads(match.group(2))
                            except:
                                args = {}
                            yield {
                                "status": "permission_required",
                                "action_name": action_name,
                                "action_args": args,
                                "chat_id": chat_id
                            }
                            paused = True
                            print(f"[DEBUG] Permission required for {action_name}")
                            break # Only one permission request at a time for UI simplicity
                    
                    if paused:
                        return # Stop generator

                    # PARALLEL EXECUTION
                    future_map = {}
                    for match in matches:
                        action_name = match.group(1)
                        try:
                            action_args = json.loads(match.group(2))
                            action_def = self.action_registry.get_action(action_name)
                            if action_def:
                                ctx = {"user_id": user_id, "chat_id": chat_id}
                                f = self.thread_pool.submit(self.action_executor.execute, action_def, action_args, ctx)
                                future_map[f] = action_name
                        except:
                            pass
                    
                    observations = []
                    if future_map:
                        for future in as_completed(future_map):
                           name = future_map[future]
                           try:
                               exec_result = future.result()
                               obs = json.dumps(exec_result.get("output", {})) if exec_result["status"] == "success" else f"Error: {exec_result.get('error')}"
                               observations.append(f"Action '{name}' Result: {obs}")
                               
                               status = "success" if exec_result["status"] == "success" else "error"
                               yield {
                                    "status": "action_output",
                                    "action_name": name,
                                    "action_status": status,
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
                if return_json and (current_loop == max_loops or not matches):
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
