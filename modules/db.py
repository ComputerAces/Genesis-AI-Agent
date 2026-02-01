import sqlite3
import os
import json
from werkzeug.security import generate_password_hash

def init_db():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    settings_path = os.path.join(base_dir, "data", "settings.json")
    
    if not os.path.exists(os.path.dirname(db_path)):
        os.makedirs(os.path.dirname(db_path))
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT UNIQUE,
        role TEXT NOT NULL DEFAULT 'user'
    )
    ''')

    # Create history table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id TEXT NOT NULL,
        chat_id TEXT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        thinking TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Create chats table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chats (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        title TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')

    # Create chat_items table (New strictly linear model)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chat_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        thinking TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (chat_id) REFERENCES chats(id)
    )
    ''')
    
    # MIGRATIONS
    cursor.execute("PRAGMA table_info(history)")
    columns = [row[1] for row in cursor.fetchall()]
    if "thinking" not in columns:
        print("[DB] Migrating: Adding 'thinking' column to history table...")
        cursor.execute("ALTER TABLE history ADD COLUMN thinking TEXT")
    if "chat_id" not in columns:
        print("[DB] Migrating: Adding 'chat_id' column to history table...")
        cursor.execute("ALTER TABLE history ADD COLUMN chat_id TEXT")
    if "raw_data" not in columns:
        print("[DB] Migrating: Adding 'raw_data' column to history table...")
        cursor.execute("ALTER TABLE history ADD COLUMN raw_data TEXT")

    cursor.execute("PRAGMA table_info(chats)")
    chat_columns = [row[1] for row in cursor.fetchall()]
    if "updated_at" not in chat_columns:
        print("[DB] Migrating: Adding 'updated_at' column to chats table...")
        # SQLite restriction: Cannot add column with non-constant default in ALTER TABLE
        cursor.execute("ALTER TABLE chats ADD COLUMN updated_at DATETIME")
        cursor.execute("UPDATE chats SET updated_at = created_at")
    
    # Check if admin exists, if not, create from settings
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                settings = json.load(f)
                admin_cfg = settings.get("auth", {}).get("default_admin", {})
                
                if admin_cfg:
                    username = admin_cfg.get("username", "admin")
                    password = admin_cfg.get("password", "adminpassword123")
                    email = admin_cfg.get("email", "admin@genesis.ai")
                    pwd_hash = generate_password_hash(password)
                    
                    cursor.execute(
                        "INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
                        (username, pwd_hash, email, "admin")
                    )
                    print(f"[DB] Default admin user '{username}' created.")
    
    conn.commit()
    conn.close()
    print("[DB] Database initialized successfully.")

def save_chat_item(chat_id, role, content, thinking=None):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    # print(f"[DEBUG:DB] save_chat_item[{role}] content_len={len(content) if content else 0} -> {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Insert
        cursor.execute(
            "INSERT INTO chat_items (chat_id, role, content, thinking) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, thinking)
        )
        row_id = cursor.lastrowid
        # print(f"[DEBUG:DB] Inserted row_id={row_id}")
        
        # Update chat timestamp
        cursor.execute("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
        # print(f"[DEBUG:DB] Updated chat timestamp (rowcount={cursor.rowcount})")
        
        conn.commit()
        conn.close()
        return row_id
    except Exception as e:
        print(f"[Error:DB] In save_chat_item: {e}")
        return None

# Deprecated: usage of parent_id
def save_history_entry(parent_id, role, content, thinking=None, chat_id=None):
    if chat_id:
        return save_chat_item(chat_id, role, content, thinking)
    return -1

def update_history_entry(entry_id, content=None, thinking=None):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        if content is not None and thinking is not None:
            cursor.execute("UPDATE chat_items SET content = ?, thinking = ? WHERE id = ?", (content, thinking, entry_id))
        elif content is not None:
            cursor.execute("UPDATE chat_items SET content = ? WHERE id = ?", (content, entry_id))
        elif thinking is not None:
            cursor.execute("UPDATE chat_items SET thinking = ? WHERE id = ?", (thinking, entry_id))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Error:DB] In update_history_entry: {e}")

def load_chat_items(chat_id):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT role, content, thinking, timestamp FROM chat_items WHERE chat_id = ? ORDER BY timestamp ASC",
        (chat_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "thinking": r[2], "timestamp": r[3]} for r in rows]

# Deprecated
def load_history_entries(parent_id=None, chat_id=None):
    if chat_id:
        return load_chat_items(chat_id)
    return []

def create_chat(chat_id, user_id, title="New Chat"):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO chats (id, user_id, title, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (chat_id, user_id, title))
    conn.commit()
    conn.close()

def get_chats_for_user(user_id):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, created_at, updated_at FROM chats WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]} for r in rows]

def update_chat_title(chat_id, title):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
    conn.commit()
    conn.close()

def get_chat_title(chat_id):
    """Get the title of a chat."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM chats WHERE id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_system_prompt(chat_id, system_prompt):
    """Save the populated system prompt for a chat session."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Store as a special system role entry 
    cursor.execute(
        "INSERT INTO chat_items (chat_id, role, content, thinking) VALUES (?, ?, ?, ?)",
        (chat_id, "system", system_prompt, None)
    )
    conn.commit()
    conn.close()

def delete_chat(chat_id):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM history WHERE chat_id = ?", (chat_id,))
    cursor.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()

def clear_chat_history(chat_id):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_items WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def clear_history_entries(parent_id=None):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    if parent_id:
        cursor.execute("DELETE FROM history WHERE parent_id = ?", (parent_id,))
    else:
        cursor.execute("DELETE FROM history")
    conn.commit()
    conn.close()

    conn.close()

def verify_user(username, password):
    from werkzeug.security import check_password_hash
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    
    if user and check_password_hash(user[2], password):
        return {"id": user[0], "username": user[1], "role": user[3]}
    return None

def log_raw_event(chat_id, role, content, thinking=None):
    """Logs raw input/output to the separate history table for debugging."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # history table: id, parent_id, chat_id, role, content, thinking, timestamp
    # We use parent_id='raw_log' to denote these entries if needed, or just ignore it.
    cursor.execute(
        "INSERT INTO history (parent_id, chat_id, role, content, thinking) VALUES (?, ?, ?, ?, ?)",
        ("raw_log", chat_id, role, content, thinking)
    )
    conn.commit()
    conn.close()

def get_all_history_items(search_query=None):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Switch to querying the 'history' table (raw logs) instead of 'chat_items'
    query = '''
    SELECT 
        h.timestamp,
        c.title,
        u.username,
        h.role,
        h.content,
        h.thinking
    FROM history h
    LEFT JOIN chats c ON h.chat_id = c.id
    LEFT JOIN users u ON c.user_id = u.id
    '''
    
    params = []
    if search_query:
        query += " WHERE h.content LIKE ? OR c.title LIKE ? OR u.username LIKE ?"
        term = f"%{search_query}%"
        params = [term, term, term]
        
    query += " ORDER BY h.timestamp DESC LIMIT 2000"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "timestamp": r[0],
            "chat_title": r[1] or "Unknown/System",
            "username": r[2] or "System",
            "role": r[3],
            "content": r[4],
            "thinking": r[5]
        }
        for r in rows
    ]

def get_chat_owner(chat_id):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM chats WHERE id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return str(row[0])
    return None

if __name__ == "__main__":
    init_db()

def save_raw_history(chat_id, data_dict):
    """
    Saves the full raw interaction data (JSON) to the history table.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "system.db")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # We store the main fields in columns for easy querying, and the full blob in raw_data
        # Using parent_id='raw' to distinguish these rows if needed, or just let them live alongside others
        
        extracted_role = data_dict.get("response", {}).get("role", "assistant")
        
        cursor.execute(
            "INSERT INTO history (parent_id, chat_id, role, content, thinking, raw_data) VALUES (?, ?, ?, ?, ?, ?)",
            ("raw_log", chat_id, extracted_role, data_dict.get("response", {}).get("content", ""), data_dict.get("response", {}).get("thinking", ""), json.dumps(data_dict, ensure_ascii=False))
        )
        
        row_id = cursor.lastrowid
        # print(f"[DB] Logged raw history chain ID: {row_id}")
        
        conn.commit()
        conn.close()
        return row_id
    except Exception as e:
        print(f"[Error:DB] Error saving raw history: {e}")
        return None
