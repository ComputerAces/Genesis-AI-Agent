"""
TaskScheduler - Lightweight task scheduling for Genesis plugins
Supports cron-style scheduling and manual triggers.
"""
import os
import json
import time
import threading
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable

class TaskScheduler:
    """Manages scheduled tasks for Genesis plugins."""
    
    def __init__(self):
        self.logger = logging.getLogger("TaskScheduler")
        self.tasks: Dict[str, Dict] = {}
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._task_callbacks: Dict[str, Callable] = {}
        self._data_dir = os.path.join("bot_data", "_system", "tasks")
        os.makedirs(self._data_dir, exist_ok=True)
        self._load_tasks()
    
    def _load_tasks(self):
        """Load tasks from persistent storage."""
        tasks_file = os.path.join(self._data_dir, "tasks.json")
        if os.path.exists(tasks_file):
            try:
                with open(tasks_file, 'r', encoding='utf-8') as f:
                    self.tasks = json.load(f)
            except:
                self.tasks = {}
    
    def _save_tasks(self):
        """Save tasks to persistent storage."""
        tasks_file = os.path.join(self._data_dir, "tasks.json")
        with open(tasks_file, 'w', encoding='utf-8') as f:
            json.dump(self.tasks, f, indent=2, default=str)
    
    def create_task(self, name: str, action: str, schedule: str = None, 
                   user_id: str = None, args: Dict = None) -> str:
        """
        Create a new scheduled task.
        
        Args:
            name: Human-readable task name
            action: Action name to execute (from registry)
            schedule: Cron-style schedule (e.g., "*/5 * * * *" for every 5 min)
                      or None for manual-only tasks
            user_id: Owner user ID
            args: Arguments to pass to the action
        
        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {
            "id": task_id,
            "name": name,
            "action": action,
            "schedule": schedule,
            "user_id": user_id,
            "args": args or {},
            "status": "active",
            "last_run": None,
            "next_run": None,
            "created_at": datetime.now().isoformat()
        }
        self._save_tasks()
        self.logger.info(f"Created task: {name} ({task_id})")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """Get a task by ID."""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self, user_id: str = None) -> List[Dict]:
        """Get all tasks, optionally filtered by user."""
        if user_id:
            return [t for t in self.tasks.values() if t.get("user_id") == user_id]
        return list(self.tasks.values())
    
    def update_task(self, task_id: str, updates: Dict) -> bool:
        """Update a task's properties."""
        if task_id not in self.tasks:
            return False
        self.tasks[task_id].update(updates)
        self._save_tasks()
        return True
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save_tasks()
            return True
        return False
    
    def run_task(self, task_id: str, executor=None, registry=None) -> Dict:
        """
        Manually run a task immediately.
        
        Args:
            task_id: Task to run
            executor: ActionExecutor instance
            registry: ActionRegistry instance
        
        Returns:
            Execution result
        """
        task = self.tasks.get(task_id)
        if not task:
            return {"status": "error", "error": "Task not found"}
        
        if not executor or not registry:
            return {"status": "error", "error": "No executor/registry provided"}
        
        action_name = task.get("action")
        action_def = registry.get_action(action_name)
        
        if not action_def:
            return {"status": "error", "error": f"Action '{action_name}' not found"}
        
        context = {"user_id": task.get("user_id")}
        result = executor.execute(action_def, task.get("args", {}), context)
        
        # Update last run time
        self.tasks[task_id]["last_run"] = datetime.now().isoformat()
        self._save_tasks()
        
        return result
    
    def start(self):
        """Start the scheduler background thread."""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        self.logger.info("TaskScheduler started")
    
    def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        self.logger.info("TaskScheduler stopped")
    
    def _scheduler_loop(self):
        """Background loop to check and execute scheduled tasks."""
        while self.running:
            try:
                now = datetime.now()
                for task_id, task in list(self.tasks.items()):
                    if task.get("status") != "active":
                        continue
                    
                    schedule = task.get("schedule")
                    if not schedule:
                        continue
                    
                    # Simple minute-based check (simplified cron)
                    # For a full cron implementation, use croniter library
                    if self._should_run(schedule, now):
                        self.logger.info(f"Scheduled run: {task.get('name')}")
                        
                        # Import here to avoid circular dependencies if any
                        from modules.actions import ActionRegistry, ActionExecutor
                        registry = ActionRegistry()
                        executor = ActionExecutor()
                        
                        # Ensure we see user's plugins
                        user_id = task.get("user_id")
                        if user_id:
                            registry.scan_plugins(user_id)
                        
                        self.run_task(task_id, executor, registry)
                
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
            
            time.sleep(60)  # Check every minute
    
    def _should_run(self, schedule: str, now: datetime) -> bool:
        """
        Simplified schedule check.
        Format: "minute hour day month weekday" (cron-like)
        Supports: * (any), */N (every N), specific values
        """
        try:
            parts = schedule.split()
            if len(parts) != 5:
                return False
            
            minute, hour, day, month, weekday = parts
            
            # Check minute
            if minute != "*":
                if minute.startswith("*/"):
                    interval = int(minute[2:])
                    if now.minute % interval != 0:
                        return False
                elif int(minute) != now.minute:
                    return False
            
            # Check hour
            if hour != "*" and int(hour) != now.hour:
                return False
            
            # Simplified: skip day/month/weekday for now
            return True
            
        except:
            return False


# Singleton instance
_scheduler: Optional[TaskScheduler] = None

def get_scheduler() -> TaskScheduler:
    """Get the global TaskScheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
