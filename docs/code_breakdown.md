# Code Structure Breakdown

Genesis AI is a modular Flask application.

## Core Structure

- **app.py**: Entry point. Initializes Flask, Database, and registers Blueprints.
- **run.bat**: Startup script for Windows.
- **modules/**: Core Python logic.
  - **routes/**: Flask Blueprints (API endpoints).
    - `auth.py`: Login/Logout.
    - `main.py`: UI Pages.
    - `chat.py`: Chat API & Stream.
    - `admin.py`: Settings, prompts, users.
    - `extensions.py`: Plugins, tasks, bot config.
  - **ai_agent/**: The brain.
    - `core.py`: Main `AIAgent` loop (Thought/Action/Observation).
    - `providers/`: LLM integrations (Qwen, etc.).
  - **actions/**: Plugin system.
    - `registry.py`: Loads/manages plugins.
    - `executor.py`: Runs actions safely.
  - **db.py**: SQLite database interface.
  - **utils.py**: Helper functions (JSON parsing).

## Data Directory

- **data/**
  - `system.db`: User and Chat storage.
  - `settings.json`: Configuration.
  - `prompts.json`: System prompts.
  - `plugins/`: System-wide actions.
  - `history/`: JSON logs of all chats.

## Frontend

- **templates/**: HTML files (Jinja2).
  - `index.html`: Main chat interface.
- **static/**: CSS/JS, Fonts.
