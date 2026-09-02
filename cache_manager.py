import json
import os
import time
import threading
from datetime import datetime, timedelta

from settings import CACHE_DIR

class CacheManager:
    """Manages video metadata caching with expiration."""
    
    def __init__(self, cache_dir=None):
        if cache_dir is None:
            # Use professional cache directory from settings
            cache_dir = CACHE_DIR
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, 'metadata_cache.json')
        self.cache_expiry_days = None  # No expiry by default
        self._ensure_cache_dir()
        self._load_cache()
        self._cleanup_thread = None
        self._cleanup_running = False
        self._start_auto_cleanup()
    
    def _ensure_cache_dir(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
    
    def _load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}
        else:
            self.cache = {}
    
    def _save_cache(self):
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=None, separators=(',', ':'))
    
    def _get_video_id(self, url):
        """Extract video ID from YouTube URL."""
        if 'v=' in url:
            return url.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in url:
            return url.split('youtu.be/')[1].split('?')[0]
        return None
    
    def _get_playlist_id(self, url):
        """Extract playlist ID from YouTube URL."""
        if 'list=' in url:
            return url.split('list=')[1].split('&')[0]
        return None
    
    def _get_cache_key(self, url):
        """Get cache key for URL (video or playlist)."""
        # Check if it's a playlist URL
        playlist_id = self._get_playlist_id(url)
        if playlist_id:
            return f"playlist_{playlist_id}"
        
        # Otherwise treat as video URL
        video_id = self._get_video_id(url)
        if video_id:
            return f"video_{video_id}"
        
        # Fallback to hash of URL
        import hashlib
        return f"url_{hashlib.md5(url.encode()).hexdigest()}"
    
    def get(self, url, force_refresh=False):
        """Get cached metadata for a video or playlist URL."""
        cache_key = self._get_cache_key(url)
        if not cache_key:
            return None
        
        if force_refresh:
            return None
        
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            cached_time = datetime.fromisoformat(entry['cached_at'])
            # If no expiry is set, always return cached data
            if self.cache_expiry_days is None:
                return entry['data']
            # Check if cache is still valid
            if datetime.now() - cached_time < timedelta(days=self.cache_expiry_days):
                return entry['data']
        
        return None
    
    def set(self, url, data):
        """Cache metadata for a video or playlist URL."""
        cache_key = self._get_cache_key(url)
        if not cache_key:
            return False
        
        self.cache[cache_key] = {
            'data': data,
            'cached_at': datetime.now().isoformat(),
            'url': url
        }
        self._save_cache()
        return True
    
    def clear(self, url=None):
        """Clear cache for specific URL or all cache."""
        if url:
            cache_key = self._get_cache_key(url)
            if cache_key and cache_key in self.cache:
                del self.cache[cache_key]
                self._save_cache()
        else:
            self.cache = {}
            self._save_cache()
    
    def cleanup_expired(self):
        """Remove expired cache entries."""
        now = datetime.now()
        expired_keys = []
        
        # If no expiry is set, nothing to clean up
        if self.cache_expiry_days is None:
            return 0
        
        for video_id, entry in self.cache.items():
            cached_time = datetime.fromisoformat(entry['cached_at'])
            if now - cached_time >= timedelta(days=self.cache_expiry_days):
                expired_keys.append(video_id)
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            self._save_cache()
        
        return len(expired_keys)
    
    def set_expiry_days(self, days):
        """Set cache expiry in days. None means no expiry."""
        old_expiry = self.cache_expiry_days
        self.cache_expiry_days = days
        
        # Stop existing cleanup thread if running
        if self._cleanup_running:
            self.stop_auto_cleanup()
        
        # Auto cleanup when expiry is set
        if days is not None:
            self.cleanup_expired()
            self._start_auto_cleanup()
    
    def get_expiry_days(self):
        """Get current cache expiry in days."""
        return self.cache_expiry_days
    
    def auto_cleanup(self):
        """Automatically cleanup expired entries if expiry is set."""
        if self.cache_expiry_days is not None:
            return self.cleanup_expired()
        return 0
    
    def _start_auto_cleanup(self):
        """Start background thread for automatic cache cleanup."""
        if self.cache_expiry_days is not None:
            self._cleanup_running = True
            self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
            self._cleanup_thread.start()
    
    def _cleanup_loop(self):
        """Background loop that periodically cleans up expired cache entries."""
        while self._cleanup_running:
            try:
                # Sleep for 1 hour between cleanups
                time.sleep(3600)
                if self._cleanup_running and self.cache_expiry_days is not None:
                    removed = self.auto_cleanup()
                    if removed > 0:
                        print(f"[Cache Auto-cleanup] Removed {removed} expired entries")
            except Exception as e:
                print(f"[Cache Auto-cleanup] Error: {e}")
    
    def stop_auto_cleanup(self):
        """Stop the automatic cleanup thread."""
        self._cleanup_running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
