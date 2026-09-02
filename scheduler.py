import json
import os
import time
from datetime import datetime, timedelta
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
import threading

class ScheduledDownload:
    """Represents a scheduled playlist download."""
    
    def __init__(self, playlist_url, interval_hours, settings, enabled=True):
        self.playlist_url = playlist_url
        self.interval_hours = interval_hours
        self.settings = settings  # Download settings (resolution, format, etc.)
        self.enabled = enabled
        self.last_run = None
        self.next_run = None
        self.created_at = datetime.now().isoformat()
        self._calculate_next_run()
    
    def _calculate_next_run(self):
        """Calculate the next run time based on interval."""
        if self.last_run:
            last = datetime.fromisoformat(self.last_run)
            self.next_run = (last + timedelta(hours=self.interval_hours)).isoformat()
        else:
            self.next_run = datetime.now().isoformat()
    
    def mark_run(self):
        """Mark this download as run and calculate next run."""
        self.last_run = datetime.now().isoformat()
        self._calculate_next_run()
    
    def to_dict(self):
        return {
            'playlist_url': self.playlist_url,
            'interval_hours': self.interval_hours,
            'settings': self.settings,
            'enabled': self.enabled,
            'last_run': self.last_run,
            'next_run': self.next_run,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data):
        obj = cls(data['playlist_url'], data['interval_hours'], data['settings'], data.get('enabled', True))
        obj.last_run = data.get('last_run')
        obj.next_run = data.get('next_run')
        obj.created_at = data.get('created_at', datetime.now().isoformat())
        return obj


class PlaylistScheduler(QObject):
    """Manages scheduled playlist downloads."""
    
    download_triggered = pyqtSignal(dict)  # Emitted when a scheduled download should start
    
    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager
        self.schedules_file = os.path.join(os.path.dirname(__file__), 'scheduled_playlists.json')
        self.scheduled_downloads = []
        self._load_schedules()
        
        # Check for due downloads every minute
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self._check_due_downloads)
        self.check_timer.start(60000)  # 1 minute
    
    def _load_schedules(self):
        """Load scheduled downloads from file."""
        if os.path.exists(self.schedules_file):
            try:
                with open(self.schedules_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.scheduled_downloads = [ScheduledDownload.from_dict(item) for item in data]
            except Exception as e:
                print(f"⚠️ Failed to load schedules: {e}")
                self.scheduled_downloads = []
    
    def _save_schedules(self):
        """Save scheduled downloads to file."""
        try:
            with open(self.schedules_file, 'w', encoding='utf-8') as f:
                json.dump([s.to_dict() for s in self.scheduled_downloads], f, indent=2)
        except Exception as e:
            print(f"⚠️ Failed to save schedules: {e}")
    
    def _check_due_downloads(self):
        """Check for downloads that are due and trigger them."""
        now = datetime.now()
        
        for schedule in self.scheduled_downloads:
            if not schedule.enabled:
                continue
            
            if schedule.next_run:
                next_run = datetime.fromisoformat(schedule.next_run)
                if now >= next_run:
                    print(f"🕐 Triggering scheduled download for: {schedule.playlist_url}")
                    self.download_triggered.emit({
                        'url': schedule.playlist_url,
                        'settings': schedule.settings,
                        'schedule_id': schedule.playlist_url
                    })
                    schedule.mark_run()
                    self._save_schedules()
    
    def add_schedule(self, playlist_url, interval_hours, settings):
        """Add a new scheduled download."""
        # Check if already exists
        for s in self.scheduled_downloads:
            if s.playlist_url == playlist_url:
                s.interval_hours = interval_hours
                s.settings = settings
                s.enabled = True
                s._calculate_next_run()
                self._save_schedules()
                return True
        
        schedule = ScheduledDownload(playlist_url, interval_hours, settings)
        self.scheduled_downloads.append(schedule)
        self._save_schedules()
        return True
    
    def remove_schedule(self, playlist_url):
        """Remove a scheduled download."""
        self.scheduled_downloads = [s for s in self.scheduled_downloads if s.playlist_url != playlist_url]
        self._save_schedules()
    
    def toggle_schedule(self, playlist_url):
        """Enable/disable a scheduled download."""
        for s in self.scheduled_downloads:
            if s.playlist_url == playlist_url:
                s.enabled = not s.enabled
                self._save_schedules()
                return s.enabled
        return False
    
    def get_schedules(self):
        """Get all scheduled downloads."""
        return [s.to_dict() for s in self.scheduled_downloads]
