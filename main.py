import sys
import queue
import threading
import json
import os
import time
import urllib.request
import urllib.error

# Import only ONE PyQt variant based on dependency check results
# This prevents double dialogs from both PyQt5 and PyQt6
PYQT_VARIANT = None  # Will be set to 'PyQt5' or 'PyQt6'

try:
    # Try to use the detected variant from dependency checker
    import importlib.util
    pyqt5_spec = importlib.util.find_spec('PyQt5')
    pyqt6_spec = importlib.util.find_spec('PyQt6')
    
    # Prioritize PyQt5 as it's more commonly used
    if pyqt5_spec:
        PYQT_VARIANT = 'PyQt5'
        print(f"Detected PyQt5 via importlib")
    elif pyqt6_spec:
        PYQT_VARIANT = 'PyQt6'
        print(f"Detected PyQt6 via importlib")
    else:
        PYQT_VARIANT = 'PyQt5'  # Default fallback
        print(f"Using default PyQt5 variant")
except Exception as e:
    print(f"Warning: Could not detect PyQt variant: {e}")
    PYQT_VARIANT = 'PyQt5'  # Default fallback

# Import ONLY the detected PyQt variant
if PYQT_VARIANT == 'PyQt5':
    from PyQt5.QtCore import QObject, pyqtSlot, Qt
    from PyQt5.QtWidgets import QApplication, QFileDialog, QSystemTrayIcon, QMenu, QAction, QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QCheckBox, QGroupBox, QMessageBox, QDialog, QTextEdit, QScrollArea
    from PyQt5.QtGui import QIcon, QCursor
    PYQT_VERSION = 5
else:  # PyQt6
    from PyQt6.QtCore import QObject, pyqtSlot, Qt
    from PyQt6.QtWidgets import QApplication, QFileDialog, QSystemTrayIcon, QMenu, QAction, QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QCheckBox, QGroupBox, QMessageBox, QDialog, QTextEdit, QScrollArea
    from PyQt6.QtGui import QIcon, QCursor
    PYQT_VERSION = 6

# Handle Qt.WindowType differences between PyQt5 and PyQt6
if PYQT_VERSION == 6:
    # PyQt6 uses different enum names
    WindowStaysOnTopHint = Qt.WindowType.WindowStaysOnTopHint
    FramelessWindowHint = Qt.WindowType.FramelessWindowHint
else:
    # PyQt5 uses the old style
    WindowStaysOnTopHint = Qt.WindowStaysOnTopHint
    FramelessWindowHint = Qt.FramelessWindowHint

from downloader import DownloadWorker, WorkerSignals
from api_server import LocalApiServer
from scheduler import PlaylistScheduler
from settings import resolve_js_runtime, load_settings

# Version information
CURRENT_VERSION = "1.0.0"
GITHUB_REPO = "Entity6814/YTDownloader"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Run dependency check on startup
try:
    import check
    print("Running dependency check...")
    checker = check.DependencyChecker()
    if not checker.run_all_checks():
        print("WARNING: Some dependencies are missing or misconfigured.")
        print("The application may not work correctly.")
        print("Please run 'python check.py' to see detailed issues.")
        print("Press Enter to continue anyway or Ctrl+C to exit...")
        input()
except ImportError:
    print("WARNING: check.py not found. Skipping dependency check.")
    print("It is recommended to run 'python check.py' before starting the application.")
except Exception as e:
    print(f"WARNING: Error running dependency check: {e}")
    print("The application will continue, but may have issues.")


class ThreadSafeJobStateManager:
    """Thread-safe Manager that synchronizes all running process statuses between DownloadWorker threads and Flask."""

    def __init__(self):
        self.lock = threading.Lock()
        self._jobs = {}

    def add_job(self, job_id, title, url, is_playlist=False):
        with self.lock:
            self._jobs[job_id] = {
                'id': job_id,
                'title': title,
                'url': url,
                'status': 'queued',
                'percent': 0,
                'speed': '0 KB/s',
                'eta': 'N/A',
                'is_playlist': is_playlist,
                'playlist_index': 0,
                'playlist_total': 0,
                'current_video_title': '',
                'last_stdout': '',
                'retry_count': 0,
                'original_payload': None
            }

    def update_job(self, job_id, **kwargs):
        with self.lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(kwargs)

    def cancel_job(self, job_id):
        with self.lock:
            if job_id in self._jobs:
                self._jobs[job_id]['status'] = 'cancelled'

    def get_job_status(self, job_id):
        with self.lock:
            return self._jobs[job_id]['status'] if job_id in self._jobs else 'none'

    def get_all_jobs(self):
        with self.lock:
            return json.loads(json.dumps(self._jobs))

    def reorder_queue(self, job_order):
        """Reorder jobs in the queue based on the provided order."""
        with self.lock:
            # Create ordered dict
            ordered_jobs = {}
            for job_id in job_order:
                if job_id in self._jobs:
                    ordered_jobs[job_id] = self._jobs[job_id]
            
            # Add any jobs not in the order list (preserve their relative order)
            for job_id in self._jobs:
                if job_id not in ordered_jobs:
                    ordered_jobs[job_id] = self._jobs[job_id]
            
            self._jobs = ordered_jobs


class HeadlessDownloaderApp(QObject):
    """Headless orchestrator using PyQt's QCoreApplication framework to coordinate tasks."""

    @pyqtSlot(str, str)
    def open_embedded_window(self, url, video_id):
        """Open the embedded video download window."""
        if self.embedded_window:
            self.embedded_window.close()
        
        self.embedded_window = EmbeddedVideoWindow(url, video_id, self.state_manager)
        self.embedded_window.show()

    def quit_application(self):
        """Quit the application."""
        print("🚪 Quitting application from system tray...")
        self.shutdown()
        QApplication.quit()

    def check_for_updates(self):
        """Check for updates from GitHub releases."""
        print("🔄 Checking for updates...")
        try:
            request = urllib.request.Request(
                GITHUB_API_URL,
                headers={'User-Agent': 'YouTubeDesktopDownloader'}
            )
            
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                latest_version = data.get('tag_name', '').replace('v', '')
                release_url = data.get('html_url', '')
                
                print(f"📦 Current version: {CURRENT_VERSION}")
                print(f"📦 Latest version: {latest_version}")
                
                if latest_version != CURRENT_VERSION:
                    print(f"✨ New version available: {latest_version}")
                    return {
                        'update_available': True,
                        'current_version': CURRENT_VERSION,
                        'latest_version': latest_version,
                        'release_url': release_url
                    }
                else:
                    print("✅ You are using the latest version")
                    return {
                        'update_available': False,
                        'current_version': CURRENT_VERSION,
                        'latest_version': latest_version,
                        'release_url': release_url
                    }
                    
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print("ℹ️ No releases found on GitHub (this is normal for new projects)")
                return {
                    'update_available': False,
                    'current_version': CURRENT_VERSION,
                    'latest_version': CURRENT_VERSION,
                    'release_url': f"https://github.com/{GITHUB_REPO}/releases",
                    'no_releases': True
                }
            else:
                print(f"❌ HTTP error checking for updates: {e}")
                return {'update_available': False, 'error': f"HTTP {e.code}: {e.reason}"}
        except urllib.error.URLError as e:
            print(f"❌ Network error checking for updates: {e}")
            return {'update_available': False, 'error': str(e)}
        except Exception as e:
            print(f"❌ Error checking for updates: {e}")
            return {'update_available': False, 'error': str(e)}

    def show_update_dialog(self):
        """Show update dialog with update information."""
        update_info = self.check_for_updates()
        
        if update_info.get('error'):
            self.show_error_dialog("Update Check Failed",
                f"Could not check for updates: {update_info['error']}")
            return
        
        if update_info.get('no_releases'):
            message = f"""
            <h3>No Releases Yet</h3>
            <p><b>Current Version:</b> {update_info['current_version']}</p>
            <p>There are no official releases on GitHub yet.</p>
            <p>You can still download the latest code from the main branch.</p>
            <hr>
            <p><a href="{update_info['release_url']}">View GitHub Releases</a></p>
            """
            self.show_info_dialog("No Releases", message)
        elif update_info['update_available']:
            message = f"""
            <h3>Update Available!</h3>
            <p><b>Current Version:</b> {update_info['current_version']}</p>
            <p><b>Latest Version:</b> {update_info['latest_version']}</p>
            <p><b>Release Notes:</b> <a href="{update_info['release_url']}">View on GitHub</a></p>
            <hr>
            <p><b>To update:</b></p>
            <ol>
                <li>Go to: <a href="{update_info['release_url']}">GitHub Releases</a></li>
                <li>Download the latest version</li>
                <li>Replace your current files with the new ones</li>
                <li>Run: <code>pip install -r requirements.txt</code></li>
                <li>Run: <code>python check.py</code></li>
            </ol>
            """
            self.show_info_dialog("Update Available", message)
        else:
            message = f"""
            <h3>No Updates Available</h3>
            <p><b>Current Version:</b> {update_info['current_version']}</p>
            <p><b>Latest Version:</b> {update_info['latest_version']}</p>
            <p>You are using the latest version of YouTube Desktop Downloader Bridge Pro!</p>
            """
            self.show_info_dialog("Up to Date", message)

    def show_error_dialog(self, title, message):
        """Show error dialog."""
        if PYQT_VERSION == 5:
            from PyQt5.QtWidgets import QMessageBox
        else:
            from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(None, title, message)

    def show_info_dialog(self, title, message):
        """Show info dialog."""
        if PYQT_VERSION == 5:
            from PyQt5.QtWidgets import QMessageBox
        else:
            from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(None, title, message)

    def show_readme_dialog(self):
        """Show README.md in a structured dialog for easy user reference."""
        # Get the README.md file path
        app_dir = os.path.dirname(os.path.abspath(__file__))
        readme_path = os.path.join(app_dir, 'README.md')

        if not os.path.exists(readme_path):
            self.show_error_dialog("README Not Found", f"Could not find README.md at {readme_path}")
            return

        # Read the README content
        try:
            with open(readme_path, 'r', encoding='utf-8') as f:
                readme_content = f.read()
        except Exception as e:
            self.show_error_dialog("Read Error", f"Could not read README.md: {e}")
            return

        # Create a dialog window
        dialog = QDialog()
        dialog.setWindowTitle("YouTube Desktop Downloader Bridge Pro - User Guide")
        dialog.setMinimumSize(900, 700)

        # Create main layout
        layout = QVBoxLayout(dialog)

        # Create scroll area for the content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        # Create text edit for displaying README
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(readme_content)

        # Set a monospace font for better readability
        font = text_edit.font()
        font.setFamily("Consolas" if os.name == 'nt' else "Monospace")
        font.setPointSize(10)
        text_edit.setFont(font)

        scroll.setWidget(text_edit)
        layout.addWidget(scroll)

        # Add close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        dialog.exec_()

    def shutdown(self):
        print("Shutting down background service threads...")
        self.api_server.terminate()
        self.api_server.wait()
        self.download_worker.stop()
        self.download_worker.wait()
        
        # Hide tray icon
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()

    def __init__(self):
        super().__init__()
        
        self.download_queue = queue.Queue()
        self.state_manager = ThreadSafeJobStateManager()

        # Connect Shared Worker Signals
        self.worker_signals = WorkerSignals()
        self.worker_signals.started.connect(self.on_download_started)
        self.worker_signals.progress.connect(self.on_download_progress)
        self.worker_signals.finished.connect(self.on_download_finished)
        self.worker_signals.error.connect(self.on_download_error)
        self.worker_signals.playlist_progress.connect(self.on_playlist_step)

        # Launch Download Consumer Thread
        self.download_worker = DownloadWorker(self.download_queue, self.worker_signals, self.state_manager)
        self.download_worker.start()

        # Launch Playlist Scheduler
        self.scheduler = PlaylistScheduler(self.state_manager)
        self.scheduler.download_triggered.connect(self.on_scheduled_download)

        # Launch HTTP API Server (Aligned parameters to match LocalApiServer's constructor)
        self.api_server = LocalApiServer(self.state_manager, port=5000)
        self.api_server.scheduler = self.scheduler  # Pass scheduler to API server
        self.api_server.signals.job_received.connect(self.on_job_enqueued)
        self.api_server.signals.cancel_requested.connect(self.on_cancel_requested)
        self.api_server.signals.folder_dialog_requested.connect(self.on_folder_dialog_requested)
        self.api_server.signals.file_dialog_requested.connect(self.on_file_dialog_requested)
        self.api_server.start()
        
        # Store for dialog results
        self.folder_dialog_result = None
        self.file_dialog_result = None

        # Connect shutdown signal
        self.download_worker.signals.shutdown_requested.connect(self.on_shutdown_requested)

        # Connect remaining signal connections
        self.api_server.signals.cancel_requested.connect(self.on_cancel_requested)
        self.api_server.signals.folder_dialog_requested.connect(self.on_folder_dialog_requested)
        self.api_server.signals.file_dialog_requested.connect(self.on_file_dialog_requested)
        
        # Track embedded video window
        self.embedded_window = None

        print("🚀 Headless Video Downloader Bridge initialized successfully!")
        runtime_info = resolve_js_runtime()
        if runtime_info["available"]:
            runtime_name = "Deno" if runtime_info["runtime"] == "deno" else "Node.js"
            print(f"🧠 yt-dlp JavaScript runtime: {runtime_name} ({runtime_info['path']})")
        else:
            print("🧠 yt-dlp JavaScript runtime: not found")
        print("🟢 Flask local API server listening on http://127.0.0.1:5000")
        print("📌 Injected userscript will automatically communicate layout parameters back here.")
        print("⚙️  Settings API: GET/POST http://127.0.0.1:5000/api/settings")
        print("📅 Playlist scheduler active")

        # Setup system tray after methods are defined
        self.setup_system_tray()
        print("🔔 System tray icon active")
        
        # Connect embedded window signal after method is defined
        self.api_server.signals.embedded_window_requested.connect(self.open_embedded_window)

    @pyqtSlot(dict)
    def on_job_enqueued(self, job_payload):
        print(f"📦 [Queued Task] {job_payload.get('custom_title') or 'Video'} -> Added to downloader.")
        job_id = job_payload.get('id')
        # Store original payload for retry
        if job_id:
            self.state_manager.update_job(job_id, original_payload=job_payload)
        
        # Check if download scheduling is enabled
        from settings import load_settings
        settings = load_settings()
        scheduling_enabled = settings.get('download_scheduling_enabled', False)
        scheduled_time = settings.get('download_scheduled_time', '')
        
        if scheduling_enabled and scheduled_time:
            from datetime import datetime, timedelta
            
            # Parse scheduled time
            try:
                scheduled_hour, scheduled_min = map(int, scheduled_time.split(':'))
                now = datetime.now()
                scheduled_datetime = now.replace(hour=scheduled_hour, minute=scheduled_min, second=0, microsecond=0)
                
                # If scheduled time has passed today, schedule for tomorrow
                if scheduled_datetime <= now:
                    scheduled_datetime += timedelta(days=1)
                
                delay_seconds = (scheduled_datetime - now).total_seconds()
                print(f"[Scheduling] Download scheduled for {scheduled_datetime} (in {delay_seconds:.0f} seconds)")
                
                def schedule_download():
                    time.sleep(delay_seconds)
                    print(f"[Scheduling] Starting scheduled download")
                    self.download_queue.put(job_payload)
                
                try:
                    schedule_thread = threading.Thread(target=schedule_download)
                    schedule_thread.daemon = True
                    schedule_thread.start()
                except Exception as e:
                    print(f"[Scheduling] Error starting schedule thread: {e}")
                    self.download_queue.put(job_payload)  # Fallback to immediate download
            except Exception as e:
                print(f"[Scheduling] Error parsing scheduled time: {e}")
                self.download_queue.put(job_payload)
        else:
            self.download_queue.put(job_payload)

    @pyqtSlot(str)
    def on_cancel_requested(self, job_id):
        did_cancel = self.download_worker.cancel_job(job_id)
        if did_cancel:
            print(f"🛑 [Cancelled Task] Current running process with ID: {job_id} terminated immediately.")
        else:
            print(f"🗑️ [Removed Task] Queued Job with ID: {job_id} marked as cancelled.")

    @pyqtSlot(dict)
    def on_scheduled_download(self, schedule_data):
        """Handle a triggered scheduled download."""
        import time
        settings = schedule_data.get('settings', {})
        url = schedule_data.get('url')
        
        job_id = f"job_{int(time.time() * 1000)}"
        
        job_payload = {
            'id': job_id,
            'url': url,
            'custom_title': f"Scheduled: {url}",
            'prefix': settings.get('prefix', ''),
            'disable_title': settings.get('disable_title', False),
            'use_numbering': settings.get('use_numbering', True),
            'is_playlist': True,
            'out_format': settings.get('out_format', 'mp4'),
            'resolution': str(settings.get('resolution', '1080')),
            'subs_mode': settings.get('subs_mode', 'none'),
            'selected_subs': settings.get('selected_subs', []),
            'folder': settings.get('folder', ''),
            'cookies': ''
        }
        
        print(f"📅 [Scheduled Download] Enqueuing: {url}")
        self.state_manager.add_job(job_id, f"Scheduled Playlist", url, is_playlist=True)
        self.download_queue.put(job_payload)

    @pyqtSlot()
    def on_folder_dialog_requested(self):
        """Open native folder dialog and store result."""
        print("📁 [Folder Dialog] Opening native folder picker...")
        folder = QFileDialog.getExistingDirectory(None, "Select Download Folder", "")
        self.folder_dialog_result = folder
        self.api_server.folder_dialog_result = folder  # Also set on API server
        print(f"📁 [Folder Dialog] Selected: {folder}")

    @pyqtSlot(dict)
    def on_file_dialog_requested(self, dialog_data):
        """Open native file dialog and store result."""
        print("📄 [File Dialog] Opening native file picker...")
        title = dialog_data.get('title', 'Select File')
        file_filter = dialog_data.get('filter', 'All files (*.*)|*.*')
        
        file_path, _ = QFileDialog.getOpenFileName(None, title, "", file_filter)
        self.file_dialog_result = file_path
        self.api_server.file_dialog_result = file_path  # Also set on API server
        print(f"📄 [File Dialog] Selected: {file_path}")

    @pyqtSlot()
    def on_shutdown_requested(self):
        """Handle auto-shutdown request from download worker."""
        print("🔌 [Auto-Shutdown] Quitting application...")
        QApplication.quit()

    @pyqtSlot(str)
    def on_download_started(self, job_id):
        print(f"🔥 [Download Started] Processing Job ID: {job_id}")

    @pyqtSlot(str, int, str, str, str)
    def on_download_progress(self, job_id, percent, status, speed, eta):
        self.state_manager.update_job(
            job_id,
            percent=percent,
            status=status,
            speed=speed,
            eta=eta
        )

    @pyqtSlot(str, int, int, str)
    def on_playlist_step(self, job_id, index, total, current_title):
        print(f"📂 [Playlist Progress] Job {job_id}: Processing video {index} of {total} ({current_title})")

    @pyqtSlot(str, str, str)
    def on_download_finished(self, job_id, url, file_path):
        print(f"✅ [Download Finished] Completed Task: {job_id} -> Saved to: {file_path}")
        
        # Add to download history
        from downloader import add_to_download_history, update_download_statistics
        job_info = self.state_manager.get_all_jobs().get(job_id, {})
        title = job_info.get('title', job_info.get('current_video_title', 'Unknown'))
        add_to_download_history(url, title, file_path, success=True)
        
        # Update statistics with file size
        try:
            import os
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            update_download_statistics(file_size, success=True)
        except Exception as e:
            print(f"[Statistics] Error getting file size: {e}")

        # Show desktop notification if enabled
        from settings import load_settings
        settings = load_settings()
        notifications_enabled = settings.get('desktop_notifications_enabled', False)
        sound_enabled = settings.get('desktop_notifications_sound', False)
        
        if notifications_enabled:
            self.show_desktop_notification(title, file_path, sound_enabled)

        # Post-download format conversion if enabled
        post_conversion_enabled = settings.get('post_conversion_enabled', False)
        target_format = settings.get('post_conversion_target_format', 'mp4')
        
        if post_conversion_enabled:
            self.convert_video_format(file_path, target_format, title)

    def show_desktop_notification(self, title, file_path, sound_enabled):
        """Show desktop notification for download completion."""
        try:
            from PyQt5.QtWidgets import QSystemTrayIcon
            if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
                self.tray_icon.showMessage(
                    "Download Complete",
                    f"{title}\nSaved to: {file_path}",
                    QSystemTrayIcon.Information,
                    5000  # 5 seconds
                )
                print(f"[Notification] Desktop notification shown for: {title}")
                
                if sound_enabled:
                    # Play default system notification sound
                    try:
                        import winsound
                        winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    except:
                        pass  # Sound not available on this platform
        except Exception as e:
            print(f"[Notification] Error showing notification: {e}")

    def convert_video_format(self, file_path, target_format, title):
        """Convert video to target format using ffmpeg."""
        try:
            import os
            import subprocess
            
            # Check if file exists
            if not os.path.exists(file_path):
                print(f"[Conversion] File not found: {file_path}")
                return
            
            # Generate output path
            base_path = os.path.splitext(file_path)[0]
            output_path = f"{base_path}.{target_format}"
            
            # Skip if already in target format
            if file_path.lower().endswith(f".{target_format.lower()}"):
                print(f"[Conversion] File already in {target_format} format")
                return
            
            print(f"[Conversion] Converting {title} to {target_format}...")
            
            # Run ffmpeg conversion
            cmd = ['ffmpeg', '-i', file_path, '-c', 'copy', output_path, '-y']
            subprocess.run(cmd, check=True, capture_output=True, creationflags=0x08000000 if sys.platform.startswith('win') else 0)
            
            print(f"[Conversion] Successfully converted to: {output_path}")
            
            # Optionally delete original file
            try:
                os.remove(file_path)
                print(f"[Conversion] Removed original file: {file_path}")
            except Exception as e:
                print(f"[Conversion] Warning: Could not remove original file: {e}")
                
        except subprocess.CalledProcessError as e:
            print(f"[Conversion] Error during conversion: {e}")
        except Exception as e:
            print(f"[Conversion] Error: {e}")

    @pyqtSlot(str, str)
    def on_download_error(self, job_id, error_msg):
        print(f"❌ [Error] Task {job_id} experienced a failure: {error_msg}")

        # Check if auto-retry is enabled
        from settings import load_settings
        settings = load_settings()
        auto_retry_enabled = settings.get('auto_retry_enabled', False)
        max_attempts = settings.get('auto_retry_max_attempts', 3)
        retry_delay = settings.get('auto_retry_delay', 5)

        if auto_retry_enabled:
            job_info = self.state_manager.get_all_jobs().get(job_id, {})
            retry_count = job_info.get('retry_count', 0)
            original_payload = job_info.get('original_payload')

            if retry_count < max_attempts and original_payload:
                print(f"🔄 [Auto-Retry] Retrying job {job_id} (attempt {retry_count + 1}/{max_attempts})")
                
                # Increment retry count
                self.state_manager.update_job(job_id, retry_count=retry_count + 1, status='queued')
                
                # Re-queue the job after delay
                import threading
                def retry_job():
                    import time
                    time.sleep(retry_delay)
                    print(f"🔄 [Auto-Retry] Re-queueing job {job_id}")
                    self.download_queue.put(original_payload)
                
                retry_thread = threading.Thread(target=retry_job)
                retry_thread.daemon = True
                retry_thread.start()
            else:
                print(f"❌ [Auto-Retry] Max retry attempts reached for job {job_id}")
        else:
            print(f"❌ [Auto-Retry] Auto-retry is disabled")

    def setup_system_tray(self):
        """Setup system tray icon with context menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("⚠️ System tray not available on this system")
            return

        # Load custom icon or use default
        settings = load_settings()
        use_custom_icon = settings.get('use_custom_tray_icon', False)
        
        # Try to load custom icon first if enabled
        icon = None
        if use_custom_icon:
            icon = self._load_custom_icon()
            if icon:
                print("🔔 Using custom tray icon")
        
        # If custom icon failed or not enabled, try default icon
        if not icon:
            icon = self._load_default_icon()
            if icon:
                print("🔔 Using default tray icon")

        # If still no icon, use Qt standard icon
        if not icon:
            icon = self._get_fallback_icon()
            print("🔔 Using Qt standard icon as fallback")

        self.tray_icon = QSystemTrayIcon(icon)
        self.tray_icon.setToolTip("Video Downloader Bridge")

        # Create context menu
        self.tray_menu = QMenu()
        
        # Status action
        self.status_action = QAction("Status: Idle", self.tray_menu)
        self.status_action.setEnabled(False)
        self.tray_menu.addAction(self.status_action)
        
        self.tray_menu.addSeparator()
        
        # Queue info action
        self.queue_action = QAction("Queue: 0 items", self.tray_menu)
        self.queue_action.setEnabled(False)
        self.tray_menu.addAction(self.queue_action)
        
        self.tray_menu.addSeparator()

        # User Guide action
        guide_action = QAction("📖 User Guide (README)", self.tray_menu)
        guide_action.triggered.connect(self.show_readme_dialog)
        self.tray_menu.addAction(guide_action)

        # Check for updates action
        update_action = QAction("🔄 Check for Updates", self.tray_menu)
        update_action.triggered.connect(self.show_update_dialog)
        self.tray_menu.addAction(update_action)

        self.tray_menu.addSeparator()

        # Exit action
        exit_action = QAction("🚪 Exit", self.tray_menu)
        exit_action.triggered.connect(self.quit_application)
        self.tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(self.tray_menu)
        
        # Connect click event to show about dialog
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        
        # Try to position menu above icon when shown
        self.tray_menu.aboutToShow.connect(self._position_menu_above)
        
        self.tray_icon.show()

        # Update tray status periodically
        self.update_tray_status()

    def _load_icon_from_path(self, icon_path):
        """Load icon from file path, supporting multiple formats."""
        try:
            # Qt QIcon supports: PNG, JPG, JPEG, BMP, ICO, SVG, and more
            icon = QIcon(icon_path)
            if not icon.isNull():
                return icon
            return None
        except Exception as e:
            print(f"⚠️ Failed to load icon from {icon_path}: {e}")
            return None

    def _load_custom_icon(self):
        """Load custom icon from application directory (custom_icon.*)."""
        app_dir = os.path.dirname(os.path.abspath(__file__))
        icon_names = ['custom_icon.png', 'custom_icon.ico', 'custom_icon.jpg', 
                      'custom_icon.jpeg', 'custom_icon.svg', 'custom_icon.bmp']
        
        for icon_name in icon_names:
            icon_path = os.path.join(app_dir, icon_name)
            if os.path.exists(icon_path):
                icon = self._load_icon_from_path(icon_path)
                if icon:
                    return icon
        
        return None

    def _load_default_icon(self):
        """Load default icon from application directory (tray_icon.*)."""
        app_dir = os.path.dirname(os.path.abspath(__file__))
        icon_names = ['tray_icon.png', 'tray_icon.ico', 'tray_icon.jpg', 
                      'tray_icon.jpeg', 'tray_icon.svg', 'tray_icon.bmp']
        
        for icon_name in icon_names:
            icon_path = os.path.join(app_dir, icon_name)
            if os.path.exists(icon_path):
                icon = self._load_icon_from_path(icon_path)
                if icon:
                    return icon
        
        return None

    def _get_fallback_icon(self):
        """Create a fallback icon using Qt's standard icons."""
        from PyQt5.QtWidgets import QStyle
        style = QApplication.style()
        return style.standardIcon(QStyle.SP_ComputerIcon)

    def _position_menu_up(self):
        """Position the context menu to appear above the tray icon."""
        try:
            from PyQt5.QtWidgets import QStyle
            menu = self.tray_menu
            menu.setStyleSheet("QMenu { menu-scrollable: 1; }")
        except Exception as e:
            print(f"Error positioning menu: {e}")

    def _position_menu_above(self):
        """Position the context menu to appear above the tray icon."""
        try:
            from PyQt5.QtGui import QCursor
            cursor_pos = QCursor.pos()
            screen = QApplication.screenAt(cursor_pos)
            if screen:
                screen_geometry = screen.availableGeometry()
                menu = self.tray_menu
                menu_height = menu.sizeHint().height()
                
                # Position menu above the cursor position
                menu_pos = cursor_pos
                menu_pos.setY(menu_pos.y() - menu_height - 10)
                
                # Ensure menu stays within screen bounds
                if menu_pos.y() < screen_geometry.top():
                    menu_pos.setY(screen_geometry.top())
                
                menu.move(menu_pos)
        except Exception as e:
            print(f"Error positioning menu: {e}")

    def update_tray_status(self):
        """Update system tray status with current download information."""
        jobs = self.state_manager.get_all_jobs()
        
        # Count active downloads and get detailed info
        active_count = 0
        downloading_count = 0
        queued_count = 0
        completed_count = 0
        total_percent = 0
        playlist_info = ""
        
        for job in jobs.values():
            status = job['status']
            if status == 'downloading':
                active_count += 1
                downloading_count += 1
                total_percent += job.get('percent', 0)
                
                # Add playlist progress if available
                if job.get('is_playlist') and job.get('playlist_total', 0) > 0:
                    current = job.get('playlist_index', 0)
                    total = job.get('playlist_total', 0)
                    playlist_info = f" | Playlist: {current}/{total}"
            elif status == 'queued':
                active_count += 1
                queued_count += 1
            elif status == 'completed':
                completed_count += 1
        
        # Calculate average download progress
        avg_percent = total_percent // downloading_count if downloading_count > 0 else 0
        
        # Update status text with detailed information
        if downloading_count > 0:
            status_text = f"Downloading: {downloading_count} active ({avg_percent}%){playlist_info}"
        elif queued_count > 0:
            status_text = f"Queued: {queued_count} waiting"
        elif completed_count > 0:
            status_text = f"Recently completed: {completed_count}"
        else:
            status_text = "Status: Idle"
        
        self.status_action.setText(status_text)
        self.queue_action.setText(f"Queue: {len(jobs)} items ({queued_count} queued)")
        
        # Update tooltip with detailed information
        tooltip_text = f"Video Downloader Bridge\n{status_text}\nTotal Queue: {len(jobs)} items"
        self.tray_icon.setToolTip(tooltip_text)
        
        # Schedule next update
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(2000, self.update_tray_status)

    def on_tray_icon_activated(self, reason):
        """Handle tray icon activation to show about dialog on left click."""
        # Only respond to left click (Trigger) and double click
        # Right click (Context) shows the context menu automatically
        if PYQT_VERSION == 5:
            from PyQt5.QtWidgets import QSystemTrayIcon
            activation_reasons = [QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick]
        else:
            from PyQt6.QtWidgets import QSystemTrayIcon
            activation_reasons = [QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick]

        if reason in activation_reasons:
            self.show_about_dialog()

    def show_about_dialog(self):
        """Show about dialog with creator information and update button."""
        about_text = f"""
        <h3>YouTube Desktop Downloader Bridge Pro</h3>
        <p><b>Version:</b> {CURRENT_VERSION}</p>
        <p><b>Creator:</b> Entity6814 (Vatsal Patel)</p>
        <p><b>License:</b> MIT License</p>
        <p><b>GitHub:</b> https://github.com/Entity6814/YTDownloader</p>
        <hr>
        <p><b>Description:</b><br>
        A powerful YouTube video downloader with playlist support, format conversion,
        and advanced scheduling features. Built with PyQt5, Flask, and yt-dlp.</p>
        <hr>
        <p><b>Legal Disclaimer:</b><br>
        This tool is for educational and personal use only. Users are responsible for
        ensuring they have the right to download content. The creator is not responsible
        for misuse of this software.</p>
        <hr>
        <p><b>Bug Fixes:</b><br>
        Bug fixes and updates may take time due to personal development schedule.
        Community contributions are welcome!</p>
        <hr>
        <p><b>Acknowledgments:</b><br>
        • yt-dlp team for the excellent YouTube downloader<br>
        • PyQt5/PyQt6 teams for the GUI framework<br>
        • Flask team for the web server framework</p>
        """
        
        dialog = QDialog()
        dialog.setWindowTitle("About YouTube Desktop Downloader")
        dialog.setMinimumWidth(450)

        layout = QVBoxLayout()

        info_label = QLabel(about_text)
        info_label.setWordWrap(True)
        info_label.setTextFormat(Qt.RichText)
        layout.addWidget(info_label)

        # Add buttons
        button_layout = QVBoxLayout()

        # Update button
        update_button = QPushButton("🔄 Check for Updates")
        update_button.clicked.connect(lambda: [dialog.close(), self.show_update_dialog()])
        button_layout.addWidget(update_button)

        # User Guide button
        guide_button = QPushButton("📖 User Guide (README)")
        guide_button.clicked.connect(lambda: [dialog.close(), self.show_readme_dialog()])
        button_layout.addWidget(guide_button)

        layout.addLayout(button_layout)
        
        # Add close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)
        
        dialog.setLayout(layout)
        dialog.exec_()

class EmbeddedVideoWindow(QWidget):
    """PyQt window for embedded YouTube video download options."""
    
    def __init__(self, url, video_id, state_manager):
        super().__init__()
        self.url = url
        self.video_id = video_id
        self.state_manager = state_manager
        self.download_settings = {}
        self.setWindowFlags(WindowStaysOnTopHint | FramelessWindowHint)
        self.resize(450, 500)
        self.setup_ui()
        self.load_saved_settings()
        
    def setup_ui(self):
        """Setup the UI for the embedded video window."""
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header
        header = QLabel("⬇ Download Options")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #e8eaf0;")
        layout.addWidget(header)
        
        # Video info
        video_info = QLabel(f"Video ID: {self.video_id}")
        video_info.setStyleSheet("font-size: 11px; color: #8b8fa8;")
        layout.addWidget(video_info)
        
        # Format selection
        format_group = QGroupBox("Format")
        format_layout = QVBoxLayout()
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["MP4 Video", "MKV Video", "WebM Video", "MP3 Audio", "WAV Audio"])
        self.format_combo.setStyleSheet("background: #0a0c10; color: #e8eaf0; padding: 8px; border: 1px solid #252836;")
        format_layout.addWidget(self.format_combo)
        
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["Best", "1080p", "720p", "480p", "360p"])
        self.resolution_combo.setStyleSheet("background: #0a0c10; color: #e8eaf0; padding: 8px; border: 1px solid #252836;")
        format_layout.addWidget(self.resolution_combo)
        
        format_group.setLayout(format_layout)
        format_group.setStyleSheet("color: #e8eaf0; border: 1px solid #252836; margin-top: 10px;")
        layout.addWidget(format_group)
        
        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout()
        
        self.download_thumbnail = QCheckBox("Download thumbnail")
        self.download_thumbnail.setStyleSheet("color: #e8eaf0;")
        options_layout.addWidget(self.download_thumbnail)
        
        self.embed_thumbnail = QCheckBox("Embed thumbnail in audio")
        self.embed_thumbnail.setStyleSheet("color: #e8eaf0;")
        options_layout.addWidget(self.embed_thumbnail)
        
        options_group.setLayout(options_layout)
        options_group.setStyleSheet("color: #e8eaf0; border: 1px solid #252836; margin-top: 10px;")
        layout.addWidget(options_group)
        
        # Download button
        download_btn = QPushButton("▶ Add to Download Queue")
        download_btn.setStyleSheet("""
            QPushButton {
                background: #7c6af7;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #6a58e0;
            }
        """)
        download_btn.clicked.connect(self.start_download)
        layout.addWidget(download_btn)
        
        # Close button
        close_btn = QPushButton("✕ Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8b8fa8;
                border: 1px solid #252836;
                padding: 8px;
                border-radius: 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.1);
                color: #e8eaf0;
            }
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Window styling
        self.setStyleSheet("""
            QWidget {
                background: #14151a;
                color: #e8eaf0;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)
        
        # Handle focus loss for auto-hide
        self.installEventFilter(self)
    
    def eventFilter(self, obj, event):
        """Handle focus loss to auto-hide the window."""
        if event.type() == event.Type.FocusOut:
            self.save_settings()
            self.hide()
        return super().eventFilter(obj, event)
    
    def load_saved_settings(self):
        """Load saved settings for this video."""
        try:
            if os.path.exists('embedded_settings.json'):
                with open('embedded_settings.json', 'r') as f:
                    settings = json.load(f)
                    video_settings = settings.get(self.video_id, {})
                    
                    if 'format' in video_settings:
                        index = self.format_combo.findText(video_settings['format'])
                        if index >= 0:
                            self.format_combo.setCurrentIndex(index)
                    
                    if 'resolution' in video_settings:
                        index = self.resolution_combo.findText(video_settings['resolution'])
                        if index >= 0:
                            self.resolution_combo.setCurrentIndex(index)
                    
                    self.download_thumbnail.setChecked(video_settings.get('download_thumbnail', False))
                    self.embed_thumbnail.setChecked(video_settings.get('embed_thumbnail', False))
        except Exception as e:
            print(f"Error loading embedded settings: {e}")
    
    def save_settings(self):
        """Save current settings for this video."""
        try:
            settings = {}
            if os.path.exists('embedded_settings.json'):
                with open('embedded_settings.json', 'r') as f:
                    settings = json.load(f)
            
            settings[self.video_id] = {
                'format': self.format_combo.currentText(),
                'resolution': self.resolution_combo.currentText(),
                'download_thumbnail': self.download_thumbnail.isChecked(),
                'embed_thumbnail': self.embed_thumbnail.isChecked()
            }
            
            with open('embedded_settings.json', 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Error saving embedded settings: {e}")
    
    def start_download(self):
        """Start the download with current settings."""
        self.save_settings()
        
        # Map format selection to backend format
        format_map = {
            "MP4 Video": "mp4",
            "MKV Video": "mkv", 
            "WebM Video": "webm",
            "MP3 Audio": "mp3",
            "WAV Audio": "wav"
        }
        
        # Map resolution to backend resolution
        resolution_map = {
            "Best": "best",
            "1080p": "1080",
            "720p": "720", 
            "480p": "480",
            "360p": "360"
        }
        
        payload = {
            'url': self.url,
            'out_format': format_map.get(self.format_combo.currentText(), "mp4"),
            'resolution': resolution_map.get(self.resolution_combo.currentText(), "best"),
            'download_thumbnail': self.download_thumbnail.isChecked(),
            'embed_thumbnail': self.embed_thumbnail.isChecked(),
            'advanced_mode': True
        }
        
        # Use HTTP request to enqueue download
        try:
            import urllib.request
            import urllib.parse
            import json
            
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                'http://localhost:5000/api/enqueue',
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    print("Download started successfully")
                    self.close()
                else:
                    print(f"Failed to start download: {response.status}")
        except Exception as e:
            print(f"Error starting download: {e}")

    def open_settings_in_browser(self):
        """Open settings panel in browser by triggering API signal."""
        print("📂 Opening settings in browser...")
        # The userscript should handle opening settings when the API is called
        # For now, just print a message - the user can open settings from the browser
        print("   Please open YouTube and click the settings button in the downloader console")

    def shutdown(self):
        print("Shutting down background service threads...")
        self.api_server.terminate()
        self.api_server.wait()
        self.download_worker.stop()
        self.download_worker.wait()
        
        # Hide tray icon
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Prevent app from closing when folder dialog closes
    coordinator = HeadlessDownloaderApp()

    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        coordinator.shutdown()
        print("Headless service stopped safely.")
