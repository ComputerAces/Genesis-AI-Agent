
import sqlite3
import os
import json
from datetime import datetime, date

# Permission Scopes
SCOPE_ONCE = "once"
SCOPE_SESSION = "session" # This chat
SCOPE_TODAY = "today"
SCOPE_ALWAYS = "always"

def init_permissions_db():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "permissions.db")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Permissions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            action_name TEXT NOT NULL,
            scope TEXT NOT NULL,
            chat_id TEXT,
            granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at DATE
        )
    """)
    
    conn.commit()
    conn.close()

def check_permission(user_id, action_name, chat_id=None):
    """
    Checks if a permission exists for the action.
    Returns: True if permitted (via ALWAYS, TODAY, or SESSION), False otherwise.
    Note: ONCE scope is ephemeral and not stored here (handled by caller logic typically, 
    but for this implementation we might assume the caller handles the immediate 'once' grant by skipping check).
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "permissions.db")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Check ALWAYS
    cursor.execute("SELECT id FROM permissions WHERE user_id = ? AND action_name = ? AND scope = ?", 
                   (user_id, action_name, SCOPE_ALWAYS))
    if cursor.fetchone():
        conn.close()
        return True
        
    # 2. Check TODAY
    today_str = date.today().isoformat()
    cursor.execute("SELECT id FROM permissions WHERE user_id = ? AND action_name = ? AND scope = ? AND expires_at >= ?", 
                   (user_id, action_name, SCOPE_TODAY, today_str))
    if cursor.fetchone():
        conn.close()
        return True
        
    # 3. Check SESSION (chat_id)
    if chat_id:
        cursor.execute("SELECT id FROM permissions WHERE user_id = ? AND action_name = ? AND scope = ? AND chat_id = ?", 
                       (user_id, action_name, SCOPE_SESSION, chat_id))
        if cursor.fetchone():
            conn.close()
            return True
            
    conn.close()
    return False

def grant_permission(user_id, action_name, scope, chat_id=None):
    """
    Grants a permission.
    SCOPES:
    - once: No-op (handled by immediate execution)
    - session: Linked to chat_id
    - today: Expires at end of today (we store just the date, check is >=)
    - always: No expiry
    """
    if scope == SCOPE_ONCE:
        return # Ephemeral
        
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "permissions.db")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    expires_at = None
    target_chat_id = None
    
    if scope == SCOPE_TODAY:
        expires_at = date.today().isoformat() # Expires "on" this day (valid until end of it)
    elif scope == SCOPE_SESSION:
        target_chat_id = chat_id
    
    # Remove existing conflicting/redundant permission logic? 
    # For now, just insert.
    cursor.execute("""
        INSERT INTO permissions (user_id, action_name, scope, chat_id, expires_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, action_name, scope, target_chat_id, expires_at))
    
    conn.commit()
    conn.close()
