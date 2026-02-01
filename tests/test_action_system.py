import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.actions.registry import ActionRegistry
from modules.actions.executor import ActionExecutor

# Configure logging
logging.basicConfig(level=logging.INFO)

def test_action_system():
    print("[TEST] Initializing Registry...")
    registry = ActionRegistry.get_instance()
    
    print("[TEST] Scanning Plugins...")
    registry.scan_plugins()
    
    actions = registry.get_all_actions()
    print(f"[TEST] Found actions: {list(actions.keys())}")
    
    if "say_hello" not in actions:
        print("[FAIL] 'say_hello' action not found!")
        return

    action_def = registry.get_action("say_hello")
    print(f"[TEST] Action Def: {action_def}")

    print("[TEST] Executing Action...")
    executor = ActionExecutor()
    
    # Mock context
    context = {"user_id": "test_user"}
    args = {"name": "Genesis"}
    
    result = executor.execute(action_def, args, context)
    print(f"[TEST] Result: {result}")

    if result["status"] == "success":
        output = result["output"]
        if output.get("message") == "Hello, Genesis!":
            print("[PASS] Message verified.")
        else:
            print("[FAIL] Wrong message.")
            
        if "genesis_home" in output:
             print(f"[PASS] GENESIS_HOME injected: {output['genesis_home']}")
        else:
             print("[FAIL] GENESIS_HOME missing.")
    else:
        print(f"[FAIL] Execution failed: {result}")

if __name__ == "__main__":
    test_action_system()
