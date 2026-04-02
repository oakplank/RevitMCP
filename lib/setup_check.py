#!/usr/bin/env python3
# RevitMCP: This script runs in a standard CPython 3.7+ environment. Modern Python syntax is expected.
"""
RevitMCP Setup Verification Script

This script checks if the RevitMCP environment is properly configured.
Run this script to verify that all dependencies are available.
"""

import os
import sys
import subprocess

# Define subprocess creation flags for suppressing console windows on Windows
subprocess_creation_flags = 0
if os.name == 'nt':
    try:
        subprocess_creation_flags = subprocess.CREATE_NO_WINDOW
    except AttributeError: 
        subprocess_creation_flags = 0x08000000

PACKAGE_TO_IMPORT_MAP = {
    "google-generativeai": "google.generativeai"
}

def check_python_version():
    """Check if Python version meets requirements."""
    print("Checking Python version...")
    version = sys.version_info
    required = (3, 7)
    
    if version >= required:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro} (meets requirement {required[0]}.{required[1]}+)")
        return True
    else:
        print(f"✗ Python {version.major}.{version.minor}.{version.micro} (requires {required[0]}.{required[1]}+)")
        return False

def check_package(package_name):
    """Check if a package is installed and importable."""
    try:
        import_name = PACKAGE_TO_IMPORT_MAP.get(package_name, package_name.replace('-', '_'))
        __import__(import_name)
        print(f"✓ {package_name}")
        return True
    except ImportError:
        print(f"✗ {package_name} (missing)")
        return False

def install_missing_packages(missing_packages):
    """Install missing packages."""
    if not missing_packages:
        return True
    
    print(f"\nAttempting to install missing packages: {', '.join(missing_packages)}")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Assume setup_check.py is in lib/, and requirements.txt is in lib/RevitMCP_ExternalServer/
    requirements_file = os.path.join(script_dir, "RevitMCP_ExternalServer", "requirements.txt") 
    
    try:
        if os.path.exists(requirements_file):
            cmd = [sys.executable, "-m", "pip", "install", "-r", requirements_file, "--user", "--quiet"]
            print(f"Installing from requirements.txt: {requirements_file}")
        else:
            cmd = [sys.executable, "-m", "pip", "install"] + missing_packages + ["--user", "--quiet"]
            print(f"Installing individual packages...")
        
        # For this manual script, we might want to see output, so don't use capture_output=True for stdout/stderr
        # but still use creationflags to prevent new windows for the pip process itself.
        process = subprocess.Popen(cmd, creationflags=subprocess_creation_flags)
        process.wait() # Wait for the process to complete
        
        if process.returncode == 0:
            print("✓ Successfully installed packages! Please re-run this script to verify.")
            return True
        else:
            # If Popen was used, stdout/stderr are not in result. Use communicate for capture or let it print to console.
            print(f"✗ Failed to install packages (pip exit code: {process.returncode}). Check pip output above.")
            return False
            
    except Exception as e:
        print(f"✗ Error installing packages: {e}")
        return False

def main():
    print("RevitMCP Setup Verification")
    print("=" * 30)
    
    python_ok = check_python_version()
    print()
    
    if not python_ok:
        print("❌ Python version too old. Please install Python 3.7 or newer from python.org.")
        return False
    
    print("Checking required packages...")
    required_packages = ["flask", "requests", "openai", "anthropic", "google-generativeai"]
    missing_packages = []
    all_packages_ok = True
    
    for package in required_packages:
        if not check_package(package):
            missing_packages.append(package)
            all_packages_ok = False
    
    print()
    
    if not all_packages_ok:
        print(f"Found {len(missing_packages)} missing package(s): {', '.join(missing_packages)}.")
        
        try:
            response = input("Would you like to attempt automatic installation? (y/n): ").lower().strip()
            if response in ['y', 'yes']:
                if install_missing_packages(missing_packages):
                    print("\nInstallation attempt finished. Please re-run this script to confirm all packages are now installed.")
                    return False # Force re-run to confirm
                else:
                    print("\n❌ Package installation failed or was incomplete.")
                    print("Please try installing packages manually:")
                    print(f"  {sys.executable} -m pip install {' '.join(missing_packages)}")
                    return False
            else:
                print("\n❌ Setup incomplete. Missing packages need to be installed manually.")
                print(f"  Run: {sys.executable} -m pip install {' '.join(missing_packages)}")
                return False
        except (KeyboardInterrupt, EOFError):
            print("\n\n❌ Setup cancelled by user.")
            return False
    else:
        print("✓ All required packages are available!")
        print("✓ RevitMCP environment appears to be properly configured.")
        return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 