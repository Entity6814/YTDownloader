import sys
import json
import logging
import subprocess
import time
import os
from flask import Flask, request, jsonify
from PyQt5.QtCore import QThread, pyqtSignal

from settings import load_settings, save_settings, build_yt_dlp_js_args, APP_DATA_DIR, DATA_DIR, VIDEO_METADATA_DB
from cache_manager import CacheManager

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

if sys.platform.startswith('win'):
    NO_WINDOW_FLAG = 0x08000000
else:
    NO_WINDOW_FLAG = 0


class ApiSignals(QThread):
    """Signals for propagating API updates to PyQt main thread."""
    job_received = pyqtSignal(dict)
    cancel_requested = pyqtSignal(str)
    open_settings_requested = pyqtSignal()  # Fired when browser asks to open the settings window
    folder_dialog_requested = pyqtSignal()  # Fired when browser requests native folder dialog
    file_dialog_requested = pyqtSignal(dict)  # Fired when browser requests native file dialog
    embedded_window_requested = pyqtSignal(str, str)  # Fired when browser requests embedded video window (url, video_id)


class LocalApiServer(QThread):
    """Headless Flask bridge coordinating network events, folder choices, and cookie validation."""

    def __init__(self, state_manager, port=5000, parent=None):
        super().__init__(parent)
        self.port = port
        self.state_manager = state_manager
        self.signals = ApiSignals()
        self.folder_dialog_result = None
        self.file_dialog_result = None
        self.cache_manager = CacheManager()
        self.app = Flask("HeadlessYoutubeBridgePro")
        self.setup_routes()

    def setup_routes(self):
        def yt_dlp_cmd(*args):
            return ['yt-dlp', *build_yt_dlp_js_args(), *args]

        @self.app.after_request
        def apply_cors(response):
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
            response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
            return response

        @self.app.route('/api/playlist-metadata', methods=['POST', 'OPTIONS'])
        def fetch_playlist_metadata():
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            data = request.json or {}
            url = data.get('url')
            cookies = data.get('cookies', '').strip()
            force_refresh = data.get('force_refresh', False)

            if not url:
                return jsonify({'error': 'Missing URL parameter'}), 400

            print(f"\n📥 [API Request] /api/playlist-metadata URL: {url}")

            # Check cache first (for playlists too)
            if not force_refresh:
                cached_data = self.cache_manager.get(url)
                if cached_data:
                    print(f"📦 [Cache Hit] Using cached playlist metadata")
                    return jsonify({
                        **cached_data,
                        'from_cache': True
                    }), 200

            try:
                # Fetch full playlist metadata with format information for all videos
                # Let yt-dlp handle PO tokens automatically - don't force configuration
                cmd = yt_dlp_cmd('-J', '--skip-download')
                
                if cookies:
                    cmd += ['--add-header', f'Cookie: {cookies}']

                cmd += [url]

                print(f"🔍 [Playlist Metadata] Running yt-dlp command: {' '.join(cmd)}")
                print(f"🔍 [Playlist Metadata] This may take a while for large playlists...")

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=NO_WINDOW_FLAG,
                    timeout=300  # Increased to 5 minutes timeout for large playlists
                )
                
                print(f"🔍 [Playlist Metadata] yt-dlp return code: {result.returncode}")
                if result.stderr:
                    print(f"🔍 [Playlist Metadata] yt-dlp stderr: {result.stderr[:500]}")
                
                if result.returncode != 0:
                    print(f"❌ [API Error] yt-dlp failed: {result.stderr}")
                    return jsonify({'error': 'Failed to fetch playlist metadata'}), 500

                print(f"🔍 [Playlist Metadata] Parsing JSON response...")
                metadata = json.loads(result.stdout)
                print(f"🔍 [Playlist Metadata] Successfully parsed metadata, title: {metadata.get('title', 'Unknown')}")
                
                # Extract relevant playlist information
                playlist_data = {
                    'title': metadata.get('title', 'Unknown Playlist'),
                    'id': metadata.get('id', ''),
                    'video_count': len(metadata.get('entries', [])),
                    'entries': []
                }

                print(f"🔍 [Playlist Metadata] Found {playlist_data['video_count']} videos in playlist")

                # Process each video entry to extract format information
                for idx, entry in enumerate(metadata.get('entries', [])):
                    if not entry:
                        continue
                    
                    if idx % 10 == 0:  # Log every 10 videos to avoid spam
                        print(f"🔍 [Playlist Metadata] Processing video {idx+1}/{playlist_data['video_count']}: {entry.get('title', 'Unknown')[:50]}...")
                    
                    video_data = {
                        'id': entry.get('id', ''),
                        'title': entry.get('title', 'Unknown'),
                        'url': entry.get('url', ''),
                        'duration': entry.get('duration', 0),
                        'formats': []
                    }

                    # Extract audio formats
                    audio_formats = entry.get('formats', [])
                    for fmt in audio_formats:
                        if fmt.get('vcodec') == 'none' and fmt.get('acodec') != 'none':
                            # Handle file size with "~" symbol
                            filesize = fmt.get('filesize')
                            filesize_approx = fmt.get('filesize_approx')
                            
                            if filesize is not None:
                                try:
                                    if isinstance(filesize, str) and '~' in filesize:
                                        filesize = None
                                    else:
                                        filesize = float(filesize) if filesize else None
                                except (ValueError, TypeError):
                                    filesize = None
                            
                            if filesize_approx is not None:
                                try:
                                    filesize_approx = float(filesize_approx) if filesize_approx else None
                                except (ValueError, TypeError):
                                    filesize_approx = None
                            
                            final_filesize = filesize if filesize is not None else filesize_approx
                            
                            video_data['formats'].append({
                                'id': fmt.get('format_id', ''),
                                'ext': fmt.get('ext', ''),
                                'abr': fmt.get('abr', 0),
                                'format_note': fmt.get('format_note', ''),
                                'filesize': final_filesize,
                                'filesize_approx': filesize_approx,
                                'type': 'audio'
                            })

                    # Extract video formats (both video-only and combined)
                    for fmt in audio_formats:
                        if fmt.get('vcodec') != 'none':
                            # Handle file size with "~" symbol
                            filesize = fmt.get('filesize')
                            filesize_approx = fmt.get('filesize_approx')
                            
                            if filesize is not None:
                                try:
                                    if isinstance(filesize, str) and '~' in filesize:
                                        filesize = None
                                    else:
                                        filesize = float(filesize) if filesize else None
                                except (ValueError, TypeError):
                                    filesize = None
                            
                            if filesize_approx is not None:
                                try:
                                    filesize_approx = float(filesize_approx) if filesize_approx else None
                                except (ValueError, TypeError):
                                    filesize_approx = None
                            
                            final_filesize = filesize if filesize is not None else filesize_approx
                            
                            video_data['formats'].append({
                                'id': fmt.get('format_id', ''),
                                'ext': fmt.get('ext', ''),
                                'width': fmt.get('width', 0),
                                'height': fmt.get('height', 0),
                                'fps': fmt.get('fps', 0),
                                'has_audio': fmt.get('acodec') != 'none',
                                'filesize': final_filesize,
                                'filesize_approx': filesize_approx,
                                'type': 'video'
                            })

                    playlist_data['entries'].append(video_data)

                print(f"✅ [API Success] Fetched metadata for {playlist_data['video_count']} playlist videos")
                
                # Cache the playlist metadata
                self.cache_manager.set(url, playlist_data)
                print(f"💾 [Cache Saved] Playlist metadata cached")
                
                return jsonify({
                    **playlist_data,
                    'from_cache': False
                }), 200

            except subprocess.TimeoutExpired:
                print(f"❌ [API Error] Timeout fetching playlist metadata (large playlist)")
                return jsonify({'error': 'Timeout: Playlist is too large. Try again or enable caching.'}), 504
            except json.JSONDecodeError as e:
                print(f"❌ [API Error] Failed to parse JSON: {e}")
                return jsonify({'error': 'Failed to parse metadata'}), 500
            except Exception as e:
                print(f"❌ [API Error] Exception: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/metadata', methods=['GET', 'POST', 'OPTIONS'])
        def fetch_metadata():
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            url = None
            cookies = ""
            force_refresh = False

            # Support both GET and POST requests for metadata querying
            if request.method == 'POST':
                data = request.json or {}
                url = data.get('url')
                cookies = data.get('cookies', '').strip()
                force_refresh = data.get('force_refresh', False)
            else:
                url = request.args.get('url')
                force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'

            if not url:
                return jsonify({'error': 'Missing URL parameter'}), 400

            # Log incoming metadata request for diagnostics
            print(f"\n📥 [API Request] /api/metadata URL: {url}")

            # Check cache first (only for videos, not playlists)
            if not force_refresh and 'list' not in url:
                cached_data = self.cache_manager.get(url)
                if cached_data:
                    print(f"📦 [Cache Hit] Using cached metadata for: '{cached_data.get('title', 'Unknown')}'")
                    return jsonify({
                        **cached_data,
                        'from_cache': True
                    }), 200

            try:
                # Let yt-dlp handle PO tokens automatically
                cmd = yt_dlp_cmd('-J', '--skip-download', '--playlist-items', '1')
                
                # Pass session cookies if forwarded by browser userscript
                if cookies:
                    cmd += ['--add-header', f'Cookie: {cookies}']

                cmd += [url]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    check=True,
                    creationflags=NO_WINDOW_FLAG
                )
                
                info = json.loads(result.stdout)
                target = info['entries'][0] if 'entries' in info else info

                all_formats = target.get('formats', [])
                
                resolutions = sorted(
                    {
                        f.get('height')
                        for f in all_formats
                        if f.get('height') is not None and f.get('vcodec') != 'none'
                    },
                    reverse=True
                )

                manual_subs = list(target.get('subtitles', {}).keys())
                auto_subs = list(target.get('automatic_captions', {}).keys())
                
                # Extract available audio languages from formats
                audio_langs = set()
                for f in all_formats:
                    if f.get('acodec') != 'none' and f.get('language'):
                        audio_langs.add(f.get('language'))
                
                # Extract detailed format information for stream selection
                audio_formats = []
                video_formats = []
                for f in all_formats:
                    # Handle file size - use filesize_approx if filesize is None or has "~" symbol
                    filesize = f.get('filesize')
                    filesize_approx = f.get('filesize_approx')
                    
                    # Clean up filesize if it contains "~" or other non-numeric characters
                    if filesize is not None:
                        try:
                            # Convert to float if it's a number, otherwise use approx
                            if isinstance(filesize, str) and '~' in filesize:
                                filesize = None  # Use approx instead
                            else:
                                filesize = float(filesize) if filesize else None
                        except (ValueError, TypeError):
                            filesize = None
                    
                    if filesize_approx is not None:
                        try:
                            filesize_approx = float(filesize_approx) if filesize_approx else None
                        except (ValueError, TypeError):
                            filesize_approx = None
                    
                    # Use approximate size if exact size is not available
                    final_filesize = filesize if filesize is not None else filesize_approx
                    
                    # Audio-only formats
                    if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                        audio_formats.append({
                            'id': f.get('format_id'),
                            'ext': f.get('ext'),
                            'abr': f.get('abr'),
                            'acodec': f.get('acodec'),
                            'format_note': f.get('format_note'),
                            'filesize': final_filesize,
                            'filesize_approx': filesize_approx
                        })
                    # Video formats (with or without audio)
                    elif f.get('vcodec') != 'none':
                        video_formats.append({
                            'id': f.get('format_id'),
                            'ext': f.get('ext'),
                            'width': f.get('width'),
                            'height': f.get('height'),
                            'fps': f.get('fps'),
                            'vcodec': f.get('vcodec'),
                            'acodec': f.get('acodec'),
                            'filesize': final_filesize,
                            'filesize_approx': filesize_approx,
                            'has_audio': f.get('acodec') != 'none'
                        })

                # Extract channel/uploader information
                channel = target.get('channel') or target.get('uploader') or target.get('artist') or 'Unknown'
                uploader_id = target.get('uploader_id') or target.get('channel_id') or ''
                
                response_data = {
                    'title': info.get('title', 'Unknown Title'),
                    'channel': channel,
                    'channel_id': uploader_id,
                    'uploader': target.get('uploader', channel),
                    'is_playlist': 'entries' in info or 'list' in url,
                    'resolutions': list(resolutions)[:6],
                    'manual_subs': list(set(manual_subs)),
                    'auto_subs': list(set(auto_subs)),
                    'audio_langs': list(audio_langs),
                    'audio_formats': audio_formats,
                    'video_formats': video_formats
                }

                # Cache the metadata (only for videos, not playlists)
                if 'list' not in url:
                    self.cache_manager.set(url, response_data)
                    print(f"💾 [Cache Saved] Metadata cached for: '{response_data['title']}' by '{response_data['channel']}'")

                print(f"✨ [API Response] Successfully fetched metadata for: '{info.get('title')}'")
                return jsonify({
                    **response_data,
                    'from_cache': False
                }), 200

            except Exception as e:
                print(f"❌ [API Error] /api/metadata extraction failed: {str(e)}")
                return jsonify({'error': f"Metadata extraction failed: {str(e)}"}), 500

        @self.app.route('/api/playlist-items', methods=['GET', 'POST', 'OPTIONS'])
        def fetch_playlist_items():
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            url = None
            cookies = ""

            if request.method == 'POST':
                data = request.json or {}
                url = data.get('url')
                cookies = data.get('cookies', '').strip()
            else:
                url = request.args.get('url')

            if not url:
                return jsonify({'error': 'Missing URL parameter'}), 400

            # Log incoming playlist metadata request for diagnostics
            print(f"\n📥 [API Request] /api/playlist-items URL: {url}")

            try:
                cmd = yt_dlp_cmd('--flat-playlist', '-J')
                
                # Pass session cookies for playlist flat list extraction
                if cookies:
                    cmd += ['--add-header', f'Cookie: {cookies}']

                cmd += [url]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    check=True,
                    creationflags=NO_WINDOW_FLAG
                )
                info = json.loads(result.stdout)
                entries = info.get('entries', [])
                
                parsed_entries = []
                for idx, entry in enumerate(entries):
                    parsed_entries.append({
                        'index': entry.get('playlist_index') or (idx + 1),
                        'id': entry.get('id'),
                        'title': entry.get('title', 'Untitled Video'),
                        'url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                    })

                print(f"✨ [API Response] Extracted {len(parsed_entries)} items from playlist: '{info.get('title')}'")
                return jsonify({
                    'playlist_title': info.get('title', 'Playlist'),
                    'videos': parsed_entries
                }), 200
            except Exception as e:
                print(f"❌ [API Error] /api/playlist-items extraction failed: {str(e)}")
                return jsonify({'error': f"Failed to extract playlist items: {str(e)}"}), 500

        @self.app.route('/api/select-dir', methods=['GET', 'OPTIONS'])
        def select_directory():
            """Deprecated: folder selection is now handled client-side in the browser."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            return jsonify({'status': 'deprecated', 'message': 'Use browser-side folder input instead.'}), 410

        @self.app.route('/api/enqueue', methods=['POST', 'OPTIONS'])
        def enqueue_download():
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            try:
                data = request.json
                if not data or 'url' not in data:
                    return jsonify({'error': 'Missing URL parameter'}), 400

                job_id = f"job_{int(time.time() * 1000)}"
                
                # Log raw data payload sent from the userscript for diagnostics
                print(f"\n📥 [API Request] /api/enqueue Job ID: {job_id}")
                print(f"Raw Request Payload:\n{json.dumps(data, indent=2)}")

                job_payload = {
                    'id': job_id,
                    'url': data.get('url'),
                    'custom_title': data.get('title', '').strip(),
                    'prefix': data.get('prefix', '').strip(),
                    'disable_title': bool(data.get('disable_title', False)),
                    'use_numbering': bool(data.get('use_numbering', False)),
                    'is_playlist': bool(data.get('is_playlist', False)),
                    'out_format': data.get('out_format', 'mp4'),
                    'resolution': str(data.get('resolution', '1080')),
                    'subs_mode': data.get('subs_mode', 'none'),
                    'selected_subs': data.get('selected_subs', []),
                    'folder': data.get('folder', ''),
                    'cookies': data.get('cookies', ''),
                    'advanced_mode': bool(data.get('advanced_mode', False)),
                    'audio_format_id': data.get('audio_format_id'),
                    'video_format_id': data.get('video_format_id'),
                    'combined_format_id': data.get('combined_format_id'),
                    'smart_playlist': bool(data.get('smart_playlist', False)),
                    'download_thumbnail': bool(data.get('download_thumbnail', False)),
                    'embed_thumbnail': bool(data.get('embed_thumbnail', False)),
                    'disable_archive': bool(data.get('disable_archive', False)),
                    'thumbnail_only': bool(data.get('thumbnail_only', False)),
                    'custom_args': data.get('custom_args', '')
                }

                # Register state manager
                self.state_manager.add_job(
                    job_id=job_id,
                    title=data.get('title', 'Initializing...'),
                    url=data.get('url'),
                    is_playlist=bool(data.get('is_playlist', False))
                )

                self.signals.job_received.emit(job_payload)
                return jsonify({'status': 'success', 'job_id': job_id}), 200

            except Exception as e:
                print(f"❌ [API Error] /api/enqueue failed: {str(e)}")
                return jsonify({'error': f"Enqueue failed: {str(e)}"}), 500

        @self.app.route('/api/status', methods=['GET', 'OPTIONS'])
        def get_all_statuses():
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            return jsonify(self.state_manager.get_all_jobs()), 200

        @self.app.route('/api/cancel', methods=['POST', 'OPTIONS'])
        def cancel_job():
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            data = request.json or {}
            job_id = data.get('job_id')
            if not job_id:
                return jsonify({'error': 'Missing job_id parameter'}), 400

            self.state_manager.cancel_job(job_id)
            self.signals.cancel_requested.emit(job_id)
            return jsonify({'status': 'success', 'message': f'Job {job_id} cancelled.'}), 200

        @self.app.route('/api/reorder-queue', methods=['POST', 'OPTIONS'])
        def reorder_queue():
            """Reorder jobs in the download queue."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            data = request.json or {}
            job_order = data.get('job_order')  # Array of job IDs in desired order

            if not job_order or not isinstance(job_order, list):
                return jsonify({'error': 'Missing or invalid job_order parameter'}), 400

            try:
                self.state_manager.reorder_queue(job_order)
                return jsonify({'status': 'success', 'message': 'Queue reordered successfully'}), 200
            except Exception as e:
                print(f"❌ [API Error] /api/reorder-queue failed: {str(e)}")
                return jsonify({'error': f"Reorder failed: {str(e)}"}), 500

        @self.app.route('/api/history', methods=['GET', 'OPTIONS'])
        def get_download_history():
            """Get download history."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            try:
                import os
                import json
                from downloader import DOWNLOAD_HISTORY_FILE
                
                history = []
                if os.path.exists(DOWNLOAD_HISTORY_FILE):
                    with open(DOWNLOAD_HISTORY_FILE, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                
                return jsonify({'status': 'success', 'history': history}), 200
            except Exception as e:
                print(f"❌ [API Error] /api/history failed: {str(e)}")
                return jsonify({'error': f"Failed to load history: {str(e)}"}), 500

        @self.app.route('/api/history/clear', methods=['POST', 'OPTIONS'])
        def clear_download_history():
            """Clear download history."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            try:
                import os
                from downloader import DOWNLOAD_HISTORY_FILE
                
                if os.path.exists(DOWNLOAD_HISTORY_FILE):
                    os.remove(DOWNLOAD_HISTORY_FILE)
                
                return jsonify({'status': 'success', 'message': 'History cleared'}), 200
            except Exception as e:
                print(f"❌ [API Error] /api/history/clear failed: {str(e)}")
                return jsonify({'error': f"Failed to clear history: {str(e)}"}), 500

        @self.app.route('/api/statistics', methods=['GET', 'OPTIONS'])
        def get_download_statistics():
            """Get download statistics."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            try:
                import os
                import json
                from downloader import DOWNLOAD_STATISTICS_FILE
                
                stats = {}
                if os.path.exists(DOWNLOAD_STATISTICS_FILE):
                    with open(DOWNLOAD_STATISTICS_FILE, 'r', encoding='utf-8') as f:
                        stats = json.load(f)
                
                return jsonify({'status': 'success', 'statistics': stats}), 200
            except Exception as e:
                print(f"❌ [API Error] /api/statistics failed: {str(e)}")
                return jsonify({'error': f"Failed to load statistics: {str(e)}"}), 500

        @self.app.route('/api/folder-dialog', methods=['POST', 'OPTIONS'])
        def open_folder_dialog():
            """Open native folder dialog and return selected path."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            # Check if dialog is already open to prevent double dialogs
            if self.folder_dialog_result is not None:
                print("⚠️ [Folder Dialog] Dialog already in progress, skipping duplicate request")
                return jsonify({'status': 'already_open', 'message': 'Folder dialog already open'}), 200

            self.signals.folder_dialog_requested.emit()
            return jsonify({'status': 'requested', 'message': 'Folder dialog opened'}), 200

        @self.app.route('/api/folder-dialog-result', methods=['GET', 'OPTIONS'])
        def get_folder_dialog_result():
            """Get the result of the folder dialog."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            if self.folder_dialog_result is not None:
                result = self.folder_dialog_result
                self.folder_dialog_result = None  # Clear after reading
                return jsonify({'status': 'success', 'path': result}), 200
            else:
                return jsonify({'status': 'pending', 'message': 'No dialog result available'}), 200

        @self.app.route('/api/file-dialog', methods=['POST', 'OPTIONS'])
        def open_file_dialog():
            """Open native file dialog and return selected path."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            data = request.json or {}
            self.signals.file_dialog_requested.emit(data)
            return jsonify({'status': 'requested', 'message': 'File dialog opened'}), 200

        @self.app.route('/api/file-dialog-result', methods=['GET', 'OPTIONS'])
        def get_file_dialog_result():
            """Get the result of the file dialog."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            if self.file_dialog_result is not None:
                result = self.file_dialog_result
                self.file_dialog_result = None  # Clear after reading
                return jsonify({'status': 'success', 'path': result}), 200
            else:
                return jsonify({'status': 'pending', 'message': 'No dialog result available'}), 200

        @self.app.route('/api/tray-icon-upload', methods=['POST', 'OPTIONS'])
        def upload_tray_icon():
            """Upload custom tray icon and save to app directory."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            try:
                import base64
                data = request.json
                file_data = data.get('file_data', '')
                file_ext = data.get('file_ext', 'png')
                
                # Extract base64 data
                if ',' in file_data:
                    file_data = file_data.split(',')[1]
                
                # Decode base64
                file_bytes = base64.b64decode(file_data)
                
                # Save to app directory as custom_icon.*
                app_dir = os.path.dirname(os.path.abspath(__file__))
                icon_path = os.path.join(app_dir, f'custom_icon.{file_ext}')
                
                with open(icon_path, 'wb') as f:
                    f.write(file_bytes)
                
                print(f"✅ [Tray Icon] Custom icon saved to: {icon_path}")
                
                # Update settings to use custom icon
                from settings import load_settings, save_settings
                settings = load_settings()
                settings['use_custom_tray_icon'] = True
                save_settings(settings)
                
                return jsonify({'status': 'success', 'message': 'Icon uploaded successfully'}), 200
            except Exception as e:
                print(f"❌ [Tray Icon] Upload failed: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/userscript.user.js', methods=['GET'])
        def serve_userscript():
            """Serve the userscript file for Tampermonkey auto-update."""
            try:
                script_path = os.path.join(os.path.dirname(__file__), 'userscript.user.js')
                if os.path.exists(script_path):
                    with open(script_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    return content, 200, {'Content-Type': 'text/javascript; charset=utf-8'}
                else:
                    return 'Userscript file not found', 404
            except Exception as e:
                print(f"Error serving userscript: {e}")
                return f'Error: {str(e)}', 500

        # ── Scheduler endpoints ─────────────────────────────────────────────

        @self.app.route('/api/schedules', methods=['GET', 'OPTIONS'])
        def get_schedules():
            """Get all scheduled playlist downloads."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            if hasattr(self, 'scheduler'):
                return jsonify(self.scheduler.get_schedules()), 200
            return jsonify([]), 200

        @self.app.route('/api/schedules', methods=['POST', 'OPTIONS'])
        def add_schedule():
            """Add a new scheduled playlist download."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            if not hasattr(self, 'scheduler'):
                return jsonify({'error': 'Scheduler not available'}), 500
            
            data = request.json or {}
            playlist_url = data.get('playlist_url')
            interval_hours = data.get('interval_hours', 24)
            settings = data.get('settings', {})
            
            if not playlist_url:
                return jsonify({'error': 'Missing playlist_url'}), 400
            
            if self.scheduler.add_schedule(playlist_url, interval_hours, settings):
                return jsonify({'status': 'success', 'message': 'Schedule added'}), 200
            return jsonify({'error': 'Failed to add schedule'}), 500

        @self.app.route('/api/schedules/<playlist_url>', methods=['DELETE', 'OPTIONS'])
        def remove_schedule(playlist_url):
            """Remove a scheduled playlist download."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            if not hasattr(self, 'scheduler'):
                return jsonify({'error': 'Scheduler not available'}), 500
            
            self.scheduler.remove_schedule(playlist_url)
            return jsonify({'status': 'success', 'message': 'Schedule removed'}), 200

        @self.app.route('/api/schedules/<playlist_url>/toggle', methods=['POST', 'OPTIONS'])
        def toggle_schedule(playlist_url):
            """Enable/disable a scheduled playlist download."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            if not hasattr(self, 'scheduler'):
                return jsonify({'error': 'Scheduler not available'}), 500
            
            enabled = self.scheduler.toggle_schedule(playlist_url)
            return jsonify({'status': 'success', 'enabled': enabled}), 200

        # ── Cache endpoints ────────────────────────────────────────────────

        @self.app.route('/api/cache/expiry', methods=['GET', 'OPTIONS'])
        def get_cache_expiry():
            """Get current cache expiry setting in days."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            if hasattr(self, 'cache_manager'):
                return jsonify({'expiry_days': self.cache_manager.get_expiry_days()}), 200
            return jsonify({'error': 'Cache manager not available'}), 500

        @self.app.route('/api/cache/expiry', methods=['POST', 'OPTIONS'])
        def set_cache_expiry():
            """Set cache expiry in days. Null means no expiry."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            if not hasattr(self, 'cache_manager'):
                return jsonify({'error': 'Cache manager not available'}), 500
            
            data = request.json or {}
            days = data.get('days')  # None means no expiry
            
            self.cache_manager.set_expiry_days(days)
            print(f"⚙️ [Cache] Expiry set to: {'No limit' if days is None else f'{days} days'}")
            return jsonify({'status': 'success', 'expiry_days': days}), 200

        @self.app.route('/api/cache/clear', methods=['POST', 'OPTIONS'])
        def clear_cache():
            """Clear all cached metadata."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            if not hasattr(self, 'cache_manager'):
                return jsonify({'error': 'Cache manager not available'}), 500
            
            self.cache_manager.clear()
            print("🗑️ [Cache] All cache cleared")
            return jsonify({'status': 'success', 'message': 'Cache cleared'}), 200

        @self.app.route('/api/cache/cleanup', methods=['POST', 'OPTIONS'])
        def cleanup_cache():
            """Remove expired cache entries."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            if not hasattr(self, 'cache_manager'):
                return jsonify({'error': 'Cache manager not available'}), 500
            
            removed = self.cache_manager.cleanup_expired()
            print(f"🧹 [Cache] Cleaned up {removed} expired entries")
            return jsonify({'status': 'success', 'removed': removed}), 200

        # ── Download Archive Editor endpoints ───────────────────────────────

        @self.app.route('/api/archive/read', methods=['POST', 'OPTIONS'])
        def read_archive_file():
            """Read a downloaded.txt file and return entries with metadata."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            data = request.json or {}
            file_path = data.get('file_path')
            
            if not file_path or not os.path.exists(file_path):
                return jsonify({'error': 'Invalid or missing file path'}), 400
            
            try:
                # Read the archive file
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Parse entries (yt-dlp format: youtube VIDEO_ID)
                entries = []
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 2:
                            extractor = parts[0]
                            video_id = parts[1]
                            entries.append({
                                'extractor': extractor,
                                'video_id': video_id,
                                'line': line.strip()
                            })
                
                # Load metadata database
                metadata_db = {}
                if os.path.exists(VIDEO_METADATA_DB):
                    with open(VIDEO_METADATA_DB, 'r', encoding='utf-8') as f:
                        metadata_db = json.load(f)
                
                # Enrich entries with metadata - try to match by video_id in URL
                enriched_entries = []
                for entry in entries:
                    title = 'Unknown'
                    channel = 'Unknown'
                    video_id = entry['video_id']
                    
                    print(f"[Archive] Looking for metadata for video_id: {video_id}")
                    print(f"[Archive] Total metadata entries: {len(metadata_db)}")
                    
                    # Try to find matching metadata by searching for video_id in URLs
                    for url, meta in metadata_db.items():
                        # Check if video_id is in the URL (handle different URL formats)
                        if video_id in url:
                            title = meta.get('title', 'Unknown')
                            channel = meta.get('channel', 'Unknown')
                            print(f"[Archive] Found metadata for {video_id}: {title} by {channel}")
                            break
                    
                    # If still unknown, try more flexible matching
                    if title == 'Unknown':
                        # Try exact match or URL parameter match
                        for url, meta in metadata_db.items():
                            # Extract video ID from metadata URL
                            if 'v=' in url:
                                url_video_id = url.split('v=')[1].split('&')[0]
                                if url_video_id == video_id:
                                    title = meta.get('title', 'Unknown')
                                    channel = meta.get('channel', 'Unknown')
                                    print(f"[Archive] Found metadata via v= param for {video_id}: {title}")
                                    break
                            elif 'youtu.be/' in url:
                                url_video_id = url.split('youtu.be/')[1].split('?')[0]
                                if url_video_id == video_id:
                                    title = meta.get('title', 'Unknown')
                                    channel = meta.get('channel', 'Unknown')
                                    print(f"[Archive] Found metadata via youtu.be for {video_id}: {title}")
                                    break
                    
                    # Try direct video_id match as key
                    if title == 'Unknown' and video_id in metadata_db:
                        title = metadata_db[video_id].get('title', 'Unknown')
                        channel = metadata_db[video_id].get('channel', 'Unknown')
                        print(f"[Archive] Found metadata via direct key match for {video_id}: {title}")
                    
                    enriched_entries.append({
                        **entry,
                        'title': title,
                        'channel': channel
                    })
                
                return jsonify({
                    'status': 'success',
                    'entries': enriched_entries,
                    'total': len(enriched_entries)
                }), 200
            except Exception as e:
                print(f"❌ [Archive] Error reading file: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/archive/remove', methods=['POST', 'OPTIONS'])
        def remove_archive_entries():
            """Remove specific entries from downloaded.txt file."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            data = request.json or {}
            file_path = data.get('file_path')
            entries_to_remove = data.get('entries', [])  # List of line strings
            
            if not file_path or not os.path.exists(file_path):
                return jsonify({'error': 'Invalid or missing file path'}), 400
            
            if not entries_to_remove:
                return jsonify({'error': 'No entries to remove'}), 400
            
            try:
                # Read the file
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Filter out entries to remove
                new_lines = []
                removed_count = 0
                for line in lines:
                    if line.strip() in entries_to_remove:
                        removed_count += 1
                    else:
                        new_lines.append(line)
                
                # Write back
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                
                print(f"🗑️ [Archive] Removed {removed_count} entries from {file_path}")
                return jsonify({
                    'status': 'success',
                    'removed': removed_count
                }), 200
            except Exception as e:
                print(f"❌ [Archive] Error removing entries: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/archive/metadata', methods=['POST', 'OPTIONS'])
        def save_video_metadata():
            """Save video metadata to centralized database."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            data = request.json or {}
            metadata = data.get('metadata', {})
            
            if not metadata:
                return jsonify({'error': 'No metadata provided'}), 400
            
            try:
                # Load existing database
                metadata_db = {}
                if os.path.exists(VIDEO_METADATA_DB):
                    with open(VIDEO_METADATA_DB, 'r', encoding='utf-8') as f:
                        metadata_db = json.load(f)
                
                # Update with new metadata
                for key, value in metadata.items():
                    metadata_db[key] = value
                    # Also add alternative keys for better matching
                    if 'original_url' in value:
                        url = value['original_url']
                        if 'v=' in url:
                            video_id = url.split('v=')[1].split('&')[0]
                            metadata_db[f"v={video_id}"] = value
                            metadata_db[video_id] = value
                        elif 'youtu.be/' in url:
                            video_id = url.split('youtu.be/')[1].split('?')[0]
                            metadata_db[f"youtu.be/{video_id}"] = value
                            metadata_db[video_id] = value
                
                # Save back
                with open(VIDEO_METADATA_DB, 'w', encoding='utf-8') as f:
                    json.dump(metadata_db, f, indent=None, separators=(',', ':'), ensure_ascii=False)
                
                print(f"✅ [Archive] Saved metadata for {len(metadata)} entries")
                return jsonify({'status': 'success'}), 200
            except Exception as e:
                print(f"❌ [Archive] Error saving metadata: {e}")
                return jsonify({'error': str(e)}), 500

        # ── Embedded Video Window endpoints ────────────────────────────────────

        @self.app.route('/api/embedded-window', methods=['POST', 'OPTIONS'])
        def open_embedded_window():
            """Open PyQt window for embedded video download options."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            
            data = request.json or {}
            url = data.get('url')
            video_id = data.get('video_id')
            
            if not url or not video_id:
                return jsonify({'error': 'Missing URL or video_id'}), 400
            
            try:
                # Emit signal to open embedded window in main thread
                self.signals.embedded_window_requested.emit(url, video_id)
                print(f"🎬 [Embedded Window] Requested for video: {video_id}")
                return jsonify({'status': 'success'}), 200
            except Exception as e:
                print(f"❌ [Embedded Window] Error: {e}")
                return jsonify({'error': str(e)}), 500

        # ── Settings endpoints ────────────────────────────────────────────

        @self.app.route('/api/settings', methods=['GET', 'POST', 'OPTIONS'])
        def handle_settings():
            """GET: return current defaults.  POST: merge + save new prefs."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200

            if request.method == 'GET':
                return jsonify(load_settings()), 200

            # POST — partial or full update
            data = request.json or {}
            if not data:
                return jsonify({'error': 'Empty payload'}), 400

            current = load_settings()
            current.update(data)          # merge; unknown keys are silently accepted
            ok = save_settings(current)
            if ok:
                print(f"⚙️ [Settings] Preferences updated via API: {list(data.keys())}")
                return jsonify({'status': 'saved', 'settings': current}), 200
            return jsonify({'error': 'Failed to write settings file'}), 500

        @self.app.route('/api/open-settings', methods=['GET', 'OPTIONS'])
        def open_settings_window():
            """Signal main thread to show the Settings dialog."""
            if request.method == 'OPTIONS':
                return jsonify({'status': 'ok'}), 200
            self.signals.open_settings_requested.emit()
            return jsonify({'status': 'ok', 'message': 'Settings window requested.'}), 200

    def run(self):
        try:
            self.app.run(host='127.0.0.1', port=self.port, debug=False, use_reloader=False)
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"❌ Port {self.port} is already in use. Please stop the other application or change the port.")
            else:
                print(f"❌ Flask execution failed: {e}")
        except Exception as err:
            print(f"❌ Flask execution failed: {err}")
