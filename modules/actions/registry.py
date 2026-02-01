import os
import json
import logging
import hashlib
from typing import Dict, List, Optional
import shutil

class ActionRegistry:
    _instance = None
    
    def __init__(self):
        self.actions = {}  # Map[action_name, action_metadata]
        self.plugins = {}  # Map[plugin_id, plugin_metadata]
        self.system_plugin_dir = os.path.join("data", "plugins")
        self.logger = logging.getLogger("ActionRegistry")

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def scan_plugins(self, user_id: str = None):
        """Scans system and user directories for plugins."""
        # 1. Scan System Plugins
        self._scan_dir(self.system_plugin_dir, role="system")
        
        # 2. Scan User Plugins (if user_id provided)
        if user_id:
            user_plugin_dir = os.path.join("bot_data", "users", user_id, "plugins")
            if os.path.exists(user_plugin_dir):
                self._scan_dir(user_plugin_dir, role="user")

    def _scan_dir(self, directory: str, role: str):
        if not os.path.exists(directory):
            return

        for entry in os.scandir(directory):
            if entry.is_dir():
                manifest_path = os.path.join(entry.path, "manifest.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, 'r') as f:
                            manifest = json.load(f)
                        
                        if self._validate_manifest(manifest):
                            plugin_id = manifest.get("id")
                            manifest["_path"] = entry.path
                            manifest["_role"] = role
                            self.plugins[plugin_id] = manifest
                            self._register_actions_from_manifest(manifest)
                            self.logger.info(f"Loaded plugin: {plugin_id} ({role})")
                        else:
                            self.logger.warning(f"Invalid manifest in {entry.path}")

                    except Exception as e:
                        self.logger.error(f"Error loading plugin {entry.name}: {e}")

    def _validate_manifest(self, manifest: Dict) -> bool:
        required_fields = ["id", "name", "version", "actions"]
        for field in required_fields:
            if field not in manifest:
                return False
        return True

    def _register_actions_from_manifest(self, manifest: Dict):
        plugin_id = manifest["id"]
        role = manifest["_role"]
        path = manifest["_path"]
        
        for action in manifest.get("actions", []):
            action_name = action.get("name")
            if action_name:
                # Store full metadata needed for execution
                self.actions[action_name] = {
                    "plugin_id": plugin_id,
                    "role": role,
                    "path": os.path.abspath(path),
                    "spec": action,  # The action definition from manifest
                    "script": os.path.abspath(os.path.join(path, action.get("script", "main.py"))),
                    "cache_ttl": action.get("cache_ttl", 0),  # 0 = no caching
                    "trigger": action.get("trigger", "manual")  # manual, pre_request, post_request
                }

    def get_action(self, action_name: str) -> Optional[Dict]:
        return self.actions.get(action_name)

    def get_all_actions(self) -> Dict:
        return self.actions

    def get_plugin(self, plugin_id: str) -> Optional[Dict]:
        """Get plugin metadata by ID."""
        return self.plugins.get(plugin_id)

    def install_plugin(self, gplug_path: str, user_id: str = None, scope: str = "user") -> Dict:
        """
        Install a .gplug file (ZIP) to the appropriate directory.
        
        Args:
            gplug_path: Path to the .gplug file
            user_id: User ID for user-scoped plugins
            scope: 'system' or 'user'
        
        Returns:
            Installed plugin manifest
        """
        from .gplug import unpack_plugin, verify_manifest
        
        # Determine target directory based on scope
        if scope == "system":
            target_dir = self.system_plugin_dir
        else:
            if not user_id:
                raise ValueError("user_id required for user-scoped plugins")
            target_dir = os.path.join("bot_data", "users", user_id, "plugins")
        
        os.makedirs(target_dir, exist_ok=True)
        
        # Unpack with integrity verification
        manifest = unpack_plugin(gplug_path, target_dir, verify=True)
        
        # Register the newly installed plugin
        self._register_actions_from_manifest(manifest)
        self.plugins[manifest['id']] = manifest
        
        self.logger.info(f"Installed plugin: {manifest['id']} ({scope})")
        return manifest

    def pack_plugin(self, plugin_id: str, output_path: str = None) -> str:
        """
        Pack an installed plugin into a .gplug file.
        
        Args:
            plugin_id: ID of the plugin to pack
            output_path: Optional output path
        
        Returns:
            Path to the created .gplug file
        """
        from .gplug import pack_plugin
        
        plugin = self.plugins.get(plugin_id)
        if not plugin:
            raise ValueError(f"Plugin not found: {plugin_id}")
        
        plugin_path = plugin.get('_path')
        if not plugin_path or not os.path.exists(plugin_path):
            raise ValueError(f"Plugin path not found: {plugin_path}")
        
        gplug_path = pack_plugin(plugin_path, output_path)
        self.logger.info(f"Packed plugin: {plugin_id} -> {gplug_path}")
        return gplug_path

    def delete_plugin(self, plugin_id: str) -> bool:
        """Delete a plugin and its folder."""
        plugin = self.plugins.get(plugin_id)
        if not plugin:
            return False
        
        plugin_path = plugin.get('_path')
        if plugin_path and os.path.exists(plugin_path):
            shutil.rmtree(plugin_path)
        
        # Remove from registries
        del self.plugins[plugin_id]
        
        # Remove associated actions
        actions_to_remove = [
            name for name, action in self.actions.items() 
            if action.get('plugin_id') == plugin_id
        ]
        for name in actions_to_remove:
            del self.actions[name]
        
        self.logger.info(f"Deleted plugin: {plugin_id}")
        return True
