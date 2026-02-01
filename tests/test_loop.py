import sys
import os
import time
import threading
import queue

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.ai_agent.core import AIAgent
from mock_provider import MockProvider

# Monkey patch QwenProvider to use MockProvider
import modules.ai_agent.core
modules.ai_agent.core.QwenProvider = MockProvider

def test_loop():
    print("[TEST] Initializing Agent with MockProvider...")
    agent = AIAgent()
    
    # We need to simulate the DB environment or mock DB calls?
    # core.py imports db functions. They work against sqlite.
    # We assume 'init_db' has run or exists.
    
    chat_id = "test_loop_chat"
    
    request = {
        "prompt": "Run hello",
        "chat_id": chat_id,
        "use_thinking": True,
        "priority": "normal",
        "return_json": False,
        "history_override": []
    }
    
    print("[TEST] Sending Request...")
    agent.request_queue.put(request)
    
    # Listen for broadcasts
    # We need to subscribe to active_tasks?
    # core.py: `self.active_tasks[chat_id]` is a list of queues.
    
    listener_q = queue.Queue()
    with agent.active_tasks_lock:
        if chat_id not in agent.active_tasks:
            agent.active_tasks[chat_id] = []
        agent.active_tasks[chat_id].append(listener_q)
        
    print("[TEST] Listening...")
    
    action_seen = False
    observation_seen = False
    final_seen = False
    
    start_time = time.time()
    while time.time() - start_time < 10:
        try:
            msg = listener_q.get(timeout=1)
            if msg is None: # Done
                break
            
            status = msg.get("status")
            chunk = msg.get("chunk", "")
            
            if status == "content":
                print(f"[STREAM] {chunk}")
                if "[System] Executing Action: say_hello" in chunk:
                    action_seen = True
                    print("[PASS] Action Trigger Detected")
                if "The action returned:" in chunk:
                    final_seen = True
                    print("[PASS] Final Answer Detected")
                if "Hello, IntegrationTest!" in chunk:
                    observation_seen = True
                    print("[PASS] Observation Data Integrated")
                    
        except queue.Empty:
            continue
            
    if action_seen and observation_seen and final_seen:
        print("[SUCCESS] Loop Logic Verified.")
    else:
        print("[FAIL] Loop logic failed.")
        print(f"Action: {action_seen}, Obs: {observation_seen}, Final: {final_seen}")

if __name__ == "__main__":
    test_loop()
