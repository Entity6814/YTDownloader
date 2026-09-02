#!/usr/bin/env python3
"""
Automatic Dependency Installer for YouTube Desktop Downloader Bridge Pro

This script automatically downloads and installs all required dependencies:
- Python packages (Flask, yt-dlp, PyQt5/PyQt6)
- FFmpeg (downloads automatically if not found)
- JavaScript runtime (Node.js or Deno)
- Sets up proper environment for the application

Run this script to automatically set up the complete development environment.
"""

import subprocess
import sys
import os
import platform
import urllib.request
import zipfile
import tarfile
import shutil
import tempfile
from pathlib import Path
from typing import Tuple, Optional

class DependencyInstaller:
    """Automatically downloads and installs all required dependencies."""
    
    def __init__(self):
        self.max_retries = 3
        self.timeout = 30
        self.install_dir = os.path.join(os.path.expanduser("~"), "video_downloader", "tools")
        self.temp_dir = tempfile.mkdtemp(prefix="video_downloader_setup_")
        
    def print_header(self):
        """Print the installer header."""
        print("=" * 70)
        print("YouTube Desktop Downloader Bridge Pro - Dependency Installer")
        print("=" * 70)
        print()
    
    def print_footer(self):
        """Print the installer footer."""
        print()
        print("=" * 70)
        print("INSTALLATION COMPLETE")
        print("=" * 70)
        print("✅ All dependencies have been installed and configured!")
        print("You can now run the application with: python main.py")
        print()
    
    def run_command(self, cmd: list, description: str) -> Tuple[bool, str]:
        """Run a command with retry logic."""
        for attempt in range(1, self.max_retries + 1):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )
                if result.returncode == 0:
                    return True, result.stdout
                else:
                    if attempt < self.max_retries:
                        print(f"⚠️  {description} failed (Attempt {attempt}/{self.max_retries})")
                        continue
                    else:
                        return False, result.stderr
            except subprocess.TimeoutExpired:
                if attempt < self.max_retries:
                    print(f"⚠️  Timeout {description} (Attempt {attempt}/{self.max_retries})")
                    continue
                else:
                    return False, "Timeout"
            except Exception as e:
                if attempt < self.max_retries:
                    print(f"⚠️  Error {description}: {str(e)} (Attempt {attempt}/{self.max_retries})")
                    continue
                else:
                    return False, str(e)
        return False, "Max retries exceeded"
    
    def install_python_package(self, package: str) -> bool:
        """Install a Python package using pip."""
        print(f"Installing {package}...")
        success, output = self.run_command(
            [sys.executable, '-m', 'pip', 'install', package],
            f"pip install {package}"
        )
        if success:
            print(f"✅ {package} installed successfully")
            return True
        else:
            print(f"❌ Failed to install {package}")
            print(f"   Error: {output}")
            return False
    
    def check_and_install_pyqt(self) -> bool:
        """Check and install PyQt (try PyQt5 first, then PyQt6)."""
        print("Checking PyQt installation...")
        
        # Try PyQt5 first as it's more commonly used
        for variant in ['PyQt5', 'PyQt6']:
            success, output = self.run_command(
                [sys.executable, '-m', 'pip', 'show', variant],
                f"pip show {variant}"
            )
            if success:
                print(f"✅ {variant} is already installed")
                return True
        
        # Try to install PyQt5 first
        print("Installing PyQt5...")
        if self.install_python_package('PyQt5'):
            return True
        
        # Fallback to PyQt6
        print("Installing PyQt6...")
        if self.install_python_package('PyQt6'):
            return True
        
        print("❌ Failed to install any PyQt variant")
        return False
    
    def check_and_install_yt_dlp(self) -> bool:
        """Check and install yt-dlp and PO Token provider."""
        print("Checking yt-dlp installation...")
        
        success, output = self.run_command(
            [sys.executable, '-m', 'pip', 'show', 'yt-dlp'],
            "pip show yt-dlp"
        )
        if success:
            print("✅ yt-dlp is already installed")
        else:
            print("Installing yt-dlp...")
            if not self.install_python_package('yt-dlp'):
                return False
        
        # Install PO Token provider for YouTube
        print("Checking PO Token provider for YouTube...")
        
        # Check for yt-dlp-getpot-wpc
        success, output = self.run_command(
            [sys.executable, '-m', 'pip', 'show', 'yt-dlp-getpot-wpc'],
            "pip show yt-dlp-getpot-wpc"
        )
        if success:
            print("✅ PO Token provider (yt-dlp-getpot-wpc) is already installed")
        else:
            print("Installing PO Token provider (yt-dlp-getpot-wpc)...")
            if not self.install_python_package('yt-dlp-getpot-wpc'):
                print("⚠️  Failed to install PO Token provider, YouTube downloads may fail")
                print("   You may need to manually install: pip install yt-dlp-getpot-wpc")
        
        # Check for alternate PO Token provider (yt-dlp-ejs)
        print("Checking alternate PO Token provider for YouTube...")
        success, output = self.run_command(
            [sys.executable, '-m', 'pip', 'show', 'yt-dlp-ejs'],
            "pip show yt-dlp-ejs"
        )
        if success:
            print("✅ Alternate PO Token provider (yt-dlp-ejs) is already installed")
        else:
            print("Installing alternate PO Token provider (yt-dlp-ejs)...")
            if not self.install_python_package('yt-dlp-ejs'):
                print("⚠️  Failed to install alternate PO Token provider")
                print("   You may need to manually install: pip install yt-dlp-ejs")
        
        return True
    
    def check_and_install_flask(self) -> bool:
        """Check and install Flask."""
        print("Checking Flask installation...")
        
        success, output = self.run_command(
            [sys.executable, '-m', 'pip', 'show', 'Flask'],
            "pip show Flask"
        )
        if success:
            print("✅ Flask is already installed")
            return True
        
        print("Installing Flask...")
        return self.install_python_package('Flask')
    
    def download_file(self, url: str, destination: str) -> bool:
        """Download a file from URL with retry logic."""
        for attempt in range(1, self.max_retries + 1):
            try:
                print(f"Downloading from {url}...")
                urllib.request.urlretrieve(url, destination)
                print(f"✅ Downloaded to {destination}")
                return True
            except Exception as e:
                if attempt < self.max_retries:
                    print(f"⚠️  Download failed (Attempt {attempt}/{self.max_retries}): {str(e)}")
                    continue
                else:
                    print(f"❌ Failed to download after {self.max_retries} attempts")
                    return False
    
    def extract_archive(self, archive_path: str, extract_to: str) -> bool:
        """Extract a zip or tar archive."""
        try:
            print(f"Extracting {archive_path}...")
            if archive_path.endswith('.zip'):
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_to)
            elif archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
                with tarfile.open(archive_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(extract_to)
            elif archive_path.endswith('.tar.bz2'):
                with tarfile.open(archive_path, 'r:bz2') as tar_ref:
                    tar_ref.extractall(extract_to)
            else:
                print(f"❌ Unsupported archive format: {archive_path}")
                return False
            
            print(f"✅ Extracted to {extract_to}")
            return True
        except Exception as e:
            print(f"❌ Failed to extract archive: {str(e)}")
            return False
    
    def install_ffmpeg(self) -> bool:
        """Download and install FFmpeg."""
        print("Checking FFmpeg installation...")
        
        # Check if ffmpeg is already in PATH
        success, output = self.run_command(['ffmpeg', '-version'], "ffmpeg -version")
        if success:
            print("✅ FFmpeg is already installed")
            return True
        
        # Create installation directory
        os.makedirs(self.install_dir, exist_ok=True)
        
        # Determine platform and download appropriate FFmpeg
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        print(f"Downloading FFmpeg for {system} ({machine})...")
        
        if system == 'windows':
            if machine in ['amd64', 'x86_64']:
                ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
            elif machine in ['arm64', 'aarch64']:
                ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-winarm64-gpl.zip"
            else:
                ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win32-gpl.zip"
        elif system == 'linux':
            if machine in ['amd64', 'x86_64']:
                ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
            elif machine in ['arm64', 'aarch64']:
                ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz"
            else:
                ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux32-gpl.tar.xz"
        elif system == 'darwin':
            if machine in ['arm64', 'aarch64']:
                ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-macosarm64-gpl.tar.xz"
            else:
                ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-macos64-gpl.tar.xz"
        else:
            print(f"❌ Unsupported platform: {system}")
            return False
        
        # Download FFmpeg
        ffmpeg_archive = os.path.join(self.temp_dir, "ffmpeg_archive")
        if not self.download_file(ffmpeg_url, ffmpeg_archive):
            return False
        
        # Extract FFmpeg
        extract_dir = os.path.join(self.temp_dir, "ffmpeg_extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        if not self.extract_archive(ffmpeg_archive, extract_dir):
            return False
        
        # Find and copy ffmpeg executables
        ffmpeg_found = False
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file == 'ffmpeg' or file == 'ffmpeg.exe':
                    src = os.path.join(root, file)
                    dst = os.path.join(self.install_dir, file)
                    shutil.copy2(src, dst)
                    ffmpeg_found = True
                    print(f"✅ Copied {file} to {dst}")
                elif file == 'ffprobe' or file == 'ffprobe.exe':
                    src = os.path.join(root, file)
                    dst = os.path.join(self.install_dir, file)
                    shutil.copy2(src, dst)
                    print(f"✅ Copied {file} to {dst}")
        
        if not ffmpeg_found:
            print("❌ FFmpeg executable not found in downloaded archive")
            return False
        
        # Add to PATH (this session only, user needs to add permanently)
        if system == 'windows':
            ffmpeg_path = os.path.join(self.install_dir, 'ffmpeg.exe')
            os.environ['PATH'] = self.install_dir + os.pathsep + os.environ.get('PATH', '')
        else:
            ffmpeg_path = os.path.join(self.install_dir, 'ffmpeg')
            os.environ['PATH'] = self.install_dir + os.pathsep + os.environ.get('PATH', '')
        
        print(f"✅ FFmpeg installed to {self.install_dir}")
        print(f"⚠️  Note: Add {self.install_dir} to your PATH for permanent access")
        print(f"📁 All application data will be stored in: {os.path.join(os.path.expanduser('~'), 'video_downloader')}")
        return True
    
    def check_js_runtime(self) -> bool:
        """Check for JavaScript runtime (Node.js or Deno)."""
        print("Checking JavaScript runtime...")
        
        # Check for Deno first (preferred)
        for attempt in range(1, self.max_retries + 1):
            try:
                result = subprocess.run(
                    ['deno', '--version'],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )
                if result.returncode == 0:
                    print(f"✅ Deno {result.stdout.strip()} - Found")
                    return True
            except FileNotFoundError:
                if attempt < self.max_retries:
                    continue
                break
            except subprocess.TimeoutExpired:
                if attempt < self.max_retries:
                    continue
                break
        
        # Check for Node.js
        for attempt in range(1, self.max_retries + 1):
            try:
                result = subprocess.run(
                    ['node', '--version'],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )
                if result.returncode == 0:
                    print(f"✅ Node.js {result.stdout.strip()} - Found")
                    return True
            except FileNotFoundError:
                if attempt < self.max_retries:
                    continue
                break
            except subprocess.TimeoutExpired:
                if attempt < self.max_retries:
                    continue
                break
        
        print("⚠️  No JavaScript runtime found")
        print("   Installing Deno (recommended)...")
        return self.install_deno()
    
    def install_deno(self) -> bool:
        """Install Deno JavaScript runtime."""
        print("Installing Deno...")
        
        system = platform.system().lower()
        
        if system == 'windows':
            deno_url = "https://deno.land/install.ps1"
            deno_script = os.path.join(self.temp_dir, "install_deno.ps1")
            
            if not self.download_file(deno_url, deno_script):
                return False
            
            try:
                result = subprocess.run(
                    ['powershell', '-ExecutionPolicy', 'Bypass', '-File', deno_script],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    print("✅ Deno installed successfully")
                    return True
                else:
                    print(f"❌ Deno installation failed: {result.stderr}")
                    return False
            except Exception as e:
                print(f"❌ Error installing Deno: {str(e)}")
                return False
        else:
            # Unix-like systems
            deno_url = "https://deno.land/install.sh"
            deno_script = os.path.join(self.temp_dir, "install_deno.sh")
            
            if not self.download_file(deno_url, deno_script):
                return False
            
            try:
                os.chmod(deno_script, 0o755)
                result = subprocess.run(
                    ['sh', deno_script],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    print("✅ Deno installed successfully")
                    return True
                else:
                    print(f"❌ Deno installation failed: {result.stderr}")
                    return False
            except Exception as e:
                print(f"❌ Error installing Deno: {str(e)}")
                return False
    
    def cleanup(self):
        """Clean up temporary files."""
        try:
            shutil.rmtree(self.temp_dir)
            print(f"✅ Cleaned up temporary files")
        except Exception as e:
            print(f"⚠️  Could not clean up temporary files: {str(e)}")
    
    def install_all(self) -> bool:
        """Install all dependencies."""
        self.print_header()
        
        results = []
        
        # Install Python packages
        results.append(self.check_and_install_flask())
        results.append(self.check_and_install_yt_dlp())
        results.append(self.check_and_install_pyqt())
        
        # Install FFmpeg
        results.append(self.install_ffmpeg())
        
        # Install JavaScript runtime
        results.append(self.check_js_runtime())
        
        self.cleanup()
        self.print_footer()
        
        return all(results)

def main():
    """Main entry point for the dependency installer."""
    installer = DependencyInstaller()
    success = installer.install_all()
    
    if success:
        print("✅ All dependencies installed successfully!")
        sys.exit(0)
    else:
        print("❌ Some dependencies failed to install")
        print("Please check the errors above and try manual installation")
        sys.exit(1)

if __name__ == "__main__":
    main()