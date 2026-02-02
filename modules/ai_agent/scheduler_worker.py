
import threading
import queue
import datetime
import psutil
import os
import re
import json
import uuid
from concurrent.futures import as_completed

# Imports from other modules
from modules.config import get_active_model_settings
from modules.db import save_chat_item, load_chat_items, update_history_entry, get_chat_owner, save_raw_history, update_chat_title
from modules.actions.registry import ActionRegistry
from modules.actions.executor import ActionExecutor
from modules.bot_config import get_bot_config
from modules.prompt_builder import format_history_for_prompt, build_system_prompt
from modules.permissions import check_permission, init_permissions_db
from modules.utils import extract_json

from .utils import GetTokenLength, clean_content, shrink_history

def run_worker_loop(agent):
    """
    Worker loop that processes requests from the agent's queue.
    replaces AIAgent._main_processor
    """
    while not agent.stop_event.is_set():
        try:
            # Get pending request
            # priority is determined by insertion order in priority queue if we used PriorityQueue
            # but currently it's a simple queue.Queue or PriorityQueue.
            # Assuming agent.request_queue contains tuples or objects.
            
            item = agent.request_queue.get(timeout=1.0)
            if item is None:
                break
                
            prompt, priority, return_json, prompt_id, chat_id, resume_action, system_prompt, history_override = item
            
            user_id = get_chat_owner(chat_id)
            
            # --- PRIORITY ADJUSTMENT ---
            p = psutil.Process(os.getpid())
            original_priority = p.nice()
            try:
                if os.name == 'nt':
                    p.nice(agent.priority_map.get(priority.lower(), psutil.NORMAL_PRIORITY_CLASS))
                else:
                     p.nice(agent.priority_map.get(priority.lower(), 0))
            except:
                pass

            # ENTRY SAVING LOGIC (Background)
            db_entry_id = None
            try:
                db_entry_id = save_chat_item(chat_id, "assistant", "", thinking="")
                if prompt and not resume_action:
                     save_chat_item(chat_id, "user", prompt)
            except Exception as e:
                print(f"[Error:History] Worker failed to save chat items for {chat_id}: {e}")

            try:
                # --- ACTION LOOP START ---
                max_loops = 5
                current_loop = 0
                
                # History Setup
                if history_override:
                    loop_history = history_override.copy()
                else:
                    loop_history = load_chat_items(chat_id)
                
                # Helper Import for Bot Config
                bot_config = get_bot_config(str(user_id)) if user_id else {"name": "Genesis AI", "personality": ""}
                
                # System Prompt Setup is handled inside loop or via `ask_stream` logic usually.
                # Assuming `system_prompt` is passed in.
                if not system_prompt:
                     from modules.config import load_prompts
                     prompts = load_prompts()
                     system_prompt = prompts.get(prompt_id, "")

                # Inject variables
                system_prompt_for_build = system_prompt # Copy
                system_prompt_for_build = system_prompt_for_build.replace("[bot_name]", bot_config.get("name", "Genesis AI"))
                system_prompt_for_build = system_prompt_for_build.replace("[bot_personality]", bot_config.get("personality", ""))
                
                loop_history = format_history_for_prompt(loop_history, system_prompt_for_build)

                # RESUME LOGIC
                if resume_action:
                    last_msg = ""
                    for m in reversed(loop_history):
                            if m['role'] == 'assistant':
                                last_msg = m['content']
                                break
                    
                    pattern = r'\[ACTION:\s*([a-zA-Z0-9_]+)\s*,\s*({.*?})\]'
                    match = re.search(pattern, last_msg, re.DOTALL)
                    if match:
                            action_name = match.group(1)
                            action_args_str = match.group(2)
                            try:
                                action_args = json.loads(action_args_str)
                                agent._broadcast(chat_id, {"status": "content", "chunk": "\n\n[System] Resuming Action: " + action_name + "...\n", "chat_id": chat_id})
                                update_history_entry(db_entry_id, thinking=f"[Resuming Action {action_name}...]")
                                
                                action_def = agent.action_registry.get_action(action_name)
                                if action_def:
                                    ctx = {"user_id": user_id, "chat_id": chat_id}
                                    exec_result = agent.action_executor.execute(action_def, action_args, ctx)
                                    observation = json.dumps(exec_result.get("output", {})) if exec_result["status"] == "success" else f"Error: {exec_result.get('error')}"
                                    
                                    action_status = "success" if exec_result["status"] == "success" else "error"
                                    agent._broadcast(chat_id, {
                                        "status": "action_output",
                                        "action_name": action_name,
                                        "action_status": action_status,
                                        "output": observation[:500],
                                        "truncated": len(observation) > 500,
                                        "chat_id": chat_id
                                    })
                                else:
                                    observation = f"Error: Action '{action_name}' not found."
                                
                                current_prompt = f"Observation: {observation}"
                                current_loop = 1
                            except:
                                pass
                
                current_prompt = prompt if not resume_action else current_prompt
                full_content_raw = ""
                final_content = ""
                accumulated_thinking = ""
                
                while current_loop < max_loops:
                    if current_loop > 0:
                        agent._broadcast(chat_id, {
                            "status": "action_loop",
                            "loop": current_loop + 1,
                            "max_loops": max_loops,
                            "chat_id": chat_id
                        })
                    
                    full_content_raw = ""
                    accumulated_thinking = ""
                    active_history = loop_history if current_loop > 0 else history_override
                    
                    # GENERATE
                    for result in agent.provider.generate(current_prompt, use_thinking=True, stop_event=agent.stop_event, return_json=return_json, parent_id=chat_id, history_override=active_history):
                        result['chat_id'] = chat_id
                        
                        if result.get("status") == "thinking":
                            chunk = result.get("chunk", "")
                            if chunk:
                                accumulated_thinking += chunk
                                update_history_entry(db_entry_id, thinking=accumulated_thinking + ("\n[Action Processing...]" if current_loop > 0 else ""))
                                agent._broadcast(chat_id, result)
                        
                        elif result.get("status") == "thinking_finished":
                            if result.get("thinking"):
                                accumulated_thinking = result.get("thinking", "")
                            update_history_entry(db_entry_id, thinking=accumulated_thinking)
                            agent._broadcast(chat_id, result)

                        else:
                            if result.get("status") == "content" or result.get("status") == "json_content":
                                chunk = result.get("chunk", "")
                                if result.get("status") == "json_content" and "raw" in result:
                                    full_content_raw = result["raw"]
                                else:
                                    full_content_raw += chunk
                                
                                update_history_entry(db_entry_id, content=full_content_raw)
                                agent._broadcast(chat_id, result)
                    
                    # ACTION DETECTION
                    found_actions = []
                    json_data = extract_json(full_content_raw)
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
                                    found_actions.append({"name": ra["name"], "args": args})
                    
                    if found_actions:
                         # Check Permissions
                         init_permissions_db()
                         paused = False
                         for act in found_actions:
                             if not check_permission(str(user_id), act["name"], chat_id=chat_id):
                                 agent._broadcast(chat_id, {
                                     "status": "permission_required",
                                     "action_name": act["name"],
                                     "action_args": act["args"],
                                     "chat_id": chat_id
                                 })
                                 paused = True
                                 break
                         
                         if paused:
                             # Save state and break
                             if db_entry_id: update_history_entry(db_entry_id, content=full_content_raw)
                             
                             # Fix variable shadowing here too!
                             try:
                                save_raw_history(chat_id, {
                                    "timestamp": datetime.datetime.now().isoformat(),
                                    "chat_id": chat_id,
                                    "model_config": {}, # Simplified for worker
                                    "system_prompt": system_prompt_for_build,
                                    "history_context": active_history,
                                    "response": {"role": "assistant", "content": full_content_raw, "thinking": accumulated_thinking},
                                    "user_id": user_id
                                })
                             except Exception as e:
                                 print(f"[Worker] Failed to save raw history on pause: {e}")
                             return

                         # Execute Actions
                         agent._broadcast(chat_id, {"status": "content", "chunk": "\n\n", "chat_id": chat_id})
                         update_history_entry(db_entry_id, thinking=accumulated_thinking + f"\n[Processing {len(found_actions)} Actions...]")
                         
                         observations = []
                         for act in found_actions:
                             action_name = act["name"]
                             agent._broadcast(chat_id, {"status": "content", "chunk": f"[Executing {action_name}...]\n", "chat_id": chat_id})
                             
                             action_def = agent.action_registry.get_action(action_name)
                             if action_def:
                                 ctx = {"user_id": user_id, "chat_id": chat_id}
                                 exec_result = agent.action_executor.execute(action_def, act["args"], ctx)
                                 out_str = json.dumps(exec_result.get("output", {})) if exec_result["status"] == "success" else f"Error: {exec_result.get('error')}"
                                 
                                 # [DEBUG:Action]
                                 print(f"[DEBUG:Action] Action '{action_name}' returned: {out_str}", flush=True)
                                 
                                 observations.append(f"Action '{action_name}' Output: {out_str}")
                                 
                                 status = "success" if exec_result["status"] == "success" else "error"
                                 agent._broadcast(chat_id, {
                                     "status": "action_output",
                                     "action_name": action_name,
                                     "action_status": status,
                                     "output": out_str[:500],
                                     "truncated": len(out_str)>500,
                                     "chat_id": chat_id
                                 })
                             else:
                                 observations.append(f"Error: Action '{action_name}' not found.")
                         
                         # Prepare Next Loop
                         if current_loop == 0:
                             loop_history.append({"role": "user", "content": current_prompt})
                         loop_history.append({"role": "assistant", "content": full_content_raw})
                         
                         current_prompt = "Observations:\n" + "\n".join(observations)
                         current_loop += 1
                         full_content_raw = ""
                         continue

                    # Final Content (No actions)
                    final_content = full_content_raw
                    final_thinking = accumulated_thinking
                    break
                
                # FINAL SAVE
                if return_json:
                    json_data = extract_json(final_content)
                    final_res = {
                        "status": "json_content",
                        "chat_id": chat_id,
                        "raw": final_content
                    }
                    if json_data and isinstance(json_data, dict):
                         final_res["message"] = json_data.get("message", final_content)
                         final_res["json"] = json_data
                         if "chat_title" in json_data:
                             update_chat_title(chat_id, json_data["chat_title"])
                    else:
                         final_res["message"] = final_content.replace("<|im_end|>", "")
                    
                    agent._broadcast(chat_id, final_res)
                    update_history_entry(db_entry_id, content=final_res["message"])
                else:
                    update_history_entry(db_entry_id, content=final_content)

            except Exception as e:
                agent._broadcast(chat_id, {"status": "error", "error": str(e)})
            finally:
                p.nice(original_priority)
                agent._broadcast(chat_id, None)
                with agent.active_tasks_lock:
                    if chat_id in agent.active_tasks:
                        del agent.active_tasks[chat_id]
                agent.request_queue.task_done()
                
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[Error] Processor error: {str(e)}")
