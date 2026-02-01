import signal
import sys
import os

# Add the project root to sys.path to allow 'from modules...' imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.ai_agent import AIAgent

agent = None

def signal_handler(sig, frame):
    print("\n[System] Shutdown signal received. Cleaning up...")
    if agent:
        agent.shutdown()
    sys.exit(0)

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python cli.py [options]")
        print("Options:")
        print("  -h, --help    Show this help message and exit")
        print("  /gui          Launch in GUI mode (handled by run.bat)")
        print("  /think [on|off]  Launch with thinking mode state")
        print("  /exit         Exit the CLI")
        print("  /clear        Clear history")
        print("  /chats        List your conversations")
        print("  /chat [id]    Select a conversation")
        print("  /new [title]  Create a new conversation")
        sys.exit(0)

    global agent
    signal.signal(signal.SIGINT, signal_handler)

    print("========================================")
    print("   Qwen3 AI Agent - CLI Interface      ")
    print("========================================")
    print("Commands: /exit (to quit), /clear (clear history), /think (on/off)")
    print("")

    from modules.db import init_db
    init_db()

    agent = AIAgent()
    
    from modules.config import get_startup_thinking_mode
    use_thinking = get_startup_thinking_mode()

    # User Authentication
    current_user_id = None
    current_username = "Guest"
    
    print("[System] Please log in using /user [username] and /pass [password]")

    selected_chat_id = None
    import uuid
    session_id = f"cli_{uuid.uuid4().hex[:8]}"
    
    # Handle one-shot /message argument
    if "/message" in sys.argv:
        try:
            idx = sys.argv.index("/message")
            if idx + 1 < len(sys.argv):
                # Join all remaining arguments as the prompt
                prompt = " ".join(sys.argv[idx + 1:])
                
                thinking_started = False
                for chunk in agent.ask_stream(prompt, use_thinking=use_thinking, return_json=True, parent_id=session_id):
                    if chunk["status"] == "thinking":
                        if not thinking_started:
                            print("\n--- Thinking Process ---")
                            thinking_started = True
                        print(chunk["chunk"], end="", flush=True)
                    elif chunk["status"] == "thinking_finished":
                        print(f"\n[Finished Thinking]\n------------------------")
                    elif chunk["status"] == "json_content":
                        print(f"Assistant: {chunk.get('message', '')}")
                        print(f"[ Reason: {chunk.get('reason', 'N/A')} ]")
                
                print("")
                agent.shutdown()
                sys.exit(0)
            else:
                print("[Error] Missing prompt after /message.")
                sys.exit(1)
        except Exception as e:
            print(f"[Error] One-shot execution failed: {str(e)}")
            sys.exit(1)

    while True:
        try:
            mode_str = "[Thinking ON]" if use_thinking else "[Thinking OFF]"
            user_input = input(f"User {mode_str}: ").strip()

            if not user_input:
                continue

            if user_input.lower() == "/exit":
                print("Goodbye!")
                break
            
            if user_input.lower() == "/clear":
                agent.clear_history()
                print("[System] History cleared.")
                continue

            if user_input.lower() == "/think on":
                use_thinking = True
                print("[System] Thinking mode enabled.")
                continue

            if user_input.lower().startswith("/user"):
                import sqlite3
                from werkzeug.security import generate_password_hash
                parts = user_input.split()
                db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "system.db")
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                if len(parts) >= 2 and parts[1] == "list":
                    cursor.execute("SELECT id, username, role FROM users")
                    print("\n--- Genesis Users ---")
                    for r in cursor.fetchall():
                        print(f"ID: {r[0]} | User: {r[1]} | Role: {r[2]}")
                    print("----------------------")
                elif len(parts) >= 5 and parts[1] == "add":
                    # /user add [user] [pwd] [role]
                    uname, pwd, role = parts[2], parts[3], parts[4]
                    pwd_hash = generate_password_hash(pwd)
                    try:
                        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", (uname, pwd_hash, role))
                        conn.commit()
                        print(f"[System] User '{uname}' added successfully.")
                    except sqlite3.IntegrityError:
                        print(f"[Error] User '{uname}' already exists.")
                elif len(parts) >= 3 and parts[1] == "remove":
                    uname = parts[2]
                    cursor.execute("DELETE FROM users WHERE username = ?", (uname,))
                    conn.commit()
                    print(f"[System] User '{uname}' removed.")
                else:
                    print("[Usage] /user list")
                    print("[Usage] /user add [username] [password] [role]")
                    print("[Usage] /user remove [username]")
                
                conn.close()
                continue

            if user_input.lower() == "/think off":
                use_thinking = False
                print("[System] Thinking mode disabled.")
                continue

            if user_input.lower() == "/chats":
                from modules.db import get_chats_for_user
                chats = get_chats_for_user(current_user_id)
                print("\n--- Your Conversations ---")
                for c in chats:
                    is_active = "*" if c['id'] == selected_chat_id else " "
                    print(f"{is_active} [{c['id'][:8]}] {c['title']} ({c['created_at']})")
                print("--------------------------")
                continue

            if user_input.lower().startswith("/user"):
                parts = user_input.split(" ", 1)
                if len(parts) > 1:
                    username_attempt = parts[1].strip()
                    print(f"[System] Username '{username_attempt}' set. Please enter password using /pass [password].")
                    active_login_username = username_attempt
                else:
                    print("[Usage] /user [username]")
                continue
                
            if user_input.lower().startswith("/pass"):
                if 'active_login_username' not in locals():
                    print("[Error] Please set username first using /user [username]")
                    continue
                    
                parts = user_input.split(" ", 1)
                if len(parts) > 1:
                    password_attempt = parts[1].strip()
                    from modules.db import verify_user
                    user = verify_user(active_login_username, password_attempt)
                    if user:
                        current_user_id = user["id"]
                        current_username = user["username"]
                        print(f"[Success] Logged in as {current_username}")
                        # Reset session ID for new user
                        session_id = f"cli_{uuid.uuid4().hex[:8]}"
                    else:
                        print("[Error] Invalid username or password.")
                else:
                    print("[Usage] /pass [password]")
                continue

            if user_input.lower().startswith("/chat "):
                cid = user_input.split()[1]
                from modules.db import get_chats_for_user
                chats = get_chats_for_user(current_user_id)
                found = next((c for c in chats if c['id'].startswith(cid)), None)
                if found:
                    selected_chat_id = found['id']
                    print(f"[System] Switched to chat: {found['title']}")
                else:
                    print(f"[Error] Chat starting with '{cid}' not found.")
                continue

            if user_input.lower().startswith("/new"):
                from modules.db import create_chat
                title = " ".join(user_input.split()[1:]) or "New Conversation"
                selected_chat_id = uuid.uuid4().hex
                create_chat(selected_chat_id, current_user_id, title)
                print(f"[System] New chat created and selected: {title}")
                continue

            # Handle thinking display
            if use_thinking:
                print("AI is starting to think...", end="\r", flush=True)
            
            thinking_started = False
            content_started = False
            full_content_raw = ""
            
            from modules.utils import extract_json
            
            print("\n")
            
            # Streaming response
            # Streaming response
            target_chat_id = selected_chat_id or f"cli_{uuid.uuid4().hex[:8]}"
            
            for chunk in agent.ask_stream(user_input, use_thinking=use_thinking, return_json=True, chat_id=target_chat_id):
                if chunk["status"] == "thinking":
                    if not thinking_started:
                        print("\n--- Thinking Process ---")
                        thinking_started = True
                    print(chunk["chunk"], end="", flush=True)
                
                elif chunk["status"] == "thinking_finished":
                    print(f"\n[Finished Thinking]")
                    print("------------------------")
                
                elif chunk["status"] == "json_content":
                    msg = chunk.get("message", "")
                    reason = chunk.get("reason", "N/A")
                    print(f"Assistant: {msg}")
                    print(f"[ Reason: {reason} ]")

            print("")

        except EOFError:
            break
        except Exception as e:
            print(f"\n[Error] {str(e)}")

    if agent:
        agent.shutdown()

if __name__ == "__main__":
    main()
