"""
Action execution cache for pre_request actions.
Implements stale-while-revalidate pattern to reduce latency.
"""
import os
import json
import time
import threading
from typing import Dict, Optional, Any

class ActionCache:
    """Singleton cache for pre_request action results."""
    
    _instance = None
    
    def __init__(self):
        self._cache: Dict[str, Dict] = {}  # key -> {data, timestamp, ttl}
        self._lock = threading.Lock()
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _make_key(self, action_name: str, user_id: str) -> str:
        """Create unique cache key."""
        return f"{action_name}:{user_id}"
    
    def get(self, action_name: str, user_id: str, ttl: int = 0) -> Optional[Dict]:
        """
        Get cached result if still valid.
        
        Args:
            action_name: Name of the action
            user_id: User ID for isolation
            ttl: Time-to-live in seconds (0 = no caching)
        
        Returns:
            Cached data if valid, None if stale or missing
        """
        if ttl <= 0:
            return None
        
        key = self._make_key(action_name, user_id)
        
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            
            age = time.time() - entry["timestamp"]
            if age < ttl:
                return entry["data"]
        
        return None
    
    def get_stale(self, action_name: str, user_id: str) -> Optional[Dict]:
        """
        Get stale data for stale-while-revalidate pattern.
        Returns data even if TTL expired (will be refreshed in background).
        """
        key = self._make_key(action_name, user_id)
        
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                return entry["data"]
        
        return None
    
    def is_stale(self, action_name: str, user_id: str, ttl: int) -> bool:
        """Check if cache entry is stale (past TTL)."""
        key = self._make_key(action_name, user_id)
        
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return True  # No entry = stale
            
            age = time.time() - entry["timestamp"]
            return age >= ttl
    
    def set(self, action_name: str, user_id: str, data: Any, ttl: int = 0):
        """Store result in cache."""
        if ttl <= 0:
            return
        
        key = self._make_key(action_name, user_id)
        
        with self._lock:
            self._cache[key] = {
                "data": data,
                "timestamp": time.time(),
                "ttl": ttl
            }
    
    def invalidate(self, action_name: str, user_id: str):
        """Remove an entry from cache."""
        key = self._make_key(action_name, user_id)
        
        with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    def clear_user(self, user_id: str):
        """Clear all cache entries for a user."""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.endswith(f":{user_id}")]
            for key in keys_to_remove:
                del self._cache[key]


def get_action_cache() -> ActionCache:
    """Get the global ActionCache instance."""
    return ActionCache.get_instance()
