import json
import re

def extract_json(text):
    """
    Extracts a JSON object from a string, handling markdown code blocks.
    """
    # Try to find JSON block in markdown
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
            
    # Try to find anything between { and }
    brace_match = re.search(r'(\{[\s\S]*\})', text)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass
            
    # Fallback: try parsing the whole thing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Double-brace repair (common model hallucination)
    # e.g. {{ "key": "value" }} -> { "key": "value" }
    if "{ {" in text and "} }" in text:
        repaired = text.replace("{ {", "{").replace("} }", "}")
        try:
             return json.loads(repaired)
        except:
             pass
             
    # Attempt to find the *first* valid JSON object by balancing braces manually
    # (Simple stack approach)
    stack = []
    start_idx = -1
    for i, char in enumerate(text):
        if char == '{':
            if not stack:
                start_idx = i
            stack.append(char)
        elif char == '}':
            if stack:
                stack.pop()
                if not stack:
                    # Found a potential complete object
                    candidate = text[start_idx:i+1]
                    try:
                        return json.loads(candidate)
                    except:
                        # Continue searching if this one failed
                        pass
    
    return None
