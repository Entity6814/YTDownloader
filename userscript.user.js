// ==UserScript==
// @name         YouTube Desktop Downloader Bridge Pro
// @namespace    http://tampermonkey.net/
// @version      0.0
// @description  Fully browser-based headless downloader. Settings panel, defaults persistence, native folder picker. No desktop windows.
// @author       Entity6814 (Vatsal Patel)
// @license      MIT
// @match        *://*.youtube.com/*
// @match        *://music.youtube.com/*
// @match        *://*.youtube.com/embed/*
// @match        *://youtube.com/embed/*
// @match        *://www.youtube.com/embed/*
// @connect      localhost
// @connect      127.0.0.1
// @updateURL    http://localhost:5000/userscript.user.js
// @downloadURL  http://localhost:5000/userscript.user.js
// @grant        GM_xmlhttpRequest
// @run-at       document-start
// ==/UserScript==

(function () {
  'use strict';

  // ─── State ────────────────────────────────────────────────────────────────
  let activeCustomPath = "";
  let isConsoleCollapsed = false;
  let lastUrl = window.location.href;
  let lastFetchedUrl = "";
  let autoFetchedData = null;
  let consoleState = {
    hiddenByUser: false,
    hiddenByBackend: false,
    dragging: false,
    dragOffsetX: 0,
    dragOffsetY: 0
  };
  let backendOnline = null;
  let backendPollBusy = false;
  let backendPollTimer = null;
  let positionSaveTimer = null;
  let consoleEl = null;

  // Loaded from /api/settings on startup, used to pre-fill wizard fields
  let savedPrefs = {
    folder: "",
    resolution: "1080",
    out_format: "original",
    disable_title: false,
    prefix: "",
    use_numbering: true,
    subs_mode: "none",
    selected_subs: [],
    download_thumbnail: false,
    smart_playlist: false,
    console_position: {
      mode: "bottom-right",
      left: null,
      top: null
    },
    console_hidden: false
  };

  // ─── Language Map ─────────────────────────────────────────────────────────
  const LANG_MAP = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "pt": "Portuguese", "ru": "Russian",
    "hi": "Hindi", "ar": "Arabic", "tr": "Turkish", "vi": "Vietnamese", "pl": "Polish",
    "nl": "Dutch", "sv": "Swedish", "da": "Danish", "fi": "Finnish", "no": "Norwegian",
    "cs": "Czech", "el": "Greek", "he": "Hebrew", "id": "Indonesian", "th": "Thai",
    "uk": "Ukrainian", "hu": "Hungarian", "ro": "Romanian", "sk": "Slovak", "bg": "Bulgarian",
    "ca": "Catalan", "hr": "Croatian", "et": "Estonian", "fa": "Persian", "gu": "Gujarati",
    "is": "Icelandic", "kn": "Kannada", "lv": "Latvian", "lt": "Lithuanian", "ml": "Malayalam",
    "mr": "Marathi", "ne": "Nepali", "pa": "Punjabi", "si": "Sinhala", "sl": "Slovenian",
    "ta": "Tamil", "te": "Telugu", "ur": "Urdu"
  };

  const UI = {
    bg: "linear-gradient(180deg, rgba(8,10,14,0.98), rgba(13,15,20,0.98))",
    panel: "linear-gradient(180deg, rgba(20,23,31,0.98), rgba(13,15,20,0.98))",
    panelSoft: "rgba(13,15,20,0.94)",
    border: "rgba(124,106,247,0.22)",
    borderSoft: "rgba(37,40,54,0.95)",
    text: "#e8eaf0",
    muted: "#8b8fa8",
    faint: "#545670",
    accent: "#7c6af7",
    accent2: "#5dd6c8",
    danger: "#ff6b6b",
    shadow: "0 24px 64px rgba(0,0,0,0.85)",
  };

  const panelShell = `
    border: 1.5px solid ${UI.borderSoft};
    border-radius: 18px;
    box-shadow: ${UI.shadow};
    background: ${UI.panel};
  `;

  const cardStyle = `
    background: rgba(17,20,28,0.94);
    border: 1px solid ${UI.borderSoft};
    border-radius: 14px;
    padding: 16px;
  `;

  const labelPill = `
    display:inline-flex;
    align-items:center;
    gap:6px;
    padding:4px 8px;
    border-radius:999px;
    background: rgba(124,106,247,0.12);
    color:${UI.text};
    border:1px solid rgba(124,106,247,0.18);
    font-size:10px;
    font-weight:700;
    letter-spacing:.2px;
  `;

  function getFullLanguageName(code, isAuto) {
    if (!code) return "Unknown Language";
    const parts = code.split(/[-_]/);
    const langCode = parts[0].toLowerCase();
    const friendly = LANG_MAP[langCode] || langCode;
    const isOrig = parts.some(p => p.toLowerCase() === 'orig');
    if (isOrig) return `${friendly} (Original${isAuto ? " Auto" : ""})`;
    const region = parts.slice(1).filter(p => p.toLowerCase() !== 'orig').join('-');
    let name = friendly;
    if (region) name += ` (${region.toUpperCase()})`;
    if (isAuto && !isOrig) name += " (Auto)";
    return name;
  }

  function formatFileSize(bytes) {
    if (!bytes || bytes === 0) return 'N/A';
    
    // Handle string values that might contain "~" or other non-numeric characters
    if (typeof bytes === 'string') {
      // Remove "~" and any other non-numeric characters except decimal point
      bytes = bytes.replace(/[^\d.]/g, '');
      if (!bytes) return 'N/A';
      bytes = parseFloat(bytes);
    }
    
    if (isNaN(bytes) || bytes === 0) return 'N/A';
    
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const k = 1024;
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const size = bytes / Math.pow(k, i);
    return size.toFixed(1) + ' ' + units[i];
  }

  // ─── UI Mode Toggle (Basic/Advanced) ─────────────────────────────────────
  let currentUIMode = 'advanced'; // Default to advanced mode
  let currentShutdownMode = 'off'; // 'off' | 'app' | 'pc'

  function toggleUIMode() {
    const newMode = currentUIMode === 'basic' ? 'advanced' : 'basic';
    savePrefsPatch({ ui_mode: newMode });
    currentUIMode = newMode;
    updateUIModeUI();
  }

  function updateUIModeUI() {
    const modeBtn = document.getElementById('yt-btn-mode-toggle');
    if (modeBtn) {
      modeBtn.textContent = currentUIMode === 'basic' ? 'Basic' : 'Advanced';
      modeBtn.style.background = currentUIMode === 'basic' 
        ? 'rgba(255,255,255,0.2)' 
        : 'rgba(124,106,247,0.4)';
    }

    // Show/hide advanced UI elements
    const advancedElements = document.querySelectorAll('[data-advanced-only]');
    console.log(`[UI Mode] Found ${advancedElements.length} advanced elements, mode: ${currentUIMode}`);
    advancedElements.forEach(el => {
      el.style.display = currentUIMode === 'advanced' ? '' : 'none';
    });
  }

  function toggleShutdown() {
    // Cycle through: off -> app shutdown -> PC shutdown -> off
    if (currentShutdownMode === 'off') {
      currentShutdownMode = 'app';
      savePrefsPatch({ auto_shutdown: true, pc_shutdown: false });
    } else if (currentShutdownMode === 'app') {
      // Show confirmation for PC shutdown
      showPCShutdownConfirmation();
      return; // Don't proceed until confirmed
    } else {
      currentShutdownMode = 'off';
      savePrefsPatch({ auto_shutdown: false, pc_shutdown: false });
    }
    updateShutdownUI();
  }
  
  function showPCShutdownConfirmation() {
    const overlay = document.createElement("div");
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0",
      width: "100vw", height: "100vh",
      backgroundColor: "rgba(0,0,0,0.85)",
      zIndex: "2147483648",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
    });
    
    const panel = document.createElement("div");
    Object.assign(panel.style, {
      width: "400px",
      background: UI.panel,
      borderRadius: "18px",
      boxShadow: UI.shadow,
      display: "flex", flexDirection: "column",
      overflow: "hidden"
    });
    
    panel.innerHTML = `
      <div style="background:linear-gradient(180deg, rgba(220,38,38,0.2), rgba(220,38,38,0.1));padding:18px 20px;border-bottom:1px solid rgba(239,68,68,0.3);display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-size:15px;font-weight:700;color:#fca5a5;">⚠️ PC Shutdown Confirmation</div>
          <div style="font-size:10px;color:#f87171;margin-top:2px;">This action cannot be undone</div>
        </div>
        <span id="yt-pc-shutdown-confirm-close" style="cursor:pointer;font-size:20px;color:#f87171;line-height:1;">×</span>
      </div>
      <div style="padding:18px 20px;display:flex;flex-direction:column;gap:16px;">
        <div style="font-size:12px;color:#e8eaf0;line-height:1.5;">
          <strong style="color:#fca5a5;">Warning:</strong> Enabling PC shutdown will completely power off your computer after all downloads complete.
        </div>
        <div style="font-size:11px;color:#8b8fa8;line-height:1.4;">
          Potential consequences:
          <ul style="margin:8px 0;padding-left:20px;">
            <li>All unsaved work will be lost</li>
            <li>Running applications will be terminated</li>
            <li>System will power off completely</li>
            <li>You will need to manually restart your computer</li>
          </ul>
        </div>
        <div style="font-size:11px;color:#fbbf24;background:rgba(251,191,36,0.1);padding:10px;border-radius:8px;border:1px solid rgba(251,191,36,0.3);">
          💡 You can disable this feature at any time by clicking the shutdown button again.
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button id="yt-pc-shutdown-cancel" style="background:transparent;border:1.5px solid rgba(239,68,68,0.3);color:#fca5a5;padding:9px 18px;border-radius:10px;cursor:pointer;font-size:11px;">Cancel</button>
          <button id="yt-pc-shutdown-confirm" style="background:linear-gradient(135deg, #dc2626, #b91c1c);border:none;color:white;padding:9px 22px;border-radius:10px;cursor:pointer;font-size:11px;font-weight:700;">I Understand, Enable PC Shutdown</button>
        </div>
      </div>
    `;
    
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    
    document.getElementById("yt-pc-shutdown-confirm-close").addEventListener("click", () => overlay.remove());
    document.getElementById("yt-pc-shutdown-cancel").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    
    document.getElementById("yt-pc-shutdown-confirm").addEventListener("click", () => {
      currentShutdownMode = 'pc';
      savePrefsPatch({ auto_shutdown: true, pc_shutdown: true });
      updateShutdownUI();
      overlay.remove();
    });
  }

  function updateShutdownUI() {
    const shutdownBtn = document.getElementById('yt-btn-shutdown-toggle');
    if (shutdownBtn) {
      if (currentShutdownMode === 'off') {
        shutdownBtn.textContent = '🔌';
        shutdownBtn.style.background = 'rgba(255,255,255,0.16)';
        shutdownBtn.title = 'Enable Auto-Shutdown';
      } else if (currentShutdownMode === 'app') {
        shutdownBtn.textContent = '🔌 App';
        shutdownBtn.style.background = 'rgba(124,106,247,0.4)';
        shutdownBtn.title = 'App will shutdown after downloads';
      } else {
        shutdownBtn.textContent = '🔌 PC';
        shutdownBtn.style.background = 'rgba(255,107,107,0.4)';
        shutdownBtn.title = 'PC will shutdown after downloads';
      }
    }
  }

  // ─── Load saved preferences from backend on startup ───────────────────────
  function loadSavedPrefs(cb) {
    GM_xmlhttpRequest({
      method: "GET",
      url: "http://localhost:5000/api/settings",
      onload: function (res) {
        if (res.status === 200) {
          try {
            const p = JSON.parse(res.responseText);
            Object.assign(savedPrefs, p);
            if (p.console_hidden) consoleState.hiddenByUser = true;
            if (p.folder) activeCustomPath = p.folder;
            if (p.ui_mode) currentUIMode = p.ui_mode;
            // Initialize shutdown mode from saved settings
            if (p.pc_shutdown) {
              currentShutdownMode = 'pc';
            } else if (p.auto_shutdown) {
              currentShutdownMode = 'app';
            } else {
              currentShutdownMode = 'off';
            }
          } catch (e) { /* use defaults */ }
        }
        if (cb) cb();
      },
      onerror: function () { if (cb) cb(); }
    });
  }

  function savePrefsPatch(patch) {
    GM_xmlhttpRequest({
      method: "POST",
      url: "http://localhost:5000/api/settings",
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify(patch)
    });
  }

  function persistConsoleState() {
    savePrefsPatch({
      console_hidden: consoleState.hiddenByUser,
      console_position: savedPrefs.console_position
    });
  }

  function setConsoleHidden(hidden, reason = "user") {
    const el = document.getElementById("yt-downloader-console");
    const launcher = document.getElementById("yt-downloader-launcher");
    
    if (reason === "backend") {
      consoleState.hiddenByBackend = hidden;
    } else {
      consoleState.hiddenByUser = hidden;
    }

    const shouldShow = !consoleState.hiddenByUser && !consoleState.hiddenByBackend;
    
    // Hide console when hidden, show when not hidden
    if (el) el.style.display = shouldShow ? "flex" : "none";
    
    // Show launcher when console is hidden, hide when console is shown
    if (launcher) launcher.style.display = shouldShow ? "none" : "flex";

    if (reason === "user") persistConsoleState();
  }

  function applyConsolePosition(el) {
    const pos = savedPrefs.console_position || {};
    if (pos.mode === "free" && typeof pos.left === "number" && typeof pos.top === "number") {
      el.style.left = `${pos.left}%`;
      el.style.top = `${pos.top}%`;
      el.style.right = "auto";
      el.style.bottom = "auto";
      el.dataset.positionMode = "free";
      return;
    }
    el.style.left = "auto";
    el.style.top = "auto";
    el.style.right = "20px";
    el.style.bottom = "20px";
    el.dataset.positionMode = "bottom-right";
  }

  function saveConsolePosition(el) {
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = Math.max(window.innerWidth, 1);
    const vh = Math.max(window.innerHeight, 1);
    const left = Math.max(0, Math.min(100, (rect.left / vw) * 100));
    const top = Math.max(0, Math.min(100, (rect.top / vh) * 100));
    savedPrefs.console_position = { mode: "free", left, top };
    persistConsoleState();
  }

  function setConsoleDocked() {
    if (!consoleEl) return;
    savedPrefs.console_position = { mode: "bottom-right", left: null, top: null };
    applyConsolePosition(consoleEl);
    persistConsoleState();
  }

  function registerMenuCommands() {
    if (typeof GM_registerMenuCommand !== "function") return;
    try {
      GM_registerMenuCommand("Show Downloader", () => setConsoleHidden(false, "user"));
      GM_registerMenuCommand("Hide Downloader", () => setConsoleHidden(true, "user"));
      GM_registerMenuCommand("Reset Downloader Position", () => setConsoleDocked());
    } catch (e) {}
  }

  function pollBackendHealth() {
    if (backendPollBusy) return;
    backendPollBusy = true;
    GM_xmlhttpRequest({
      method: "GET",
      url: "http://localhost:5000/api/status",
      timeout: 2500,
      onload: function (res) {
        backendPollBusy = false;
        const isUp = res.status === 200;
        if (backendOnline !== isUp) {
          backendOnline = isUp;
          if (!isUp) {
            consoleState.hiddenByBackend = true;
            setConsoleHidden(true, "backend");
          } else {
            consoleState.hiddenByBackend = false;
            if (!consoleState.hiddenByUser) setConsoleHidden(false, "backend");
          }
        }
      },
      onerror: function () {
        backendPollBusy = false;
        if (backendOnline !== false) {
          backendOnline = false;
          consoleState.hiddenByBackend = true;
          setConsoleHidden(true, "backend");
        }
      },
      ontimeout: function () {
        backendPollBusy = false;
        if (backendOnline !== false) {
          backendOnline = false;
          consoleState.hiddenByBackend = true;
          setConsoleHidden(true, "backend");
        }
      }
    });
  }

  // ─── Fullscreen hide/show ─────────────────────────────────────────────────
  function checkFullscreenState() {
    const el = document.getElementById("yt-downloader-console");
    const launcher = document.getElementById("yt-downloader-launcher");
    if (!el) return;
    const isBrowserFS = document.fullscreenElement || document.webkitFullscreenElement;
    const isYTFS = document.querySelector(".html5-video-player.ytp-fullscreen");
    
    // Hide both console and launcher in fullscreen
    if (isBrowserFS || isYTFS) {
      el.style.setProperty("display", "none", "important");
      if (launcher) launcher.style.setProperty("display", "none", "important");
    } else {
      // If not in fullscreen, respect the current hidden state
      const shouldShow = !consoleState.hiddenByUser && !consoleState.hiddenByBackend;
      el.style.setProperty("display", shouldShow ? "flex" : "none", "important");
      if (launcher) launcher.style.setProperty("display", shouldShow ? "none" : "flex", "important");
    }
  }

  document.addEventListener('fullscreenchange', checkFullscreenState);
  document.addEventListener('webkitfullscreenchange', checkFullscreenState);

  // ─── Polling loops ────────────────────────────────────────────────────────
  setInterval(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      document.getElementById("yt-wizard-overlay")?.remove();
      document.getElementById("yt-matrix-overlay")?.remove();
      document.getElementById("yt-settings-overlay")?.remove();
      autoFetchMetadata();
    }
    injectFloatingConsole();
    checkFullscreenState();
    detectWindowSize(); // Check window size for embed protection
  }, 1000);

  setInterval(pollStateProgress, 1000);
  setInterval(pollBackendHealth, 4000);

  // ─── URL context ──────────────────────────────────────────────────────────
  function getActiveUrlContext() {
    const url = new URL(window.location.href);
    const hasVideo = url.searchParams.has("v");
    const hasPlaylist = url.searchParams.has("list");
    const isPlaylistPage = url.pathname.includes("playlist");

    // Check if we're in an embedded YouTube video (iframe context)
    if (window !== window.top) {
      const videoId = url.searchParams.get("v");
      if (videoId) {
        return { 
          type: "embedded_video", 
          url: `https://www.youtube.com/watch?v=${videoId}`, 
          videoId: videoId,
          isEmbedded: true
        };
      }
    }

    if (isPlaylistPage && hasPlaylist)
      return { type: "playlist_only", url: url.href, listId: url.searchParams.get("list") };
    if (hasVideo && hasPlaylist)
      return { type: "video_in_playlist", url: url.href, videoId: url.searchParams.get("v"), listId: url.searchParams.get("list") };
    if (hasVideo)
      return { type: "single_video", url: url.href, videoId: url.searchParams.get("v") };
    return { type: "generic_page", url: url.href };
  }

  // ─── Window size detection for embed protection ─────────────────────────────
  let isSmallIconMode = false;
  const CONSOLE_WIDTH = 450; // Width of the userscript console UI
  const SIZE_THRESHOLD = 500; // Threshold for switching to small icon mode

  function detectWindowSize() {
    try {
      // Get the YouTube video player element
      const player = document.querySelector('#movie_player') || 
                     document.querySelector('.html5-video-player') ||
                     document.querySelector('ytd-player');
      
      if (player) {
        const playerRect = player.getBoundingClientRect();
        const playerWidth = playerRect.width;
        
        // Check if player is too small for full console UI
        if (playerWidth < SIZE_THRESHOLD) {
          if (!isSmallIconMode) {
            console.log(`[Size Detection] Player too small (${playerWidth}px < ${SIZE_THRESHOLD}px), switching to small icon mode`);
            switchToSmallIconMode();
          }
          return true;
        } else {
          if (isSmallIconMode) {
            console.log(`[Size Detection] Player large enough (${playerWidth}px >= ${SIZE_THRESHOLD}px), switching to full UI`);
            switchToFullUI();
          }
          return false;
        }
      }
      
      // Fallback to window size if player not found
      const windowWidth = window.innerWidth;
      if (windowWidth < SIZE_THRESHOLD) {
        if (!isSmallIconMode) {
          console.log(`[Size Detection] Window too small (${windowWidth}px < ${SIZE_THRESHOLD}px), switching to small icon mode`);
          switchToSmallIconMode();
        }
        return true;
      } else {
        if (isSmallIconMode) {
          console.log(`[Size Detection] Window large enough (${windowWidth}px >= ${SIZE_THRESHOLD}px), switching to full UI`);
          switchToFullUI();
        }
        return false;
      }
    } catch (e) {
      console.error("[Size Detection] Error detecting window size:", e);
      return false;
    }
  }

  function switchToSmallIconMode() {
    isSmallIconMode = true;
    
    // Hide full console
    const consoleEl = document.getElementById("yt-downloader-console");
    if (consoleEl) {
      consoleEl.style.display = "none";
    }
    
    // Show launcher button
    const launcher = document.getElementById("yt-downloader-launcher");
    if (launcher) {
      launcher.style.display = "flex";
      launcher.title = "Show Download Options";
    }
  }

  function switchToFullUI() {
    isSmallIconMode = false;
    
    // Show full console (respecting other hidden states)
    const shouldShow = !consoleState.hiddenByUser && !consoleState.hiddenByBackend;
    const consoleEl = document.getElementById("yt-downloader-console");
    if (consoleEl) {
      consoleEl.style.display = shouldShow ? "flex" : "none";
    }
    
    // Hide launcher if console should be shown
    const launcher = document.getElementById("yt-downloader-launcher");
    if (launcher) {
      launcher.style.display = shouldShow ? "none" : "flex";
      launcher.title = "Show Downloader";
    }
  }

  // ─── Auto-fetch metadata ──────────────────────────────────────────────────
  function autoFetchMetadata() {
    const ctx = getActiveUrlContext();
    if (ctx.type === "generic_page" || ctx.url === lastFetchedUrl) return;
    lastFetchedUrl = ctx.url;

    // Show loading state in console body if it exists
    const consoleBody = document.getElementById("yt-console-body");
    if (consoleBody) {
      consoleBody.innerHTML = `<div style="text-align:center;padding:20px;color:#8b8fa8;">
        <div style="font-size:24px;margin-bottom:10px;">⏳</div>
        <div>Fetching data...</div>
        <div style="font-size:10px;margin-top:5px;">Getting video information from YouTube</div>
      </div>`;
    }

    GM_xmlhttpRequest({
      method: "POST",
      url: "http://localhost:5000/api/metadata",
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ url: ctx.url, cookies: document.cookie || "" }),
      onload: function (res) {
        if (res.status === 200) {
          try { 
            autoFetchedData = JSON.parse(res.responseText);
            // Clear loading state when data arrives
            if (consoleBody && autoFetchedData) {
              consoleBody.innerHTML = `<div style="text-align:center;color:#545670;padding:15px 0;">No active download tasks.</div>`;
            }
          } catch (e) {
            // Show error state
            if (consoleBody) {
              consoleBody.innerHTML = `<div style="text-align:center;padding:20px;color:#f87171;">
                <div style="font-size:24px;margin-bottom:10px;">❌</div>
                <div>Failed to fetch data</div>
                <div style="font-size:10px;margin-top:5px;">Please try again</div>
              </div>`;
            }
          }
        } else {
          // Show error state for non-200 responses
          if (consoleBody) {
            consoleBody.innerHTML = `<div style="text-align:center;padding:20px;color:#f87171;">
              <div style="font-size:24px;margin-bottom:10px;">❌</div>
              <div>Service unavailable</div>
              <div style="font-size:10px;margin-top:5px;">Backend may be offline</div>
            </div>`;
          }
        }
      },
      onerror: function() {
        // Show error state for network errors
        if (consoleBody) {
          consoleBody.innerHTML = `<div style="text-align:center;padding:20px;color:#f87171;">
            <div style="font-size:24px;margin-bottom:10px;">❌</div>
            <div>Connection failed</div>
            <div style="font-size:10px;margin-top:5px;">Check if backend is running</div>
          </div>`;
        }
      }
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // EMBEDDED VIDEO DOWNLOAD BUTTON
  // ─────────────────────────────────────────────────────────────────────────
  function injectEmbeddedDownloadButton(ctx) {
    if (document.getElementById("yt-embedded-download-btn")) return;
    
    console.log("[Embedded] Injecting download button for embedded video");
    
    const btn = document.createElement("button");
    btn.id = "yt-embedded-download-btn";
    btn.textContent = "⬇";
    btn.title = "Open Download Options";
    Object.assign(btn.style, {
      position: "fixed",
      top: "10px",
      right: "10px",
      width: "32px",
      height: "32px",
      borderRadius: "8px",
      background: "rgba(0,0,0,0.8)",
      color: "white",
      border: "2px solid rgba(255,255,255,0.3)",
      cursor: "pointer",
      zIndex: "2147483647",
      fontSize: "16px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      transition: "background 0.2s"
    });
    
    btn.addEventListener("mouseover", () => {
      btn.style.background = "rgba(124,106,247,0.9)";
    });
    
    btn.addEventListener("mouseout", () => {
      btn.style.background = "rgba(0,0,0,0.8)";
    });
    
    btn.addEventListener("click", () => {
      openEmbeddedVideoWindow(ctx);
    });
    
    document.body.appendChild(btn);
  }
  
  function openEmbeddedVideoWindow(ctx) {
    // Request the backend to open a PyQt window for this embedded video
    GM_xmlhttpRequest({
      method: "POST",
      url: "http://localhost:5000/api/embedded-window",
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ 
        url: ctx.url, 
        video_id: ctx.videoId,
        is_embedded: true 
      }),
      onload: function(res) {
        if (res.status === 200) {
          console.log("[Embedded] PyQt window opened successfully");
        } else {
          console.error("[Embedded] Failed to open PyQt window");
        }
      },
      onerror: function() {
        console.error("[Embedded] Backend offline - cannot open PyQt window");
      }
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // HUD CONSOLE
  // ─────────────────────────────────────────────────────────────────────────
  function injectFloatingConsole() {
    if (!document.body) return;

    const ctx = getActiveUrlContext();
    
    // For embedded videos, only show the small download button, completely skip full console
    if (ctx.type === "embedded_video" || ctx.isEmbedded) {
      console.log("[Embedded] Detected embedded video, skipping full console UI");
      
      // Remove any existing console UI that might have been injected
      const existingConsole = document.getElementById("yt-console-container");
      if (existingConsole) {
        console.log("[Embedded] Removing existing console UI");
        existingConsole.remove();
      }
      
      const existingLauncher = document.getElementById("yt-downloader-launcher");
      if (existingLauncher) {
        console.log("[Embedded] Removing existing launcher");
        existingLauncher.remove();
      }
      
      if (!document.getElementById("yt-embedded-download-btn")) {
        injectEmbeddedDownloadButton(ctx);
      }
      return; // Exit early - don't inject any console UI
    }

    // Always ensure launcher exists
    let launcher = document.getElementById("yt-downloader-launcher");
    if (!launcher) {
      launcher = document.createElement("button");
      launcher.id = "yt-downloader-launcher";
      launcher.title = "Show Downloader";
      launcher.textContent = "↓";
      Object.assign(launcher.style, {
        position: "fixed",
        right: "20px",
        bottom: "20px",
        width: "42px",
        height: "42px",
        borderRadius: "999px",
        border: "1px solid rgba(124,106,247,0.35)",
        background: "linear-gradient(135deg, rgba(124,106,247,0.95), rgba(93,214,200,0.85))",
        color: "#fff",
        fontSize: "18px",
        fontWeight: "700",
        cursor: "pointer",
        zIndex: "2147483647",
        display: "none",
        boxShadow: "0 16px 36px rgba(0,0,0,0.45)"
      });
      launcher.addEventListener("click", () => {
        if (isSmallIconMode) {
          // In small icon mode, show download options instead of full console
          const ctx = getActiveUrlContext();
          if (ctx.type === "single_video" || ctx.type === "video_in_playlist") {
            openWizardModal();
          } else {
            // For other contexts, just show the console
            setConsoleHidden(false, "user");
          }
        } else {
          setConsoleHidden(false, "user");
        }
      });
      document.body.appendChild(launcher);
    }

    // Only create console if it doesn't exist
    if (document.getElementById("yt-downloader-console")) return;

    const el = document.createElement("div");
    consoleEl = el;
    el.id = "yt-downloader-console";
    Object.assign(el.style, {
      position: "fixed",
      width: "450px", maxHeight: "500px",
      background: UI.bg,
      border: `1px solid ${UI.border}`,
      borderRadius: "18px",
      boxShadow: "0 20px 50px rgba(0,0,0,0.72), 0 0 0 1px rgba(124,106,247,0.10)",
      zIndex: "2147483647",
      color: UI.text, fontFamily: "'Segoe UI', Roboto, Arial, sans-serif",
      fontSize: "13px", overflow: "hidden",
      display: "flex", flexDirection: "column"
    });
    applyConsolePosition(el);

    el.innerHTML = `
      <div id="yt-console-header" style="
        background: linear-gradient(135deg, rgba(124,106,247,0.96), rgba(93,214,200,0.88));
        padding: 12px 14px;
        font-weight: bold;
        display: flex; justify-content: space-between; align-items: center;
        cursor: grab; user-select: none; border-radius: 13px 13px 0 0;">
        <span style="display:flex;align-items:center;gap:8px;">
          📥 <span style="font-size:13px;">Downloader</span>
        </span>
        <span style="display:flex;align-items:center;gap:6px;">
          <span id="yt-btn-mode-toggle" title="Switch Basic/Advanced Mode" style="cursor:pointer;font-size:12px;padding:3px 6px;border-radius:5px;background:rgba(255,255,255,0.2);transition:background .15s;">Basic</span>
          <span id="yt-btn-shutdown-toggle" title="Toggle Auto-Shutdown" style="cursor:pointer;font-size:12px;padding:3px 6px;border-radius:5px;background:rgba(255,255,255,0.16);transition:background .15s;">🔌</span>
          <span id="yt-btn-settings-hud" title="Open Settings" style="cursor:pointer;font-size:15px;padding:2px 4px;border-radius:5px;transition:background .15s;">⚙️</span>
          <span id="yt-console-dock" title="Dock bottom-right" style="cursor:pointer;font-size:13px;width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;border-radius:6px;background:rgba(255,255,255,0.16);">⬛</span>
          <span id="yt-console-hide" title="Hide panel" style="cursor:pointer;font-size:18px;line-height:1;padding:0 2px;">×</span>
        </span>
      </div>
      <div id="yt-console-actions" style="padding: 10px 10px 8px 10px; display: flex; gap: 8px; flex-wrap: wrap;">
        <button id="yt-btn-analyze-url" style="
          flex: 1; background: linear-gradient(180deg, rgba(124,106,247,0.20), rgba(124,106,247,0.10)); border: 1px solid rgba(124,106,247,0.35);
          color: #ece9ff; padding: 9px 10px; border-radius: 10px;
          cursor: pointer; font-weight: bold; font-size: 11px;
          transition: background .15s;">🔍 Analyze &amp; Download</button>
        <button id="yt-btn-manual-url" style="
          background: linear-gradient(180deg, rgba(255,107,107,0.16), rgba(255,107,107,0.08)); border: 1px solid rgba(255,107,107,0.38);
          color: #ffd2d2; padding: 9px 12px; border-radius: 10px;
          cursor: pointer; font-weight: bold; font-size: 11px;
          transition: background .15s;">🔗 URL</button>
        <button id="yt-btn-batch-download" data-advanced-only style="
          display: none; background: linear-gradient(180deg, rgba(93,214,200,0.16), rgba(93,214,200,0.08)); border: 1px solid rgba(93,214,200,0.38);
          color: #d2f5ff; padding: 9px 12px; border-radius: 10px;
          cursor: pointer; font-weight: bold; font-size: 11px;
          transition: background .15s;">📄 Batch</button>
        <button id="yt-btn-archive-editor" data-advanced-only style="
          display: none; background: linear-gradient(180deg, rgba(255,193,7,0.16), rgba(255,193,7,0.08)); border: 1px solid rgba(255,193,7,0.38);
          color: #fff9c4; padding: 9px 12px; border-radius: 10px;
          cursor: pointer; font-weight: bold; font-size: 11px;
          transition: background .15s;">📝 Archive</button>
        <button id="yt-btn-queue-manager" data-advanced-only style="
          display: none; background: linear-gradient(180deg, rgba(236,72,153,0.16), rgba(236,72,153,0.08)); border: 1px solid rgba(236,72,153,0.38);
          color: #fce7f3; padding: 9px 12px; border-radius: 10px;
          cursor: pointer; font-weight: bold; font-size: 11px;
          transition: background .15s;">📋 Queue</button>
        <button id="yt-btn-history" data-advanced-only style="
          display: none; background: linear-gradient(180deg, rgba(168,85,247,0.16), rgba(168,85,247,0.08)); border: 1px solid rgba(168,85,247,0.38);
          color: #f3e8ff; padding: 9px 12px; border-radius: 10px;
          cursor: pointer; font-weight: bold; font-size: 11px;
          transition: background .15s;">📜 History</button>
        <button id="yt-btn-statistics" data-advanced-only style="
          display: none; background: linear-gradient(180deg, rgba(34,197,94,0.16), rgba(34,197,94,0.08)); border: 1px solid rgba(34,197,94,0.38);
          color: #dcfce7; padding: 9px 12px; border-radius: 10px;
          cursor: pointer; font-weight: bold; font-size: 11px;
          transition: background .15s;">📊 Statistics</button>
      </div>
      <div id="yt-console-body" style="
        padding: 12px; display: flex; flex-direction: column; gap: 10px;
        overflow-y: auto; flex: 1; min-height: 80px; scrollbar-width: thin;
        scrollbar-color: #333 transparent;">
        <div style="text-align:center;color:#545670;padding:15px 0;">No active download tasks.</div>
      </div>
    `;

    document.body.appendChild(el);

    const header = document.getElementById("yt-console-header");
    const body = document.getElementById("yt-console-body");
    const actions = document.getElementById("yt-console-actions");
    const settingsBtn = document.getElementById("yt-btn-settings-hud");
    const hideBtn = document.getElementById("yt-console-hide");
    const dockBtn = document.getElementById("yt-console-dock");
    const modeToggleBtn = document.getElementById("yt-btn-mode-toggle");
    const shutdownToggleBtn = document.getElementById("yt-btn-shutdown-toggle");

    settingsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openSettingsPanel();
    });

    shutdownToggleBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleShutdown();
    });

    hideBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setConsoleHidden(true, "user");
    });

    dockBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setConsoleDocked();
    });

    modeToggleBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleUIMode();
    });

    const startDrag = (e) => {
      if (e.target.closest("#yt-btn-settings-hud, #yt-console-hide, #yt-console-dock")) return;
      consoleState.dragging = true;
      const rect = el.getBoundingClientRect();
      consoleState.dragOffsetX = e.clientX - rect.left;
      consoleState.dragOffsetY = e.clientY - rect.top;
      header.style.cursor = "grabbing";
      e.preventDefault();
    };

    const dragMove = (e) => {
      if (!consoleState.dragging) return;
      const vw = Math.max(window.innerWidth, 1);
      const vh = Math.max(window.innerHeight, 1);
      const leftPx = Math.min(Math.max(0, e.clientX - consoleState.dragOffsetX), vw - el.offsetWidth);
      const topPx = Math.min(Math.max(0, e.clientY - consoleState.dragOffsetY), vh - el.offsetHeight);
      el.style.left = `${(leftPx / vw) * 100}%`;
      el.style.top = `${(topPx / vh) * 100}%`;
      el.style.right = "auto";
      el.style.bottom = "auto";
      el.dataset.positionMode = "free";
      if (positionSaveTimer) clearTimeout(positionSaveTimer);
      positionSaveTimer = setTimeout(() => saveConsolePosition(el), 250);
    };

    const stopDrag = () => {
      if (!consoleState.dragging) return;
      consoleState.dragging = false;
      header.style.cursor = "grab";
      saveConsolePosition(el);
    };

    header.addEventListener("mousedown", startDrag);
    document.addEventListener("mousemove", dragMove);
    document.addEventListener("mouseup", stopDrag);

    document.getElementById("yt-btn-analyze-url").addEventListener("click", (e) => {
      e.stopPropagation();
      openWizardModal();
    });

    document.getElementById("yt-btn-manual-url").addEventListener("click", (e) => {
      e.stopPropagation();
      openManualURLModal();
    });

    document.getElementById("yt-btn-batch-download").addEventListener("click", (e) => {
      e.stopPropagation();
      openBatchDownloadModal();
    });

    document.getElementById("yt-btn-archive-editor").addEventListener("click", (e) => {
      e.stopPropagation();
      openArchiveEditorModal();
    });

    // Add button listeners with existence checks and error handling
    setTimeout(() => {
      const queueBtn = document.getElementById("yt-btn-queue-manager");
      if (queueBtn) {
        queueBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          console.log("[Queue Manager] Button clicked");
          try {
            openQueueManagerModal();
          } catch (err) {
            console.error("[Queue Manager] Error:", err);
            alert("Failed to open Queue Manager: " + err.message);
          }
        });
        console.log("[Queue Manager] Event listener attached");
      } else {
        console.error("[Queue Manager] Button not found in DOM");
      }

      const historyBtn = document.getElementById("yt-btn-history");
      if (historyBtn) {
        historyBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          console.log("[History] Button clicked");
          try {
            openHistoryModal();
          } catch (err) {
            console.error("[History] Error:", err);
            alert("Failed to open History: " + err.message);
          }
        });
        console.log("[History] Event listener attached");
      } else {
        console.error("[History] Button not found in DOM");
      }

      const statsBtn = document.getElementById("yt-btn-statistics");
      if (statsBtn) {
        statsBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          console.log("[Statistics] Button clicked");
          try {
            openStatisticsModal();
          } catch (err) {
            console.error("[Statistics] Error:", err);
            alert("Failed to open Statistics: " + err.message);
          }
        });
        console.log("[Statistics] Event listener attached");
      } else {
        console.error("[Statistics] Button not found in DOM");
      }
    }, 100); // Small delay to ensure DOM is ready

    // Load prefs on first inject
    loadSavedPrefs(() => {
      if (savedPrefs.console_hidden === true) {
        consoleState.hiddenByUser = true;
      }
      // Initial visibility check - respect both user and backend state
      if (backendOnline === false) {
        consoleState.hiddenByBackend = true;
      }
      const shouldShow = !consoleState.hiddenByUser && !consoleState.hiddenByBackend;
      if (el) el.style.display = shouldShow ? "flex" : "none";
      if (launcher) launcher.style.display = shouldShow ? "none" : "flex";
      if (consoleEl) applyConsolePosition(consoleEl);
      // Update UI mode based on saved preference
      updateUIModeUI();
      // Update shutdown button state
      updateShutdownUI();
    });
    registerMenuCommands();
  }

  // ─────────────────────────────────────────────────────────────────────────
  // MANUAL URL MODAL
  // ─────────────────────────────────────────────────────────────────────────
  function openManualURLModal() {
    document.getElementById("yt-manual-url-overlay")?.remove();

    const overlay = document.createElement("div");
    overlay.id = "yt-manual-url-overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0",
      width: "100vw", height: "100vh",
      backgroundColor: "rgba(0,0,0,0.82)",
      zIndex: "2147483647",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
    });

    const panel = document.createElement("div");
    Object.assign(panel.style, {
      width: "480px",
      background: UI.panel,
      borderRadius: "18px",
      boxShadow: UI.shadow,
      display: "flex", flexDirection: "column",
      overflow: "hidden"
    });

    panel.innerHTML = `
      <div style="background:linear-gradient(180deg, rgba(20,23,31,0.98), rgba(13,15,20,0.98));padding:18px 20px;border-bottom:1px solid rgba(37,40,54,0.95);display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-size:15px;font-weight:700;color:${UI.text};">🔗 Manual URL</div>
          <div style="font-size:10px;color:${UI.muted};margin-top:2px;">Enter any YouTube URL to analyze</div>
        </div>
        <span id="yt-mu-close" style="cursor:pointer;font-size:20px;color:${UI.faint};line-height:1;">×</span>
      </div>
      <div style="padding:18px 20px 20px;display:flex;flex-direction:column;gap:16px;">
        <div>
          <label style="font-size:11px;font-weight:700;color:${UI.text};margin-bottom:8px;display:block;">Video/Playlist URL</label>
          <input type="text" id="yt-mu-url" placeholder="https://www.youtube.com/watch?v=..." style="
            width:100%;background:#0a0c10;border:1.5px solid rgba(37,40,54,0.95);border-radius:12px;
            color:${UI.text};padding:12px;font-size:12px;outline:none;box-sizing:border-box;">
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button id="yt-mu-cancel" style="background:transparent;border:1.5px solid rgba(37,40,54,0.95);color:${UI.muted};padding:9px 18px;border-radius:10px;cursor:pointer;font-size:11px;">Cancel</button>
          <button id="yt-mu-analyze" style="background:linear-gradient(135deg, ${UI.accent}, ${UI.accent2});border:none;color:white;padding:9px 22px;border-radius:10px;cursor:pointer;font-size:11px;font-weight:700;">Analyze</button>
        </div>
      </div>
    `;

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    document.getElementById("yt-mu-close").addEventListener("click", () => overlay.remove());
    document.getElementById("yt-mu-cancel").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

    document.getElementById("yt-mu-analyze").addEventListener("click", () => {
      const url = document.getElementById("yt-mu-url").value.trim();
      if (!url) return;
      
      // Store the manual URL and open wizard
      window.manualUrl = url;
      overlay.remove();
      openWizardModal();
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // BATCH DOWNLOAD MODAL
  // ─────────────────────────────────────────────────────────────────────────
  function openBatchDownloadModal() {
    document.getElementById("yt-batch-overlay")?.remove();

    const overlay = document.createElement("div");
    overlay.id = "yt-batch-overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0",
      width: "100vw", height: "100vh",
      backgroundColor: "rgba(0,0,0,0.82)",
      zIndex: "2147483647",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
    });

    const panel = document.createElement("div");
    Object.assign(panel.style, {
      width: "550px",
      background: UI.panel,
      borderRadius: "18px",
      boxShadow: UI.shadow,
      display: "flex", flexDirection: "column",
      overflow: "hidden"
    });

    panel.innerHTML = `
      <div style="background:linear-gradient(180deg, rgba(20,23,31,0.98), rgba(13,15,20,0.98));padding:18px 20px;border-bottom:1px solid rgba(37,40,54,0.95);display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-size:15px;font-weight:700;color:${UI.text};">📄 Batch Download</div>
          <div style="font-size:10px;color:${UI.muted};margin-top:2px;">Import URLs from clipboard, text files, or CSV</div>
        </div>
        <span id="yt-batch-close" style="cursor:pointer;font-size:20px;color:${UI.faint};line-height:1;">×</span>
      </div>
      <div style="padding:18px 20px 20px;display:flex;flex-direction:column;gap:16px;">
        <div style="display:flex;gap:8px;margin-bottom:8px;">
          <button id="yt-batch-import-clipboard" style="flex:1;background:rgba(124,106,247,0.16);border:1px solid rgba(124,106,247,0.38);color:#ece9ff;padding:8px;border-radius:8px;font-size:10px;cursor:pointer;">📋 Import from Clipboard</button>
          <button id="yt-batch-import-file" style="flex:1;background:rgba(93,214,200,0.16);border:1px solid rgba(93,214,200,0.38);color:#d2f5ff;padding:8px;border-radius:8px;font-size:10px;cursor:pointer;">📁 Import from File</button>
        </div>
        <div>
          <label style="font-size:11px;font-weight:700;color:${UI.text};margin-bottom:8px;display:block;">URLs (one per line)</label>
          <textarea id="yt-batch-urls" placeholder="https://www.youtube.com/watch?v=...&#10;https://www.youtube.com/watch?v=..." style="
            width:100%;height:150px;background:#0a0c10;border:1.5px solid rgba(37,40,54,0.95);border-radius:12px;
            color:${UI.text};padding:12px;font-size:12px;outline:none;box-sizing:border-box;resize:vertical;font-family:monospace;"></textarea>
          <div style="font-size:9px;color:${UI.muted};margin-top:4px;">Enter one YouTube URL per line. Supports videos and playlists. CSV format: url,title</div>
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button id="yt-batch-cancel" style="background:transparent;border:1.5px solid rgba(37,40,54,0.95);color:${UI.muted};padding:9px 18px;border-radius:10px;cursor:pointer;font-size:11px;">Cancel</button>
          <button id="yt-batch-add" style="background:linear-gradient(135deg, ${UI.accent}, ${UI.accent2});border:none;color:white;padding:9px 22px;border-radius:10px;cursor:pointer;font-size:11px;font-weight:700;">Add to Queue</button>
        </div>
      </div>
    `;

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    document.getElementById("yt-batch-close").addEventListener("click", () => overlay.remove());
    document.getElementById("yt-batch-cancel").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

    // Import from clipboard
    document.getElementById("yt-batch-import-clipboard").addEventListener("click", async () => {
      try {
        const text = await navigator.clipboard.readText();
        document.getElementById("yt-batch-urls").value = text;
      } catch (err) {
        alert("Failed to read clipboard. Please paste manually.");
      }
    });

    // Import from file
    document.getElementById("yt-batch-import-file").addEventListener("click", () => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".txt,.csv";
      input.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
          document.getElementById("yt-batch-urls").value = event.target.result;
        };
        reader.readAsText(file);
      });
      input.click();
    });

    document.getElementById("yt-batch-add").addEventListener("click", () => {
      const urlsText = document.getElementById("yt-batch-urls").value.trim();
      if (!urlsText) return;
      
      const lines = urlsText.split('\n').map(line => line.trim()).filter(line => line);
      let addedCount = 0;
      
      lines.forEach(line => {
        // Check if line is CSV format (url,title)
        let url = line;
        let customTitle = null;
        
        if (line.includes(',')) {
          const parts = line.split(',');
          url = parts[0].trim();
          customTitle = parts.slice(1).join(',').trim();
        }
        
        if (url.includes('youtube.com') || url.includes('youtu.be')) {
          // Enqueue each URL with default settings
          const payload = {
            url: url,
            folder: savedPrefs.folder || "",
            resolution: savedPrefs.resolution || "1080",
            out_format: savedPrefs.out_format || "original",
            subs_mode: savedPrefs.subs_mode || "none",
            selected_subs: savedPrefs.selected_subs || [],
            disable_title: savedPrefs.disable_title || false,
            prefix: savedPrefs.prefix || "",
            use_numbering: savedPrefs.use_numbering || false,
            advanced_mode: false,
            cookies: ""
          };
          
          if (customTitle) {
            payload.custom_title = customTitle;
          }
          
          GM_xmlhttpRequest({
            method: "POST",
            url: "http://localhost:5000/api/enqueue",
            headers: { "Content-Type": "application/json" },
            data: JSON.stringify(payload),
            onload: () => addedCount++,
            onerror: () => console.error("Failed to enqueue:", url)
          });
        }
      });
      
      overlay.remove();
      alert(`Added ${addedCount} URLs to download queue.`);
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ARCHIVE EDITOR MODAL
  // ─────────────────────────────────────────────────────────────────────────
  function openArchiveEditorModal() {
    document.getElementById("yt-archive-overlay")?.remove();

    const overlay = document.createElement("div");
    overlay.id = "yt-archive-overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0",
      width: "100vw", height: "100vh",
      backgroundColor: "rgba(0,0,0,0.82)",
      zIndex: "2147483647",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
    });

    const panel = document.createElement("div");
    Object.assign(panel.style, {
      width: "600px", maxHeight: "80vh",
      background: UI.panel,
      borderRadius: "18px",
      boxShadow: UI.shadow,
      display: "flex", flexDirection: "column",
      overflow: "hidden"
    });

    panel.innerHTML = `
      <div style="background:linear-gradient(180deg, rgba(20,23,31,0.98), rgba(13,15,20,0.98));padding:18px 20px;border-bottom:1px solid rgba(37,40,54,0.95);display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-size:15px;font-weight:700;color:${UI.text};">📝 Archive Editor</div>
          <div style="font-size:10px;color:${UI.muted};margin-top:2px;">Edit downloaded.txt to allow re-downloads</div>
        </div>
        <span id="yt-archive-close" style="cursor:pointer;font-size:20px;color:${UI.faint};line-height:1;">×</span>
      </div>
      <div style="padding:18px 20px;display:flex;flex-direction:column;gap:16px;">
        <div>
          <label style="font-size:11px;font-weight:700;color:${UI.text};margin-bottom:8px;display:block;">downloaded.txt file path</label>
          <div style="display:flex;gap:8px;">
            <input id="yt-archive-file-path" type="text" placeholder="e.g. C:/Downloads/downloaded.txt" style="flex:1;background:#0a0c10;border:1.5px solid rgba(37,40,54,0.95);color:${UI.text};padding:8px 12px;border-radius:10px;font-size:11px;outline:none;" />
            <button id="yt-archive-load" style="background:linear-gradient(135deg, ${UI.accent}, ${UI.accent2});border:none;color:white;padding:8px 16px;border-radius:10px;cursor:pointer;font-size:11px;font-weight:700;">Load</button>
          </div>
          <div style="font-size:9px;color:${UI.muted};margin-top:4px;">Enter the full path to your downloaded.txt file</div>
        </div>
        <div id="yt-archive-entries" style="max-height:300px;overflow-y:auto;border:1.5px solid rgba(37,40,54,0.95);border-radius:10px;background:#0a0c10;padding:10px;display:none;">
          <div style="font-size:10px;color:${UI.muted};margin-bottom:8px;">Select entries to remove:</div>
          <div id="yt-archive-list" style="display:flex;flex-direction:column;gap:4px;"></div>
        </div>
        <div id="yt-archive-status" style="font-size:10px;color:${UI.muted};"></div>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button id="yt-archive-cancel" style="background:transparent;border:1.5px solid rgba(37,40,54,0.95);color:${UI.muted};padding:9px 18px;border-radius:10px;cursor:pointer;font-size:11px;">Cancel</button>
          <button id="yt-archive-remove" disabled style="background:rgba(255,107,107,0.16);border:1px solid rgba(255,107,107,0.38);color:#ffd2d2;padding:9px 18px;border-radius:10px;cursor:pointer;font-size:11px;font-weight:700;opacity:0.5;">Remove Selected</button>
        </div>
      </div>
    `;

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    let archiveEntries = [];
    let selectedEntries = new Set();

    document.getElementById("yt-archive-close").addEventListener("click", () => overlay.remove());
    document.getElementById("yt-archive-cancel").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

    document.getElementById("yt-archive-load").addEventListener("click", () => {
      const filePath = document.getElementById("yt-archive-file-path").value.trim();
      if (!filePath) {
        document.getElementById("yt-archive-status").textContent = "❌ Please enter a file path";
        document.getElementById("yt-archive-status").style.color = "#f87171";
        return;
      }

      document.getElementById("yt-archive-status").textContent = "Loading...";
      document.getElementById("yt-archive-status").style.color = "#fb923c";

      // Request backend to read the file
      GM_xmlhttpRequest({
        method: "POST",
        url: "http://localhost:5000/api/archive/read",
        headers: { "Content-Type": "application/json" },
        data: JSON.stringify({ file_path: filePath }),
        onload: function(res) {
          if (res.status === 200) {
            const data = JSON.parse(res.responseText);
            archiveEntries = data.entries;
            renderArchiveEntries();
            document.getElementById("yt-archive-entries").style.display = "block";
            document.getElementById("yt-archive-status").textContent = `✓ Loaded ${data.total} entries`;
            document.getElementById("yt-archive-status").style.color = "#4ade80";
          } else {
            document.getElementById("yt-archive-status").textContent = "❌ Failed to load file";
            document.getElementById("yt-archive-status").style.color = "#f87171";
          }
        },
        onerror: function() {
          document.getElementById("yt-archive-status").textContent = "❌ Service offline";
          document.getElementById("yt-archive-status").style.color = "#f87171";
        }
      });
    });

    function renderArchiveEntries() {
      const listDiv = document.getElementById("yt-archive-list");
      listDiv.innerHTML = "";

      archiveEntries.forEach((entry, index) => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:8px;padding:6px;background:#13161e;border-radius:6px;";
        row.innerHTML = `
          <input type="checkbox" data-index="${index}" style="accent-color:#7c6af7;cursor:pointer;" />
          <div style="flex:1;overflow:hidden;">
            <div style="font-size:11px;color:${UI.text};font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${entry.title}</div>
            <div style="font-size:9px;color:${UI.muted};">${entry.channel}</div>
          </div>
        `;

        row.querySelector("input").addEventListener("change", (e) => {
          if (e.target.checked) {
            selectedEntries.add(entry.line);
          } else {
            selectedEntries.delete(entry.line);
          }
          updateRemoveButton();
        });

        listDiv.appendChild(row);
      });
    }

    function updateRemoveButton() {
      const removeBtn = document.getElementById("yt-archive-remove");
      if (selectedEntries.size > 0) {
        removeBtn.disabled = false;
        removeBtn.style.opacity = "1";
      } else {
        removeBtn.disabled = true;
        removeBtn.style.opacity = "0.5";
      }
    }

    document.getElementById("yt-archive-remove").addEventListener("click", () => {
      if (selectedEntries.size === 0) return;

      const filePath = document.getElementById("yt-archive-file-path").value.trim();
      document.getElementById("yt-archive-status").textContent = "Removing...";
      document.getElementById("yt-archive-status").style.color = "#fb923c";

      GM_xmlhttpRequest({
        method: "POST",
        url: "http://localhost:5000/api/archive/remove",
        headers: { "Content-Type": "application/json" },
        data: JSON.stringify({
          file_path: filePath,
          entries: Array.from(selectedEntries)
        }),
        onload: function(res) {
          if (res.status === 200) {
            const data = JSON.parse(res.responseText);
            document.getElementById("yt-archive-status").textContent = `✓ Removed ${data.removed} entries`;
            document.getElementById("yt-archive-status").style.color = "#4ade80";
            selectedEntries.clear();
            // Reload entries
            document.getElementById("yt-archive-load").click();
          } else {
            document.getElementById("yt-archive-status").textContent = "❌ Failed to remove entries";
            document.getElementById("yt-archive-status").style.color = "#f87171";
          }
        },
        onerror: function() {
          document.getElementById("yt-archive-status").textContent = "❌ Service offline";
          document.getElementById("yt-archive-status").style.color = "#f87171";
        }
      });
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // IN-BROWSER SETTINGS PANEL
  // ─────────────────────────────────────────────────────────────────────────
  function openSettingsPanel() {
    document.getElementById("yt-settings-overlay")?.remove();

    const overlay = document.createElement("div");
    overlay.id = "yt-settings-overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0",
      width: "100vw", height: "100vh",
      backgroundColor: "rgba(0,0,0,0.82)",
      zIndex: "2147483647",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
    });

    const panel = document.createElement("div");
    Object.assign(panel.style, {
      width: "520px", maxHeight: "85vh",
      background: UI.panel,
      borderRadius: "18px",
      boxShadow: UI.shadow,
      display: "flex", flexDirection: "column",
      overflow: "hidden"
    });

    const p = savedPrefs;
    const folderDisplay = activeCustomPath || p.folder || "";

    panel.innerHTML = `
      <!-- Header -->
      <div style="background:linear-gradient(180deg, rgba(20,23,31,0.98), rgba(13,15,20,0.98));padding:18px 20px;border-bottom:1px solid rgba(37,40,54,0.95);display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-size:15px;font-weight:700;color:${UI.text};">⚙️ Preferences</div>
          <div style="font-size:10px;color:${UI.muted};margin-top:2px;">Default settings for every new download</div>
        </div>
        <span id="yt-settings-close" style="cursor:pointer;font-size:20px;color:${UI.faint};line-height:1;">×</span>
      </div>

      <!-- Scrollable body -->
      <div style="overflow-y:auto;flex:1;padding:18px;display:flex;flex-direction:column;gap:16px;scrollbar-width:thin;scrollbar-color:#252836 transparent;">

        <!-- Download Folder -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">📁 Download Location</div>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:6px;">Default Save Folder</div>
          <div style="display:flex;gap:8px;align-items:center;">
            <input id="yt-s-folder" type="text" value="${escHtml(folderDisplay)}"
              placeholder="e.g. C:/Users/you/Downloads"
              style="flex:1;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            <button id="yt-s-folder-picker" title="Browse folder" style="
              background:#0d0f14;border:1.5px solid #7c6af7;color:#9b8fff;
              padding:7px 12px;border-radius:8px;font-size:11px;cursor:pointer;white-space:nowrap;">
              Browse…
            </button>
          </div>
          <div style="font-size:9px;color:#545670;margin-top:5px;">Click Browse to open native folder dialog.</div>
        </div>

        <!-- Video Quality -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🎬 Video Quality</div>

          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Default Resolution</div>
          <select id="yt-s-res" style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px;border-radius:8px;font-size:11px;outline:none;margin-bottom:12px;">
            ${["best","2160","1440","1080","720","480","360","240"].map(r =>
              `<option value="${r}" ${p.resolution === r ? "selected" : ""}>${r === "best" ? "Best Available" : r + "p"}</option>`
            ).join("")}
          </select>

          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Default Output Format</div>
          <select id="yt-s-fmt" style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px;border-radius:8px;font-size:11px;outline:none;">
            ${[["original","Original (no re-encode)"],["mp4","MP4"],["mkv","MKV"],["webm","WebM"],["mp3","MP3 (audio only)"],["wav","WAV (audio only)"]].map(([v,l]) =>
              `<option value="${v}" ${p.out_format === v ? "selected" : ""}>${l}</option>`
            ).join("")}
          </select>
        </div>

        <!-- File Naming -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">✏️ File Naming</div>

          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Default Filename Prefix</div>
          <input id="yt-s-prefix" type="text" value="${escHtml(p.prefix || "")}"
            placeholder="e.g. MyChannel — "
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;box-sizing:border-box;margin-bottom:12px;"/>

          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-disable-title" ${p.disable_title ? "checked" : ""}
              style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Strip video title from filename
          </label>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;">
            <input type="checkbox" id="yt-s-numbering" ${p.use_numbering ? "checked" : ""}
              style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Auto-number playlist items (001, 002…)
          </label>
        </div>

        <!-- Subtitles -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">💬 Subtitles</div>

          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Subtitle Mode</div>
          <select id="yt-s-submode" style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px;border-radius:8px;font-size:11px;outline:none;margin-bottom:12px;">
            <option value="none" ${p.subs_mode === "none" ? "selected" : ""}>Do not download</option>
            <option value="embed" ${p.subs_mode === "embed" ? "selected" : ""}>Embed in video</option>
            <option value="external_srt" ${p.subs_mode === "external_srt" ? "selected" : ""}>External SRT files</option>
          </select>

          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Default Subtitle Languages (comma-separated)</div>
          <input id="yt-s-subs" type="text" value="${(p.selected_subs || []).join(", ")}"
            placeholder="e.g. en, fr, es"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;box-sizing:border-box;"/>
          <div style="font-size:9px;color:#545670;margin-top:4px;">ISO 639-1 codes. Only used when mode ≠ 'Do not download'.</div>
        </div>

        <!-- Thumbnail -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🖼️ Thumbnail</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-thumbnail" ${p.download_thumbnail ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Download thumbnail image (separate file, not cached)
          </label>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-embed-thumbnail" ${p.embed_thumbnail ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Embed thumbnail in audio files (MP3/WAV)
          </label>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-thumbnail-only" ${p.thumbnail_only ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Download thumbnail only (no video)
          </label>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;">
            <input type="checkbox" id="yt-s-disable-archive" ${p.disable_archive ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Disable download archive (allow re-downloads)
          </label>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Automatically embeds thumbnail when downloading audio formats</div>
        </div>

        <!-- Cache Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">💾 Cache Settings</div>

          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Metadata Cache Expiry (days)</div>
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;">
            <input id="yt-s-cache-days" type="number" value="${p.cache_expiry_days !== undefined && p.cache_expiry_days !== null ? p.cache_expiry_days : ''}"
              placeholder="No limit"
              min="1"
              style="flex:1;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            <span style="font-size:10px;color:#545670;">Leave empty for no limit</span>
          </div>

          <div style="display:flex;gap:8px;">
            <button id="yt-s-cache-clear" style="flex:1;background:#252836;border:none;color:#e8eaf0;padding:7px;border-radius:8px;font-size:10px;cursor:pointer;">Clear Cache</button>
            <button id="yt-s-cache-cleanup" style="flex:1;background:#252836;border:none;color:#e8eaf0;padding:7px;border-radius:8px;font-size:10px;cursor:pointer;">Cleanup Expired</button>
          </div>
          <div id="yt-s-cache-status" style="font-size:9px;color:#545670;margin-top:6px;"></div>
        </div>

        <!-- Auto-Retry Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🔄 Auto-Retry Settings</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-auto-retry-enabled" ${p.auto_retry_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable automatic retry of failed downloads
          </label>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Maximum Retry Attempts</div>
          <input id="yt-s-auto-retry-max" type="number" value="${p.auto_retry_max_attempts || 3}" min="1" max="10"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;margin-bottom:8px;"/>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Retry Delay (seconds)</div>
          <input id="yt-s-auto-retry-delay" type="number" value="${p.auto_retry_delay || 5}" min="1" max="60"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Automatically re-queue failed downloads with specified delay</div>
        </div>

        <!-- Speed Limiting Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">⚡ Speed Limiting</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-speed-limit-enabled" ${p.speed_limit_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable download speed limiting
          </label>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Speed Limit (e.g., 10M for 10 MB/s, 5M for 5 MB/s)</div>
          <input id="yt-s-speed-limit-value" type="text" value="${p.speed_limit_value || '10M'}" placeholder="10M"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Use suffixes: K (KB/s), M (MB/s), G (GB/s)</div>
        </div>

        <!-- Playlist Filtering Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🎯 Playlist Filtering</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-playlist-filter-enabled" ${p.playlist_filter_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable playlist filtering
          </label>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;">
            <div>
              <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Min Duration</div>
              <input id="yt-s-playlist-filter-min-duration" type="text" value="${p.playlist_filter_min_duration || ''}" placeholder="5:00"
                style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            </div>
            <div>
              <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Max Duration</div>
              <input id="yt-s-playlist-filter-max-duration" type="text" value="${p.playlist_filter_max_duration || ''}" placeholder="30:00"
                style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;">
            <div>
              <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Min Views</div>
              <input id="yt-s-playlist-filter-min-views" type="text" value="${p.playlist_filter_min_views || ''}" placeholder="1000"
                style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            </div>
            <div>
              <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Max Views</div>
              <input id="yt-s-playlist-filter-max-views" type="text" value="${p.playlist_filter_max_views || ''}" placeholder="1000000"
                style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <div>
              <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">After Date (YYYYMMDD)</div>
              <input id="yt-s-playlist-filter-date-after" type="text" value="${p.playlist_filter_date_after || ''}" placeholder="20230101"
                style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            </div>
            <div>
              <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Before Date (YYYYMMDD)</div>
              <input id="yt-s-playlist-filter-date-before" type="text" value="${p.playlist_filter_date_before || ''}" placeholder="20231231"
                style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            </div>
          </div>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Filters apply to playlist downloads only</div>
        </div>

        <!-- Desktop Notifications Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🔔 Desktop Notifications</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-desktop-notifications-enabled" ${p.desktop_notifications_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable download completion notifications
          </label>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;">
            <input type="checkbox" id="yt-s-desktop-notifications-sound" ${p.desktop_notifications_sound ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Play notification sound
          </label>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Notifications appear via system tray</div>
        </div>

        <!-- Post-Download Conversion Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🔄 Post-Download Conversion</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-post-conversion-enabled" ${p.post_conversion_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable automatic format conversion after download
          </label>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Target Format</div>
          <select id="yt-s-post-conversion-target" style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;">
            <option value="mp4" ${p.post_conversion_target_format === 'mp4' ? 'selected' : ''}>MP4</option>
            <option value="mkv" ${p.post_conversion_target_format === 'mkv' ? 'selected' : ''}>MKV</option>
            <option value="webm" ${p.post_conversion_target_format === 'webm' ? 'selected' : ''}>WebM</option>
            <option value="avi" ${p.post_conversion_target_format === 'avi' ? 'selected' : ''}>AVI</option>
            <option value="mov" ${p.post_conversion_target_format === 'mov' ? 'selected' : ''}>MOV</option>
          </select>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Requires ffmpeg to be installed</div>
        </div>

        <!-- Download Scheduling Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">⏰ Download Scheduling</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-download-scheduling-enabled" ${p.download_scheduling_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable download scheduling
          </label>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Scheduled Time (HH:MM)</div>
          <input id="yt-s-download-scheduled-time" type="time" value="${p.download_scheduled_time || ''}"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Downloads will start at the specified time</div>
        </div>

        <!-- Multi-threaded Downloads Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🧵 Multi-threaded Downloads</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-multi-threaded-enabled" ${p.multi_threaded_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable multi-threaded downloads
          </label>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Number of Concurrent Threads</div>
          <input id="yt-s-multi-threaded-threads" type="number" value="${p.multi_threaded_threads || 4}" min="1" max="16"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
          <div style="font-size:9px;color:#545670;margin-top:4px;">More threads = faster downloads but higher CPU usage</div>
        </div>

        <!-- Proxy Support Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🌐 Proxy Support</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-proxy-enabled" ${p.proxy_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable proxy for downloads
          </label>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Proxy URL</div>
          <input id="yt-s-proxy-url" type="text" value="${p.proxy_url || ''}" placeholder="http://proxy.example.com:8080"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Format: http://proxy:port or socks5://proxy:port</div>
        </div>

        <!-- Audio Normalization Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">🎚️ Audio Normalization</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;">
            <input type="checkbox" id="yt-s-audio-normalization-enabled" ${p.audio_normalization_enabled ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Enable audio normalization for downloads
          </label>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Normalizes audio volume across all downloads</div>
        </div>

        <!-- Chapter/Segment Support Settings -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">📑 Chapter/Segment Support</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-download-chapters" ${p.download_chapters ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Download as separate chapters
          </label>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Specific Sections (e.g., *10-15,20-30)</div>
          <input id="yt-s-download-sections" type="text" value="${p.download_sections || ''}" placeholder="*10-15,20-30"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Download specific time segments of the video</div>
        </div>

        <!-- Playlist Scheduler -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">📅 Playlist Scheduler</div>

          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Add New Schedule</div>
          <input id="yt-s-sched-url" type="text" placeholder="Playlist URL"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;box-sizing:border-box;margin-bottom:8px;"/>
          
          <div style="display:flex;gap:8px;margin-bottom:8px;">
            <div style="flex:1;">
              <div style="font-size:9px;color:#8b8fa8;margin-bottom:2px;">Interval (hours)</div>
              <input id="yt-s-sched-interval" type="number" value="24" min="1"
                style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
            </div>
            <button id="yt-s-sched-add" style="background:#7c6af7;border:none;color:white;padding:7px 16px;border-radius:8px;font-size:10px;cursor:pointer;font-weight:700;">Add</button>
          </div>

          <div style="font-size:10px;color:#8b8fa8;margin-bottom:6px;margin-top:12px;">Scheduled Playlists</div>
          <div id="yt-s-sched-list" style="max-height:120px;overflow-y:auto;scrollbar-width:thin;scrollbar-color:#252836 transparent;">
            <div style="text-align:center;color:#545670;padding:10px;font-size:10px;">Loading schedules...</div>
          </div>
          <div id="yt-s-sched-status" style="font-size:9px;color:#545670;margin-top:6px;"></div>
        </div>

        <!-- Advanced Features -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">⚡ Advanced Features</div>

          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-auto-shutdown" ${p.auto_shutdown ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Auto-shutdown app after downloads complete
          </label>
          <div style="font-size:9px;color:#545670;margin-bottom:12px;">Closes the application when all downloads finish</div>

          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-pc-shutdown" ${p.pc_shutdown ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Shutdown PC after downloads complete
          </label>
          <div style="font-size:9px;color:#545670;margin-bottom:12px;">⚠️ This will completely shut down your computer</div>

          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
            <input type="checkbox" id="yt-s-use-custom-icon" ${p.use_custom_tray_icon ? "checked" : ""} style="accent-color:#7c6af7;width:16px;height:16px;cursor:pointer;"/>
            Use custom tray icon
          </label>
          <div style="font-size:9px;color:#545670;margin-bottom:8px;">Upload a custom icon to replace the default tray icon</div>

          <div id="yt-s-icon-upload-section" style="${p.use_custom_tray_icon ? '' : 'display:none;'}">
            <div style="display:flex;gap:8px;align-items:center;">
              <input id="yt-s-icon-file" type="file" accept=".png,.jpg,.jpeg,.bmp,.ico,.svg"
                style="flex:1;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;"/>
              <button id="yt-s-icon-upload" title="Upload icon" style="
                background:#7c6af7;border:none;color:white;
                padding:7px 12px;border-radius:8px;font-size:11px;cursor:pointer;white-space:nowrap;">
                Upload
              </button>
            </div>
            <div id="yt-s-icon-status" style="font-size:9px;color:#545670;margin-top:5px;"></div>
          </div>
          <div style="font-size:9px;color:#545670;margin-top:5px;">Default icon: Place 'tray_icon.png' (or any supported format) in the app folder. Custom icon will be saved as 'custom_icon.*' in the app folder.</div>
        </div>

        <!-- Custom Arguments -->
        <div style="background:#13161e;border:1.5px solid #252836;border-radius:12px;padding:16px;">
          <div style="font-size:11px;font-weight:700;color:#e8eaf0;margin-bottom:10px;">⚙️ Custom Arguments</div>
          <div style="font-size:10px;color:#8b8fa8;margin-bottom:4px;">Default yt-dlp arguments</div>
          <input id="yt-s-custom-args" type="text" value="${p.custom_args || ''}" placeholder="e.g. --limit-rate 1M --extractor-args youtube:player_client=ios"
            style="width:100%;background:#0d0f14;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;box-sizing:border-box;"/>
          <div style="font-size:9px;color:#545670;margin-top:4px;">Additional arguments passed to every yt-dlp command. Use with caution.</div>
        </div>

      </div>

      <!-- Footer -->
      <div id="yt-s-status" style="display:none;padding:6px 22px;font-size:10px;color:#4ade80;background:#0d0f14;"></div>
      <div style="background:#13161e;border-top:1px solid #252836;padding:14px 18px;display:flex;justify-content:flex-end;gap:10px;align-items:center;">
        <span id="yt-s-reset" style="font-size:10px;color:#8b8fa8;cursor:pointer;padding:4px 8px;border-radius:6px;transition:color .15s;">↺ Reset</span>
        <button id="yt-s-cancel" style="background:transparent;border:1.5px solid #252836;color:#8b8fa8;padding:8px 18px;border-radius:8px;cursor:pointer;font-size:11px;">Cancel</button>
        <button id="yt-s-save" style="background:#7c6af7;border:none;color:white;padding:8px 22px;border-radius:8px;cursor:pointer;font-size:11px;font-weight:700;">Save Preferences</button>
      </div>
    `;

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    // Load current cache expiry from API
    GM_xmlhttpRequest({
      method: "GET",
      url: "http://localhost:5000/api/cache/expiry",
      onload: function(res) {
        if (res.status === 200) {
          const data = JSON.parse(res.responseText);
          const cacheInput = document.getElementById("yt-s-cache-days");
          if (cacheInput && data.expiry_days !== null && data.expiry_days !== undefined) {
            cacheInput.value = data.expiry_days;
          }
        }
      }
    });

    // Close
    document.getElementById("yt-settings-close").addEventListener("click", () => overlay.remove());
    document.getElementById("yt-s-cancel").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

    // API-based native folder picker
    document.getElementById("yt-s-folder-picker").addEventListener("click", function () {
      console.log("[Folder Picker] Requesting native folder dialog via API...");
      
      // Request native folder dialog
      GM_xmlhttpRequest({
        method: "POST",
        url: "http://localhost:5000/api/folder-dialog",
        headers: { "Content-Type": "application/json" },
        onload: function(res) {
          if (res.status === 200) {
            console.log("[Folder Picker] Dialog requested, polling for result...");
            // Poll for result
            let pollCount = 0;
            const maxPolls = 30; // 30 seconds max
            const pollInterval = setInterval(() => {
              pollCount++;
              GM_xmlhttpRequest({
                method: "GET",
                url: "http://localhost:5000/api/folder-dialog-result",
                onload: function(resultRes) {
                  if (resultRes.status === 200) {
                    const data = JSON.parse(resultRes.responseText);
                    if (data.status === "success" && data.path) {
                      clearInterval(pollInterval);
                      const input = document.getElementById("yt-s-folder");
                      input.value = data.path;
                      console.log("[Folder Picker] Selected path:", data.path);
                      const statusDiv = document.getElementById("yt-s-status");
                      if (statusDiv) {
                        statusDiv.style.display = "block";
                        statusDiv.style.color = "#4ade80";
                        statusDiv.textContent = "✓ Folder selected successfully!";
                        setTimeout(() => {
                          statusDiv.style.display = "none";
                        }, 2000);
                      }
                    } else if (pollCount >= maxPolls) {
                      clearInterval(pollInterval);
                      console.log("[Folder Picker] Poll timeout");
                    }
                  }
                }
              });
            }, 1000);
          }
        }
      });
    });

    // Toggle custom icon upload section visibility
    document.getElementById("yt-s-use-custom-icon").addEventListener("change", function (e) {
      const uploadSection = document.getElementById("yt-s-icon-upload-section");
      uploadSection.style.display = e.target.checked ? "block" : "none";
    });

    // Handle icon upload
    document.getElementById("yt-s-icon-upload").addEventListener("click", function () {
      const fileInput = document.getElementById("yt-s-icon-file");
      const statusDiv = document.getElementById("yt-s-icon-status");
      
      if (!fileInput.files || fileInput.files.length === 0) {
        statusDiv.textContent = "❌ Please select a file first";
        statusDiv.style.color = "#f87171";
        return;
      }
      
      const file = fileInput.files[0];
      const reader = new FileReader();
      
      reader.onload = function(e) {
        const fileData = e.target.result;
        const fileName = file.name;
        const fileExt = fileName.split('.').pop().toLowerCase();
        
        statusDiv.textContent = "Uploading...";
        statusDiv.style.color = "#fb923c";
        
        // Send file data to backend
        GM_xmlhttpRequest({
          method: "POST",
          url: "http://localhost:5000/api/tray-icon-upload",
          headers: { "Content-Type": "application/json" },
          data: JSON.stringify({
            file_data: fileData,
            file_name: fileName,
            file_ext: fileExt
          }),
          onload: function(res) {
            if (res.status === 200) {
              const data = JSON.parse(res.responseText);
              if (data.status === "success") {
                statusDiv.textContent = "✓ Icon uploaded successfully! Restart app to apply changes.";
                statusDiv.style.color = "#4ade80";
              } else {
                statusDiv.textContent = "❌ " + (data.message || "Upload failed");
                statusDiv.style.color = "#f87171";
              }
            } else {
              statusDiv.textContent = "❌ Upload failed";
              statusDiv.style.color = "#f87171";
            }
          },
          onerror: function() {
            statusDiv.textContent = "❌ Upload failed";
            statusDiv.style.color = "#f87171";
          }
        });
      };
      
      reader.readAsDataURL(file);
    });

    // Auto-enable numbering when omit title is checked in settings panel (to prevent filename collisions)
    document.getElementById("yt-s-disable-title").addEventListener("change", e => {
      const numberingCheckbox = document.getElementById("yt-s-numbering");
      if (e.target.checked) {
        numberingCheckbox.checked = true;
        numberingCheckbox.disabled = true; // Disable numbering checkbox when omit title is on
      } else {
        numberingCheckbox.disabled = false; // Re-enable when omit title is off
      }
    });

    // Initialize numbering checkbox state based on disable_title on panel load
    if (p.disable_title) {
      const numberingCheckbox = document.getElementById("yt-s-numbering");
      numberingCheckbox.checked = true;
      numberingCheckbox.disabled = true;
    }

    // Reset to defaults
    document.getElementById("yt-s-reset").addEventListener("click", () => {
      GM_xmlhttpRequest({
        method: "GET",
        url: "http://localhost:5000/api/settings",
        onload: function(res) {
          // Just show the note — user still has to save
          const st = document.getElementById("yt-s-status");
          st.textContent = "Showing current saved settings. Edit & save to change.";
          st.style.color = "#fb923c";
          st.style.display = "block";
        }
      });
    });

    // Cache controls
    document.getElementById("yt-s-cache-clear").addEventListener("click", () => {
      const statusDiv = document.getElementById("yt-s-cache-status");
      statusDiv.textContent = "Clearing cache...";
      statusDiv.style.color = "#fb923c";
      
      GM_xmlhttpRequest({
        method: "POST",
        url: "http://localhost:5000/api/cache/clear",
        headers: { "Content-Type": "application/json" },
        onload: function(res) {
          if (res.status === 200) {
            statusDiv.textContent = "✓ Cache cleared";
            statusDiv.style.color = "#4ade80";
          } else {
            statusDiv.textContent = "✗ Failed to clear cache";
            statusDiv.style.color = "#f87171";
          }
          setTimeout(() => { statusDiv.textContent = ""; }, 3000);
        }
      });
    });

    document.getElementById("yt-s-cache-cleanup").addEventListener("click", () => {
      const statusDiv = document.getElementById("yt-s-cache-status");
      statusDiv.textContent = "Cleaning up expired entries...";
      statusDiv.style.color = "#fb923c";
      
      GM_xmlhttpRequest({
        method: "POST",
        url: "http://localhost:5000/api/cache/cleanup",
        headers: { "Content-Type": "application/json" },
        onload: function(res) {
          if (res.status === 200) {
            const data = JSON.parse(res.responseText);
            statusDiv.textContent = `✓ Cleaned ${data.removed} expired entries`;
            statusDiv.style.color = "#4ade80";
          } else {
            statusDiv.textContent = "✗ Failed to cleanup";
            statusDiv.style.color = "#f87171";
          }
          setTimeout(() => { statusDiv.textContent = ""; }, 3000);
        }
      });
    });

    // Load and render schedules
    function loadSchedules() {
      const listDiv = document.getElementById("yt-s-sched-list");
      const statusDiv = document.getElementById("yt-s-sched-status");
      
      GM_xmlhttpRequest({
        method: "GET",
        url: "http://localhost:5000/api/schedules",
        onload: function(res) {
          if (res.status === 200) {
            const schedules = JSON.parse(res.responseText);
            if (schedules.length === 0) {
              listDiv.innerHTML = `<div style="text-align:center;color:#545670;padding:10px;font-size:10px;">No scheduled playlists</div>`;
            } else {
              listDiv.innerHTML = schedules.map(s => `
                <div style="background:#0d0f14;border:1px solid #252836;border-radius:6px;padding:8px;margin-bottom:6px;">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <span style="font-size:9px;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px;">${escHtml(s.playlist_url)}</span>
                    <span style="font-size:9px;color:${s.enabled ? '#4ade80' : '#545670'};">${s.enabled ? 'Active' : 'Paused'}</span>
                  </div>
                  <div style="font-size:8px;color:#8b8fa8;margin-bottom:6px;">
                    Every ${s.interval_hours}h • Last: ${s.last_run ? new Date(s.last_run).toLocaleDateString() : 'Never'}
                  </div>
                  <div style="display:flex;gap:6px;">
                    <button class="yt-s-sched-toggle" data-url="${escHtml(s.playlist_url)}" style="flex:1;background:${s.enabled ? '#252836' : '#7c6af7'};border:none;color:#e8eaf0;padding:4px;border-radius:4px;font-size:8px;cursor:pointer;">${s.enabled ? 'Pause' : 'Enable'}</button>
                    <button class="yt-s-sched-delete" data-url="${escHtml(s.playlist_url)}" style="flex:1;background:#252836;border:none;color:#f87171;padding:4px;border-radius:4px;font-size:8px;cursor:pointer;">Delete</button>
                  </div>
                </div>
              `).join('');
              
              // Add event listeners to dynamically created buttons
              listDiv.querySelectorAll('.yt-s-sched-toggle').forEach(btn => {
                btn.addEventListener('click', function() {
                  const url = this.getAttribute('data-url');
                  toggleSchedule(url);
                });
              });
              
              listDiv.querySelectorAll('.yt-s-sched-delete').forEach(btn => {
                btn.addEventListener('click', function() {
                  const url = this.getAttribute('data-url');
                  deleteSchedule(url);
                });
              });
            }
          } else {
            listDiv.innerHTML = `<div style="text-align:center;color:#f87171;padding:10px;font-size:10px;">Failed to load schedules</div>`;
          }
        }
      });
    }

    function toggleSchedule(url) {
      const statusDiv = document.getElementById("yt-s-sched-status");
      statusDiv.textContent = "Toggling schedule...";
      statusDiv.style.color = "#fb923c";
      
      GM_xmlhttpRequest({
        method: "POST",
        url: `http://localhost:5000/api/schedules/${encodeURIComponent(url)}/toggle`,
        headers: { "Content-Type": "application/json" },
        onload: function(res) {
          if (res.status === 200) {
            loadSchedules();
            statusDiv.textContent = "";
          } else {
            statusDiv.textContent = "✗ Failed to toggle";
            statusDiv.style.color = "#f87171";
            setTimeout(() => { statusDiv.textContent = ""; }, 2000);
          }
        }
      });
    }

    function deleteSchedule(url) {
      const statusDiv = document.getElementById("yt-s-sched-status");
      statusDiv.textContent = "Deleting schedule...";
      statusDiv.style.color = "#fb923c";
      
      GM_xmlhttpRequest({
        method: "DELETE",
        url: `http://localhost:5000/api/schedules/${encodeURIComponent(url)}`,
        headers: { "Content-Type": "application/json" },
        onload: function(res) {
          if (res.status === 200) {
            loadSchedules();
            statusDiv.textContent = "✓ Schedule deleted";
            statusDiv.style.color = "#4ade80";
            setTimeout(() => { statusDiv.textContent = ""; }, 2000);
          } else {
            statusDiv.textContent = "✗ Failed to delete";
            statusDiv.style.color = "#f87171";
            setTimeout(() => { statusDiv.textContent = ""; }, 2000);
          }
        }
      });
    }

    // Add new schedule
    document.getElementById("yt-s-sched-add").addEventListener("click", () => {
      const urlInput = document.getElementById("yt-s-sched-url");
      const intervalInput = document.getElementById("yt-s-sched-interval");
      const statusDiv = document.getElementById("yt-s-sched-status");
      
      const url = urlInput.value.trim();
      const interval = parseInt(intervalInput.value);
      
      if (!url) {
        statusDiv.textContent = "✗ Enter a playlist URL";
        statusDiv.style.color = "#f87171";
        return;
      }
      
      if (!interval || interval < 1) {
        statusDiv.textContent = "✗ Enter valid interval";
        statusDiv.style.color = "#f87171";
        return;
      }
      
      statusDiv.textContent = "Adding schedule...";
      statusDiv.style.color = "#fb923c";
      
      // Use current saved settings as the schedule settings
      const settings = {
        folder: savedPrefs.folder,
        resolution: savedPrefs.resolution,
        out_format: savedPrefs.out_format,
        prefix: savedPrefs.prefix,
        disable_title: savedPrefs.disable_title,
        use_numbering: savedPrefs.use_numbering,
        subs_mode: savedPrefs.subs_mode,
        selected_subs: savedPrefs.selected_subs
      };
      
      GM_xmlhttpRequest({
        method: "POST",
        url: "http://localhost:5000/api/schedules",
        headers: { "Content-Type": "application/json" },
        data: JSON.stringify({
          playlist_url: url,
          interval_hours: interval,
          settings: settings
        }),
        onload: function(res) {
          if (res.status === 200) {
            urlInput.value = "";
            loadSchedules();
            statusDiv.textContent = "✓ Schedule added";
            statusDiv.style.color = "#4ade80";
            setTimeout(() => { statusDiv.textContent = ""; }, 2000);
          } else {
            statusDiv.textContent = "✗ Failed to add schedule";
            statusDiv.style.color = "#f87171";
            setTimeout(() => { statusDiv.textContent = ""; }, 2000);
          }
        }
      });
    });

    // Initial load of schedules
    loadSchedules();

    // Save
    document.getElementById("yt-s-save").addEventListener("click", () => {
      const cacheDaysInput = document.getElementById("yt-s-cache-days").value;
      const cacheExpiryDays = cacheDaysInput ? parseInt(cacheDaysInput) : null;
      
      const newPrefs = {
        folder:               document.getElementById("yt-s-folder").value.trim(),
        resolution:           document.getElementById("yt-s-res").value,
        out_format:           document.getElementById("yt-s-fmt").value,
        prefix:               document.getElementById("yt-s-prefix").value.trim(),
        disable_title:        document.getElementById("yt-s-disable-title").checked,
        use_numbering:        document.getElementById("yt-s-numbering").checked,
        subs_mode:            document.getElementById("yt-s-submode").value,
        selected_subs:        parseLangList(document.getElementById("yt-s-subs").value),
        download_thumbnail:   document.getElementById("yt-s-thumbnail").checked,
        embed_thumbnail:      document.getElementById("yt-s-embed-thumbnail").checked,
        thumbnail_only:       document.getElementById("yt-s-thumbnail-only").checked,
        disable_archive:      document.getElementById("yt-s-disable-archive").checked,
        cache_expiry_days:    cacheExpiryDays,
        auto_shutdown:        document.getElementById("yt-s-auto-shutdown").checked,
        pc_shutdown:          document.getElementById("yt-s-pc-shutdown").checked,
        use_custom_tray_icon: document.getElementById("yt-s-use-custom-icon").checked,
        custom_args:          document.getElementById("yt-s-custom-args")?.value || "",
        auto_retry_enabled:   document.getElementById("yt-s-auto-retry-enabled").checked,
        auto_retry_max_attempts: parseInt(document.getElementById("yt-s-auto-retry-max").value) || 3,
        auto_retry_delay:     parseInt(document.getElementById("yt-s-auto-retry-delay").value) || 5,
        speed_limit_enabled:  document.getElementById("yt-s-speed-limit-enabled").checked,
        speed_limit_value:    document.getElementById("yt-s-speed-limit-value").value.trim() || "10M",
        playlist_filter_enabled: document.getElementById("yt-s-playlist-filter-enabled").checked,
        playlist_filter_min_duration: document.getElementById("yt-s-playlist-filter-min-duration").value.trim(),
        playlist_filter_max_duration: document.getElementById("yt-s-playlist-filter-max-duration").value.trim(),
        playlist_filter_min_views: document.getElementById("yt-s-playlist-filter-min-views").value.trim(),
        playlist_filter_max_views: document.getElementById("yt-s-playlist-filter-max-views").value.trim(),
        playlist_filter_date_after: document.getElementById("yt-s-playlist-filter-date-after").value.trim(),
        playlist_filter_date_before: document.getElementById("yt-s-playlist-filter-date-before").value.trim(),
        desktop_notifications_enabled: document.getElementById("yt-s-desktop-notifications-enabled").checked,
        desktop_notifications_sound: document.getElementById("yt-s-desktop-notifications-sound").checked,
        post_conversion_enabled: document.getElementById("yt-s-post-conversion-enabled").checked,
        post_conversion_target_format: document.getElementById("yt-s-post-conversion-target").value,
        download_scheduling_enabled: document.getElementById("yt-s-download-scheduling-enabled").checked,
        download_scheduled_time: document.getElementById("yt-s-download-scheduled-time").value,
        multi_threaded_enabled: document.getElementById("yt-s-multi-threaded-enabled").checked,
        multi_threaded_threads: parseInt(document.getElementById("yt-s-multi-threaded-threads").value) || 4,
        proxy_enabled: document.getElementById("yt-s-proxy-enabled").checked,
        proxy_url: document.getElementById("yt-s-proxy-url").value.trim(),
        audio_normalization_enabled: document.getElementById("yt-s-audio-normalization-enabled").checked,
        download_chapters: document.getElementById("yt-s-download-chapters").checked,
        download_sections: document.getElementById("yt-s-download-sections").value.trim(),
      };

      const saveBtn = document.getElementById("yt-s-save");
      saveBtn.textContent = "Saving…";
      saveBtn.disabled = true;

      GM_xmlhttpRequest({
        method: "POST",
        url: "http://localhost:5000/api/settings",
        headers: { "Content-Type": "application/json" },
        data: JSON.stringify(newPrefs),
        onload: function (res) {
          const st = document.getElementById("yt-s-status");
          if (res.status === 200) {
            Object.assign(savedPrefs, newPrefs);
            if (newPrefs.folder) activeCustomPath = newPrefs.folder;
            
            // Also update cache expiry via cache API
            GM_xmlhttpRequest({
              method: "POST",
              url: "http://localhost:5000/api/cache/expiry",
              headers: { "Content-Type": "application/json" },
              data: JSON.stringify({ days: cacheExpiryDays }),
              onload: function() {
                // Cache expiry updated
              }
            });
            
            st.textContent = "✓ Preferences saved successfully!";
            st.style.color = "#4ade80";
            st.style.display = "block";
            saveBtn.textContent = "✓ Saved!";
            setTimeout(() => overlay.remove(), 1100);
          } else {
            st.textContent = "✗ Failed to save. Is the service running?";
            st.style.color = "#f87171";
            st.style.display = "block";
            saveBtn.textContent = "Save Preferences";
            saveBtn.disabled = false;
          }
        },
        onerror: function () {
          const st = document.getElementById("yt-s-status");
          st.textContent = "✗ Service offline.";
          st.style.color = "#f87171";
          st.style.display = "block";
          saveBtn.textContent = "Save Preferences";
          saveBtn.disabled = false;
        }
      });
    });
  }

  // ─── Helpers ──────────────────────────────────────────────────────────────
  function escHtml(s) {
    return String(s).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }

  function parseLangList(str) {
    return str.split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // DOWNLOAD WIZARD MODAL
  // ─────────────────────────────────────────────────────────────────────────
  function openWizardModal() {
    document.getElementById("yt-wizard-overlay")?.remove();
    let ctx = getActiveUrlContext();
    
    // Use manual URL if set
    if (window.manualUrl) {
      ctx = { type: "manual", url: window.manualUrl };
      window.manualUrl = null; // Clear after use
      // Show loading state for manual URL
      const overlay = document.createElement("div");
      overlay.id = "yt-wizard-overlay";
      Object.assign(overlay.style, {
        position: "fixed", top: "0", left: "0",
        width: "100vw", height: "100vh",
        backgroundColor: "rgba(0,0,0,0.82)",
        zIndex: "2147483647",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
      });

      const modal = document.createElement("div");
      modal.id = "yt-wizard-modal";
      Object.assign(modal.style, {
        width: "650px", maxHeight: "88vh",
        background: "#0d0f14",
        border: "1.5px solid #252836",
        borderRadius: "16px",
        boxShadow: "0 20px 60px rgba(0,0,0,0.85)",
        display: "flex", flexDirection: "column",
        overflow: "hidden"
      });

      modal.innerHTML = `
        <div style="background:#13161e;padding:16px 20px;border-bottom:1px solid #252836;display:flex;justify-content:space-between;align-items:center;border-radius:15px 15px 0 0;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-size:14px;font-weight:700;color:#e8eaf0;">📥 Download Analyzer</span>
          </div>
          <span id="yt-wizard-close" style="cursor:pointer;font-size:20px;color:#545670;">×</span>
        </div>
        <div id="yt-wizard-content" style="flex:1;overflow-y:auto;padding:16px;scrollbar-width:thin;scrollbar-color:#252836 transparent;">
          <div style="text-align:center;padding:30px 0;color:#8b8fa8;">
            <div style="font-size:32px;margin-bottom:15px;animation:spin 1s linear infinite;">⏳</div>
            <div style="font-size:14px;margin-bottom:5px;">Fetching data...</div>
            <div style="font-size:11px;color:#545670;">Getting video information from YouTube</div>
          </div>
          <style>
            @keyframes spin {
              from { transform: rotate(0deg); }
              to { transform: rotate(360deg); }
            }
          </style>
        </div>
      `;

      overlay.appendChild(modal);
      document.body.appendChild(overlay);

      document.getElementById("yt-wizard-close").addEventListener("click", () => overlay.remove());
      overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });

      // Load metadata after showing loading state
      setTimeout(() => {
        loadWizardMetadata(ctx, document.getElementById("yt-wizard-content"));
      }, 100);
      return;
    }

    const overlay = document.createElement("div");
    overlay.id = "yt-wizard-overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0",
      width: "100vw", height: "100vh",
      backgroundColor: "rgba(0,0,0,0.82)",
      zIndex: "2147483647",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
    });

    const modal = document.createElement("div");
    modal.id = "yt-wizard-modal";
    Object.assign(modal.style, {
      width: "650px", maxHeight: "88vh",
      background: "#0d0f14",
      border: "1.5px solid #252836",
      borderRadius: "16px",
      boxShadow: "0 20px 60px rgba(0,0,0,0.85)",
      display: "flex", flexDirection: "column",
      overflow: "hidden"
    });

    modal.innerHTML = `
      <div style="background:#13161e;padding:16px 20px;border-bottom:1px solid #252836;display:flex;justify-content:space-between;align-items:center;border-radius:15px 15px 0 0;">
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="font-size:14px;font-weight:700;color:#e8eaf0;">📥 Download Analyzer</span>
          <span id="yt-cache-indicator" style="display:none;font-size:10px;background:#4ade80;color:#0d0f14;padding:2px 6px;border-radius:4px;">Cached</span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
          <button id="yt-wizard-refresh" style="background:transparent;border:1px solid #252836;color:#8b8fa8;padding:4px 8px;border-radius:6px;cursor:pointer;font-size:10px;">🔄 Refresh</button>
          <span id="yt-wizard-close" style="cursor:pointer;font-size:20px;color:#545670;">×</span>
        </div>
      </div>
      <div id="yt-wizard-content" style="flex:1;overflow-y:auto;padding:16px;scrollbar-width:thin;scrollbar-color:#252836 transparent;">
        <div style="text-align:center;padding:30px 0;color:#8b8fa8;">⌛ Querying stream metadata…</div>
      </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    document.getElementById("yt-wizard-close").addEventListener("click", () => overlay.remove());
    document.getElementById("yt-wizard-refresh").addEventListener("click", () => {
      loadWizardMetadata(ctx, document.getElementById("yt-wizard-content"), true);
    });
    overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });

    loadWizardMetadata(ctx, document.getElementById("yt-wizard-content"));
  }

  function loadWizardMetadata(ctx, contentBox, forceRefresh = false) {
    if (!forceRefresh && autoFetchedData && ctx.url === lastFetchedUrl) {
      renderWizardForm(ctx, contentBox, autoFetchedData);
      return;
    }
    
    const cacheIndicator = document.getElementById("yt-cache-indicator");
    if (cacheIndicator) cacheIndicator.style.display = "none";
    
    // Show loading state with spinner
    contentBox.innerHTML = `
      <div style="text-align:center;padding:30px 0;color:#8b8fa8;">
        <div style="font-size:32px;margin-bottom:15px;animation:spin 1s linear infinite;">⏳</div>
        <div style="font-size:14px;margin-bottom:5px;">Fetching data...</div>
        <div style="font-size:11px;color:#545670;">Getting video information from YouTube</div>
      </div>
      <style>
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      </style>
    `;
    
    // For playlists, use the playlist-metadata endpoint to get format information
    const isPlaylist = ctx.type === "playlist_only" || ctx.type === "video_in_playlist";
    const apiUrl = isPlaylist ? "http://localhost:5000/api/playlist-metadata" : "http://localhost:5000/api/metadata";
    
    GM_xmlhttpRequest({
      method: "POST",
      url: apiUrl,
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ url: ctx.url, cookies: document.cookie || "", force_refresh: forceRefresh }),
      timeout: 180000, // 3 minute timeout for large playlists
      ontimeout: function() {
        contentBox.innerHTML = `
          <div style="text-align:center;padding:20px;">
            <div style="color:#f87171;margin-bottom:10px;">⏱️ Timeout loading playlist metadata</div>
            <div style="color:#8b8fa8;font-size:12px;margin-bottom:15px;">The playlist is very large. This is normal for playlists with many videos.</div>
            <button id="yt-retry-analyze" style="background:#7c6af7;border:none;color:white;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:11px;">Retry (will use cache if available)</button>
          </div>
        `;
        document.getElementById("yt-retry-analyze").addEventListener("click", () => {
          // Retry with force_refresh=false to use cache
          renderWizardForm(ctx, contentBox, null, false);
        });
      },
      onload: function (res) {
        if (res.status === 200) {
          try {
            const data = JSON.parse(res.responseText);
            autoFetchedData = data;
            lastFetchedUrl = ctx.url;
            
            if (data.from_cache && cacheIndicator) {
              cacheIndicator.style.display = "inline";
            }
            
            renderWizardForm(ctx, contentBox, data);
          } catch (e) {
            console.error("[Wizard] Failed to parse metadata:", e);
            contentBox.innerHTML = `<div style="color:#f87171;text-align:center;padding:20px;">Failed parsing metadata. Please try refreshing.</div>`;
          }
        } else {
          console.error("[Wizard] API error response:", res.status);
          contentBox.innerHTML = `<div style="color:#f87171;text-align:center;padding:20px;">API error response (${res.status}). Please try again.</div>`;
        }
      },
      onerror: function () {
        console.error("[Wizard] API request failed");
        contentBox.innerHTML = `
          <div style="color:#f87171;text-align:center;padding:20px;">
            ⚠️ Headless service is offline.<br>
            <span style="font-size:11px;color:#8b8fa8;">Run "python main.py" in your terminal.</span>
          </div>`;
      }
    });
  }

  // ─── Shared input style ───────────────────────────────────────────────────
  const iStyle = `background:#0a0c10;border:1.5px solid #252836;color:#e8eaf0;padding:7px 10px;border-radius:8px;font-size:11px;outline:none;width:100%;box-sizing:border-box;`;
  const selStyle = iStyle;
  const sectionStyle = `margin-bottom:14px;`;
  const labelStyle = `display:block;font-size:10px;color:#8b8fa8;margin-bottom:4px;`;

  function renderWizardForm(ctx, box, data) {
    const p = savedPrefs;
    // Use the actual path from picker or settings, don't modify it
    const folderDisplay = activeCustomPath || p.folder || "";
    const isPlaylistPage = ctx.type === "playlist_only";

    // Pick the best default resolution from available list
    const availRes = (data.resolutions && data.resolutions.length > 0) ? data.resolutions : [1080, 720, 480, 360];
    const defaultRes = p.resolution === "best"
      ? availRes[0]
      : (availRes.find(r => String(r) === String(p.resolution)) || availRes[0]);

    let html = ``;

    // Target selector (video-in-playlist only)
    if (ctx.type === "video_in_playlist") {
      html += `<div style="${sectionStyle}">
        <label style="${labelStyle}">Download Target</label>
        <select id="yt-wiz-target" style="${selStyle}">
          <option value="single" selected>Single Video only</option>
          <option value="playlist">Full Playlist</option>
        </select>
      </div>`;
    }

    // Save folder
    html += `<div style="${sectionStyle}">
      <label style="${labelStyle}">Save Directory</label>
      <div style="display:flex;gap:8px;">
        <input type="text" id="yt-wiz-path" value="${escHtml(folderDisplay)}"
          placeholder="Default Downloads folder"
          style="flex:1;${iStyle}" />
        <button id="yt-wiz-folder-picker" style="background:#1a1d27;border:1.5px solid #7c6af7;color:#9b8fff;padding:7px 10px;border-radius:8px;font-size:11px;cursor:pointer;white-space:nowrap;">
          Browse
        </button>
      </div>
    </div>`;

    // Format Presets
    html += `<div style="${sectionStyle}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
        <label style="${labelStyle}">Format Presets</label>
        <div style="display:flex;gap:6px;">
          <button id="yt-wiz-save-preset" style="background:rgba(124,106,247,0.16);border:1px solid rgba(124,106,247,0.38);color:#ece9ff;padding:4px 8px;border-radius:6px;font-size:10px;cursor:pointer;">Save</button>
          <button id="yt-wiz-load-preset" style="background:rgba(93,214,200,0.16);border:1px solid rgba(93,214,200,0.38);color:#d2f5ff;padding:4px 8px;border-radius:6px;font-size:10px;cursor:pointer;">Load</button>
          <button id="yt-wiz-delete-preset" style="background:rgba(255,107,107,0.16);border:1px solid rgba(255,107,107,0.38);color:#ffd2d2;padding:4px 8px;border-radius:6px;font-size:10px;cursor:pointer;">Delete</button>
        </div>
      </div>
      <select id="yt-wiz-preset-select" style="${selStyle}">
        <option value="">-- Select a preset --</option>
        ${Object.keys(p.format_presets || {}).map(name => `<option value="${escHtml(name)}">${escHtml(name)}</option>`).join('')}
      </select>
    </div>`;

    // Custom title (single video)
    html += `<div id="yt-wiz-title-row" style="${sectionStyle}${isPlaylistPage ? "display:none;" : ""}">
      <label style="${labelStyle}">Custom Filename</label>
      <input type="text" id="yt-wiz-title" value="${escHtml(data.title || "")}" style="${iStyle}" />
    </div>`;

    // Format
    html += `<div style="${sectionStyle}">
      <label style="${labelStyle}">Format Container</label>
      <select id="yt-wiz-format" style="${selStyle}">
        ${[["original","Original (No Re-encode)"],["mp4","Video: MP4"],["mkv","Video: MKV"],["webm","Video: WebM"],["mp3","Audio: MP3"],["wav","Audio: WAV"]].map(([v,l]) =>
          `<option value="${v}" ${p.out_format === v ? "selected" : ""}>${l}</option>`
        ).join("")}
      </select>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-top:8px;" id="yt-wiz-thumbnail-label">
        <input type="checkbox" id="yt-wiz-thumbnail" ${p.download_thumbnail ? "checked" : ""} style="accent-color:#7c6af7;width:15px;height:15px;" />
        Download thumbnail image (separate file)
      </label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-top:8px;" id="yt-wiz-embed-thumbnail-label">
        <input type="checkbox" id="yt-wiz-embed-thumbnail" ${p.embed_thumbnail ? "checked" : ""} style="accent-color:#7c6af7;width:15px;height:15px;" />
        Embed thumbnail in audio file (MP3/WAV)
      </label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-top:8px;">
        <input type="checkbox" id="yt-wiz-thumbnail-only" ${p.thumbnail_only ? "checked" : ""} style="accent-color:#7c6af7;width:15px;height:15px;" />
        Download thumbnail only (no video)
      </label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-top:8px;" id="yt-wiz-disable-archive-label">
        <input type="checkbox" id="yt-wiz-disable-archive" ${p.disable_archive ? "checked" : ""} style="accent-color:#7c6af7;width:15px;height:15px;" />
        Disable download archive (allow re-downloads)
      </label>
      <div style="${labelStyle}margin-top:8px;" data-advanced-only>Custom yt-dlp Arguments</div>
      <input type="text" id="yt-wiz-custom-args" value="${p.custom_args || ''}" placeholder="e.g. --limit-rate 1M --extractor-args youtube:player_client=ios"
        style="${iStyle}" data-advanced-only />
      <div style="font-size:9px;color:#545670;margin-top:2px;" data-advanced-only>Advanced: Additional arguments passed directly to yt-dlp</div>
    </div>`;

    // Stream Selection (always visible)
    html += `<div style="${sectionStyle}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <div style="font-size:10px;font-weight:700;color:#8b8fa8;text-transform:uppercase;letter-spacing:.5px;">Stream Selection</div>
        <select id="yt-wiz-sort-by" style="background:#0a0c10;border:1.5px solid #252836;color:#8b8fa8;font-size:10px;padding:4px;border-radius:6px;outline:none;">
          <option value="default">Default</option>
          <option value="quality-desc">Quality (High→Low)</option>
          <option value="quality-asc">Quality (Low→High)</option>
          <option value="id">Format ID</option>
        </select>
      </div>

      <!-- Audio streams table (always visible) -->
      <div style="margin-bottom:16px;">
        <div style="font-size:10px;font-weight:700;color:#7c6af7;margin-bottom:6px;">🎵 Audio Streams</div>
        <div style="max-height:200px;overflow-y:auto;">
          <table style="width:100%;border-collapse:collapse;font-size:10px;">
            <thead>
              <tr style="background:#0d0f14;color:#8b8fa8;">
                <th style="padding:6px;text-align:left;">Select</th>
                <th style="padding:6px;text-align:left;">ID</th>
                <th style="padding:6px;text-align:left;">Ext</th>
                <th style="padding:6px;text-align:left;">Bitrate</th>
                <th style="padding:6px;text-align:left;">Size</th>
                <th style="padding:6px;text-align:left;">Note</th>
              </tr>
            </thead>
            <tbody id="yt-wiz-audio-table">
              ${data.audio_formats && data.audio_formats.length > 0 ? data.audio_formats.map(f => `
                <tr style="border-bottom:1px solid #1a1d27;">
                  <td style="padding:6px;"><input type="radio" name="audio-select" value="${f.id}" data-size="${f.filesize || 0}" style="accent-color:#7c6af7;cursor:pointer;" class="deselectable-radio" /></td>
                  <td style="padding:6px;color:#e8eaf0;">${f.id}</td>
                  <td style="padding:6px;color:#8b8fa8;">${f.ext}</td>
                  <td style="padding:6px;color:#8b8fa8;">${f.abr ? Math.round(f.abr) + 'k' : 'N/A'}</td>
                  <td style="padding:6px;color:#8b8fa8;">${f.filesize ? formatFileSize(f.filesize) : 'N/A'}</td>
                  <td style="padding:6px;color:#545670;">${f.format_note || ''}</td>
                </tr>
              `).join('') : '<tr><td colspan="6" style="padding:10px;text-align:center;color:#545670;">No audio streams found</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
      
      <!-- Video streams table (always visible) -->
      <div>
        <div style="font-size:10px;font-weight:700;color:#7c6af7;margin-bottom:6px;">🎞️ Video Streams</div>
        <div style="max-height:200px;overflow-y:auto;">
          <table style="width:100%;border-collapse:collapse;font-size:10px;">
            <thead>
              <tr style="background:#0d0f14;color:#8b8fa8;">
                <th style="padding:6px;text-align:left;">Select</th>
                <th style="padding:6px;text-align:left;">ID</th>
                <th style="padding:6px;text-align:left;">Ext</th>
                <th style="padding:6px;text-align:left;">Resolution</th>
                <th style="padding:6px;text-align:left;">FPS</th>
                <th style="padding:6px;text-align:left;">Size</th>
              </tr>
            </thead>
            <tbody id="yt-wiz-video-table">
              ${data.video_formats && data.video_formats.length > 0 ? data.video_formats.filter(f => !f.has_audio).map(f => `
                <tr style="border-bottom:1px solid #1a1d27;">
                  <td style="padding:6px;"><input type="radio" name="video-select" value="${f.id}" data-size="${f.filesize || 0}" style="accent-color:#7c6af7;cursor:pointer;" class="deselectable-radio" /></td>
                  <td style="padding:6px;color:#e8eaf0;">${f.id}</td>
                  <td style="padding:6px;color:#8b8fa8;">${f.ext}</td>
                  <td style="padding:6px;color:#8b8fa8;">${f.width && f.height ? f.width + 'x' + f.height : 'N/A'}</td>
                  <td style="padding:6px;color:#8b8fa8;">${f.fps ? f.fps + 'fps' : 'N/A'}</td>
                  <td style="padding:6px;color:#8b8fa8;">${f.filesize ? formatFileSize(f.filesize) : 'N/A'}</td>
                </tr>
              `).join('') : '<tr><td colspan="6" style="padding:10px;text-align:center;color:#545670;">No video-only streams found</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>`;

    // Playlist panel
    html += `<div id="yt-wiz-playlist-panel" style="${isPlaylistPage ? "" : "display:none;"}background:#13161e;border:1.5px solid #252836;border-radius:10px;padding:12px;${sectionStyle}">
      <div style="font-size:10px;font-weight:700;color:#8b8fa8;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px;">Playlist Options</div>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:8px;">
        <input type="checkbox" id="yt-wiz-numbering" ${p.use_numbering ? "checked" : ""} style="accent-color:#7c6af7;width:15px;height:15px;" />
        Auto-number tracks (001, 002…)
      </label>
      <label style="${labelStyle}">Filename Prefix</label>
      <input type="text" id="yt-wiz-prefix" value="${escHtml(p.prefix || "")}" placeholder="Leave blank to skip" style="${iStyle}margin-bottom:8px;" />
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11px;color:#e8eaf0;margin-bottom:10px;">
        <input type="checkbox" id="yt-wiz-disable-title" ${p.disable_title ? "checked" : ""} style="accent-color:#7c6af7;width:15px;height:15px;" />
        Omit video title from filename
      </label>
      <div style="border-top:1px solid #252836;padding-top:8px;text-align:center;">
        <span id="yt-wiz-btn-pl-advanced" style="font-size:11px;color:#7c6af7;cursor:pointer;font-weight:bold;">🔍 Open Playlist Customizer Matrix</span>
      </div>
    </div>`;

    // Subtitles
    html += `<div style="background:#13161e;border:1.5px solid #252836;border-radius:10px;padding:12px;${sectionStyle}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:11px;font-weight:700;color:#e8eaf0;">💬 Subtitles</span>
        <select id="yt-wiz-submode" style="background:#0a0c10;border:1.5px solid #252836;color:#e8eaf0;font-size:10px;padding:4px;border-radius:6px;outline:none;">
          <option value="none" ${p.subs_mode === "none" ? "selected" : ""}>Off</option>
          <option value="embed" ${p.subs_mode === "embed" ? "selected" : ""}>Embed</option>
          <option value="external_srt" ${p.subs_mode === "external_srt" ? "selected" : ""}>External SRT</option>
        </select>
      </div>
      <div id="yt-sub-search-area" style="${p.subs_mode !== "none" ? "" : "display:none;"}">
        <input type="text" id="yt-wiz-sub-search" placeholder="Search languages…" style="${iStyle}margin-bottom:6px;" />
        <div id="yt-wiz-sub-summary" style="font-size:10px;color:#4ade80;margin-bottom:4px;">Selected: ${(p.selected_subs||[]).length > 0 ? p.selected_subs.join(", ") : "None"}</div>
        <div id="yt-sub-list-box" style="max-height:80px;overflow-y:auto;border:1.5px solid #252836;background:#0a0c10;border-radius:8px;padding:6px;scrollbar-width:thin;"></div>
      </div>
    </div>`;

    // Internet usage estimate
    html += `<div style="background:#13161e;border:1.5px solid #252836;border-radius:10px;padding:12px;${sectionStyle}">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:11px;font-weight:700;color:#e8eaf0;">📊 Expected Internet Usage</span>
        <span id="yt-wiz-internet-usage" style="font-size:11px;font-weight:700;color:#5dd6c8;">Calculating...</span>
      </div>
      <div style="font-size:9px;color:#545670;margin-top:4px;">Estimate based on selected format sizes (may vary due to encoding)</div>
    </div>`;

    // Enqueue button
    html += `<button id="yt-wiz-btn-enqueue" style="
      width:100%;background:#7c6af7;border:none;color:white;
      padding:12px;border-radius:10px;font-weight:700;font-size:13px;
      cursor:pointer;transition:background .15s;margin-top:4px;">
      ▶ Add to Download Queue
    </button>`;

    box.innerHTML = html;

    let selectedSubLanguages = [...(p.selected_subs || [])];
    let playlistItemOverrides = null;

    const rawSubsList = [
      ...(data.manual_subs || []).map(code => ({ code, type: "manual", name: getFullLanguageName(code, false) })),
      ...(data.auto_subs || []).map(code => ({ code, type: "auto", name: getFullLanguageName(code, true) }))
    ].filter((v, i, a) => a.findIndex(x => x.code === v.code && x.type === v.type) === i)
     .sort((a, b) => a.name.localeCompare(b.name));

    function rebuildSubListUI(q = "") {
      const c = document.getElementById("yt-sub-list-box");
      if (!c) return;
      c.innerHTML = "";
      const filtered = rawSubsList.filter(i => i.name.toLowerCase().includes(q.toLowerCase()));
      if (!filtered.length) { c.innerHTML = `<div style="font-size:10px;color:#545670;text-align:center;padding:4px;">No match</div>`; return; }
      filtered.forEach(item => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;padding:2px 0;";
        const chkd = selectedSubLanguages.includes(item.code);
        row.innerHTML = `
          <input type="checkbox" value="${item.code}" ${chkd ? "checked" : ""} style="margin-right:6px;accent-color:#7c6af7;cursor:pointer;" />
          <span style="font-size:11px;color:${item.type === "manual" ? "#4ade80" : "#8b8fa8"};cursor:pointer;">${item.name}</span>`;
        row.querySelector("input").addEventListener("change", e => {
          if (e.target.checked) { if (!selectedSubLanguages.includes(item.code)) selectedSubLanguages.push(item.code); }
          else selectedSubLanguages = selectedSubLanguages.filter(c => c !== item.code);
          updateSubSummary();
        });
        row.querySelector("span").addEventListener("click", () => {
          const inp = row.querySelector("input");
          inp.checked = !inp.checked;
          inp.dispatchEvent(new Event("change"));
        });
        c.appendChild(row);
      });
    }

    function updateSubSummary() {
      const el = document.getElementById("yt-wiz-sub-summary");
      if (el) el.textContent = "Selected: " + (selectedSubLanguages.length ? selectedSubLanguages.join(", ") : "None");
    }

    document.getElementById("yt-wiz-sub-search")?.addEventListener("input", e => rebuildSubListUI(e.target.value));

    document.getElementById("yt-wiz-submode").addEventListener("change", e => {
      document.getElementById("yt-sub-search-area").style.display = e.target.value !== "none" ? "block" : "none";
    });

    rebuildSubListUI();

    const formatSelect = document.getElementById("yt-wiz-format");
    const audioOnlyFormats = new Set(["mp3", "wav"]);

    function applyFormatMode() {
      const selectedFormat = formatSelect ? formatSelect.value : "original";
      const audioOnlyMode = audioOnlyFormats.has(selectedFormat);

      if (audioOnlyMode) {
        document.querySelectorAll('input[name="video-select"]').forEach(inp => {
          inp.checked = false;
        });
      }
    }

    if (formatSelect) {
      formatSelect.addEventListener("change", () => {
        applyFormatMode();
      });
      applyFormatMode();
    }

    // Smart format auto-configuration based on selection
    function autoConfigureFormat() {
      const audioRadio = document.querySelector('input[name="audio-select"]:checked');
      const videoRadio = document.querySelector('input[name="video-select"]:checked');
      const formatSelect = document.getElementById("yt-wiz-format");
      
      if (audioRadio && !videoRadio) {
        // Only audio selected - auto-switch to audio format
        if (formatSelect.value !== "mp3" && formatSelect.value !== "wav") {
          formatSelect.value = "mp3";
          console.log("[Smart Format] Auto-switched to MP3 for audio-only selection");
        }
      } else if (videoRadio && audioRadio) {
        // Video+audio selected - ensure video format
        if (formatSelect.value === "mp3" || formatSelect.value === "wav") {
          formatSelect.value = "mp4";
          console.log("[Smart Format] Auto-switched to MP4 for video selection");
        }
      }
    }

    // Calculate and update internet usage estimate
    function updateInternetUsage() {
      const usageEl = document.getElementById("yt-wiz-internet-usage");
      if (!usageEl) return;

      const audioRadio = document.querySelector('input[name="audio-select"]:checked');
      const videoRadio = document.querySelector('input[name="video-select"]:checked');
      
      let totalBytes = 0;

      if (videoRadio && audioRadio) {
        totalBytes = (parseInt(videoRadio.dataset.size) || 0) + (parseInt(audioRadio.dataset.size) || 0);
      } else if (videoRadio) {
        totalBytes = parseInt(videoRadio.dataset.size) || 0;
      } else if (audioRadio) {
        totalBytes = parseInt(audioRadio.dataset.size) || 0;
      }

      if (totalBytes > 0) {
        usageEl.textContent = formatFileSize(totalBytes);
      } else {
        usageEl.textContent = "N/A";
      }
    }

    // Add listeners for format auto-configuration
    document.querySelectorAll('input[name="audio-select"]').forEach(radio => {
      radio.addEventListener("change", () => {
        autoConfigureFormat();
        updateInternetUsage();
      });
      // Allow deselecting by clicking again
      radio.addEventListener("mousedown", function(e) {
        if (this.checked) {
          this.dataset.wasChecked = "true";
        } else {
          this.dataset.wasChecked = "false";
        }
      });
      radio.addEventListener("click", function(e) {
        if (this.dataset.wasChecked === "true") {
          this.checked = false;
          this.dataset.wasChecked = "false";
          autoConfigureFormat();
          updateInternetUsage();
          e.preventDefault();
        }
      });
    });
    document.querySelectorAll('input[name="video-select"]').forEach(radio => {
      radio.addEventListener("change", () => {
        autoConfigureFormat();
        updateInternetUsage();
      });
      // Allow deselecting by clicking again
      radio.addEventListener("mousedown", function(e) {
        if (this.checked) {
          this.dataset.wasChecked = "true";
        } else {
          this.dataset.wasChecked = "false";
        }
      });
      radio.addEventListener("click", function(e) {
        if (this.dataset.wasChecked === "true") {
          this.checked = false;
          this.dataset.wasChecked = "false";
          autoConfigureFormat();
          updateInternetUsage();
          e.preventDefault();
        }
      });
    });

    // Initial internet usage calculation
    updateInternetUsage();
    
    // Handle thumbnail-only logic
    const thumbnailOnlyCheckbox = document.getElementById("yt-wiz-thumbnail-only");
    const thumbnailLabel = document.getElementById("yt-wiz-thumbnail-label");
    const embedThumbnailLabel = document.getElementById("yt-wiz-embed-thumbnail-label");
    const disableArchiveLabel = document.getElementById("yt-wiz-disable-archive-label");
    
    function applyThumbnailOnlyLogic() {
      if (thumbnailOnlyCheckbox && thumbnailOnlyCheckbox.checked) {
        // Disable/hide other thumbnail options when thumbnail-only is enabled
        if (thumbnailLabel) {
          thumbnailLabel.style.opacity = "0.3";
          thumbnailLabel.style.pointerEvents = "none";
          document.getElementById("yt-wiz-thumbnail").disabled = true;
        }
        if (embedThumbnailLabel) {
          embedThumbnailLabel.style.opacity = "0.3";
          embedThumbnailLabel.style.pointerEvents = "none";
          document.getElementById("yt-wiz-embed-thumbnail").disabled = true;
        }
        if (disableArchiveLabel) {
          disableArchiveLabel.style.opacity = "0.3";
          disableArchiveLabel.style.pointerEvents = "none";
          document.getElementById("yt-wiz-disable-archive").disabled = true;
        }
      } else {
        // Re-enable other thumbnail options
        if (thumbnailLabel) {
          thumbnailLabel.style.opacity = "1";
          thumbnailLabel.style.pointerEvents = "auto";
          document.getElementById("yt-wiz-thumbnail").disabled = false;
        }
        if (embedThumbnailLabel) {
          embedThumbnailLabel.style.opacity = "1";
          embedThumbnailLabel.style.pointerEvents = "auto";
          document.getElementById("yt-wiz-embed-thumbnail").disabled = false;
        }
        if (disableArchiveLabel) {
          disableArchiveLabel.style.opacity = "1";
          disableArchiveLabel.style.pointerEvents = "auto";
          document.getElementById("yt-wiz-disable-archive").disabled = false;
        }
      }
    }
    
    if (thumbnailOnlyCheckbox) {
      thumbnailOnlyCheckbox.addEventListener("change", applyThumbnailOnlyLogic);
      applyThumbnailOnlyLogic(); // Apply initial state
    }

    // Format Presets functionality
    document.getElementById("yt-wiz-save-preset").addEventListener("click", () => {
      const presetName = prompt("Enter preset name:");
      if (!presetName) return;

      const presetConfig = {
        resolution: document.getElementById("yt-wiz-resolution").value,
        format: document.getElementById("yt-wiz-format").value,
        subs_mode: document.getElementById("yt-wiz-submode").value,
        selected_subs: selectedSubLanguages,
        disable_title: document.getElementById("yt-wiz-disable-title").checked,
        prefix: document.getElementById("yt-wiz-prefix").value,
        use_numbering: document.getElementById("yt-wiz-numbering").checked,
        download_thumbnail: document.getElementById("yt-wiz-thumbnail")?.checked || false,
        embed_thumbnail: document.getElementById("yt-wiz-embed-thumbnail")?.checked || false,
        disable_archive: document.getElementById("yt-wiz-disable-archive")?.checked || false,
        thumbnail_only: document.getElementById("yt-wiz-thumbnail-only")?.checked || false,
        custom_args: document.getElementById("yt-wiz-custom-args")?.value || ""
      };

      savedPrefs.format_presets = savedPrefs.format_presets || {};
      savedPrefs.format_presets[presetName] = presetConfig;
      savePrefs();

      // Update preset dropdown
      const presetSelect = document.getElementById("yt-wiz-preset-select");
      presetSelect.innerHTML = `<option value="">-- Select a preset --</option>` +
        Object.keys(savedPrefs.format_presets).map(name => `<option value="${escHtml(name)}">${escHtml(name)}</option>`).join('');
      presetSelect.value = presetName;

      alert(`Preset "${presetName}" saved successfully!`);
    });

    document.getElementById("yt-wiz-load-preset").addEventListener("click", () => {
      const presetSelect = document.getElementById("yt-wiz-preset-select");
      const presetName = presetSelect.value;
      if (!presetName) {
        alert("Please select a preset to load.");
        return;
      }

      const preset = savedPrefs.format_presets?.[presetName];
      if (!preset) {
        alert("Preset not found.");
        return;
      }

      // Apply preset values
      if (preset.resolution) document.getElementById("yt-wiz-resolution").value = preset.resolution;
      if (preset.format) document.getElementById("yt-wiz-format").value = preset.format;
      if (preset.subs_mode) document.getElementById("yt-wiz-submode").value = preset.subs_mode;
      if (preset.selected_subs) {
        selectedSubLanguages = [...preset.selected_subs];
        rebuildSubListUI();
        updateSubSummary();
      }
      if (typeof preset.disable_title === "boolean") document.getElementById("yt-wiz-disable-title").checked = preset.disable_title;
      if (preset.prefix !== undefined) document.getElementById("yt-wiz-prefix").value = preset.prefix;
      if (typeof preset.use_numbering === "boolean") document.getElementById("yt-wiz-numbering").checked = preset.use_numbering;
      if (typeof preset.download_thumbnail === "boolean") document.getElementById("yt-wiz-thumbnail").checked = preset.download_thumbnail;
      if (typeof preset.embed_thumbnail === "boolean") document.getElementById("yt-wiz-embed-thumbnail").checked = preset.embed_thumbnail;
      if (typeof preset.disable_archive === "boolean") document.getElementById("yt-wiz-disable-archive").checked = preset.disable_archive;
      if (typeof preset.thumbnail_only === "boolean") document.getElementById("yt-wiz-thumbnail-only").checked = preset.thumbnail_only;
      if (preset.custom_args !== undefined) document.getElementById("yt-wiz-custom-args").value = preset.custom_args;

      applyFormatMode();
      alert(`Preset "${presetName}" loaded successfully!`);
    });

    document.getElementById("yt-wiz-delete-preset").addEventListener("click", () => {
      const presetSelect = document.getElementById("yt-wiz-preset-select");
      const presetName = presetSelect.value;
      if (!presetName) {
        alert("Please select a preset to delete.");
        return;
      }

      if (!confirm(`Are you sure you want to delete preset "${presetName}"?`)) {
        return;
      }

      delete savedPrefs.format_presets[presetName];
      savePrefs();

      // Update preset dropdown
      presetSelect.innerHTML = `<option value="">-- Select a preset --</option>` +
        Object.keys(savedPrefs.format_presets).map(name => `<option value="${escHtml(name)}">${escHtml(name)}</option>`).join('');
      presetSelect.value = "";

      alert(`Preset "${presetName}" deleted successfully!`);
    });

    // ─────────────────────────────────────────────────────────────────────────
    // QUEUE MANAGER MODAL
    // ─────────────────────────────────────────────────────────────────────────
    function openQueueManagerModal() {
      console.log("[Queue Manager] Function called");
      document.getElementById("yt-queue-overlay")?.remove();

      const overlay = document.createElement("div");
      overlay.id = "yt-queue-overlay";
      Object.assign(overlay.style, {
        position: "fixed", top: "0", left: "0",
        width: "100vw", height: "100vh",
        backgroundColor: "rgba(0,0,0,0.82)",
        zIndex: "2147483647",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
      });

      const panel = document.createElement("div");
      Object.assign(panel.style, {
        width: "500px", maxHeight: "80vh",
        background: UI.panel,
        borderRadius: "18px",
        boxShadow: UI.shadow,
        display: "flex", flexDirection: "column",
        overflow: "hidden"
      });

      panel.innerHTML = `
        <div style="background:linear-gradient(180deg, rgba(20,23,31,0.98), rgba(13,15,20,0.98));padding:18px 20px;border-bottom:1px solid rgba(37,40,54,0.95);display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-size:15px;font-weight:700;color:${UI.text};">📋 Queue Manager</div>
            <div style="font-size:10px;color:${UI.muted};margin-top:2px;">Drag to reorder download queue</div>
          </div>
          <span id="yt-queue-close" style="cursor:pointer;font-size:20px;color:${UI.faint};line-height:1;">×</span>
        </div>
        <div style="padding:18px 20px;display:flex;flex-direction:column;gap:16px;">
          <div id="yt-queue-list" style="max-height:400px;overflow-y:auto;border:1.5px solid rgba(37,40,54,0.95);border-radius:10px;background:#0a0c10;padding:10px;">
            <div style="text-align:center;color:#545670;padding:20px;">Loading queue...</div>
          </div>
          <div style="display:flex;gap:10px;justify-content:flex-end;">
            <button id="yt-queue-cancel" style="background:transparent;border:1.5px solid rgba(37,40,54,0.95);color:${UI.muted};padding:9px 18px;border-radius:10px;cursor:pointer;font-size:11px;">Cancel</button>
            <button id="yt-queue-save" style="background:linear-gradient(135deg, ${UI.accent}, ${UI.accent2});border:none;color:white;padding:9px 22px;border-radius:10px;cursor:pointer;font-size:11px;font-weight:700;">Save Order</button>
          </div>
        </div>
      `;

      overlay.appendChild(panel);
      document.body.appendChild(overlay);

      let queueItems = [];
      let draggedItem = null;

      document.getElementById("yt-queue-close").addEventListener("click", () => overlay.remove());
      document.getElementById("yt-queue-cancel").addEventListener("click", () => overlay.remove());
      overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

      // Load current queue
      GM_xmlhttpRequest({
        method: "GET",
        url: "http://localhost:5000/api/status",
        onload: function(res) {
          if (res.status === 200) {
            const jobs = JSON.parse(res.responseText);
            queueItems = Object.entries(jobs).map(([id, job]) => ({ id, ...job }));
            renderQueueList();
          } else {
            document.getElementById("yt-queue-list").innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Failed to load queue</div>`;
          }
        },
        onerror: function() {
          document.getElementById("yt-queue-list").innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Service offline</div>`;
        }
      });

      function renderQueueList() {
        const listDiv = document.getElementById("yt-queue-list");
        listDiv.innerHTML = "";

        if (queueItems.length === 0) {
          listDiv.innerHTML = `<div style="text-align:center;color:#545670;padding:20px;">Queue is empty</div>`;
          return;
        }

        queueItems.forEach((item, index) => {
          const row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;gap:8px;padding:8px;background:#13161e;border-radius:6px;margin-bottom:4px;cursor:move;";
          row.dataset.index = index;
          row.dataset.jobId = item.id;
          row.innerHTML = `
            <span style="color:#545670;font-size:12px;font-weight:700;">${index + 1}.</span>
            <div style="flex:1;overflow:hidden;">
              <div style="font-size:11px;color:${UI.text};font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${item.title}</div>
              <div style="font-size:9px;color:${UI.muted};">Status: ${item.status}</div>
            </div>
          `;

          // Drag events
          row.addEventListener("dragstart", (e) => {
            draggedItem = row;
            row.style.opacity = "0.5";
            e.dataTransfer.effectAllowed = "move";
          });

          row.addEventListener("dragend", () => {
            draggedItem = null;
            row.style.opacity = "1";
          });

          row.addEventListener("dragover", (e) => {
            e.preventDefault();
            if (draggedItem && draggedItem !== row) {
              const rect = row.getBoundingClientRect();
              const midY = rect.top + rect.height / 2;
              if (e.clientY < midY) {
                row.parentNode.insertBefore(draggedItem, row);
              } else {
                row.parentNode.insertBefore(draggedItem, row.nextSibling);
              }
              updateIndices();
            }
          });

          row.setAttribute("draggable", "true");
          listDiv.appendChild(row);
        });
      }

      function updateIndices() {
        const rows = document.getElementById("yt-queue-list").querySelectorAll("div[draggable='true']");
        rows.forEach((row, index) => {
          row.querySelector("span").textContent = `${index + 1}.`;
          row.dataset.index = index;
        });
      }

      document.getElementById("yt-queue-save").addEventListener("click", () => {
        const rows = document.getElementById("yt-queue-list").querySelectorAll("div[draggable='true']");
        const newOrder = Array.from(rows).map(row => row.dataset.jobId);

        GM_xmlhttpRequest({
          method: "POST",
          url: "http://localhost:5000/api/reorder-queue",
          headers: { "Content-Type": "application/json" },
          data: JSON.stringify({ job_order: newOrder }),
          onload: function(res) {
            if (res.status === 200) {
              alert("Queue order saved successfully!");
              overlay.remove();
            } else {
              alert("Failed to save queue order");
            }
          },
          onerror: function() {
            alert("Service offline");
          }
        });
      });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // DOWNLOAD HISTORY MODAL
    // ─────────────────────────────────────────────────────────────────────────
    function openHistoryModal() {
      document.getElementById("yt-history-overlay")?.remove();

      const overlay = document.createElement("div");
      overlay.id = "yt-history-overlay";
      Object.assign(overlay.style, {
        position: "fixed", top: "0", left: "0",
        width: "100vw", height: "100vh",
        backgroundColor: "rgba(0,0,0,0.82)",
        zIndex: "2147483647",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
      });

      const panel = document.createElement("div");
      Object.assign(panel.style, {
        width: "600px", maxHeight: "80vh",
        background: UI.panel,
        borderRadius: "18px",
        boxShadow: UI.shadow,
        display: "flex", flexDirection: "column",
        overflow: "hidden"
      });

      panel.innerHTML = `
        <div style="background:linear-gradient(180deg, rgba(20,23,31,0.98), rgba(13,15,20,0.98));padding:18px 20px;border-bottom:1.5px solid rgba(37,40,54,0.95);display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-size:15px;font-weight:700;color:${UI.text};">📜 Download History</div>
            <div style="font-size:10px;color:${UI.muted};margin-top:2px;">View past downloads with timestamps</div>
          </div>
          <span id="yt-history-close" style="cursor:pointer;font-size:20px;color:${UI.faint};line-height:1;">×</span>
        </div>
        <div style="padding:18px 20px;display:flex;flex-direction:column;gap:16px;">
          <div id="yt-history-list" style="max-height:400px;overflow-y:auto;border:1.5px solid rgba(37,40,54,0.95);border-radius:10px;background:#0a0c10;padding:10px;">
            <div style="text-align:center;color:#545670;padding:20px;">Loading history...</div>
          </div>
          <div style="display:flex;gap:10px;justify-content:flex-end;">
            <button id="yt-history-clear" style="background:rgba(255,107,107,0.16);border:1.5px solid rgba(255,107,107,0.38);color:#ffd2d2;padding:9px 18px;border-radius:10px;cursor:pointer;font-size:11px;">Clear History</button>
            <button id="yt-history-close-btn" style="background:transparent;border:1.5px solid rgba(37,40,54,0.95);color:${UI.muted};padding:9px 18px;border-radius:10px;cursor:pointer;font-size:11px;">Close</button>
          </div>
        </div>
      `;

      overlay.appendChild(panel);
      document.body.appendChild(overlay);

      document.getElementById("yt-history-close").addEventListener("click", () => overlay.remove());
      document.getElementById("yt-history-close-btn").addEventListener("click", () => overlay.remove());
      overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

      // Load download history
      GM_xmlhttpRequest({
        method: "GET",
        url: "http://localhost:5000/api/history",
        onload: function(res) {
          if (res.status === 200) {
            const data = JSON.parse(res.responseText);
            renderHistoryList(data.history || []);
          } else {
            document.getElementById("yt-history-list").innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Failed to load history</div>`;
          }
        },
        onerror: function() {
          document.getElementById("yt-history-list").innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Service offline</div>`;
        }
      });

      function renderHistoryList(history) {
        const listDiv = document.getElementById("yt-history-list");
        listDiv.innerHTML = "";

        if (history.length === 0) {
          listDiv.innerHTML = `<div style="text-align:center;color:#545670;padding:20px;">No download history</div>`;
          return;
        }

        history.forEach((entry, index) => {
          const row = document.createElement("div");
          const date = new Date(entry.timestamp);
          const dateStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
          const statusColor = entry.success ? '#4ade80' : '#f87171';
          const statusText = entry.success ? '✓' : '✗';

          row.style.cssText = "display:flex;align-items:center;gap:8px;padding:10px;background:#13161e;border-radius:6px;margin-bottom:4px;";
          row.innerHTML = `
            <span style="color:${statusColor};font-size:14px;font-weight:700;">${statusText}</span>
            <div style="flex:1;overflow:hidden;">
              <div style="font-size:11px;color:${UI.text};font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${entry.title}</div>
              <div style="font-size:9px;color:${UI.muted};">${dateStr}</div>
            </div>
            <div style="font-size:9px;color:#545670;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${entry.file_path}">${entry.file_path}</div>
          `;
          listDiv.appendChild(row);
        });
      }

      document.getElementById("yt-history-clear").addEventListener("click", () => {
        if (!confirm("Are you sure you want to clear all download history?")) {
          return;
        }

        GM_xmlhttpRequest({
          method: "POST",
          url: "http://localhost:5000/api/history/clear",
          headers: { "Content-Type": "application/json" },
          onload: function(res) {
            if (res.status === 200) {
              alert("History cleared successfully!");
              renderHistoryList([]);
            } else {
              alert("Failed to clear history");
            }
          },
          onerror: function() {
            alert("Service offline");
          }
        });
      });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // DOWNLOAD STATISTICS MODAL
    // ─────────────────────────────────────────────────────────────────────────
    function openStatisticsModal() {
      document.getElementById("yt-statistics-overlay")?.remove();

      const overlay = document.createElement("div");
      overlay.id = "yt-statistics-overlay";
      Object.assign(overlay.style, {
        position: "fixed", top: "0", left: "0",
        width: "100vw", height: "100vh",
        backgroundColor: "rgba(0,0,0,0.82)",
        zIndex: "2147483647",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
      });

      const panel = document.createElement("div");
      Object.assign(panel.style, {
        width: "500px", maxHeight: "80vh",
        background: UI.panel,
        borderRadius: "18px",
        boxShadow: UI.shadow,
        display: "flex", flexDirection: "column",
        overflow: "hidden"
      });

      panel.innerHTML = `
        <div style="background:linear-gradient(180deg, rgba(20,23,31,0.98), rgba(13,15,20,0.98));padding:18px 20px;border-bottom:1.5px solid rgba(37,40,54,0.95);display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-size:15px;font-weight:700;color:${UI.text};">📊 Download Statistics</div>
            <div style="font-size:10px;color:${UI.muted};margin-top:2px;">Track data, counts, and storage</div>
          </div>
          <span id="yt-statistics-close" style="cursor:pointer;font-size:20px;color:${UI.faint};line-height:1;">×</span>
        </div>
        <div id="yt-statistics-content" style="padding:18px 20px;">
          <div style="text-align:center;color:#545670;padding:20px;">Loading statistics...</div>
        </div>
      `;

      overlay.appendChild(panel);
      document.body.appendChild(overlay);

      document.getElementById("yt-statistics-close").addEventListener("click", () => overlay.remove());
      overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

      // Load statistics
      GM_xmlhttpRequest({
        method: "GET",
        url: "http://localhost:5000/api/statistics",
        onload: function(res) {
          if (res.status === 200) {
            const data = JSON.parse(res.responseText);
            renderStatistics(data.statistics || {});
          } else {
            document.getElementById("yt-statistics-content").innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Failed to load statistics</div>`;
          }
        },
        onerror: function() {
          document.getElementById("yt-statistics-content").innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Service offline</div>`;
        }
      });

      function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
      }

      function renderStatistics(stats) {
        const content = document.getElementById("yt-statistics-content");
        
        if (Object.keys(stats).length === 0) {
          content.innerHTML = `<div style="text-align:center;color:#545670;padding:20px;">No statistics available yet</div>`;
          return;
        }

        const totalDownloads = stats.total_downloads || 0;
        const successfulDownloads = stats.successful_downloads || 0;
        const failedDownloads = stats.failed_downloads || 0;
        const totalData = stats.total_data_downloaded || 0;
        const lastUpdated = stats.last_updated ? new Date(stats.last_updated).toLocaleString() : 'Never';

        const successRate = totalDownloads > 0 ? ((successfulDownloads / totalDownloads) * 100).toFixed(1) : 0;

        content.innerHTML = `
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
            <div style="background:#13161e;padding:12px;border-radius:8px;">
              <div style="font-size:9px;color:#8b8fa8;margin-bottom:4px;">Total Downloads</div>
              <div style="font-size:18px;font-weight:700;color:#e8eaf0;">${totalDownloads}</div>
            </div>
            <div style="background:#13161e;padding:12px;border-radius:8px;">
              <div style="font-size:9px;color:#8b8fa8;margin-bottom:4px;">Successful</div>
              <div style="font-size:18px;font-weight:700;color:#4ade80;">${successfulDownloads}</div>
            </div>
            <div style="background:#13161e;padding:12px;border-radius:8px;">
              <div style="font-size:9px;color:#8b8fa8;margin-bottom:4px;">Failed</div>
              <div style="font-size:18px;font-weight:700;color:#f87171;">${failedDownloads}</div>
            </div>
            <div style="background:#13161e;padding:12px;border-radius:8px;">
              <div style="font-size:9px;color:#8b8fa8;margin-bottom:4px;">Success Rate</div>
              <div style="font-size:18px;font-weight:700;color:#7c6af7;">${successRate}%</div>
            </div>
          </div>
          <div style="background:#13161e;padding:12px;border-radius:8px;margin-bottom:16px;">
            <div style="font-size:9px;color:#8b8fa8;margin-bottom:4px;">Total Data Downloaded</div>
            <div style="font-size:20px;font-weight:700;color:#22c55e;">${formatBytes(totalData)}</div>
          </div>
          <div style="font-size:9px;color:#545670;text-align:center;">Last updated: ${lastUpdated}</div>
        `;
      }
    }

    // Stream sorting functionality
    function sortStreams(sortBy) {
      const audioTable = document.getElementById("yt-wiz-audio-table");
      const videoTable = document.getElementById("yt-wiz-video-table");
      
      if (!audioTable || !videoTable) return;
      
      const sortRows = (tableBody, sortBy, type) => {
        const rows = Array.from(tableBody.querySelectorAll("tr"));
        if (rows.length === 0) return;
        
        const sortedRows = rows.sort((a, b) => {
          const aCells = a.querySelectorAll("td");
          const bCells = b.querySelectorAll("td");
          
          switch (sortBy) {
            case 'quality-desc':
              if (type === 'audio') {
                const aBitrate = parseFloat(aCells[3].textContent) || 0;
                const bBitrate = parseFloat(bCells[3].textContent) || 0;
                return bBitrate - aBitrate;
              } else {
                const aRes = aCells[3].textContent.match(/(\d+)x(\d+)/);
                const bRes = bCells[3].textContent.match(/(\d+)x(\d+)/);
                if (aRes && bRes) {
                  const aPixels = parseInt(aRes[1]) * parseInt(aRes[2]);
                  const bPixels = parseInt(bRes[1]) * parseInt(bRes[2]);
                  return bPixels - aPixels;
                }
                return 0;
              }
            case 'quality-asc':
              if (type === 'audio') {
                const aBitrate = parseFloat(aCells[3].textContent) || 0;
                const bBitrate = parseFloat(bCells[3].textContent) || 0;
                return aBitrate - bBitrate;
              } else {
                const aRes = aCells[3].textContent.match(/(\d+)x(\d+)/);
                const bRes = bCells[3].textContent.match(/(\d+)x(\d+)/);
                if (aRes && bRes) {
                  const aPixels = parseInt(aRes[1]) * parseInt(aRes[2]);
                  const bPixels = parseInt(bRes[1]) * parseInt(bRes[2]);
                  return aPixels - bPixels;
                }
                return 0;
              }
            case 'id':
              const aId = aCells[1].textContent;
              const bId = bCells[1].textContent;
              return aId.localeCompare(bId);
            default:
              return 0;
          }
        });
        
        sortedRows.forEach(row => tableBody.appendChild(row));
      };
      
      sortRows(audioTable, sortBy, 'audio');
      sortRows(videoTable, sortBy, 'video');
      sortRows(combinedTable, sortBy, 'video');
    }

    document.getElementById("yt-wiz-sort-by")?.addEventListener("change", function() {
      sortStreams(this.value);
    });

    // API-based native folder picker inside wizard
    document.getElementById("yt-wiz-folder-picker")?.addEventListener("click", function () {
      console.log("[Wizard Folder Picker] Requesting native folder dialog via API...");
      
      // Request native folder dialog
      GM_xmlhttpRequest({
        method: "POST",
        url: "http://localhost:5000/api/folder-dialog",
        headers: { "Content-Type": "application/json" },
        onload: function(res) {
          if (res.status === 200) {
            console.log("[Wizard Folder Picker] Dialog requested, polling for result...");
            // Poll for result
            let pollCount = 0;
            const maxPolls = 30; // 30 seconds max
            const pollInterval = setInterval(() => {
              pollCount++;
              GM_xmlhttpRequest({
                method: "GET",
                url: "http://localhost:5000/api/folder-dialog-result",
                onload: function(resultRes) {
                  if (resultRes.status === 200) {
                    const data = JSON.parse(resultRes.responseText);
                    if (data.status === "success" && data.path) {
                      clearInterval(pollInterval);
                      const pathInput = document.getElementById("yt-wiz-path");
                      pathInput.value = data.path;
                      activeCustomPath = data.path;
                      console.log("[Wizard Folder Picker] Selected path:", data.path);
                      console.log("[Wizard Folder Picker] Final activeCustomPath:", activeCustomPath);
                    } else if (pollCount >= maxPolls) {
                      clearInterval(pollInterval);
                      console.log("[Wizard Folder Picker] Poll timeout");
                    }
                  }
                }
              });
            }, 1000);
          }
        }
      });
    });

    rebuildSubListUI();

    // Target toggle (video_in_playlist)
    const targetSel = document.getElementById("yt-wiz-target");
    const playPanel = document.getElementById("yt-wiz-playlist-panel");
    const titleRow = document.getElementById("yt-wiz-title-row");
    if (targetSel) {
      targetSel.addEventListener("change", e => {
        const isPl = e.target.value === "playlist";
        playPanel.style.display = isPl ? "block" : "none";
        titleRow.style.display = isPl ? "none" : "block";
      });
    }

    // Auto-enable numbering when omit title is checked (to prevent filename collisions)
    document.getElementById("yt-wiz-disable-title")?.addEventListener("change", e => {
      const numberingCheckbox = document.getElementById("yt-wiz-numbering");
      if (e.target.checked) {
        numberingCheckbox.checked = true;
        numberingCheckbox.disabled = true; // Disable numbering checkbox when omit title is on
      } else {
        numberingCheckbox.disabled = false; // Re-enable when omit title is off
      }
    });

    // Initialize numbering checkbox state based on disable_title on wizard load
    if (p.disable_title) {
      const numberingCheckbox = document.getElementById("yt-wiz-numbering");
      if (numberingCheckbox) {
        numberingCheckbox.checked = true;
        numberingCheckbox.disabled = true;
      }
    }

    // Smart playlist format matching logic
    function findBestMatchingFormat(targetFormat, availableFormats) {
      if (!targetFormat || !availableFormats || availableFormats.length === 0) return null;
      
      const targetRes = targetFormat.width && targetFormat.height ? 
        parseInt(targetFormat.width) * parseInt(targetFormat.height) : 0;
      const targetHasAudio = targetFormat.has_audio;
      
      // Try to find exact match first
      let exactMatch = availableFormats.find(f => {
        const fRes = f.width && f.height ? parseInt(f.width) * parseInt(f.height) : 0;
        const fHasAudio = f.has_audio;
        return fRes === targetRes && fHasAudio === targetHasAudio;
      });
      
      if (exactMatch) return exactMatch;
      
      // If no exact match, try to find nearest bigger resolution
      const biggerMatches = availableFormats.filter(f => {
        const fRes = f.width && f.height ? parseInt(f.width) * parseInt(f.height) : 0;
        const fHasAudio = f.has_audio;
        return fRes > targetRes && fHasAudio === targetHasAudio;
      }).sort((a, b) => {
        const aRes = a.width && a.height ? parseInt(a.width) * parseInt(a.height) : 0;
        const bRes = b.width && b.height ? parseInt(b.width) * parseInt(b.height) : 0;
        return aRes - bRes; // Sort ascending to get smallest bigger resolution
      });
      
      if (biggerMatches.length > 0) return biggerMatches[0];
      
      // If no bigger match, try nearest smaller resolution
      const smallerMatches = availableFormats.filter(f => {
        const fRes = f.width && f.height ? parseInt(f.width) * parseInt(f.height) : 0;
        const fHasAudio = f.has_audio;
        return fRes < targetRes && fHasAudio === targetHasAudio;
      }).sort((a, b) => {
        const aRes = a.width && a.height ? parseInt(a.width) * parseInt(a.height) : 0;
        const bRes = b.width && b.height ? parseInt(b.width) * parseInt(b.height) : 0;
        return bRes - aRes; // Sort descending to get largest smaller resolution
      });
      
      if (smallerMatches.length > 0) return smallerMatches[0];
      
      // Fallback: return any format with same audio type
      const sameAudioType = availableFormats.find(f => f.has_audio === targetHasAudio);
      if (sameAudioType) return sameAudioType;
      
      // Last resort: return first available format
      return availableFormats[0];
    }

    // Advanced matrix
    document.getElementById("yt-wiz-btn-pl-advanced")?.addEventListener("click", () => {
      openAdvancedPlaylistMatrix(ctx, availRes, overrides => {
        playlistItemOverrides = overrides;
        document.getElementById("yt-wiz-btn-pl-advanced").innerHTML =
          `✅ Matrix saved (${overrides.length} items)`;
        document.getElementById("yt-wiz-btn-pl-advanced").style.color = "#4ade80";
      });
    });

    // ── ENQUEUE ─────────────────────────────────────────────────────────────
    document.getElementById("yt-wiz-btn-enqueue").addEventListener("click", () => {
      const btn = document.getElementById("yt-wiz-btn-enqueue");
      btn.textContent = "⌛ Sending…";
      btn.disabled = true;

      const targetMode = targetSel ? targetSel.value : (ctx.type === "playlist_only" ? "playlist" : "single");
      let downloadUrl = ctx.url;

      if (ctx.type === "video_in_playlist" && targetMode === "single") {
        const u = new URL(ctx.url);
        u.searchParams.delete("list");
        u.searchParams.delete("index");
        downloadUrl = u.href;
      }

      const folderPath = document.getElementById("yt-wiz-path").value.trim();
      const prefixVal  = document.getElementById("yt-wiz-prefix")?.value || "";
      const isPlaylistActive = targetMode === "playlist";
      const sessionCookies = document.cookie || "";

      // Get selected format IDs (always use stream selection)
      let selectedAudioFormatId = null;
      let selectedVideoFormatId = null;
      let selectedCombinedFormatId = null;
      
      const audioRadio = document.querySelector('input[name="audio-select"]:checked');
      const videoRadio = document.querySelector('input[name="video-select"]:checked');
      const combinedRadio = document.querySelector('input[name="combined-select"]:checked');

      const selectedFormatValue = document.getElementById("yt-wiz-format")?.value || "original";
      const audioOnlyMode = audioOnlyFormats.has(selectedFormatValue);
      
      if (audioOnlyMode) {
        if (audioRadio) selectedAudioFormatId = audioRadio.value;
      } else {
        if (audioRadio) selectedAudioFormatId = audioRadio.value;
        if (videoRadio) selectedVideoFormatId = videoRadio.value;
        if (combinedRadio) selectedCombinedFormatId = combinedRadio.value;
      }
      
      console.log("[Stream Selection] Selected audio format ID:", selectedAudioFormatId);
      console.log("[Stream Selection] Selected video format ID:", selectedVideoFormatId);
      console.log("[Stream Selection] Selected combined format ID:", selectedCombinedFormatId);

      const basePayload = {
        prefix:               prefixVal.trim(),
        disable_title:        document.getElementById("yt-wiz-disable-title")?.checked || false,
        use_numbering:        isPlaylistActive ? (document.getElementById("yt-wiz-numbering")?.checked || false) : false,
        out_format:           document.getElementById("yt-wiz-format").value,
        resolution:           "best", // Always use best when using format IDs
        subs_mode:            document.getElementById("yt-wiz-submode").value,
        selected_subs:        selectedSubLanguages,
        folder:               folderPath,
        cookies:              sessionCookies,
        advanced_mode:        true, // Always in advanced mode now
        audio_format_id:      selectedAudioFormatId,
        video_format_id:      selectedVideoFormatId,
        combined_format_id:   selectedCombinedFormatId,
        smart_playlist:       isPlaylistActive ? true : false, // Force smart features for playlists
        download_thumbnail:   document.getElementById("yt-wiz-thumbnail")?.checked || false,
        embed_thumbnail:      document.getElementById("yt-wiz-embed-thumbnail")?.checked || false,
        thumbnail_only:       document.getElementById("yt-wiz-thumbnail-only")?.checked || false,
        disable_archive:      document.getElementById("yt-wiz-disable-archive")?.checked || false,
        custom_args:          document.getElementById("yt-wiz-custom-args")?.value || ""
      };

      function postJob(payload, onDone, onFail) {
        GM_xmlhttpRequest({
          method: "POST",
          url: "http://localhost:5000/api/enqueue",
          headers: { "Content-Type": "application/json" },
          data: JSON.stringify(payload),
          onload: r => r.status === 200 ? onDone() : onFail(r),
          onerror: onFail
        });
      }

      if (isPlaylistActive && playlistItemOverrides && playlistItemOverrides.length > 0) {
        let done = 0;
        playlistItemOverrides.forEach(v => {
          // For playlist matrix, use custom title if provided, otherwise use individual video title
          const matrixTitle = v.customTitle && v.customTitle.trim() !== "" ? v.customTitle : "";
          console.log("[Matrix] Enqueueing:", v.url, "Resolution from matrix:", v.resolution, "Custom title:", matrixTitle);
          console.log("[Matrix] Base payload resolution:", basePayload.resolution);
          const payload = { ...basePayload, url: v.url, title: matrixTitle, resolution: v.resolution, is_playlist: true };
          console.log("[Matrix] Final payload resolution:", payload.resolution);
          postJob(payload,
            () => { if (++done === playlistItemOverrides.length) { btn.textContent = "✅ Matrix jobs queued!"; btn.style.background = "#248232"; setTimeout(() => document.getElementById("yt-wizard-overlay")?.remove(), 1200); } },
            () => { btn.textContent = "❌ Error"; btn.style.background = "#cc0000"; btn.disabled = false; }
          );
        });
      } else {
        // For playlist downloads, don't send custom title so yt-dlp uses individual video titles
        // For single videos, use the custom title if provided
        const titleToSend = isPlaylistActive ? "" : (document.getElementById("yt-wiz-title")?.value || data.title || "");
        postJob({ ...basePayload, url: downloadUrl, title: titleToSend, is_playlist: isPlaylistActive },
          () => {
            btn.textContent = "✅ Queued!";
            btn.style.background = "#248232";
            setTimeout(() => { document.getElementById("yt-wizard-overlay")?.remove(); isConsoleCollapsed = false; }, 1200);
          },
          (r) => {
            try { const e = JSON.parse(r.responseText); btn.textContent = `❌ ${e.error || "Refused"}`; }
            catch { btn.textContent = "❌ Connection failed"; }
            btn.style.background = "#cc0000";
            btn.disabled = false;
          }
        );
      }
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ADVANCED PLAYLIST MATRIX
  // ─────────────────────────────────────────────────────────────────────────
  function openAdvancedPlaylistMatrix(ctx, resolutionsAvailable, saveCallback) {
    const overlay = document.createElement("div");
    overlay.id = "yt-matrix-overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0", width: "100vw", height: "100vh",
      backgroundColor: "rgba(0,0,0,0.9)", zIndex: "2147483647",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'Segoe UI', Roboto, Arial, sans-serif"
    });

    const board = document.createElement("div");
    Object.assign(board.style, {
      width: "82%", height: "82%",
      background: "#0d0f14",
      border: "1.5px solid #7c6af7",
      borderRadius: "16px", padding: "22px",
      color: "white", display: "flex", flexDirection: "column", boxSizing: "border-box"
    });

    board.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #252836;padding-bottom:12px;margin-bottom:16px;">
        <div>
          <h2 style="margin:0;font-size:15px;font-weight:700;color:#e8eaf0;">🔍 Playlist Customizer Matrix</h2>
          <span style="font-size:10px;color:#8b8fa8;">Configure each video individually</span>
        </div>
        <span id="yt-matrix-close" style="cursor:pointer;font-size:22px;color:#545670;">×</span>
      </div>
      <div id="yt-matrix-list" style="flex:1;overflow-y:auto;margin-bottom:16px;scrollbar-width:thin;scrollbar-color:#252836 transparent;">
        <div style="text-align:center;padding:50px;color:#8b8fa8;">⌛ Loading playlist…</div>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:10px;">
        <button id="yt-matrix-btn-cancel" style="background:transparent;border:1.5px solid #252836;color:#8b8fa8;padding:8px 18px;border-radius:8px;cursor:pointer;font-size:11px;">Cancel</button>
        <button id="yt-matrix-btn-save" style="background:#7c6af7;border:none;color:white;padding:8px 22px;border-radius:8px;cursor:pointer;font-size:11px;font-weight:700;">Save Matrix</button>
      </div>`;

    overlay.appendChild(board);
    document.body.appendChild(overlay);

    const closeFn = () => overlay.remove();
    document.getElementById("yt-matrix-close").addEventListener("click", closeFn);
    document.getElementById("yt-matrix-btn-cancel").addEventListener("click", closeFn);

    GM_xmlhttpRequest({
      method: "POST",
      url: "http://localhost:5000/api/playlist-items",
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ url: ctx.url, cookies: document.cookie || "" }),
      onload: function (res) {
        if (res.status === 200) {
          try {
            const r = JSON.parse(res.responseText);
            renderMatrixList(r.videos, resolutionsAvailable);
          } catch (e) {
            document.getElementById("yt-matrix-list").innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Failed to parse response.</div>`;
          }
        } else {
          document.getElementById("yt-matrix-list").innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Server error.</div>`;
        }
      }
    });

    function renderMatrixList(videos, resList) {
      const container = document.getElementById("yt-matrix-list");
      const res = resList && resList.length > 0 ? resList : [1080, 720, 480, 360];
      container.innerHTML = "";
      const table = document.createElement("table");
      table.style.cssText = "width:100%;border-collapse:collapse;font-size:12px;";
      table.innerHTML = `
        <thead>
          <tr style="border-bottom:2px solid #252836;text-align:left;color:#8b8fa8;">
            <th style="padding:8px;width:40px;"><input type="checkbox" id="yt-matrix-select-all" checked style="accent-color:#7c6af7;cursor:pointer;" /></th>
            <th style="padding:8px;width:50px;">Index</th>
            <th style="padding:8px;">Title</th>
            <th style="padding:8px;width:200px;">Override Title</th>
            <th style="padding:8px;width:110px;">Quality</th>
          </tr>
        </thead>
        <tbody id="yt-matrix-rows"></tbody>`;
      container.appendChild(table);

      const tbody = document.getElementById("yt-matrix-rows");
      const optHtml = res.map(r => `<option value="${r}">${r}p</option>`).join("");

      videos.forEach(v => {
        const tr = document.createElement("tr");
        tr.className = "yt-matrix-row-item";
        tr.style.borderBottom = "1px solid #1a1d27";
        tr.innerHTML = `
          <td style="padding:8px;"><input type="checkbox" class="yt-matrix-row-enabled" checked value="${v.url}" style="accent-color:#7c6af7;cursor:pointer;" /></td>
          <td style="padding:8px;color:#545670;">${v.index}</td>
          <td style="padding:8px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#8b8fa8;" title="${escHtml(v.title)}">${escHtml(v.title)}</td>
          <td style="padding:8px;"><input type="text" class="yt-matrix-row-title" value="${escHtml(v.title)}" style="width:100%;background:#0a0c10;border:1.5px solid #252836;color:#e8eaf0;padding:5px;border-radius:6px;font-size:11px;box-sizing:border-box;outline:none;" /></td>
          <td style="padding:8px;"><select class="yt-matrix-row-resolution" style="width:100%;background:#0a0c10;border:1.5px solid #252836;color:#e8eaf0;padding:5px;border-radius:6px;font-size:11px;outline:none;">${optHtml}</select></td>`;
        tbody.appendChild(tr);
      });

      document.getElementById("yt-matrix-select-all").addEventListener("change", e => {
        document.querySelectorAll(".yt-matrix-row-enabled").forEach(c => c.checked = e.target.checked);
      });
    }

    document.getElementById("yt-matrix-btn-save").addEventListener("click", () => {
      const selected = [];
      document.querySelectorAll(".yt-matrix-row-item").forEach(row => {
        if (row.querySelector(".yt-matrix-row-enabled").checked) {
          const url = row.querySelector(".yt-matrix-row-enabled").value;
          const customTitle = row.querySelector(".yt-matrix-row-title").value.trim();
          const resolution = row.querySelector(".yt-matrix-row-resolution").value;
          console.log("[Matrix Save] URL:", url, "Title:", customTitle, "Resolution:", resolution);
          selected.push({
            url: url,
            customTitle: customTitle,
            resolution: resolution
          });
        }
      });
      if (!selected.length) { alert("Select at least 1 video."); return; }
      console.log("[Matrix Save] Final selected array:", selected);
      saveCallback(selected);
      overlay.remove();
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // CANCEL & PROGRESS POLLING
  // ─────────────────────────────────────────────────────────────────────────
  function cancelJobRequest(jobId) {
    GM_xmlhttpRequest({
      method: "POST",
      url: "http://localhost:5000/api/cancel",
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ job_id: jobId }),
      onload: () => pollStateProgress()
    });
  }

  function pollStateProgress() {
    if (!document.getElementById("yt-downloader-console")) return;
    GM_xmlhttpRequest({
      method: "GET",
      url: "http://localhost:5000/api/status",
      onload: function (res) {
        if (res.status !== 200) return;
        const jobs = JSON.parse(res.responseText);
        const body = document.getElementById("yt-console-body");
        const el = document.getElementById("yt-downloader-console");
        if (!body || !el) return;

        const ids = Object.keys(jobs);
        if (!ids.length) {
          if (!isConsoleCollapsed) {
            body.innerHTML = `<div style="text-align:center;color:#545670;padding:15px 0;">No active download tasks.</div>`;
          }
          el.dataset.activeJobs = "0";
          return;
        }

        el.dataset.activeJobs = String(ids.length);
        const STATUS_COLOR = { downloading: "#7c6af7", completed: "#4ade80", cancelled: "#f87171", failed: "#fb923c", queued: "#8b8fa8", converting: "#fbbf24" };
        let html = "";

        ids.slice().reverse().forEach(id => {
          const job = jobs[id];
          const sc = STATUS_COLOR[job.status] || "#8b8fa8";

          html += `
            <div style="border-bottom:1px solid #1a1d27;padding-bottom:10px;margin-bottom:10px;">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:210px;color:#e8eaf0;" title="${escHtml(job.title)}">${escHtml(job.title)}</div>
                <div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">
                  <span style="font-size:9px;color:${sc};font-weight:700;text-transform:uppercase;letter-spacing:.5px;">${job.status}</span>
                  ${(job.status === "downloading" || job.status === "queued")
                    ? `<button class="yt-cancel-btn" data-id="${id}" title="Cancel" style="background:none;border:none;color:#f87171;cursor:pointer;padding:0;font-size:13px;line-height:1;">✕</button>`
                    : ""}
                </div>
              </div>`;

          if (job.is_playlist && job.playlist_total > 0) {
            const pp = Math.round((job.playlist_index / job.playlist_total) * 100) || 0;
            html += `
              <div style="margin-top:7px;">
                <div style="display:flex;justify-content:space-between;font-size:10px;color:#7c6af7;margin-bottom:3px;">
                  <span>Playlist</span><span>${job.playlist_index} / ${job.playlist_total}</span>
                </div>
                <div style="background:#1a1d27;height:5px;border-radius:3px;overflow:hidden;">
                  <div style="background:#7c6af7;width:${pp}%;height:100%;transition:width .3s;border-radius:3px;"></div>
                </div>
              </div>
              <div style="margin-top:6px;">
                <div style="display:flex;justify-content:space-between;font-size:10px;color:#8b8fa8;margin-bottom:3px;">
                  <span style="max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${job.current_video_title || "Initializing…"}</span>
                  <span>${job.percent}%</span>
                </div>
                <div style="background:#1a1d27;height:4px;border-radius:2px;overflow:hidden;">
                  <div style="background:#4ade80;width:${job.percent}%;height:100%;transition:width .3s;border-radius:2px;"></div>
                </div>
              </div>`;
          } else {
            if (job.status === "converting") {
              html += `
                <div style="margin-top:7px;">
                  <div style="background:#1a1d27;height:7px;border-radius:4px;overflow:hidden;">
                    <div style="background:${sc};width:100%;height:100%;transition:width .3s;border-radius:4px;"></div>
                  </div>
                  <div style="display:flex;justify-content:space-between;font-size:10px;color:#8b8fa8;margin-top:4px;">
                    <span>Converting to desired format...</span>
                    <span>FFmpeg</span>
                  </div>
                </div>`;
            } else {
              html += `
                <div style="margin-top:7px;">
                  <div style="background:#1a1d27;height:7px;border-radius:4px;overflow:hidden;">
                    <div style="background:${sc};width:${job.percent}%;height:100%;transition:width .3s;border-radius:4px;"></div>
                  </div>
                  <div style="display:flex;justify-content:space-between;font-size:10px;color:#8b8fa8;margin-top:4px;">
                    <span>${job.percent}%</span>
                    <span>${job.speed || "N/A"} · ETA ${job.eta || "N/A"}</span>
                  </div>
                </div>`;
            }
          }

          html += `</div>`;
        });

        if (!isConsoleCollapsed) {
          body.innerHTML = html;

          body.querySelectorAll(".yt-cancel-btn").forEach(btn => {
            btn.addEventListener("click", () => cancelJobRequest(btn.getAttribute("data-id")));
          });
        }
      }
    });
  }

})();
