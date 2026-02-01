# User & Admin Management

Genesis AI creates a secure, multi-user compatible environment (even for local execution) using a robust Role-Based Access Control (RBAC) system.

## Roles

### 1. User

The standard role for personal use.

* **Capabilities**:
  * Chat with the AI.
  * Manage personal chat history (Create, Delete, Clear).
  * Configure personal Bot personality (Name, Description).
  * install/Create Personal Plugins (scoped to their account).
  * View *their own* Tasks.
* **Restrictions**:
  * Cannot access Global Settings.
  * Cannot view other users' chats or history.
  * Cannot install System-wide plugins.

### 2. Admin

The super-user role.

* **Capabilities**:
  * **All User capabilities**.
  * **Global Settings**: Edit system prompts, model endpoints, and server configuration (`/settings`).
  * **User Management**: Create, Delete, or Modify other user accounts (`/admin`).
  * **System Plugins**: Install plugins available to *all* users.
  * **Global History**: View forensic logs of all interactions on the server (`/admin/history`).
  * **Prompts**: Edit the core system prompts (`prompts.json`).

## Managing Users

### Via the Interface

1. Log in as an **Admin**.
2. Navigate to the **Admin Dashboard** (click "Admin" in the sidebar).
3. Scroll to the **User Management** section.
4. **Add User**: Enter a username, email (optional), password, and role.
5. **Delete User**: Click the trash icon next to a user.

### Via Database (Advanced)

Users are stored in `data/system.db` in the `users` table.
Password hashes are generated using `werkzeug.security`.

**Default Admin**:
If the database is empty, the system does not create a default user automatically (unless configured). You usually register the first user or run a setup script.
*(Note: Ensure you have an admin account created during initial setup or via the command line if provided).*
