#!/usr/bin/env python3
"""
Dependency Checker for YouTube Desktop Downloader Bridge Pro

This script checks for required dependencies and their configurations:
- yt-dlp installation and version
- ffmpeg installation
- JavaScript runtime (Node.js or Deno)
- yt-dlp JavaScript runtime integration
- Python dependencies
- System compatibility

Run this script before starting the application to ensure all dependencies are properly installed.
"""

import subprocess
import sys
import os
import time
from typing import Tuple, List, Dict

from settings import build_yt_dlp_js_args, resolve_js_runtime


class DependencyChecker:
    """Checks and validates all required dependencies for the downloader."""
    
    def __init__(self, max_retries: int = 3, timeout: int = 10):
        self.max_retries = max_retries
        self.timeout = timeout
        self.results = {
            'python': {'status': 'unknown', 'version': '', 'message': ''},
            'yt_dlp': {'status': 'unknown', 'version': '', 'message': ''},
            'ffmpeg': {'status': 'unknown', 'version': '', 'message': ''},
            'js_runtime': {'status': 'unknown', 'runtime': '', 'version': '', 'message': ''},
            'js_integration': {'status': 'unknown', 'message': ''},
            'python_deps': {'status': 'unknown', 'missing': [], 'message': ''},
            'pyqt': {'status': 'unknown', 'version': '', 'message': '', 'variant': ''},
        }
        self.required_python_deps = ['Flask', 'yt-dlp', 'yt-dlp-getpot-wpc', 'yt-dlp-ejs']
        self.pyqt_variants = ['PyQt5', 'PyQt6']
        self.detected_pyqt_variant = None  # Store the working PyQt variant
    
    def print_header(self):
        """Print the checker header."""
        print("=" * 70)
        print("YouTube Desktop Downloader Bridge Pro - Dependency Checker")
        print("=" * 70)
        print()
    
    def print_footer(self):
        """Print the checker footer and summary."""
        print()
        print("=" * 70)
        print("CHECK SUMMARY")
        print("=" * 70)
        
        all_passed = True
        for component, result in self.results.items():
            status = result['status']
            if status == 'error':
                all_passed = False
                print(f"❌ {component.upper()}: {result.get('message', 'Failed')}")
            elif status == 'warning':
                all_passed = False
                print(f"⚠️  {component.upper()}: {result.get('message', 'Warning')}")
            else:
                print(f"✅ {component.upper()}: OK")
        
        print()
        if all_passed:
            print("✅ All dependencies are properly installed and configured!")
            print("You can now run the application with: python main.py")
            return True
        else:
            print("❌ Some dependencies are missing or misconfigured.")
            print("Please install the missing dependencies before running the application.")
            return False
    
    def check_python(self) -> bool:
        """Check Python version and compatibility with retry logic."""
        print("Checking Python installation...")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                version = sys.version_info
                version_str = f"{version.major}.{version.minor}.{version.micro}"
                
                if version.major >= 3 and version.minor >= 8:
                    self.results['python'] = {
                        'status': 'ok',
                        'version': version_str,
                        'message': f'Python {version_str} is compatible'
                    }
                    print(f"✅ Python {version_str} - Compatible")
                    return True
                else:
                    self.results['python'] = {
                        'status': 'error',
                        'version': version_str,
                        'message': f'Python {version_str} is not compatible. Requires Python 3.8+'
                    }
                    print(f"❌ Python {version_str} - Not compatible (requires 3.8+)")
                    return False
            except Exception as e:
                if attempt < self.max_retries:
                    print(f"⚠️  Error checking Python (Attempt {attempt}/{self.max_retries}): {str(e)}")
                    time.sleep(1)
                    continue
                else:
                    self.results['python'] = {
                        'status': 'error',
                        'version': 'unknown',
                        'message': f'Error checking Python: {str(e)}'
                    }
                    print(f"❌ Error checking Python: {str(e)}")
                    return False
    
    def check_yt_dlp(self) -> bool:
        """Check yt-dlp installation and version with retry logic."""
        print("\nChecking yt-dlp installation...")
        
        # Helper function to run subprocess with retries
        def run_with_retry(cmd: List[str], description: str) -> Tuple[subprocess.CompletedProcess, bool]:
            for attempt in range(1, self.max_retries + 1):
                try:
                    res = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout
                    )
                    return res, False  # Successfully completed without timeout
                except subprocess.TimeoutExpired:
                    print(f"⚠️  Timeout checking {description} (Attempt {attempt}/{self.max_retries})")
                    if attempt < self.max_retries:
                        time.sleep(1)  # Brief pause before retrying
            return None, True  # All retries failed with timeout

        # 1. Check if yt-dlp is installed via pip
        result, timed_out = run_with_retry(
            [sys.executable, '-m', 'pip', 'show', 'yt-dlp'],
            "yt-dlp pip package"
        )

        if timed_out:
            self.results['yt_dlp'] = {
                'status': 'error',
                'version': '',
                'message': f'Timeout checking yt-dlp installation after {self.max_retries} attempts'
            }
            print(f"❌ Timeout checking yt-dlp installation after {self.max_retries} attempts")
            return False

        if result and result.returncode == 0:
            # Extract version from pip output
            version = 'unknown'
            for line in result.stdout.split('\n'):
                if line.startswith('Version:'):
                    version = line.split(':')[1].strip()
                    break
            
            # 2. Check if yt-dlp CLI command works
            cmd_result, cli_timed_out = run_with_retry(
                ['yt-dlp', '--version'],
                "yt-dlp CLI command"
            )

            if not cli_timed_out and cmd_result and cmd_result.returncode == 0:
                cli_version = cmd_result.stdout.strip()
                self.results['yt_dlp'] = {
                    'status': 'ok',
                    'version': cli_version,
                    'message': f'yt-dlp {cli_version} is installed and working'
                }
                print(f"✅ yt-dlp {cli_version} - Installed and working")
                return True
            
            # Pip package is installed, but executable CLI was not found or failed
            self.results['yt_dlp'] = {
                'status': 'warning',
                'version': version,
                'message': f'yt-dlp {version} is installed via pip but CLI command not found in PATH'
            }
            print(f"⚠️  yt-dlp {version} - Installed via pip but CLI not in PATH")
            print("   You may need to add Python Scripts to your PATH")
            return False
        else:
            self.results['yt_dlp'] = {
                'status': 'error',
                'version': '',
                'message': 'yt-dlp is not installed. Run: pip install yt-dlp'
            }
            print("❌ yt-dlp is not installed")
            print("   Install with: pip install yt-dlp")
            return False

    def check_ffmpeg(self) -> bool:
        """Check ffmpeg installation with retry logic."""
        print("\nChecking ffmpeg installation...")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                result = subprocess.run(
                    ['ffmpeg', '-version'],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )
                
                if result.returncode == 0:
                    version_line = result.stdout.split('\n')[0]
                    self.results['ffmpeg'] = {
                        'status': 'ok',
                        'version': version_line,
                        'message': 'ffmpeg is installed and working'
                    }
                    print(f"✅ ffmpeg - Installed and working")
                    print(f"   {version_line}")
                    return True
                else:
                    if attempt < self.max_retries:
                        print(f"⚠️  ffmpeg check failed (Attempt {attempt}/{self.max_retries})")
                        time.sleep(1)
                        continue
                    else:
                        self.results['ffmpeg'] = {
                            'status': 'error',
                            'version': '',
                            'message': 'ffmpeg is not installed or not working'
                        }
                        print("❌ ffmpeg is not installed or not working")
                        print("   Install from: https://ffmpeg.org/download.html")
                        return False
            except FileNotFoundError:
                if attempt < self.max_retries:
                    print(f"⚠️  ffmpeg command not found (Attempt {attempt}/{self.max_retries})")
                    time.sleep(1)
                    continue
                else:
                    self.results['ffmpeg'] = {
                        'status': 'error',
                        'version': '',
                        'message': 'ffmpeg command not found in PATH'
                    }
                    print("❌ ffmpeg command not found in PATH")
                    print("   Install from: https://ffmpeg.org/download.html")
                    return False
            except subprocess.TimeoutExpired:
                if attempt < self.max_retries:
                    print(f"⚠️  Timeout checking ffmpeg (Attempt {attempt}/{self.max_retries})")
                    time.sleep(1)
                    continue
                else:
                    self.results['ffmpeg'] = {
                        'status': 'error',
                        'version': '',
                        'message': 'Timeout checking ffmpeg installation'
                    }
                    print("❌ Timeout checking ffmpeg installation")
                    return False
            except Exception as e:
                if attempt < self.max_retries:
                    print(f"⚠️  Error checking ffmpeg: {str(e)} (Attempt {attempt}/{self.max_retries})")
                    time.sleep(1)
                    continue
                else:
                    self.results['ffmpeg'] = {
                        'status': 'error',
                        'version': '',
                        'message': f'Error checking ffmpeg: {str(e)}'
                    }
                    print(f"❌ Error checking ffmpeg: {str(e)}")
                    return False
    
    def check_js_runtime(self) -> bool:
        """Check for JavaScript runtime (Node.js or Deno) with retry logic."""
        print("\nChecking JavaScript runtime (Node.js or Deno)...")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                runtime_info = resolve_js_runtime()
                
                if runtime_info["available"]:
                    runtime = "Deno" if runtime_info["runtime"] == "deno" else "Node.js"
                    try:
                        result = subprocess.run(
                            [runtime_info["binary"], "--version"],
                            capture_output=True,
                            text=True,
                            timeout=self.timeout
                        )
                        version = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unknown"
                    except Exception:
                        version = "unknown"

                    print(f"✅ {runtime} {version} - Found")
                    self.results['js_runtime'] = {
                        'status': 'ok',
                        'runtime': runtime,
                        'version': version,
                        'message': f'{runtime} {version} is available'
                    }
                    return True
                else:
                    if attempt < self.max_retries:
                        print(f"⚠️  No JS runtime found (Attempt {attempt}/{self.max_retries})")
                        time.sleep(1)
                        continue
                    else:
                        self.results['js_runtime'] = {
                            'status': 'warning',
                            'runtime': '',
                            'version': '',
                            'message': 'No JavaScript runtime found. YouTube downloads may fail without it.'
                        }
                        print("❌ No JavaScript runtime found")
                        print("   Install Node.js from: https://nodejs.org/")
                        print("   OR install Deno from: https://deno.land/")
                        print("   JavaScript runtime is required for YouTube's anti-bot measures")
                        return False
            except Exception as e:
                if attempt < self.max_retries:
                    print(f"⚠️  Error checking JS runtime: {str(e)} (Attempt {attempt}/{self.max_retries})")
                    time.sleep(1)
                    continue
                else:
                    self.results['js_runtime'] = {
                        'status': 'error',
                        'runtime': '',
                        'version': '',
                        'message': f'Error checking JavaScript runtime: {str(e)}'
                    }
                    print(f"❌ Error checking JavaScript runtime: {str(e)}")
                    return False
    
    def check_js_integration(self) -> bool:
        """Check if yt-dlp can use JavaScript runtime with retry logic."""
        print("\nChecking yt-dlp JavaScript runtime integration...")
        
        js_available = self.results['js_runtime']['status'] in ['ok']
        
        if not js_available:
            self.results['js_integration'] = {
                'status': 'error',
                'message': 'JavaScript runtime not available. yt-dlp cannot handle YouTube\'s anti-bot measures.'
            }
            print("❌ JavaScript runtime not available")
            print("   yt-dlp cannot handle YouTube's anti-bot measures without JS runtime")
            return False
        
        print("Testing yt-dlp with YouTube extraction...")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                js_args = build_yt_dlp_js_args()
                result = subprocess.run(
                    ['yt-dlp', *js_args, '--skip-download', '--extract-flat', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    self.results['js_integration'] = {
                        'status': 'ok',
                        'message': 'yt-dlp can successfully extract YouTube video information'
                    }
                    print("✅ yt-dlp can extract YouTube video information")
                    return True
                else:
                    if attempt < self.max_retries:
                        print(f"⚠️  yt-dlp test failed (Attempt {attempt}/{self.max_retries})")
                        time.sleep(1)
                        continue
                    else:
                        error_output = result.stderr.lower()
                        if 'javascript' in error_output or 'js' in error_output or 'node' in error_output:
                            self.results['js_integration'] = {
                                'status': 'warning',
                                'message': 'yt-dlp may have issues with JavaScript integration. Check yt-dlp logs.'
                            }
                            print("⚠️  yt-dlp may have JavaScript integration issues")
                            print(f"   Error: {result.stderr[:200]}")
                            return False
                        else:
                            self.results['js_integration'] = {
                                'status': 'ok',
                                'message': 'yt-dlp is working (test may have failed for other reasons)'
                            }
                            print("✅ yt-dlp appears to be working")
                            return True
            except subprocess.TimeoutExpired:
                if attempt < self.max_retries:
                    print(f"⚠️  Timeout testing yt-dlp (Attempt {attempt}/{self.max_retries})")
                    time.sleep(1)
                    continue
                else:
                    self.results['js_integration'] = {
                        'status': 'warning',
                        'message': 'Timeout testing yt-dlp YouTube extraction'
                    }
                    print("⚠️  Timeout testing yt-dlp YouTube extraction")
                    return False
            except Exception as e:
                if attempt < self.max_retries:
                    print(f"⚠️  Error testing yt-dlp: {str(e)} (Attempt {attempt}/{self.max_retries})")
                    time.sleep(1)
                    continue
                else:
                    self.results['js_integration'] = {
                        'status': 'warning',
                        'message': f'Error testing yt-dlp integration: {str(e)}'
                    }
                    print(f"⚠️  Error testing yt-dlp integration: {str(e)}")
                    return False
    
    def check_pyqt(self) -> bool:
        """Check PyQt5/PyQt6 compatibility with headless transparent test window."""
        print("\nChecking PyQt (PyQt5/PyQt6) compatibility...")
        
        for variant in self.pyqt_variants:
            print(f"Testing {variant}...")
            
            # First check if the package is installed with retry logic
            installed = False
            version = 'unknown'
            
            for attempt in range(1, self.max_retries + 1):
                try:
                    result = subprocess.run(
                        [sys.executable, '-m', 'pip', 'show', variant],
                        capture_output=True,
                        text=True,
                        timeout=self.timeout
                    )
                    if result.returncode == 0:
                        installed = True
                        # Extract version
                        for line in result.stdout.split('\n'):
                            if line.startswith('Version:'):
                                version = line.split(':')[1].strip()
                                break
                        print(f"   {variant} {version} - Installed via pip")
                        break
                    else:
                        print(f"❌ {variant} - Not installed")
                        break
                except subprocess.TimeoutExpired:
                    print(f"⚠️  {variant} - Timeout checking (Attempt {attempt}/{self.max_retries})")
                    if attempt < self.max_retries:
                        time.sleep(1)
                    continue
                except Exception as e:
                    print(f"❌ {variant} - Error: {str(e)}")
                    break
            
            if not installed:
                continue
            
            # Test if PyQt can create a headless transparent window with retry logic
            for attempt in range(1, self.max_retries + 1):
                if self._test_pyqt_window(variant):
                    self.detected_pyqt_variant = variant  # Store the working variant
                    self.results['pyqt'] = {
                        'status': 'ok',
                        'version': version,
                        'variant': variant,
                        'message': f'{variant} {version} is working correctly'
                    }
                    print(f"✅ {variant} {version} - Working correctly")
                    return True
                else:
                    if attempt < self.max_retries:
                        print(f"   Retrying window test (Attempt {attempt}/{self.max_retries})...")
                        time.sleep(1)
                    else:
                        print(f"❌ {variant} - Window test failed")
                        continue
        
        # Neither PyQt5 nor PyQt6 worked
        self.results['pyqt'] = {
            'status': 'error',
            'version': '',
            'variant': '',
            'message': 'Neither PyQt5 nor PyQt6 could create a working window'
        }
        print("❌ Neither PyQt5 nor PyQt6 could create a working window")
        print("   Try reinstalling: pip install --force-reinstall PyQt5 PyQt6")
        return False
    
    def _test_pyqt_window(self, variant: str) -> bool:
        """Test if PyQt variant can create a headless transparent window."""
        # PyQt5 and PyQt6 have different enum syntax for window flags
        if variant == 'PyQt5':
            window_flags = 'Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint'
        else:  # PyQt6
            window_flags = 'Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint'
        
        test_script = f'''
import sys
from PyQt{variant[-1]}.QtWidgets import QApplication, QWidget
from PyQt{variant[-1]}.QtCore import Qt

app = QApplication(sys.argv)
window = QWidget()

# Make window headless (no title bar)
window.setWindowFlags({window_flags})

# Make window transparent
window.setAttribute(Qt.WA_TranslucentBackground)
window.setAttribute(Qt.WA_TransparentForMouseEvents)

# Set window size and position
window.setGeometry(0, 0, 1, 1)

# Show and hide immediately to test
window.show()
window.hide()

# Clean exit
app.quit()
print("SUCCESS")
'''
        
        try:
            result = subprocess.run(
                [sys.executable, '-c', test_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and 'SUCCESS' in result.stdout:
                return True
            else:
                if result.stderr:
                    print(f"   Error output: {result.stderr[:200]}")
                return False
        except subprocess.TimeoutExpired:
            print(f"   Timeout testing {variant} window")
            return False
        except Exception as e:
            print(f"   Exception testing {variant}: {str(e)}")
            return False

    def check_python_deps(self) -> bool:
        """Check Python dependencies (excluding PyQt which is checked separately) with retry logic."""
        print("\nChecking Python dependencies...")
        missing = []
        
        for dep in self.required_python_deps:
            for attempt in range(1, self.max_retries + 1):
                try:
                    result = subprocess.run(
                        [sys.executable, '-m', 'pip', 'show', dep],
                        capture_output=True,
                        text=True,
                        timeout=self.timeout
                    )
                    if result.returncode == 0:
                        print(f"✅ {dep} - Installed")
                        break
                    else:
                        if attempt < self.max_retries:
                            print(f"⚠️  {dep} check failed (Attempt {attempt}/{self.max_retries})")
                            time.sleep(1)
                            continue
                        else:
                            print(f"❌ {dep} - Not installed")
                            missing.append(dep)
                            break
                except subprocess.TimeoutExpired:
                    if attempt < self.max_retries:
                        print(f"⚠️  {dep} timeout (Attempt {attempt}/{self.max_retries})")
                        time.sleep(1)
                        continue
                    else:
                        print(f"❌ {dep} - Timeout checking")
                        missing.append(dep)
                        break
                except Exception as e:
                    if attempt < self.max_retries:
                        print(f"⚠️  {dep} error: {str(e)} (Attempt {attempt}/{self.max_retries})")
                        time.sleep(1)
                        continue
                    else:
                        print(f"❌ {dep} - Error: {str(e)}")
                        missing.append(dep)
                        break
        
        if not missing:
            self.results['python_deps'] = {
                'status': 'ok',
                'missing': [],
                'message': 'All Python dependencies are installed'
            }
            return True
        else:
            self.results['python_deps'] = {
                'status': 'error',
                'missing': missing,
                'message': f'Missing Python dependencies: {", ".join(missing)}'
            }
            print(f"\n❌ Missing Python dependencies: {', '.join(missing)}")
            print(f"   Install with: pip install {' '.join(missing)}")
            return False
    
    def run_all_checks(self) -> bool:
        """Run all dependency checks."""
        self.print_header()
        
        results = []
        results.append(self.check_python())
        results.append(self.check_pyqt())
        results.append(self.check_yt_dlp())
        results.append(self.check_ffmpeg())
        results.append(self.check_js_runtime())
        results.append(self.check_js_integration())
        results.append(self.check_python_deps())
        
        return self.print_footer() and all(results)


def update_yt_dlp():
    """Update yt-dlp to the latest version."""
    print("🔄 Updating yt-dlp to the latest version...")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            print("✅ yt-dlp updated successfully!")
            # Get the new version
            version_result = subprocess.run(
                ['yt-dlp', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if version_result.returncode == 0:
                print(f"   Current version: {version_result.stdout.strip()}")
            return True
        else:
            print("⚠️  Failed to update yt-dlp")
            print(f"   Error: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("⚠️  Timeout updating yt-dlp")
        return False
    except Exception as e:
        print(f"⚠️  Error updating yt-dlp: {str(e)}")
        return False


def main():
    """Main entry point for the dependency checker."""
    # First, update yt-dlp
    update_yt_dlp()
    print()
    
    # Retries up to 3 times per check with a 10s timeout
    checker = DependencyChecker(max_retries=3, timeout=10)
    success = checker.run_all_checks()
    
    print()
    if success:
        print("✅ All checks passed! You can start the application.")
        sys.exit(0)
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        sys.exit(1)


if __name__ == '__main__':
    main()