class MockProvider:
    def __init__(self, **kwargs):
        pass

    def generate(self, prompt, use_thinking=False, stop_event=None, return_json=False, parent_id=None, history_override=None):
        # Scenario:
        # 1. User asks "Run hello" -> AI Action
        # 2. Obs -> AI Final Answer
        
        # We detect loop stage by inspecting checking if prompt starts with "Observation:"
        
        if "Observation:" in prompt:
             # Final Answer Stage
             yield {"status": "thinking", "chunk": "I have the result."}
             yield {"status": "thinking_finished", "thinking": "I have the result."}
             yield {"status": "content", "chunk": "The action returned: "}
             yield {"status": "content", "chunk": prompt.replace("Observation: ", "")}
        else:
             # Action Stage
             yield {"status": "thinking", "chunk": "I need to say hello."}
             yield {"status": "thinking_finished", "thinking": "I need to say hello."}
             yield {"status": "content", "chunk": 'I will run the tool.\n\n[ACTION: say_hello, {"name": "IntegrationTest"}]'}
