import os
import sys
import json
import time
import queue
import threading
import subprocess
import shutil
import re
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, QThread, pyqtSlot
from PyQt5.QtWidgets import QApplication
from settings import build_yt_dlp_js_args, APP_DATA_DIR, DATA_DIR, VIDEO_METADATA_DB

# Download history file
DOWNLOAD_HISTORY_FILE = os.path.join(DATA_DIR, "download_history.json")

# Download statistics file
DOWNLOAD_STATISTICS_FILE = os.path.join(DATA_DIR, "download_statistics.json")

def add_to_download_history(url, title, file_path, success=True):
    """Add a download entry to history."""
    try:
        history = []
        if os.path.exists(DOWNLOAD_HISTORY_FILE):
            with open(DOWNLOAD_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        
        from settings import load_settings
        settings = load_settings()
        max_entries = settings.get('download_history_max_entries', 1000)
        history_enabled = settings.get('download_history_enabled', True)
        
        if not history_enabled:
            return
        
        entry = {
            'timestamp': datetime.now().isoformat(),
            'url': url,
            'title': title,
            'file_path': file_path,
            'success': success
        }
        
        history.insert(0, entry)  # Add to beginning
        
        # Trim to max entries
        if len(history) > max_entries:
            history = history[:max_entries]
        
        with open(DOWNLOAD_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=None, separators=(',', ':'), ensure_ascii=False)
        
        print(f"[History] Added entry: {title}")
    except Exception as e:
        print(f"[History] Error adding entry: {e}")

def update_download_statistics(file_size, success=True):
    """Update download statistics."""
    try:
        from settings import load_settings
        settings = load_settings()
        stats_enabled = settings.get('download_statistics_enabled', True)
        
        if not stats_enabled:
            return
        
        stats = {}
        if os.path.exists(DOWNLOAD_STATISTICS_FILE):
            with open(DOWNLOAD_STATISTICS_FILE, 'r', encoding='utf-8') as f:
                stats = json.load(f)
        
        stats['total_downloads'] = stats.get('total_downloads', 0) + 1
        if success:
            stats['successful_downloads'] = stats.get('successful_downloads', 0) + 1
            stats['total_data_downloaded'] = stats.get('total_data_downloaded', 0) + file_size
        else:
            stats['failed_downloads'] = stats.get('failed_downloads', 0) + 1
        
        stats['last_updated'] = datetime.now().isoformat()
        
        with open(DOWNLOAD_STATISTICS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=None, separators=(',', ':'), ensure_ascii=False)
        
        print(f"[Statistics] Updated: total={stats['total_downloads']}, success={stats['successful_downloads']}, data={stats['total_data_downloaded']}")
    except Exception as e:
        print(f"[Statistics] Error updating: {e}")

# Safe fallback imports for settings directory structures
try:
    from VedioDownloader.core.settings import BROWSER_PROFILE_DIR
except ModuleNotFoundError:
    BROWSER_PROFILE_DIR = ""

if sys.platform.startswith('win'):
    NO_WINDOW_FLAG = 0x08000000  # CREATE_NO_WINDOW
else:
    NO_WINDOW_FLAG = 0


# Compiled regular expression to strip terminal escape/ANSI formatting sequences instantly
ANSI_ESCAPE = re.compile(r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])')

def clean_ansi_escape_codes(text):
    """Removes ANSI escape codes and styling sequences to produce plain text."""
    return ANSI_ESCAPE.sub('', text)


def save_video_metadata(url, title, channel):
    """Save video metadata to centralized database."""
    try:
        metadata_db = {}
        if os.path.exists(VIDEO_METADATA_DB):
            with open(VIDEO_METADATA_DB, 'r', encoding='utf-8') as f:
                metadata_db = json.load(f)
        
        # Use multiple keys for better matching
        keys = [url]
        
        # Add video ID based keys for better matching
        if 'v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
            keys.append(f"v={video_id}")
            keys.append(video_id)
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
            keys.append(f"youtu.be/{video_id}")
            keys.append(video_id)
        
        # Save metadata for all keys
        for key in keys:
            metadata_db[key] = {
                'title': title,
                'channel': channel,
                'original_url': url
            }
        
        with open(VIDEO_METADATA_DB, 'w', encoding='utf-8') as f:
            json.dump(metadata_db, f, indent=None, separators=(',', ':'), ensure_ascii=False)
        
        print(f"[Metadata] Saved: {title} by {channel} (keys: {len(keys)})")
    except Exception as e:
        print(f"[Metadata] Error saving: {e}")


class WorkerSignals(QObject):
    """Signals available from a running worker thread."""
    progress = pyqtSignal(str, int, str, str, str)  # job_id, percent, status, speed, eta
    finished = pyqtSignal(str, str, str)  # job_id, url, output_path
    started = pyqtSignal(str)  # job_id
    error = pyqtSignal(str, str)  # job_id, error_message
    playlist_progress = pyqtSignal(str, int, int, str)  # job_id, index, total, current_title
    shutdown_requested = pyqtSignal()  # emitted when auto-shutdown is triggered
    embedded_window_requested = pyqtSignal(str, str)  # url, video_id for embedded window


class DownloadWorker(QThread):
    """Background worker executing sequential downloading tasks from queue."""

    def __init__(self, queue_obj, signals, state_manager):
        super().__init__()
        self.queue_obj = queue_obj
        self.signals = signals
        self.state_manager = state_manager
        self._running = True
        self._current_proc = None
        self._current_job_id = None
        self.dependencies_checked = False
        self._playlist_metadata_cache = {}  # Cache for playlist metadata to reuse on retries

    def stop(self):
        self._running = False
        self.cancel_current_process()

    def cancel_current_process(self):
        """Kills active yt-dlp subprocess immediately."""
        if self._current_proc:
            try:
                if sys.platform.startswith('win'):
                    subprocess.run(f"taskkill /F /T /PID {self._current_proc.pid}", shell=True, creationflags=NO_WINDOW_FLAG)
                else:
                    self._current_proc.terminate()
            except Exception as e:
                print(f"Error terminating process: {e}")
            self._current_proc = None

    def cancel_job(self, job_id):
        if self._current_job_id == job_id:
            self.cancel_current_process()
            return True
        return False

    @staticmethod
    def _build_playlist_format(resolution: str):
        # Prevent conversion crash by cleaning any trailing 'p' characters (e.g., '1080p' -> '1080')
        cleaned_res = str(resolution).strip().lower().replace('p', '')
        print(f"[Format Builder] Resolution: {resolution} -> Cleaned: {cleaned_res}")

        if cleaned_res == "best":
            format_string = "bestvideo+bestaudio/best"
            print(f"[Format Builder] Final format (best): {format_string}")
            return format_string

        try:
            target = int(cleaned_res)
        except Exception:
            format_string = "bestvideo+bestaudio/best"
            print(f"[Format Builder] Final format (exception): {format_string}")
            return format_string

        format_string = f"bestvideo[height={target}]+bestaudio/best[height={target}]/bestvideo[height<={target}]+bestaudio/best"
        print(f"[Format Builder] Final format (target): {format_string}")
        return format_string

    def check_dependencies(self):
        try:
            subprocess.run(['yt-dlp', *build_yt_dlp_js_args(), '--version'], check=True, capture_output=True, creationflags=NO_WINDOW_FLAG)
            self.dependencies_checked = True
        except FileNotFoundError:
            self.signals.error.emit("system", "yt-dlp is missing from environment PATH.")
            return
        self.dependencies_checked = True

    def _yt_dlp_base_cmd(self, client='web'):
        """Build a yt-dlp command with the preferred JavaScript runtime enabled and anti-403 headers."""
        base_cmd = ['yt-dlp', *build_yt_dlp_js_args()]
        
        # Add anti-403 headers to prevent YouTube blocking
        base_cmd += ['--add-header', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36']
        base_cmd += ['--add-header', 'Accept: */*']
        base_cmd += ['--add-header', 'Accept-Language: en-US,en;q=0.9']
        base_cmd += ['--add-header', 'Accept-Encoding: gzip, deflate, br']
        base_cmd += ['--add-header', 'Referer: https://www.youtube.com/']
        base_cmd += ['--add-header', 'Origin: https://www.youtube.com/']
        base_cmd += ['--add-header', 'Connection: keep-alive']
        
        # Use specified client with fallback options
        base_cmd += ['--extractor-args', f'youtube:player_client={client}']
        
        return base_cmd

    def run(self):
        if not self.dependencies_checked:
            self.check_dependencies()

        last_speed, last_eta = "N/A", "N/A"

        while self._running:
            try:
                item = self.queue_obj.get(block=True, timeout=1)
            except queue.Empty:
                time.sleep(0.1)
                continue
            if not item:
                continue

            job_id = item.get('id')
            self._current_job_id = job_id
            print(f"\n[{job_id}] ====== JOB STARTED ======")
            print(f"[{job_id}] URL: {item.get('url')}")
            print(f"[{job_id}] Is Playlist: {item.get('is_playlist')}")
            print(f"[{job_id}] Folder: {item.get('folder')}")
            print(f"[{job_id}] Resolution: {item.get('resolution')}")
            print(f"[{job_id}] Format: {item.get('out_format')}")
            print(f"[{job_id}] Custom Title: {item.get('custom_title')}")
            print(f"[{job_id}] Prefix: {item.get('prefix')}")
            
            # Skip if cancelled while waiting in queue
            if self.state_manager.get_job_status(job_id) == 'cancelled':
                self.queue_obj.task_done()
                continue

            url = item.get('url')
            folder = item.get('folder') or os.path.expanduser('~/Downloads')
            print(f"[{job_id}] Folder path: '{folder}'")
            print(f"[{job_id}] Folder from item: '{item.get('folder')}'")
            print(f"[{job_id}] Folder exists: {os.path.exists(folder) if folder else 'N/A'}")
            
            # Create folder if it doesn't exist
            if folder and not os.path.exists(folder):
                try:
                    os.makedirs(folder, exist_ok=True)
                    print(f"[{job_id}] Created folder: {folder}")
                except OSError as e:
                    print(f"[{job_id}] Failed to create folder: {e}")
                    folder = os.path.expanduser('~/Downloads')  # Fallback to default
            
            selected_subs = item.get('selected_subs', [])
            subs_mode = item.get('subs_mode', 'none')
            
            out_format = item.get('out_format', 'mp4')
            is_audio_only = out_format in ['mp3', 'wav']
            
            custom_title = item.get('custom_title', '').strip()
            prefix = item.get('prefix', '').strip()
            disable_title = item.get('disable_title', False)
            is_playlist = item.get('is_playlist', False)
            use_numbering = item.get('use_numbering', False) if is_playlist else False
            download_thumbnail = item.get('download_thumbnail', False)
            embed_thumbnail = item.get('embed_thumbnail', False)
            disable_archive = item.get('disable_archive', False)
            thumbnail_only = item.get('thumbnail_only', False)
            custom_args = item.get('custom_args', '').strip()
            
            resolution = item.get('resolution') or '1080'
            cookies_str = item.get('cookies', '').strip()
            
            # Advanced mode: use specific format IDs
            advanced_mode = item.get('advanced_mode', False)
            audio_format_id = item.get('audio_format_id')
            video_format_id = item.get('video_format_id')
            combined_format_id = item.get('combined_format_id')
            smart_playlist = item.get('smart_playlist', False)
            
            # Handle string boolean values from JSON
            if isinstance(advanced_mode, str):
                advanced_mode = advanced_mode.lower() in ['true', '1', 'yes']
            if isinstance(smart_playlist, str):
                smart_playlist = smart_playlist.lower() in ['true', '1', 'yes']
            if isinstance(download_thumbnail, str):
                download_thumbnail = download_thumbnail.lower() in ['true', '1', 'yes']
            if isinstance(embed_thumbnail, str):
                embed_thumbnail = embed_thumbnail.lower() in ['true', '1', 'yes']
            if isinstance(disable_archive, str):
                disable_archive = disable_archive.lower() in ['true', '1', 'yes']
            if isinstance(thumbnail_only, str):
                thumbnail_only = thumbnail_only.lower() in ['true', '1', 'yes']
            
            print(f"[{job_id}] Advanced mode: {advanced_mode} (type: {type(advanced_mode)})")
            print(f"[{job_id}] Audio format ID: {audio_format_id}")
            print(f"[{job_id}] Video format ID: {video_format_id}")
            print(f"[{job_id}] Combined format ID: {combined_format_id}")
            print(f"[{job_id}] Smart playlist: {smart_playlist}")
            print(f"[{job_id}] is_audio_only: {is_audio_only}")

            self.signals.started.emit(job_id)
            self.state_manager.update_job(job_id, status='downloading', percent=0)

            # Naming schemas
            safe_prefix = prefix.replace('/', '_').replace(':', '_') if prefix else ""
            
            # Enforce numbering when omit title is enabled (to prevent filename collisions)
            if disable_title:
                use_numbering = True
            
            name_parts = []
            # Order: number (if enabled) -> prefix (if present) -> title (if not omitted)
            if is_playlist and use_numbering:
                name_parts.append("%(playlist_index)03d")
            if safe_prefix:
                name_parts.append(safe_prefix)
            if not disable_title:
                if is_playlist and not custom_title:
                    name_parts.append("%(title)s")
                else:
                    name_parts.append(custom_title if custom_title else "%(title)s")
            if not name_parts:
                name_parts.append("%(title)s")
                
            output_template_filename = " - ".join(name_parts) + ".%(ext)s"
            output_template = os.path.join(folder, output_template_filename)
            archive_path = os.path.join(folder, 'downloaded.txt')
            
            print(f"[{job_id}] Output template: {output_template}")
            print(f"[{job_id}] Archive path: {archive_path}")
            print(f"[{job_id}] Name parts: {name_parts}")

            # Smart playlist format matching
            if smart_playlist and is_playlist:
                print(f"[{job_id}] Smart playlist mode enabled - checking metadata cache")
                
                # Check if we have cached metadata for this playlist (from previous attempt)
                if url in self._playlist_metadata_cache:
                    print(f"[{job_id}] Using cached playlist metadata from previous attempt")
                    playlist_metadata = self._playlist_metadata_cache[url]
                else:
                    print(f"[{job_id}] Fetching full playlist metadata")
                    
                    # Fetch full playlist metadata
                    smart_cmd = self._yt_dlp_base_cmd(client='web') + ['-J', '--skip-download']
                    if cookies_str:
                        smart_cmd += ['--add-header', f'Cookie: {cookies_str}']
                    smart_cmd += [url]
                    
                    try:
                        smart_result = subprocess.run(
                            smart_cmd,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            creationflags=NO_WINDOW_FLAG,
                        )
                        
                        if smart_result.returncode == 0:
                            import json
                            playlist_metadata = json.loads(smart_result.stdout)
                            # Cache the metadata for potential retries
                            self._playlist_metadata_cache[url] = playlist_metadata
                            print(f"[{job_id}] Cached playlist metadata for potential retries")
                        else:
                            print(f"[{job_id}] Failed to fetch playlist metadata: {smart_result.stderr}")
                            self._playlist_video_formats = None
                    except Exception as e:
                        print(f"[{job_id}] Exception fetching playlist metadata: {e}")
                        self._playlist_video_formats = None
                
                # Process metadata if available
                if 'playlist_metadata' in locals() and playlist_metadata:
                    entries = playlist_metadata.get('entries', [])
                    print(f"[{job_id}] Processing metadata for {len(entries)} playlist videos")
                    
                    # Process each video to find best matching format
                    self._playlist_video_formats = {}
                    for entry in entries:
                        if not entry:
                            continue
                        
                        video_id = entry.get('id', '')
                        video_url = entry.get('url', '')
                        video_title = entry.get('title', 'Unknown')
                        
                        if not video_id or not video_url:
                            continue
                        
                        # Extract available formats
                        available_formats = []
                        available_audio_formats = []
                        for fmt in entry.get('formats', []):
                            if fmt.get('vcodec') != 'none':
                                available_formats.append({
                                    'id': fmt.get('format_id', ''),
                                    'ext': fmt.get('ext', ''),
                                    'width': fmt.get('width', 0),
                                    'height': fmt.get('height', 0),
                                    'fps': fmt.get('fps', 0),
                                    'has_audio': fmt.get('acodec') != 'none',
                                    'vcodec': fmt.get('vcodec', ''),
                                    'acodec': fmt.get('acodec', '')
                                })
                            elif fmt.get('acodec') != 'none':
                                available_audio_formats.append({
                                    'id': fmt.get('format_id', ''),
                                    'ext': fmt.get('ext', ''),
                                    'abr': fmt.get('abr', 0),
                                    'acodec': fmt.get('acodec', ''),
                                    'format_note': fmt.get('format_note', '')
                                })
                        
                        # Find best matching format based on user selection
                        selected_format_id = self._find_best_matching_format(
                            combined_format_id, video_format_id, audio_format_id, 
                            available_formats, resolution
                        )
                        
                        # Find best matching audio format for smart audio selection
                        selected_audio_format_id = None
                        if audio_format_id:
                            selected_audio_format_id = self._find_best_matching_audio_format(
                                audio_format_id, available_audio_formats
                            )
                        
                        self._playlist_video_formats[video_id] = {
                            'url': video_url,
                            'title': video_title,
                            'format_id': selected_format_id,
                            'audio_format_id': selected_audio_format_id,
                            'formats': available_formats,
                            'audio_formats': available_audio_formats
                        }
                        
                        print(f"[{job_id}] Video {video_id}: selected format {selected_format_id}, audio format {selected_audio_format_id}")
                    
                    print(f"[{job_id}] Smart matching complete for {len(self._playlist_video_formats)} videos")
                    
                    # For smart playlist, download videos individually with specific format IDs
                    if self._playlist_video_formats:
                        playlist_total_tracker = 0  # Initialize tracker
                        return self._download_playlist_with_smart_formats(
                            job_id, url, folder, output_template, archive_path,
                            cookies_str, out_format, subs_mode, selected_subs,
                            use_numbering, safe_prefix, disable_title, custom_title,
                            playlist_total_tracker
                        )
                else:
                    self._playlist_video_formats = None
            else:
                self._playlist_video_formats = None

            success = False
            final_path = ""
            temp_cookies_file = None

            cmd = [
                *self._yt_dlp_base_cmd(client='web'), '--newline', '--continue', '--no-overwrites',
                '--ignore-errors', '-o', output_template, url
            ]

            # Only add download archive if not disabled
            if not disable_archive:
                cmd += ['--download-archive', archive_path]
            else:
                print(f"[{job_id}] Archive file creation disabled")

            # Handle thumbnail-only mode
            if thumbnail_only:
                print(f"[{job_id}] Thumbnail-only mode enabled")
                cmd += ['--skip-download', '--write-thumbnail', '--convert-thumbnails', 'jpg']

            # Convert raw cookie header string to Netscape format cookie jar file for secure segment authentication
            if cookies_str:
                print(f"[{job_id}] Cookies provided, length: {len(cookies_str)}")
                try:
                    temp_cookies_file = os.path.join(folder, f"cookies_{job_id}.txt")
                    with open(temp_cookies_file, "w", encoding="utf-8") as cookie_file:
                        cookie_file.write("# Netscape HTTP Cookie File\n")
                        cookie_file.write("# This file was generated automatically by Video Downloader Bridge Pro.\n")
                        
                        # Parse standard "Key1=Val1; Key2=Val2" strings to write valid Netscape tab structures
                        for pair in cookies_str.split(";"):
                            pair = pair.strip()
                            if not pair or "=" not in pair:
                                continue
                            k, v = pair.split("=", 1)
                            k = k.strip()  # Remove any leading/trailing whitespace from key names
                            v = v.strip()  # Remove any leading/trailing whitespace from values
                            if not k:
                                continue
                            # Scope cookies dynamically back to youtube.com natively
                            cookie_file.write(f".youtube.com\tTRUE\t/\tFALSE\t0\t{k}\t{v}\n")
                    
                    cmd += ['--cookies', temp_cookies_file]
                    print(f"[{job_id}] Cookie file created: {temp_cookies_file}")
                except Exception as ex:
                    print(f"⚠️ [{job_id}] Cookie Engine Exception: Failed preparing cookie jar: {ex}")
            elif BROWSER_PROFILE_DIR:
                cmd += ['--cookies-from-browser', f'chrome:\"{BROWSER_PROFILE_DIR}\"']
                print(f"[{job_id}] Using browser profile: {BROWSER_PROFILE_DIR}")

            # Standard extraction arguments without client restrictions
            cmd += [
                '--newline',  # Force newline output for proper line-by-line parsing
            ]

            if is_audio_only:
                cmd += ['-x', '--audio-format', out_format, '--audio-quality', '0']
                print(f"[{job_id}] Audio-only mode: {out_format}")
            elif advanced_mode:
                # Use specific format IDs for no re-encoding download
                print(f"[{job_id}] ENTERING ADVANCED MODE BRANCH")
                
                # Smart playlist format matching
                if smart_playlist and is_playlist:
                    print(f"[{job_id}] Using smart playlist format matching")
                    
                    # For smart playlist, use yt-dlp's format selection language
                    # to automatically select best matching formats for each video
                    # based on the user's selected quality preference
                    
                    # Convert resolution to format selection string
                    # If user selected a specific format ID, try to match similar quality
                    if combined_format_id:
                        # User selected a combined format, try to match similar quality
                        # Extract resolution from the format ID if possible
                        # Fallback to best quality
                        format_string = "bestvideo+bestaudio/best"
                        print(f"[{job_id}] Smart playlist using best combined format")
                    elif video_format_id:
                        # User selected a video-only format, try to match similar quality
                        # Use format selection to get best video+audio combination
                        format_string = "bestvideo+bestaudio/best"
                        print(f"[{job_id}] Smart playlist using best video+audio format")
                    elif audio_format_id:
                        # User selected audio-only, use best audio
                        format_string = "bestaudio/best"
                        print(f"[{job_id}] Smart playlist using best audio format")
                    else:
                        # No specific format selected, use resolution-based
                        format_string = self._build_playlist_format(resolution)
                        print(f"[{job_id}] Smart playlist using resolution-based format: {format_string}")
                elif combined_format_id:
                    # Combined format has both video and audio
                    format_string = combined_format_id
                    print(f"[{job_id}] Using combined format: {format_string}")
                elif video_format_id and audio_format_id:
                    format_string = f"{video_format_id}+{audio_format_id}"
                    print(f"[{job_id}] Using combined format: {format_string}")
                elif video_format_id:
                    format_string = video_format_id
                    print(f"[{job_id}] Using video-only format: {format_string}")
                elif audio_format_id:
                    format_string = audio_format_id
                    print(f"[{job_id}] Using audio-only format: {format_string}")
                else:
                    # Fallback to resolution-based if no format IDs selected
                    format_string = self._build_playlist_format(resolution)
                    print(f"[{job_id}] No format IDs selected, using resolution-based: {format_string}")
                cmd += ['-f', format_string]
                # In advanced mode, don't recode by default (use --fixup never to skip processing)
                cmd += ['--fixup', 'never']
                print(f"[{job_id}] Advanced mode: no re-encoding (fixup never)")
            else:
                print(f"[{job_id}] ENTERING NORMAL MODE BRANCH")
                format_string = self._build_playlist_format(resolution)
                cmd += ['-f', format_string]

            if selected_subs and subs_mode != 'none':
                print(f"[{job_id}] Subtitles: mode={subs_mode}, langs={selected_subs}")
                cmd += ['--write-subs', '--write-auto-subs', '--sub-langs', ','.join(selected_subs), '--sub-format', 'best', '--ignore-errors']
                if subs_mode == 'embed':
                    cmd += ['--embed-subs']
                elif subs_mode == 'external_srt':
                    cmd += ['--convert-subs', 'srt']

            if download_thumbnail:
                print(f"[{job_id}] Thumbnail download enabled")
                cmd += ['--write-thumbnail', '--convert-thumbnails', 'jpg']

            if embed_thumbnail and is_audio_only:
                print(f"[{job_id}] Embedding thumbnail in audio file")
                cmd += ['--embed-thumbnail']

            cmd += ['--embed-metadata']

            # Add custom arguments if provided
            if custom_args:
                print(f"[{job_id}] Adding custom arguments: {custom_args}")
                # Split custom args by spaces, respecting quotes
                import shlex
                try:
                    custom_args_list = shlex.split(custom_args)
                    cmd += custom_args_list
                except Exception as e:
                    print(f"[{job_id}] Warning: Failed to parse custom arguments: {e}")

            # Only trigger ffmpeg container recoding when not downloading original formats
            if (not is_audio_only) and (out_format != 'original'):
                cmd += ['--recode-video', out_format]
                print(f"[{job_id}] Recoding to: {out_format}")

            # Add speed limit if enabled
            from settings import load_settings
            settings = load_settings()
            speed_limit_enabled = settings.get('speed_limit_enabled', False)
            speed_limit_value = settings.get('speed_limit_value', '10M')
            
            if speed_limit_enabled:
                cmd += ['--limit-rate', speed_limit_value]
                print(f"[{job_id}] Speed limit enabled: {speed_limit_value}")

            # Add playlist filters if enabled
            playlist_filter_enabled = settings.get('playlist_filter_enabled', False)
            if playlist_filter_enabled:
                filter_parts = []
                
                min_duration = settings.get('playlist_filter_min_duration', '')
                max_duration = settings.get('playlist_filter_max_duration', '')
                min_views = settings.get('playlist_filter_min_views', '')
                max_views = settings.get('playlist_filter_max_views', '')
                date_after = settings.get('playlist_filter_date_after', '')
                date_before = settings.get('playlist_filter_date_before', '')
                
                if min_duration:
                    filter_parts.append(f"duration >= {min_duration}")
                if max_duration:
                    filter_parts.append(f"duration <= {max_duration}")
                if min_views:
                    filter_parts.append(f"view_count >= {min_views}")
                if max_views:
                    filter_parts.append(f"view_count <= {max_views}")
                if date_after:
                    filter_parts.append(f"upload_date >= {date_after}")
                if date_before:
                    filter_parts.append(f"upload_date <= {date_before}")
                
                if filter_parts:
                    filter_string = " & ".join(filter_parts)
                    cmd += ['--match-filter', filter_string]
                    print(f"[{job_id}] Playlist filter: {filter_string}")

            # Add multi-threaded download if enabled
            multi_threaded_enabled = settings.get('multi_threaded_enabled', False)
            multi_threaded_threads = settings.get('multi_threaded_threads', 4)
            
            if multi_threaded_enabled:
                cmd += ['--concurrent-fragments', str(multi_threaded_threads)]
                print(f"[{job_id}] Multi-threaded download enabled: {multi_threaded_threads} threads")

            # Add proxy if enabled
            proxy_enabled = settings.get('proxy_enabled', False)
            proxy_url = settings.get('proxy_url', '')
            
            if proxy_enabled and proxy_url:
                cmd += ['--proxy', proxy_url]
                print(f"[{job_id}] Proxy enabled: {proxy_url}")

            # Add audio normalization if enabled
            audio_normalization_enabled = settings.get('audio_normalization_enabled', False)
            
            if audio_normalization_enabled:
                cmd += ['--audio-normalize']
                print(f"[{job_id}] Audio normalization enabled")

            # Add chapter/segment support if enabled
            download_chapters = settings.get('download_chapters', False)
            download_sections = settings.get('download_sections', '')
            
            if download_chapters:
                cmd += ['--split-chapters']
                print(f"[{job_id}] Chapter splitting enabled")
            
            if download_sections:
                cmd += ['--download-sections', download_sections]
                print(f"[{job_id}] Download sections: {download_sections}")

            # === DIAGNOSTICS: Print complete task configuration ===
            print(f"\n==================== [DIAGNOSTICS - JOB: {job_id}] ====================")
            print(f"Target URL: {url}")
            print(f"Save Directory: {folder}")
            print(f"Format Container: {out_format} (Audio Only: {is_audio_only})")
            print(f"Subtitles: {subs_mode} | Preferred Languages: {selected_subs}")
            print(f"Command Array to be Executed:\n {' '.join(cmd)}")
            print("========================================================================\n")

            try:
                self._current_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,  # Line buffering for real-time output
                    creationflags=NO_WINDOW_FLAG,
                )

                playlist_total_tracker = 0
                current_video_title = ""
                format_issue_detected = False

                # Read complete execution stream line-by-line
                for line in self._current_proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Detect format availability issues
                    if 'Requested format is not available' in line or \
                       'Only images are available' in line or \
                       'SABR streaming' in line:
                        format_issue_detected = True
                        print(f"[{job_id}] ⚠️ Format availability issue detected: {line}")
                    
                    # Clean ANSI escape styling sequences
                    line = clean_ansi_escape_codes(line)
                    
                    # === DIAGNOSTICS: Verbose print output of EVERY LINE ===
                    print(f"[{job_id} Engine Output] {line}")

                    if self.state_manager.get_job_status(job_id) == 'cancelled':
                        print(f"[{job_id}] Cancel requested! Killing active process tree.")
                        self.cancel_current_process()
                        break

                    if os.path.isabs(line) and os.path.exists(line):
                        final_path = line

                    # Also try to extract final path from destination lines
                    dest_match = re.search(r'\[download\] Destination:\s*(.+)$', line)
                    if dest_match:
                        potential_path = dest_match.group(1).strip()
                        if os.path.exists(potential_path):
                            final_path = potential_path
                        filename = os.path.basename(potential_path)
                        current_video_title = filename
                        print(f"[{job_id}] Destination detected: {filename}")
                        self.state_manager.update_job(job_id, current_video_title=filename)

                    pl_match = re.search(r'Downloading item (\d+) of (\d+)', line)
                    if pl_match:
                        current_idx = int(pl_match.group(1))
                        playlist_total_tracker = int(pl_match.group(2))
                        print(f"[{job_id}] Playlist Progress: {current_idx}/{playlist_total_tracker} - {current_video_title}")
                        self.signals.playlist_progress.emit(job_id, current_idx, playlist_total_tracker, current_video_title)
                        self.state_manager.update_job(job_id, playlist_index=current_idx, playlist_total=playlist_total_tracker)

                    if '[download]' in line and '%' in line:
                        percent = 0
                        speed = "N/A"
                        eta = "N/A"
                        
                        # Use simpler regex patterns from reference implementation
                        pct_match = re.search(r'(\d+(?:\.\d+)?)%', line)
                        spd_match = re.search(r'(\d+(?:\.\d+)?[KiMG]iB/s)', line)
                        eta_match = re.search(r'ETA\s+([^\s]+)', line)
                        
                        if pct_match:
                            try:
                                percent_float = float(pct_match.group(1))
                                percent = int(round(percent_float))
                                # Clamp percentage between 0 and 100
                                percent = max(0, min(100, percent))
                            except (ValueError, AttributeError):
                                percent = 0
                        
                        if spd_match:
                            speed = spd_match.group(1)
                        
                        if eta_match:
                            eta = eta_match.group(1)

                        # Detect which stream is being downloaded for clearer status
                        status_message = "downloading"
                        if 'video' in line.lower() and 'audio' not in line.lower():
                            status_message = "downloading video stream"
                        elif 'audio' in line.lower():
                            status_message = "downloading audio stream"

                        last_speed, last_eta = speed, eta
                        self.signals.progress.emit(job_id, percent, status_message, speed, eta)
                        self.state_manager.update_job(job_id, percent=percent, speed=speed, eta=eta, status=status_message)
                    else:
                        if line.startswith('[download]') and not '%' in line:
                            clean_status = line.replace('[download]', '').strip()
                            self.state_manager.update_job(job_id, last_stdout=clean_status)
                        
                        # Detect ffmpeg conversion/recoding phase
                        if '[ffmpeg]' in line or 'Converting' in line or 'Merging' in line:
                            conversion_status = "Converting to desired format..."
                            if 'Merging' in line:
                                conversion_status = "Merging video and audio streams..."
                            print(f"[{job_id}] {conversion_status}")
                            self.state_manager.update_job(job_id, status="merging", last_stdout=conversion_status)
                            self.signals.progress.emit(job_id, 100, "merging", "Converting", "--")

                self._current_proc.wait()
                return_code = self._current_proc.returncode
                
                # === DIAGNOSTICS: Print final status code ===
                print(f"[{job_id} Process Terminated] Exit Code: {return_code}")

                # Client fallback for format availability issues
                if return_code != 0 and format_issue_detected:
                    print(f"[{job_id}] 🔄 Format availability issue detected, trying different clients...")
                    
                    # Try different clients
                    clients_to_try = ['android', 'tv', 'ios']
                    for attempt, client in enumerate(clients_to_try):
                        print(f"[{job_id}] Attempt {attempt + 2}/{len(clients_to_try) + 1}: Trying with client '{client}'")
                        
                        # Create fallback command with different client
                        fallback_cmd = cmd.copy()
                        for i, arg in enumerate(fallback_cmd):
                            if '--extractor-args' in arg and 'youtube:player_client=' in arg:
                                fallback_cmd[i] = f'--extractor-args youtube:player_client={client}'
                                break
                        
                        try:
                            self._current_proc = subprocess.Popen(
                                fallback_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                encoding='utf-8',
                                errors='replace',
                                bufsize=1,
                                creationflags=NO_WINDOW_FLAG,
                            )

                            # Process output for fallback attempt
                            for line in self._current_proc.stdout:
                                line = line.strip()
                                if not line:
                                    continue
                                
                                print(f"[{job_id} Engine Output] {line}")
                                
                                # Check for format issues again
                                if 'Requested format is not available' in line or \
                                   'Only images are available' in line or \
                                   'SABR streaming' in line:
                                    print(f"[{job_id}] ⚠️ Format issue persists with client '{client}'")
                                
                                # Process progress updates
                                if '[download]' in line and '%' in line:
                                    percent = 0
                                    speed = "N/A"
                                    eta = "N/A"
                                    
                                    pct_match = re.search(r'(\d+(?:\.\d+)?)%', line)
                                    spd_match = re.search(r'(\d+(?:\.\d+)?[KiMG]iB/s)', line)
                                    eta_match = re.search(r'ETA\s+([^\s]+)', line)
                                    
                                    if pct_match:
                                        try:
                                            percent_float = float(pct_match.group(1))
                                            percent = int(round(percent_float))
                                            percent = max(0, min(100, percent))
                                        except (ValueError, AttributeError):
                                            percent = 0
                                    
                                    if spd_match:
                                        speed = spd_match.group(1)
                                    
                                    if eta_match:
                                        eta = eta_match.group(1)

                                    self.signals.progress.emit(job_id, percent, f"downloading ({client})", speed, eta)
                                    self.state_manager.update_job(job_id, percent=percent, speed=speed, eta=eta, status=f"downloading ({client})")

                            self._current_proc.wait()
                            return_code = self._current_proc.returncode
                            
                            if return_code == 0:
                                print(f"[{job_id}] ✅ Success with client '{client}'")
                                break
                            else:
                                print(f"[{job_id}] ❌ Failed with client '{client}'")
                                
                        except Exception as e:
                            print(f"[{job_id}] ❌ Exception with client '{client}': {str(e)}")
                            continue

                if self.state_manager.get_job_status(job_id) == 'cancelled':
                    success = False
                elif return_code == 0:
                    success = True
                    self.signals.progress.emit(job_id, 100, "completed", "Done", "--")
                    self.state_manager.update_job(job_id, percent=100, status="completed", speed="N/A", eta="--")
                    
                    # Save video metadata to centralized database
                    try:
                        # Get title from job info
                        job_info = self.state_manager.get_all_jobs().get(job_id, {})
                        title = job_info.get('title', current_video_title or 'Unknown')
                        
                        # Try to get channel from yt-dlp info
                        channel = "Unknown"
                        try:
                            info_cmd = [*self._yt_dlp_base_cmd(client='web'), '--dump-json', '--no-playlist', url]
                            info_result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW_FLAG)
                            if info_result.returncode == 0:
                                info_data = json.loads(info_result.stdout)
                                channel = info_data.get('channel', info_data.get('uploader', 'Unknown'))
                                title = info_data.get('title', title)
                        except:
                            pass
                        
                        save_video_metadata(url, title, channel)
                        print(f"[{job_id}] Successfully saved metadata: {title} by {channel}")
                    except Exception as e:
                        print(f"[{job_id}] Failed to save metadata: {e}")
                else:
                    success = False
                    job_info = self.state_manager.get_all_jobs().get(job_id, {})
                    last_out = job_info.get('last_stdout', '')
                    error_message = f"yt-dlp exited with non-zero code {return_code}."
                    if last_out:
                        error_message += f" Last line: {last_out}"
                    self.signals.error.emit(job_id, error_message)
                    self.state_manager.update_job(job_id, status="failed", last_stdout=error_message)

            except Exception as exc:
                print(f"❌ [{job_id} Pipeline Exception] {str(exc)}")
                self.signals.error.emit(job_id, f"Download pipeline exception: {str(exc)}")
                self.state_manager.update_job(job_id, status="failed", last_stdout=str(exc))
            finally:
                self._current_proc = None
                # Clean up temporary cookie file jar on disk
                if temp_cookies_file and os.path.exists(temp_cookies_file):
                    try:
                        os.remove(temp_cookies_file)
                    except OSError as e:
                        print(f"⚠️ [{job_id}] Failed to remove temporary cookie file: {e}")

            if self.state_manager.get_job_status(job_id) == 'cancelled':
                self.state_manager.update_job(job_id, status="cancelled")
            elif success:
                self.signals.finished.emit(job_id, url, final_path)
            else:
                if self.state_manager.get_job_status(job_id) != 'cancelled':
                    self.state_manager.update_job(job_id, status="failed")

            self._current_job_id = None
            self.queue_obj.task_done()
            
            # Check if all downloads are complete and trigger shutdown if enabled
            self._check_shutdown_conditions()

    def _find_best_matching_format(self, combined_format_id, video_format_id, audio_format_id, available_formats, resolution):
        """
        Custom format matching algorithm to find the best format for each video
        based on user's selected format preference and available formats.
        
        This avoids yt-dlp's built-in format selection which can be inconsistent.
        """
        if not available_formats or len(available_formats) == 0:
            return None
        
        # If user selected a specific format ID, try to find exact match
        if combined_format_id:
            # Check if exact format ID exists
            exact_match = next((f for f in available_formats if f['id'] == combined_format_id), None)
            if exact_match:
                return combined_format_id
            
            # Extract resolution from format ID if possible
            # Format IDs like '137', '22', '18' have known resolutions
            target_resolution = self._get_resolution_from_format_id(combined_format_id)
            if target_resolution:
                # Find format with closest resolution
                return self._find_closest_resolution_format(available_formats, target_resolution, has_audio=True)
        
        elif video_format_id:
            # User selected video-only format
            exact_match = next((f for f in available_formats if f['id'] == video_format_id), None)
            if exact_match:
                return video_format_id
            
            target_resolution = self._get_resolution_from_format_id(video_format_id)
            if target_resolution:
                return self._find_closest_resolution_format(available_formats, target_resolution, has_audio=False)
        
        elif audio_format_id:
            # User selected audio-only format
            exact_match = next((f for f in available_formats if f['id'] == audio_format_id), None)
            if exact_match:
                return audio_format_id
            
            # For audio, find best audio format
            return self._find_best_audio_format(available_formats)
        
        # If no specific format selected, use resolution preference
        target_res = int(resolution) if resolution.isdigit() else 1080
        return self._find_closest_resolution_format(available_formats, target_res, has_audio=True)
    
    def _get_resolution_from_format_id(self, format_id):
        """
        Extract approximate resolution from common YouTube format IDs.
        Returns height in pixels (e.g., 1080, 720, 480).
        """
        # Common YouTube format IDs and their resolutions
        format_resolutions = {
            # Combined formats (video + audio)
            '22': 720,      # 720p MP4
            '18': 360,      # 360p MP4
            '137': 1080,    # 1080p video only
            '136': 720,     # 720p video only
            '135': 480,     # 480p video only
            '134': 360,     # 360p video only
            '133': 240,     # 240p video only
            '160': 144,     # 144p video only
            # WebM formats
            '248': 1080,    # 1080p WebM
            '247': 720,     # 720p WebM
            '244': 480,     # 480p WebM
            '243': 360,     # 360p WebM
            '242': 240,     # 240p WebM
            '278': 144,     # 144p WebM
        }
        return format_resolutions.get(format_id, None)
    
    def _get_audio_bitrate_from_format_id(self, format_id):
        """
        Extract approximate bitrate from common YouTube audio format IDs.
        Returns bitrate in kbps (e.g., 128, 192, 320).
        """
        # Common YouTube audio format IDs and their bitrates
        audio_bitrates = {
            # AAC audio formats
            '140': 128,     # 128kbps AAC (m4a)
            '141': 256,     # 256kbps AAC
            '139': 48,      # 48kbps AAC (low quality)
            # Opus audio formats
            '251': 160,     # 160kbps Opus (webm)
            '250': 70,      # 70kbps Opus
            '249': 50,      # 50kbps Opus
            # Legacy audio formats
            '171': 128,     # 128kbps WebM
            '172': 256,     # 256kbps WebM
        }
        return audio_bitrates.get(format_id, None)
    
    def _find_best_matching_audio_format(self, target_audio_format_id, available_audio_formats):
        """
        Find best matching audio format based on user's selected audio format.
        Uses bitrate matching with codec preference.
        """
        if not available_audio_formats or len(available_audio_formats) == 0:
            return None
        
        # If user selected a specific audio format ID, try to find exact match
        if target_audio_format_id:
            exact_match = next((f for f in available_audio_formats if f['id'] == target_audio_format_id), None)
            if exact_match:
                return target_audio_format_id
            
            # Extract target bitrate from format ID
            target_bitrate = self._get_audio_bitrate_from_format_id(target_audio_format_id)
            if target_bitrate:
                return self._find_closest_bitrate_format(available_audio_formats, target_bitrate)
        
        # Fallback to best audio format
        return self._find_best_audio_format(available_audio_formats)
    
    def _find_closest_bitrate_format(self, available_audio_formats, target_bitrate):
        """
        Find audio format with bitrate closest to target.
        Prefers same codec family if possible.
        """
        if not available_audio_formats:
            return None
        
        # Calculate bitrate difference for each format
        scored_formats = []
        for fmt in available_audio_formats:
            abr = fmt.get('abr', 0)
            if abr == 0:
                continue
            
            # Prefer exact match
            if abr == target_bitrate:
                scored_formats.append((fmt, 0))
            else:
                # Calculate difference score
                diff = abs(abr - target_bitrate)
                # Prefer slightly higher bitrate over lower
                if abr > target_bitrate:
                    diff *= 0.8  # Penalty for higher bitrate is smaller
                scored_formats.append((fmt, diff))
        
        if not scored_formats:
            return available_audio_formats[0]['id'] if available_audio_formats else None
        
        # Sort by score (lower is better)
        scored_formats.sort(key=lambda x: x[1])
        return scored_formats[0][0]['id']
    
    def _find_closest_resolution_format(self, available_formats, target_resolution, has_audio=True):
        """
        Find format with resolution closest to target.
        Prefers formats with same audio type (has_audio).
        """
        # Filter by audio type
        matching_formats = [f for f in available_formats if f['has_audio'] == has_audio]
        if not matching_formats:
            # Fallback to any format if no match with preferred audio type
            matching_formats = available_formats
        
        # Calculate resolution difference for each format
        scored_formats = []
        for fmt in matching_formats:
            height = fmt.get('height', 0)
            if height == 0:
                continue
            
            # Prefer exact match
            if height == target_resolution:
                scored_formats.append((fmt, 0))
            else:
                # Calculate difference score
                diff = abs(height - target_resolution)
                # Prefer slightly higher resolution over lower
                if height > target_resolution:
                    diff *= 0.8  # Penalty for higher resolution is smaller
                scored_formats.append((fmt, diff))
        
        if not scored_formats:
            return available_formats[0]['id'] if available_formats else None
        
        # Sort by score (lower is better)
        scored_formats.sort(key=lambda x: x[1])
        return scored_formats[0][0]['id']
    
    def _find_best_audio_format(self, available_formats):
        """
        Find best audio format based on codec preference.
        """
        # Prefer AAC audio, then Opus, then others
        audio_codecs = ['aac', 'mp4a', 'opus', 'vorbis', 'mp3']
        
        for codec in audio_codecs:
            match = next((f for f in available_formats if codec in f.get('acodec', '').lower()), None)
            if match:
                return match['id']
        
        # Fallback to first audio format
        return available_formats[0]['id'] if available_formats else None

    def _download_playlist_with_smart_formats(self, job_id, url, folder, output_template, archive_path,
                                             cookies_str, out_format, subs_mode, selected_subs,
                                             use_numbering, safe_prefix, disable_title, custom_title,
                                             playlist_total_tracker):
        """
        Download playlist videos individually with custom format IDs.
        This provides precise control over format selection for each video.
        """
        print(f"[{job_id}] Starting smart playlist download for {len(self._playlist_video_formats)} videos")
        
        success = True
        downloaded_count = 0
        failed_count = 0
        
        for idx, (video_id, video_info) in enumerate(self._playlist_video_formats.items(), 1):
            if self.state_manager.get_job_status(job_id) == 'cancelled':
                print(f"[{job_id}] Playlist download cancelled")
                break
            
            video_url = video_info['url']
            video_title = video_info['title']
            format_id = video_info['format_id']
            audio_format_id = video_info.get('audio_format_id')
            
            print(f"[{job_id}] Downloading video {idx}/{len(self._playlist_video_formats)}: {video_title}")
            print(f"[{job_id}] Using format ID: {format_id}, audio format ID: {audio_format_id}")
            
            # Update playlist progress
            self.signals.playlist_progress.emit(job_id, idx, len(self._playlist_video_formats), video_title)
            self.state_manager.update_job(job_id, playlist_index=idx, playlist_total=len(self._playlist_video_formats))
            
            # Build individual video download command
            cmd = [
                *self._yt_dlp_base_cmd(client='web'), '--newline', '--continue', '--no-overwrites',
                '--download-archive', archive_path, '--ignore-errors',
                '--fixup', 'never',
                '-o', output_template,
                video_url
            ]
            
            # Use smart audio format selection if available
            if audio_format_id and format_id:
                # Combine video and audio format IDs
                cmd += ['-f', f'{format_id}+{audio_format_id}']
                print(f"[{job_id}] Using combined format: {format_id}+{audio_format_id}")
            elif format_id:
                cmd += ['-f', format_id]
                print(f"[{job_id}] Using video-only format: {format_id}")
            else:
                # Fallback to best format
                cmd += ['-f', 'best']
                print(f"[{job_id}] Using fallback format: best")
            
            # Add subtitle options
            if subs_mode == 'list' and selected_subs:
                cmd += ['--write-subs', '--sub-lang', ','.join(selected_subs)]
            elif subs_mode == 'all':
                cmd += ['--write-subs', '--sub-langs', 'all']
            
            # Add cookies if provided
            temp_cookies_file = None
            if cookies_str:
                try:
                    temp_cookies_file = os.path.join(folder, f"cookies_{job_id}_{video_id}.txt")
                    with open(temp_cookies_file, "w", encoding="utf-8") as cookie_file:
                        cookie_file.write("# Netscape HTTP Cookie File\n")
                        cookie_file.write("# This file was generated automatically by Video Downloader Bridge Pro.\n")
                        for pair in cookies_str.split(";"):
                            pair = pair.strip()
                            if not pair:
                                continue
                            if '=' in pair:
                                key, val = pair.split('=', 1)
                                cookie_file.write(f".youtube.com\tTRUE\t/\tFALSE\t0\t{key.strip()}\t{val.strip()}\n")
                    cmd += ['--cookies', temp_cookies_file]
                except Exception as e:
                    print(f"[{job_id}] Failed to create cookie file: {e}")
            
            try:
                self._current_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=NO_WINDOW_FLAG,
                )
                
                # Process output
                for line in iter(self._current_proc.stdout.readline, ''):
                    if self.state_manager.get_job_status(job_id) == 'cancelled':
                        self.cancel_current_process()
                        break
                    
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Parse progress
                    if '[download]' in line and '%' in line:
                        percent = 0
                        match = re.search(r'(\d+\.\d+|\d+)%', line)
                        if match:
                            try:
                                percent_float = float(match.group(1))
                                percent = int(round(percent_float))
                                percent = max(0, min(100, percent))
                            except (ValueError, AttributeError):
                                percent = 0
                        
                        self.signals.progress.emit(job_id, percent, "downloading", "N/A", "N/A")
                        self.state_manager.update_job(job_id, percent=percent, status="downloading")
                
                self._current_proc.wait()
                return_code = self._current_proc.returncode
                
                if return_code == 0:
                    downloaded_count += 1
                    print(f"[{job_id}] Successfully downloaded: {video_title}")
                else:
                    failed_count += 1
                    print(f"[{job_id}] Failed to download: {video_title} (exit code: {return_code})")
                    success = False
                
            except Exception as e:
                print(f"[{job_id}] Exception downloading {video_title}: {e}")
                failed_count += 1
                success = False
            finally:
                self._current_proc = None
                # Clean up temporary cookie file
                if temp_cookies_file and os.path.exists(temp_cookies_file):
                    try:
                        os.remove(temp_cookies_file)
                    except OSError as e:
                        print(f"[{job_id}] Failed to remove cookie file: {e}")
        
        print(f"[{job_id}] Smart playlist download complete: {downloaded_count} succeeded, {failed_count} failed")
        
        if success:
            self.signals.progress.emit(job_id, 100, "completed", "Done", "--")
            self.state_manager.update_job(job_id, percent=100, status="completed")
            self.signals.finished.emit(job_id, url, folder)
        else:
            self.state_manager.update_job(job_id, status="completed")  # Still mark as completed even if some failed
        
        # Check shutdown conditions after playlist download
        self._check_shutdown_conditions()
        
        return success

    def _check_shutdown_conditions(self):
        """
        Check if all downloads are complete and trigger shutdown if enabled.
        """
        from settings import load_settings
        
        # Check if queue is empty and no active downloads
        if self.queue_obj.empty() and self._current_job_id is None:
            settings = load_settings()
            
            # Check if auto-shutdown is enabled
            if settings.get('auto_shutdown', False):
                print("🔌 [Auto-Shutdown] All downloads complete. Shutting down application...")
                self.signals.shutdown_requested.emit()
            
            # Check if PC shutdown is enabled
            if settings.get('pc_shutdown', False):
                print("💻 [PC Shutdown] All downloads complete. Shutting down PC...")
                self._shutdown_pc()

    def _shutdown_pc(self):
        """Shutdown the PC based on the operating system."""
        import platform
        import os
        
        system = platform.system()
        
        try:
            if system == 'Windows':
                os.system('shutdown /s /t 30')
                print("💻 [PC Shutdown] Windows shutdown initiated (30 seconds)")
            elif system == 'Linux':
                os.system('shutdown -h +1')
                print("💻 [PC Shutdown] Linux shutdown initiated (1 minute)")
            elif system == 'Darwin':  # macOS
                os.system('shutdown -h +1')
                print("💻 [PC Shutdown] macOS shutdown initiated (1 minute)")
            else:
                print(f"⚠️ [PC Shutdown] Unsupported system: {system}")
        except Exception as e:
            print(f"❌ [PC Shutdown] Failed to shutdown: {e}")
