
import re
from modules.utils import extract_json

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
            
    return preserved + filtered_older
