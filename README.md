# YouTube Desktop Downloader Bridge Pro

A fully browser-based headless YouTube downloader with advanced format selection, smart playlist processing, native folder picker integration, and a draggable browser HUD. No desktop windows required - everything runs through a browser userscript and local API server.

**GitHub Repository:** https://github.com/Entity6814/YTDownloader

## Features

### Core Features
- **Advanced Stream Selection**: Choose specific video/audio format IDs for precise quality control
- **Independent Audio/Video Picks**: Select audio-only and video-only streams separately to build the exact output you want
- **Always-Visible Audio/Video Tables**: Both audio and video stream tables are always visible for easy comparison
- **Smart Playlist Processing**: Custom format matching algorithm ensures consistent quality across playlist downloads
- **Smart Audio Selection**: Bitrate-based audio format matching with codec preference (AAC > Opus > others)
- **Format ID Mapping**: Intelligent resolution matching (137→1080p, 136→720p, etc.)
- **Native Folder Picker**: Browser-integrated folder selection via local API
- **Auto Format Configuration**: Smart recode automatically switches output format based on selection
- **Stream Sorting**: Sort streams by quality, format ID, or default order
- **Progress Tracking**: Real-time download progress with speed and ETA display
- **Playlist Matrix**: Advanced playlist customization with per-video quality overrides
- **Movable Browser HUD**: Drag the downloader panel anywhere and keep its position across restarts
- **Hide/Restore Flow**: Hide the panel with the close button and bring it back from the OrangeMonkey script menu

### Advanced Features
- **Basic/Advanced Mode Toggle**: Switch between simple and advanced UI modes
  - **Basic Mode**: Essential features for normal users
  - **Advanced Mode**: Batch downloads, archive editor, custom arguments, and shutdown options
- **Batch Download**: Download multiple URLs from text input in advanced mode
- **Archive Editor**: Edit downloaded.txt files to allow re-downloading previously downloaded videos
  - Centralized JSON database stores video metadata (title, channel)
  - Select and remove entries from downloaded.txt files
  - Metadata automatically saved during downloads
- **Auto-Shutdown**: Automatically close the application when all downloads complete
- **PC Shutdown**: Automatically shut down the computer when all downloads complete (Windows/Linux/macOS support)
- **Quick Shutdown Toggle**: Accessible shutdown button in console header (advanced mode)
  - Cycles through: Off → App Shutdown → PC Shutdown
  - Visual indicator shows current mode
- **Custom Tray Icon**: Upload custom icons for the system tray (supports PNG, JPG, JPEG, ICO, BMP, SVG)
- **System Tray Integration**: System tray icon with real-time download status and queue information
- **PyQt6 Support**: Automatic PyQt5/PyQt6 compatibility checking with fallback support
- **Dependency Checker**: Built-in dependency verification with PyQt compatibility testing

### Technical Features
- **Custom Format Matching**: Bypasses yt-dlp's inconsistent format selection with per-video analysis
- **Resolution-Based Fallback**: Finds closest resolution match when exact format unavailable
- **Codec Preference**: Prioritizes AAC over Opus for audio quality
- **Error Handling**: Robust error handling with timeout and retry logic
- **Thread-Safe State Management**: Synchronized job tracking across threads

## Setup

### Prerequisites
- Python 3.8 or higher
- PyQt5 or PyQt6 (automatic compatibility check)
- Flask
- yt-dlp
- yt-dlp-getpot-wpc (for PO token support)
- A JavaScript runtime for yt-dlp: Deno preferred, Node.js as fallback
- OrangeMonkey Pro browser extension (recommended)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Entity6814/YTDownloader.git
   cd YTDownloader
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run dependency checker** (recommended - also updates yt-dlp)
   ```bash
   python check.py
   ```
   This will:
   - Update yt-dlp to the latest version
   - Verify all dependencies including PyQt5/PyQt6 compatibility
   - Check JavaScript runtime installation
   - Test yt-dlp integration

4. **Install a JavaScript runtime**
   - Deno is preferred and will be used first if available
   - Node.js is supported as a fallback
   - yt-dlp is started with `--js-runtimes` automatically by the app

   **Install Deno (Recommended):**
   ```bash
   # Windows (PowerShell)
   irm https://deno.land/install.ps1 | iex

   # Linux/Mac
   curl -fsSL https://deno.land/install.sh | sh
   ```

   **Install Node.js (Alternative):**
   ```bash
   # Download from: https://nodejs.org/
   ```

5. **Install OrangeMonkey Pro** (Recommended)
   - Chrome/Edge: [OrangeMonkey Pro Extension](https://chrome.google.com/webstore/detail/orangemonkey-pro/gmehilddngnlaajdghbmbhnjdgocgbb)
   - Firefox: [OrangeMonkey Pro Extension](https://addons.mozilla.org/en-US/firefox/addon/orangemonkey-pro/)

   **Note**: This script has been tested and works flawlessly with OrangeMonkey Pro. Tampermonkey may experience compatibility issues.

6. **Install the Userscript**
   - Open `userscript.user.js` in a text editor
   - Copy the entire content
   - In OrangeMonkey Pro, click "Create a new script"
   - Paste the userscript content
   - Save the script (Ctrl+S)

## Usage

### Quick Start Commands

```bash
# Clone the repository
git clone https://github.com/Entity6814/YTDownloader.git
cd YTDownloader

# Install dependencies
pip install -r requirements.txt

# Run dependency checker (updates yt-dlp automatically)
python check.py

# Start the application
python main.py
```

### Starting the Application

1. **Run the main application**
   ```bash
   python main.py
   ```

2. **The application will:**
   - Start the local API server on `http://localhost:5000`
   - Show a system tray icon in your system tray
   - Open a settings window on first run
   - Display "YouTube Desktop Downloader Bridge Pro" in the tray

3. **Configure settings** (first run only)
   - Set default download folder
   - Choose default resolution
   - Set output format preference
   - Configure subtitle options
   - Save the downloader panel position and visibility state

4. **System Tray Features**
   - **Left-click on tray icon**: Shows about dialog with creator info
   - **Right-click on tray icon**: Shows context menu with:
     - Current download status
     - Queue information
     - Exit option

## Quick Commands Reference

```bash
# Clone and setup
git clone https://github.com/Entity6814/YTDownloader.git
cd YTDownloader
pip install -r requirements.txt

# Run dependency checker (updates yt-dlp automatically)
python check.py

# Start the application
python main.py

# Update yt-dlp manually
pip install --upgrade yt-dlp
```

### Downloading Videos

1. **Navigate to any YouTube video**
2. **Click the download button** that appears on the video page
3. **Configure download options:**
   - **Folder**: Choose download location (uses native folder picker)
   - **Format Container**: MP4, MKV, WebM, MP3, WAV, or Original
   - **Stream Selection**: Both audio and video tables are always visible:
     - **🎵 Audio**: Audio-only formats with bitrate info
     - **🎞️ Video**: Video-only formats (no audio)
   - **Sort By**: Sort streams by Default, Quality (High→Low), Quality (Low→High), or Format ID
   - **Top Format Filter**: Selecting MP3/WAV focuses the picker on audio streams and clears video selections
   - **Subtitles**: Choose subtitle download options
   - **Playlist Options**: For playlists, enable auto-numbering and custom prefixes
   - **Thumbnail Options**:
     - Download thumbnail as separate file
     - Embed thumbnail in audio files (MP3/WAV)
     - Download thumbnail only (no video)
   - **Archive Options**:
     - Disable download archive to allow re-downloads
   - **Custom Arguments** (Advanced Mode): Additional yt-dlp arguments for advanced users

4. **Click "Download"** to start the download

### Advanced Usage

#### Smart Playlist Mode
1. **Enable "Smart format matching"** checkbox in playlist options
2. **Select your preferred format** from the stream selection tabs
3. **Download playlist** - each video will be analyzed individually:
   - Exact format match if available
   - Closest resolution match if exact unavailable
   - Smart audio format matching for consistent audio quality

#### Playlist Matrix (Advanced)
1. **Click "🔍 Open Playlist Customizer Matrix"**
2. **View all playlist videos** with individual quality settings
3. **Override quality per video** if needed
4. **Set custom titles** for individual videos
5. **Save matrix** to apply custom settings

#### Archive Editor (Advanced Mode)
1. **Click "📝 Archive"** button in the console header
2. **Enter the full path** to your downloaded.txt file
3. **Click "Load"** to read the archive file
4. **Select entries** you want to remove by checking the checkboxes
5. **Click "Remove Selected"** to delete entries from the archive
6. **Reload** to see updated entries

**Note**: The archive editor uses a centralized JSON database (`~/.video_downloader_metadata.json`) to store video metadata (title, channel) for easier identification. This metadata is automatically saved during successful downloads.

#### Stream Selection Guide
- **Audio Table**: Choose audio-only formats (good for music/podcasts)
  - Format IDs: 140 (128kbps AAC), 141 (256kbps AAC), 251 (160kbps Opus)
- **Video Table**: Choose video-only formats (requires audio merging)
  - Format IDs: 137 (1080p), 136 (720p), 135 (480p)

#### UI Behavior Notes
- The downloader HUD is draggable by its header.
- The panel position is stored as percentages so it can restore more gracefully after window-size changes.
- The close button hides the panel, and the OrangeMonkey menu can show it again.
- If the backend goes offline, the userscript hides the HUD automatically and shows it again once the API returns.

## Configuration

### Settings File
Settings are stored in `settings.json`:
```json
{
  "folder": "D:/Downloads",
  "resolution": "1080",
  "out_format": "mp4",
  "disable_title": false,
  "prefix": "",
  "use_numbering": true,
  "subs_mode": "none",
  "selected_subs": [],
  "smart_playlist": false,
  "console_position": {
    "mode": "bottom-right",
    "left": null,
    "top": null
  },
  "console_hidden": false
}
```

### Format ID Reference

#### Video Format IDs
| Format ID | Resolution | Codec | Type |
|-----------|------------|-------|------|
| 137 | 1080p | H.264 | Video-only |
| 136 | 720p | H.264 | Video-only |
| 135 | 480p | H.264 | Video-only |
| 134 | 360p | H.264 | Video-only |
| 248 | 1080p | VP9 | Video-only (WebM) |
| 247 | 720p | VP9 | Video-only (WebM) |
| 22 | 720p | H.264 | Combined |
| 18 | 360p | H.264 | Combined |

#### Audio Format IDs
| Format ID | Bitrate | Codec | Container |
|-----------|---------|-------|-----------|
| 140 | 128kbps | AAC | M4A |
| 141 | 256kbps | AAC | M4A |
| 139 | 48kbps | AAC | M4A |
| 251 | 160kbps | Opus | WebM |
| 250 | 70kbps | Opus | WebM |
| 249 | 50kbps | Opus | WebM |

## Debugging

### Common Issues

#### "Headless service is offline"
**Cause**: The Python application is not running
**Solution**: Run `python main.py` and ensure it stays running

#### "Failed to fetch metadata"
**Cause**: Network issues or yt-dlp not installed
**Solution**: 
1. Check internet connection
2. Update yt-dlp: `pip install --upgrade yt-dlp`
3. Check browser console for detailed errors

#### "Download failed with non-zero code"
**Cause**: Various reasons (video unavailable, region restrictions, etc.)
**Solution**:
1. Check the error message in the download console
2. Try a different format
3. Check if video is available in your region
4. Update yt-dlp to latest version

#### Smart playlist not working
**Cause**: Playlist metadata fetch failed
**Solution**:
1. Check browser console for errors
2. Ensure playlist is public (not private)
3. Try without smart mode first to verify basic functionality

#### Downloader panel disappears
**Cause**: The backend is offline or the panel was hidden manually
**Solution**:
1. Start the Python app with `python main.py`
2. Use the OrangeMonkey script menu to show the downloader again
3. Reset the saved panel position if it ended up off-screen

### Debug Mode

Enable debug logging by checking the console output:
```bash
python main.py
```

The application logs:
- API requests and responses
- Format selection decisions
- Download progress
- Error details

### Browser Console Debugging

1. **Open browser console** (F12)
2. **Filter for "[Wizard]"** to see userscript logs
3. **Check for API errors** in the Network tab
4. **Verify API server** is running on `http://localhost:5000`

### Log Files

The application outputs detailed logs to the console:
- `[API Request]` - API server requests
- `[Wizard]` - Userscript operations
- `[Job ID]` - Download worker operations
- `[Smart matching]` - Format matching decisions
- `yt-dlp JavaScript runtime` - The selected runtime used by yt-dlp at startup

## Architecture

### Components

1. **main.py**: Application entry point, PyQt5 GUI
2. **api_server.py**: Flask API server for browser communication
3. **downloader.py**: Download worker with smart format matching
4. **scheduler.py**: Playlist job scheduling
5. **settings.py**: Settings persistence
6. **cache_manager.py**: Metadata caching
7. **userscript.user.js**: Browser userscript for YouTube integration

### Data Flow

1. **User clicks download** → Userscript opens wizard
2. **Wizard requests metadata** → API server calls yt-dlp
3. **User selects formats** → Userscript sends job to API
4. **API queues job** → Download worker processes job
5. **Smart format matching** → Custom algorithm selects optimal formats
6. **Download execution** → yt-dlp downloads with specific format IDs
7. **Progress updates** → API server updates state manager
8. **Userscript polls status** → Real-time progress display

### Smart Format Matching Algorithm

1. **Fetch playlist metadata** for all videos
2. **Extract available formats** for each video
3. **Match user selection**:
   - Exact format ID match if available
   - Closest resolution match if exact unavailable
   - Prefer slightly higher quality over lower
4. **Audio format matching**:
   - Bitrate-based matching
   - Codec preference (AAC > Opus > others)
5. **Download individually** with specific format IDs

## Troubleshooting

### Performance Issues

**Slow metadata fetching**
- Check internet connection speed
- Disable VPN if causing delays
- Clear cache in settings

**Download speed issues**
- Check internet bandwidth
- Try different format (lower quality = faster)
- Check if YouTube is throttling

### Compatibility

**Browser compatibility**
- Chrome/Edge: Full support (OrangeMonkey Pro recommended)
- Firefox: Full support (OrangeMonkey Pro recommended)
- Safari: Limited support (userscript may need adjustments)
- Tampermonkey: May experience compatibility issues (OrangeMonkey Pro recommended)

**YouTube changes**
- If YouTube breaks the userscript:
  - Check for updates to yt-dlp
  - Update userscript selectors if needed
  - Report issues for troubleshooting

## Advanced Usage

### Command Line Options

The application can be customized by modifying the source code:
- Change API port in `api_server.py`
- Adjust format ID mappings in `downloader.py`
- Modify smart matching algorithm in `downloader.py`

### API Endpoints

- `GET/POST /api/metadata` - Fetch video metadata
- `POST /api/playlist-metadata` - Fetch playlist metadata
- `POST /api/enqueue` - Queue download job
- `POST /api/cancel` - Cancel download job
- `GET /api/jobs` - Get job status
- `POST /api/folder-dialog` - Request native folder picker
- `GET /api/settings` - Get settings
- `POST /api/settings` - Save settings
- `POST /api/archive/read` - Read downloaded.txt file with enriched metadata
- `POST /api/archive/remove` - Remove entries from downloaded.txt file
- `POST /api/archive/metadata` - Save video metadata to centralized database
- `GET /userscript.user.js` - Userscript auto-update

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

### How to Contribute
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Development Setup
To extend the application:
1. Add new format IDs to the mapping dictionaries
2. Extend the smart matching algorithm
3. Add new API endpoints for additional features
4. Enhance the userscript UI for new options

### Bug Fixes
**Please note:** Bug fixes and updates may take time due to personal development schedule. The creator provides no guarantee of regular updates or response times.

## GitHub Repository

**Project:** YouTube Desktop Downloader Bridge Pro  
**Creator:** Entity6814 (Vatsal Patel)  
**Repository:** https://github.com/Entity6814/YTDownloader  
**License:** MIT License

### Star the Repository
If you find this project useful, please consider giving it a ⭐ on GitHub!

### Report Issues
To report bugs or request features:
- Open an issue on GitHub: https://github.com/Entity6814/YTDownloader/issues
- Provide detailed error logs and reproduction steps
- Be patient with response times

## License

This project is licensed under the MIT License.

**Attribution:** While not required by the MIT License, it is appreciated to credit Entity6814 (Vatsal Patel) as the original creator when using, modifying, or distributing this software.

For full license details, see the [LICENSE](LICENSE) file.

## Legal Disclaimer

**IMPORTANT:** This software is intended for educational and personal use only. By using this software, you agree to:

- **Only download content you have the legal right to access**
- **Comply with YouTube's Terms of Service**
- **Respect copyright and intellectual property laws**
- **Take full responsibility for your use of this software**

The creator (Entity6814/Vatsal Patel) is **NOT responsible** for:
- Copyright infringement committed by users
- Violation of YouTube's Terms of Service
- Legal consequences arising from misuse
- Any damages or losses from software use

For the complete legal disclaimer, see [DISCLAIMER.md](DISCLAIMER.md).

## Bug Fixes and Support

**Please note:** Bug fixes and updates may take time due to personal development schedule. The creator provides no guarantee of:
- Regular updates or maintenance
- Response time for issues or bugs
- Implementation of feature requests

Community contributions are welcome! If you encounter issues:
1. Check existing GitHub issues for similar problems
2. Provide detailed error logs and reproduction steps
3. Be patient with response times

## Version History

## Version History

### Current Version
- Archive Editor: Edit downloaded.txt files with centralized metadata database
- Thumbnail Options: Download thumbnail only, embed in audio, or download as separate file
- Disable Archive Option: Allow re-downloads by skipping archive file creation
- Custom Arguments: Advanced mode support for custom yt-dlp arguments
- Quick Shutdown Toggle: Accessible shutdown button in console header
- Compact JSON Format: Settings and cache saved in single-line format for easier manual inspection
- Smart playlist format matching
- Custom audio format selection
- Advanced stream sorting
- Improved error handling
- Enhanced progress display
- Deno-first yt-dlp JavaScript runtime detection
- Draggable, persistently positioned browser HUD
- Hide/show support with OrangeMonkey menu commands

### Previous Versions
- Basic playlist support
- Stream selection UI
- Native folder picker
- Settings persistence
