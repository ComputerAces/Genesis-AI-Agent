# Genesis AI

**Current Status: "Baby" Stage**

Genesis is a powerful, modular, and locally-hosted AI Agent platform. It features a robust plugin system, autonomous action execution, and a sleek web interface.

> **Note**: This entire system was built in just **3 days** using **Antigravity**.

## Vision & Growth

We are currently in the "Baby" stage of development, but the potential is limitless. We are actively looking for contributors, visionaries, and supporters to help **grow this system** and push it out to the world.

If you believe in local, private, and powerful AI, join us in making Genesis a standard for personal AI agents.

## 🧪 Help Us Test & Build Actions

We need **YOUR** help to expand Genesis's capabilities. The Action System is modular, powerful, and ready for experimentation.

### How You Can Help

1. **Test Existing Actions**: Try running `search_files`, `system_info`, or `say_hello`. Push them to their limits and report any bugs.
2. **Build New Actions**:
    * Navigate to `data/plugins/`.
    * Copy the structure of an existing plugin (like `search_files`).
    * Create your own Python tools!
3. **Feedback**: Tell us what Actions you want to see next. File management? Email? Home Automation?

This is a community-driven effort. Your code can help define the next generation of Genesis.

## Quick Install

1. **Install Python 3.10+**
2. **Install Dependencies**:

    ```bash
    pip install -r requirements.txt
    ```

3. **Run**:

    ```bash
    ./run.bat gui
    ```

4. **Open**: `http://127.0.0.1:5000`

## 🧠 Why Qwen3 (0.6B)?

You might wonder why we default to such a small model. The reason is simple: **Efficiency & Accessibility**.

The lead developer of Genesis does currently not have access to a dedicated GPU. Optimizing for the Qwen3 0.6B model proves that the **Architecture** of Genesis (the Action Loops, Logic, and Plugin System) is robust enough to perform complex tasks even with a lightweight brain.

**Think about it:**
If Genesis is this powerful with a 0.6B model running on a CPU, imagine what it can do with:

* **Qwen 4B / 7B / 14B / 72B**
* **OpenAI GPT-4o** (Genesis support coming soon!)
* **DeepSeek R1**

The system is designed to scale. The intelligence is in the **Agentic Loop**, not just the LLM.

### 🤝 Help Us Upgrade

If you want to see Genesis running on top-tier hardware, consider **donating to help us buy a GPU**. This will allow us to:

1. Test and support larger local models (7B+).
2. Develop Vision and Image Generation features faster.
3. Train custom LoRAs for better Tool Use.

[**Donate via CashApp**](#support-the-project) to help power the next stage of evolution.

## Upgrading Models

By default, Genesis is configured for lightweight models (like Qwen 0.5B/1.5B) to ensure it runs on most hardware.

**Want more power?**
To enable better, larger, or different models:

1. Load this codebase into **Antigravity**.
2. Provide the specs of the new model you want (e.g., Llama 3, Mistral, larger Qwen variants).
3. Tell Antigravity to add it.

It's that simple. The system is designed to be evolved *by* AI.

> **Prefer doing it yourself?**
> Check out the [Manual Integration Guide (Hard Edit)](docs/hardedit.md) to learn how to add providers the old-fashioned way.

## User & Admin System

Genesis features a secure **Role-Based Access Control (RBAC)** system.

* **Users**: Private managed chat, personal memory, and personal plugins.
* **Admins**: Full control over system settings, global history, prompts, and user accounts.

For full details on managing users and permissions, see the **[User Management Guide](docs/user_management.md)**.

## Documentation

For detailed instructions, please check the [docs](docs/) folder:

* [Full Installation Guide](docs/full_install.md)
* [Code Breakdown](docs/code_breakdown.md)
* [Adding Actions / Plugins](docs/adding_actions.md)

## Community

Join the conversation, ask questions, and show off your plugins on our **[GitHub Discussions Board](https://github.com/ComputerAces/Genesis-AI-Agent/discussions)**.

## Support the Project

If you enjoy Genesis and want to support its rapid development:

**CashApp**: @brafordBrooks

## License

Use of this software is subject to the terms in [LICENSE.md](LICENSE.md).

* **Free** for personal, individual use.
* **Paid License Required** for commercial or corporate use.

Contact **<compaces79@gmail.com>** for commercial licensing inquiries.
