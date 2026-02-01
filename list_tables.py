import sqlite3
import os

db_path = os.path.join("data", "system.db")
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Database Tables:")
    for t in tables:
        print(f" - {t[0]}")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
