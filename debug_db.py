import sqlite3
import os

# Define DB Path
db_path = os.path.join("data", "system.db")

print(f"Connecting to database at: {db_path}")

try:
    if not os.path.exists(db_path):
        print("ERROR: Database file not found!")
        exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. List Tables
    print("\n--- TABLES ---")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for t in tables:
        print(f"- {t[0]}")

    # 2. Inspect chat_items
    table_name = "chat_items"
    if (table_name,) in tables:
        print(f"\n--- LAST 5 ENTRIES IN '{table_name}' ---")
        try:
            # Get columns
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            print(f"Columns: {columns}")
            
            # Get Data
            cursor.execute(f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 5")
            rows = cursor.fetchall()
            if not rows:
                print("No rows found.")
            for row in rows:
                print(row)
        except Exception as e:
            print(f"Error reading {table_name}: {e}")
    else:
        print(f"\nTable '{table_name}' not found!")

    # 3. Check Chats
    print("\n--- LAST 5 CHATS ---")
    cursor.execute("SELECT * FROM chats ORDER BY updated_at DESC LIMIT 5")
    rows = cursor.fetchall()
    for row in rows:
        print(row)

    conn.close()

except Exception as e:
    print(f"An error occurred: {e}")
