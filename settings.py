import os
import json
import subprocess
import shutil

# Professional app data directory structure
APP_DATA_DIR = os.path.join(os.path.expanduser("~"), "video_downloader")
CACHE_DIR = os.path.join(APP_DATA_DIR, "cache")
DATA_DIR = os.path.join(APP_DATA_DIR, "data")
LOGS_DIR = os.path.join(APP_DATA_DIR, "logs")

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
VIDEO_METADATA_DB = os.path.join(DATA_DIR, "video_metadata.json")

def ensure_app_data_structure():
    """Ensure the professional app data directory structure exists."""
    directories = [APP_DATA_DIR, CACHE_DIR, DATA_DIR, LOGS_DIR]
    
    for directory in directories:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                print(f"[App Data] Created directory: {directory}")
            except Exception as e:
                print(f"[App Data] Failed to create directory {directory}: {e}")

def migrate_old_data():
    """Migrate data from old locations to new professional structure."""
    old_app_data_dir = os.path.join(os.path.expanduser("~"), ".video_downloader")
    old_settings_file = os.path.join(os.path.expanduser("~"), ".headless_downloader_settings.json")
    old_history_file = os.path.join(os.path.expanduser("~"), ".video_downloader_history.json")
    old_stats_file = os.path.join(os.path.expanduser("~"), ".video_downloader_stats.json")
    
    # Migrate from old app directory if it exists
    if os.path.exists(old_app_data_dir):
        print(f"[Migration] Found old app data directory: {old_app_data_dir}")
        
        # Migrate cache
        old_cache_dir = os.path.join(old_app_data_dir, 'cache')
        if os.path.exists(old_cache_dir) and not os.path.exists(CACHE_DIR):
            try:
                shutil.copytree(old_cache_dir, CACHE_DIR)
                print(f"[Migration] Migrated cache from {old_cache_dir}")
            except Exception as e:
                print(f"[Migration] Failed to migrate cache: {e}")
        
        # Migrate settings from old app directory
        old_settings_in_app = os.path.join(old_app_data_dir, "headless_downloader_settings.json")
        if os.path.exists(old_settings_in_app) and not os.path.exists(SETTINGS_FILE):
            try:
                shutil.copy2(old_settings_in_app, SETTINGS_FILE)
                print(f"[Migration] Migrated settings from {old_settings_in_app}")
            except Exception as e:
                print(f"[Migration] Failed to migrate settings: {e}")
        
        # Migrate video metadata from old app directory
        old_metadata_in_app = os.path.join(old_app_data_dir, "video_metadata.json")
        if os.path.exists(old_metadata_in_app) and not os.path.exists(VIDEO_METADATA_DB):
            try:
                shutil.copy2(old_metadata_in_app, VIDEO_METADATA_DB)
                print(f"[Migration] Migrated metadata from {old_metadata_in_app}")
            except Exception as e:
                print(f"[Migration] Failed to migrate metadata: {e}")
    
    # Migrate from home directory (old locations)
    if os.path.exists(old_settings_file) and not os.path.exists(SETTINGS_FILE):
        try:
            shutil.copy2(old_settings_file, SETTINGS_FILE)
            print(f"[Migration] Migrated settings from {old_settings_file}")
        except Exception as e:
            print(f"[Migration] Failed to migrate settings: {e}")
    
    if os.path.exists(old_history_file) and not os.path.exists(os.path.join(DATA_DIR, "download_history.json")):
        try:
            new_history_file = os.path.join(DATA_DIR, "download_history.json")
            shutil.copy2(old_history_file, new_history_file)
            print(f"[Migration] Migrated history from {old_history_file}")
        except Exception as e:
            print(f"[Migration] Failed to migrate history: {e}")
    
    if os.path.exists(old_stats_file) and not os.path.exists(os.path.join(DATA_DIR, "download_statistics.json")):
        try:
            new_stats_file = os.path.join(DATA_DIR, "download_statistics.json")
            shutil.copy2(old_stats_file, new_stats_file)
            print(f"[Migration] Migrated statistics from {old_stats_file}")
        except Exception as e:
            print(f"[Migration] Failed to migrate statistics: {e}")

# Ensure directory structure exists when module is loaded
ensure_app_data_structure()
# Migrate existing data to new professional structure
migrate_old_data()

DEFAULT_SETTINGS = {
    # === Download Location ===
    "folder": os.path.join(os.path.expanduser("~"), "Downloads"),

    # === Video Quality ===
    "resolution": "1080",
    "out_format": "original",

    # === Title & Naming ===
    "disable_title": False,
    "prefix": "",
    "use_numbering": True,

    # === Subtitles ===
    "subs_mode": "none",          # "none" | "embed" | "external_srt"
    "selected_subs": [],

    # === Floating Console ===
    "console_position": {
        "mode": "bottom-right",   # "bottom-right" | "free"
        "left": None,
        "top": None
    },
    "console_hidden": False,

    # === UI Mode ===
    "ui_mode": "basic",            # "basic" | "advanced"

    # === Advanced Features ===
    "auto_shutdown": False,        # Shutdown app after downloads complete
    "pc_shutdown": False,          # Shutdown PC after downloads complete
    "use_custom_tray_icon": False, # Use custom tray icon instead of default
    "download_thumbnail": False,  # Download thumbnail as separate file
    "embed_thumbnail": False,     # Embed thumbnail in audio files (MP3/WAV)
    "disable_archive": False,     # Disable download.txt archive file creation
    "thumbnail_only": False,      # Download only thumbnail (no video)
    "custom_args": "",            # Custom yt-dlp arguments

    # === Format Presets ===
    "format_presets": {},         # Saved format configurations

    # === Auto-Retry Settings ===
    "auto_retry_enabled": False,  # Enable automatic retry of failed downloads
    "auto_retry_max_attempts": 3, # Maximum number of retry attempts
    "auto_retry_delay": 5,        # Delay between retries in seconds

    # === Download History Settings ===
    "download_history_enabled": True,  # Enable download history tracking
    "download_history_max_entries": 1000,  # Maximum history entries to keep

    # === Speed Limiting Settings ===
    "speed_limit_enabled": False,  # Enable download speed limiting
    "speed_limit_value": "10M",    # Speed limit (e.g., 10M for 10 MB/s)

    # === Playlist Filtering Settings ===
    "playlist_filter_enabled": False,  # Enable playlist filtering
    "playlist_filter_min_duration": "",  # Minimum duration (e.g., 5:00, 300s)
    "playlist_filter_max_duration": "",  # Maximum duration (e.g., 30:00, 1800s)
    "playlist_filter_min_views": "",     # Minimum view count
    "playlist_filter_max_views": "",     # Maximum view count
    "playlist_filter_date_after": "",    # Only videos after this date (YYYYMMDD)
    "playlist_filter_date_before": "",   # Only videos before this date (YYYYMMDD)

    # === Desktop Notifications Settings ===
    "desktop_notifications_enabled": False,  # Enable desktop notifications
    "desktop_notifications_sound": False,    # Play sound with notifications

    # === Post-Download Conversion Settings ===
    "post_conversion_enabled": False,  # Enable post-download format conversion
    "post_conversion_target_format": "mp4",  # Target format for conversion

    # === Download Statistics Settings ===
    "download_statistics_enabled": True,  # Enable download statistics tracking

    # === Download Scheduling Settings ===
    "download_scheduling_enabled": False,  # Enable download scheduling
    "download_scheduled_time": "",  # Scheduled time (HH:MM format)

    # === Multi-threaded Downloads Settings ===
    "multi_threaded_enabled": False,  # Enable multi-threaded downloads
    "multi_threaded_threads": 4,  # Number of concurrent threads

    # === Proxy Support Settings ===
    "proxy_enabled": False,  # Enable proxy support
    "proxy_url": "",  # Proxy URL (e.g., http://proxy.example.com:8080)

    # === Audio Normalization Settings ===
    "audio_normalization_enabled": False,  # Enable audio normalization

    # === Chapter/Segment Support Settings ===
    "download_chapters": False,  # Download as separate chapters
    "download_sections": "",  # Specific sections to download (e.g., "*10-15,20-30")

}


def resolve_js_runtime() -> dict:
    """Detect the best available JavaScript runtime for yt-dlp.

    yt-dlp supports `--js-runtimes` and prefers Deno over Node when both are
    available. We mirror that preference here so every launch path can reuse it.
    """
    candidates = (
        ("deno", "deno"),
        ("node", "node"),
    )

    for runtime, binary in candidates:
        path = shutil.which(binary)
        if path:
            return {
                "available": True,
                "runtime": runtime,
                "binary": binary,
                "path": path,
            }

    return {
        "available": False,
        "runtime": "",
        "binary": "",
        "path": "",
    }


def build_yt_dlp_js_args() -> list:
    """Build yt-dlp CLI args that enable the best available JS runtime."""
    runtime = resolve_js_runtime()
    if not runtime["available"]:
        return []

    return ["--js-runtimes", f'{runtime["runtime"]}:{runtime["path"]}']


def load_settings() -> dict:
    """Load configuration dictionary from disk or fallback to factory defaults.
    
    Performs a safe overlay so that any new keys added to DEFAULT_SETTINGS
    are always present even when loading an older saved file.
    """
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # Overlay saved values onto defaults for forward-compatibility
            merged = DEFAULT_SETTINGS.copy()
            merged.update(saved)
            return merged
        except (json.JSONDecodeError, OSError, IOError) as e:
            print(f"⚠️ Error reading settings file, resetting defaults: {e}")
    return DEFAULT_SETTINGS.copy()


def save_settings(settings_dict: dict) -> bool:
    """Persist settings dictionary to disk at the well-known path."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=None, separators=(',', ':'), ensure_ascii=False)
        return True
    except (OSError, IOError, TypeError) as e:
        print(f"❌ Failed to persist user settings: {e}")
        return False


def reset_settings() -> dict:
    """Wipe saved settings and return fresh defaults."""
    if os.path.exists(SETTINGS_FILE):
        try:
            os.remove(SETTINGS_FILE)
        except (OSError, IOError) as e:
            print(f"⚠️ Could not delete settings file: {e}")
    return DEFAULT_SETTINGS.copy()


def check_system_dependencies() -> dict:
    """Verify vital command-line binaries exist in system PATH environment."""
    report = {"yt_dlp": False, "ffmpeg": False, "js_runtime": False}

    # Check yt-dlp
    if shutil.which("yt-dlp"):
        report["yt_dlp"] = True
    else:
        try:
            subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            report["yt_dlp"] = True
        except FileNotFoundError:
            pass

    # Check ffmpeg
    if shutil.which("ffmpeg"):
        report["ffmpeg"] = True
    else:
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            report["ffmpeg"] = True
        except FileNotFoundError:
            pass

    report["js_runtime"] = resolve_js_runtime()["available"]

    return report
