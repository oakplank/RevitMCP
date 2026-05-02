# RevitMCP: This script runs in pyRevit (IronPython). Use Python 2.7 syntax (no f-strings, use 'except Exception, e:').
"""
Revit UI Launcher & Manager for RevitMCP (pyRevit)

This script will be part of a pyRevit extension's lib folder and will be responsible for:
- Providing functions to start/stop the external CPython server.
- Detecting a suitable CPython environment.
"""

import subprocess
import os
import sys
import json
import tempfile
import datetime

# --- Configuration ---

# When this script (ui_manager.py) is in <ExtensionRoot>/lib/RevitMCP_UI/,
# __file__ is .../lib/RevitMCP_UI/ui_manager.py
# os.path.dirname(__file__) is .../lib/RevitMCP_UI/
# We need to get to .../lib/RevitMCP_ExternalServer/server.py

# Path to the root of the 'lib' directory for this extension.
# This assumes ui_manager.py is in lib/RevitMCP_UI/
LIB_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

EXTERNAL_SERVER_SCRIPT_PATH = os.path.join(LIB_ROOT, "RevitMCP_ExternalServer", "server.py")

# User-configurable CPython executable path.
# If this is set to a valid Python 3.7+ executable, it will be used.
# Otherwise, the script will attempt to find a suitable Python in PATH.
CPYTHON_EXECUTABLE_OVERRIDE = ""  # Leave empty for auto-detection

SERVER_PROCESS = None
DETECTED_CPYTHON_EXECUTABLE = None # Stores the path found by auto-detection or override

MIN_PYTHON_VERSION = (3, 7)
REQUIRED_PACKAGES = ["flask", "requests", "openai", "anthropic", "google-generativeai"]

# Define subprocess creation flags for suppressing console windows on Windows
subprocess_creation_flags = 0 # Default for non-Windows
if os.name == 'nt':
    try:
        subprocess_creation_flags = subprocess.CREATE_NO_WINDOW
    except AttributeError: # Fallback if constant not found (should be available in subprocess)
        subprocess_creation_flags = 0x08000000 # Also CREATE_NO_WINDOW

# --- Settings File Management ---
USER_DATA_DIR_NAME = "user_data"
SETTINGS_FILE_NAME = "revitmcp_settings.json"

def _get_settings_file_path():
    # Get user's Documents folder
    try:
        # For Python 2.7 (IronPython) getenv should work, but expanduser is more direct for user profile paths
        user_profile_dir = os.path.expanduser("~") # Gets C:\Users\YourUser
        if not user_profile_dir:
            raise EnvironmentError("Could not determine user profile directory.")
        
        # Construct path to Documents\RevitMCP\user_data
        # Standard path for Documents is usually directly under user_profile_dir + "Documents"
        # However, this can vary by OS language or user configuration. 
        # A more robust way for Documents is harder in pure Python 2.7 without specific libraries.
        # For simplicity and commonality, we'll use os.path.join(user_profile_dir, "Documents")
        # Fallback if "Documents" is not found directly under user_profile could be just user_profile_dir itself.
        
        documents_dir = os.path.join(user_profile_dir, "Documents")
        if not os.path.isdir(documents_dir): # Simple check, might not be robust enough for all systems
            print("[UI_MANAGER] Warning: Standard 'Documents' folder not found directly under user profile. Using profile root as fallback for RevitMCP data.")
            # Fallback to creating RevitMCP folder directly in user profile if Documents isn't where expected
            base_app_data_dir = os.path.join(user_profile_dir, "RevitMCP") 
        else:
            base_app_data_dir = os.path.join(documents_dir, "RevitMCP")
            
    except Exception as e:
        print("[UI_MANAGER] Error determining user documents directory: {}. Falling back to extension directory (might fail due to permissions).".format(e))
        # Fallback to original logic if user profile detection fails (though this is the problematic path)
        extension_root = os.path.abspath(os.path.join(LIB_ROOT, ".."))
        base_app_data_dir = extension_root # This would put user_data back in the extension dir

    user_data_dir = os.path.join(base_app_data_dir, USER_DATA_DIR_NAME)
    return os.path.join(user_data_dir, SETTINGS_FILE_NAME)

def _get_default_settings():
    # IronPython's datetime might not have isoformat() directly, build it manually
    now = datetime.datetime.now()
    timestamp = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:06d}".format(
        now.year, now.month, now.day,
        now.hour, now.minute, now.second, now.microsecond
    )

    return {
        "version": "1.0",
        "created": timestamp,
        "last_updated": timestamp,
        "setup": {
            "completed": False,
            "completion_date": None,
            "python_path": None,
            "packages_installed": [],
            "setup_version": "1.0" # Version of the setup logic itself
        },
        "api_keys": {
            "openai": "",
            "anthropic": "",
            "google": ""
        },
        "preferences": {
            "default_model": "echo_model", # A safe default
            "server_surface": "web", # web | mcp
            "auto_start_servers": False,
            "save_chat_history": True,
            "log_level": "INFO"
        },
        "chat_history": { # Basic structure, can be expanded
            "sessions": [],
            "max_sessions": 20,
            "max_messages_per_session": 50
        },
        "servers": {
            "external_server_port": 8000,
            "listener_port": 8001,
            "auto_install_packages": True # Matches current behavior of _check_python_environment
        }
    }

def _load_settings_file():
    settings_path = _get_settings_file_path()
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r') as f:
                settings = json.load(f)
                # Basic validation: check if it's a dictionary
                if not isinstance(settings, dict):
                    print("[UI_MANAGER] Settings file {} is corrupted (not a dict). Loading defaults.".format(settings_path))
                    return None # Indicates corruption or invalid format
                return settings
        except (IOError, ValueError) as e: # ValueError for JSON decoding errors
            print("[UI_MANAGER] Error loading settings file {}: {}. Loading defaults.".format(settings_path, e))
            return None # Indicates error loading
    return None # File doesn't exist

def _save_settings_file(settings_data):
    settings_path = _get_settings_file_path()
    user_data_dir = os.path.dirname(settings_path)

    try:
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir)
            print("[UI_MANAGER] Created user_data directory: {}".format(user_data_dir))

        # Update 'last_updated' timestamp
        now = datetime.datetime.now()
        settings_data["last_updated"] = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:06d}".format(
            now.year, now.month, now.day,
            now.hour, now.minute, now.second, now.microsecond
        )

        with open(settings_path, 'w') as f:
            json.dump(settings_data, f, indent=2, sort_keys=True) # indent for readability
        print("[UI_MANAGER] Settings saved to {}".format(settings_path))
        return True
    except (IOError, OSError) as e:
        print("[UI_MANAGER] Error saving settings file {}: {}".format(settings_path, e))
        # Assuming show_alert is defined elsewhere and accessible
        # If not, this line will cause an error. For now, keeping it as per your existing style.
        # Consider passing show_alert as a dependency if it's not globally available.
        try:
            show_alert("Error saving settings: {}".format(e), title="RevitMCP Settings Error")
        except NameError:
            print("[UI_MANAGER] show_alert function not found while trying to report save error.")
        return False

def get_or_create_settings():
    """
    Loads settings from revitmcp_settings.json.
    If the file doesn't exist or is invalid, creates it with default values.
    """
    settings = _load_settings_file()
    if settings is None: # File didn't exist, was empty, or corrupted
        print("[UI_MANAGER] Generating default settings file.")
        settings = _get_default_settings()
        _save_settings_file(settings) # Save the newly created default settings
    else:
        # Lightweight migration for older settings files.
        preferences = settings.get("preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
            settings["preferences"] = preferences
        if "server_surface" not in preferences:
            preferences["server_surface"] = "web"
            _save_settings_file(settings)
    return settings

# --- End Settings File Management ---

# --- Helper Functions ---

def _is_windows():
    return os.name == 'nt'

def _check_python_environment(python_exe):
    """Checks if the given Python executable meets version and package requirements."""
    if not python_exe or not os.path.exists(python_exe):
        return False, "Python executable not found."

    try: 
        # Check version
        cmd_version = [python_exe, "-c", "import sys; import json; print(json.dumps(sys.version_info))"]
        proc_version = subprocess.Popen(cmd_version, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess_creation_flags)
        stdout_bytes, stderr_bytes = proc_version.communicate()
        
        if proc_version.returncode != 0:
            stderr_decoded = stderr_bytes.decode(sys.getfilesystemencoding() or 'utf-8', errors='ignore').strip()
            return False, "Error checking Python version ({}): {}".format(python_exe, stderr_decoded or "No stderr output")

        version_out_decoded = stdout_bytes.decode(sys.getfilesystemencoding() or 'utf-8', errors='ignore').strip()
        version_info = json.loads(version_out_decoded)
        py_version = tuple(version_info[:3])

        if py_version < MIN_PYTHON_VERSION:
            return False, "Python version {}.{}.{} is older than required {}.{}.{}".format(
                py_version[0], py_version[1], py_version[2],
                MIN_PYTHON_VERSION[0], MIN_PYTHON_VERSION[1], MIN_PYTHON_VERSION[2] if len(MIN_PYTHON_VERSION) > 2 else ''
            )

        # Check and install packages automatically
        success, msg = _check_and_install_packages(python_exe, REQUIRED_PACKAGES)
        if not success:
            return False, "Package check/installation failed: {}".format(msg)
            
        # If all checks passed
        return True, "Valid: {} (Version: {}.{}.{})".format(
            python_exe, py_version[0], py_version[1], py_version[2]
        )

    except (IOError, OSError) as e:
        return False, "OS error when trying to run {}: {}".format(python_exe, str(e))
    except ValueError as e:
        return False, "Error parsing version output from {}: {}".format(python_exe, str(e))
    except Exception as e:
        return False, "Unexpected error checking {}: {}".format(python_exe, str(e))

def find_cpython_executable():
    """
    Attempts to find a suitable CPython executable.
    1. Uses CPYTHON_EXECUTABLE_OVERRIDE if set and valid.
    2. Searches PATH for common Python commands, prioritizing system installs.
    Returns the path to a suitable executable or None.
    """
    global DETECTED_CPYTHON_EXECUTABLE
    if DETECTED_CPYTHON_EXECUTABLE: # Already found
        return DETECTED_CPYTHON_EXECUTABLE

    import shutil # Ensure shutil is imported

    # 1. Check override
    if CPYTHON_EXECUTABLE_OVERRIDE and CPYTHON_EXECUTABLE_OVERRIDE != "PLEASE_CONFIGURE_THIS":
        is_valid, msg = _check_python_environment(CPYTHON_EXECUTABLE_OVERRIDE)
        if is_valid:
            print("Using configured CPYTHON_EXECUTABLE_OVERRIDE: {}".format(msg))
            DETECTED_CPYTHON_EXECUTABLE = CPYTHON_EXECUTABLE_OVERRIDE
            return DETECTED_CPYTHON_EXECUTABLE
        else:
            print("Warning: CPYTHON_EXECUTABLE_OVERRIDE ('{}') is not valid or does not meet requirements: {}".format(CPYTHON_EXECUTABLE_OVERRIDE, msg))
            print("Attempting to find Python in PATH...")

    # 2. Search PATH with improved strategy
    common_names = ["python3", "python"]
    if _is_windows():
        common_names = ["python.exe", "python3.exe"] + common_names 

    all_found_pythons = []
    
    for name in common_names:
        found_paths_for_name = []
        try:
            found_path = shutil.which(name)
            if found_path:
                found_paths_for_name.append(found_path)
        except AttributeError:
            pass
            
        if _is_windows():
            try:
                command_str = 'where {}'.format(name)
                output_bytes = subprocess.check_output(command_str, shell=True, creationflags=subprocess_creation_flags)
                output_str = output_bytes.decode(sys.getfilesystemencoding() or 'utf-8', errors='ignore')
                
                lines = output_str.strip().splitlines()
                for line in lines:
                    path = line.strip()
                    if os.path.exists(path) and path not in found_paths_for_name:
                        found_paths_for_name.append(path)
                        
            except (subprocess.CalledProcessError, IOError, OSError):
                pass
        
        for path in found_paths_for_name:
            if path not in [p[1] for p in all_found_pythons]:  # Avoid duplicates
                priority = 1 if 'WindowsApps' in path else 0
                all_found_pythons.append((priority, path))
    
    all_found_pythons.sort(key=lambda x: x[0])
    
    for priority, python_path in all_found_pythons:
        print("Found Python at '{}'. Checking environment...".format(python_path))
        is_valid, msg = _check_python_environment(python_path)
        if is_valid:
            print("Using detected Python: {}".format(msg))
            DETECTED_CPYTHON_EXECUTABLE = python_path
            return DETECTED_CPYTHON_EXECUTABLE
        else:
            print("Skipping '{}': {}".format(python_path, msg))
    
    err_msg_parts = [
        "Error: Could not find a suitable CPython {}.{}+ executable.".format(MIN_PYTHON_VERSION[0], MIN_PYTHON_VERSION[1]),
        "Please do one of the following:",
        "1. Install Python {}.{} or newer from python.org".format(MIN_PYTHON_VERSION[0], MIN_PYTHON_VERSION[1]),
        "2. Ensure Python is in your system PATH",
        "3. Manually set the 'CPYTHON_EXECUTABLE_OVERRIDE' variable in the RevitMCP_UI/ui_manager.py script"
    ]
    full_err_msg = '\n'.join(err_msg_parts)
    print(full_err_msg)
    show_alert(full_err_msg, title="RevitMCP Setup Error")
    DETECTED_CPYTHON_EXECUTABLE = None
    return None

def get_pyrevit_forms():
    """Safely import and return pyrevit.forms if available."""
    try:
        from pyrevit import forms
        return forms
    except ImportError:
        return None

def show_alert(message, title="RevitMCP"):
    forms = get_pyrevit_forms()
    if forms:
        forms.alert(message, title=title)
    else:
        print("[{}] {}".format(title, message))

def start_external_server():
    global SERVER_PROCESS
    
    print("[UI_MANAGER] Ensuring settings file is available...")
    current_settings = get_or_create_settings()
    if not current_settings:
        show_alert("Critical error: Could not load or create settings file. Server cannot start.", title="RevitMCP Settings Error")
        return

    print("[UI_MANAGER] Attempting to start external server...")
    python_exe_to_use = find_cpython_executable()
    if not python_exe_to_use:
        print("[UI_MANAGER] Python executable not found or configured.") 
        show_alert("CPython executable not found or not configured correctly. Please check logs/console and configure 'CPYTHON_EXECUTABLE_OVERRIDE' in ui_manager.py if needed.", title="RevitMCP Error")
        return

    if not os.path.exists(EXTERNAL_SERVER_SCRIPT_PATH):
        error_msg = "External server script not found: {}".format(EXTERNAL_SERVER_SCRIPT_PATH)
        print("[UI_MANAGER] {}".format(error_msg))
        show_alert(error_msg, title="RevitMCP Error")
        return

    if SERVER_PROCESS is None or SERVER_PROCESS.poll() is not None:
        preferred_surface = current_settings.get("preferences", {}).get("server_surface", "web")
        if preferred_surface not in ["web", "mcp"]:
            print("[UI_MANAGER] Invalid server_surface '{}'. Falling back to 'web'.".format(preferred_surface))
            preferred_surface = "web"

        launch_cmd = [python_exe_to_use, EXTERNAL_SERVER_SCRIPT_PATH, "--surface", preferred_surface]
        print("[UI_MANAGER] Starting RevitMCP External Server from: {}".format(EXTERNAL_SERVER_SCRIPT_PATH))
        print("[UI_MANAGER] Using Python executable: {}".format(python_exe_to_use))
        print("[UI_MANAGER] Selected server surface: {}".format(preferred_surface))
        try:
            env = os.environ.copy()
            print("[UI_MANAGER] Starting Popen with command: {}".format(' '.join(launch_cmd)))
            SERVER_PROCESS = subprocess.Popen(
                launch_cmd,
                env=env,
            )
            success_msg = "[UI_MANAGER] RevitMCP External Server process started (surface: {}). PID: {}. Its console window should appear.".format(preferred_surface, SERVER_PROCESS.pid)
            print(success_msg)
            show_alert(success_msg)

        except FileNotFoundError:
            error_msg = "Error: The Python executable '{}' was not found. This should not happen if find_cpython_executable worked.".format(python_exe_to_use)
            print("[UI_MANAGER] {}".format(error_msg))
            show_alert(error_msg, title="RevitMCP Error")
            SERVER_PROCESS = None
        except Exception as e:
            error_msg = "[UI_MANAGER] Failed to start RevitMCP External Server with Popen: {} (Type: {})".format(e, type(e).__name__)
            import traceback
            tb_str = traceback.format_exc()
            print(error_msg + "\nTraceback:\n" + tb_str)
            show_alert(error_msg, title="RevitMCP Error - Popen Failed")
            SERVER_PROCESS = None
    else:
        running_msg = "[UI_MANAGER] RevitMCP External Server is already running."
        print(running_msg)
        show_alert(running_msg)

def stop_external_server():
    global SERVER_PROCESS
    if SERVER_PROCESS and SERVER_PROCESS.poll() is None:
        print("Stopping RevitMCP External Server...")
        SERVER_PROCESS.terminate()
        try:
            SERVER_PROCESS.wait(timeout=5)
            stopped_msg = "RevitMCP External Server stopped."
            print(stopped_msg)
            show_alert(stopped_msg)
        except subprocess.TimeoutExpired:
            print("Server did not terminate in time, killing...")
            SERVER_PROCESS.kill()
            killed_msg = "RevitMCP External Server forcefully stopped."
            print(killed_msg)
            show_alert(killed_msg)
        SERVER_PROCESS = None
    else:
        not_running_msg = "RevitMCP External Server is not running."
        print(not_running_msg)
        show_alert(not_running_msg)

def _install_packages_automatically(python_exe, missing_packages):
    """Attempts to install missing packages using pip."""
    if not missing_packages:
        return True, "No packages to install"
    
    print("Attempting to install missing packages: {}".format(', '.join(missing_packages)))
    show_alert("Installing required packages: {}. This may take a moment...".format(', '.join(missing_packages)), 
               title="RevitMCP Setup")
    
    try:
        requirements_file = os.path.join(LIB_ROOT, "RevitMCP_ExternalServer", "requirements.txt")
        
        if os.path.exists(requirements_file):
            cmd = [python_exe, "-m", "pip", "install", "-r", requirements_file, "--user", "--quiet"]
            print("Installing from requirements.txt: {}".format(requirements_file))
        else:
            cmd = [python_exe, "-m", "pip", "install"] + missing_packages + ["--user", "--quiet"]
            print("Installing individual packages: {}".format(' '.join(missing_packages)))
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess_creation_flags)
        stdout_bytes, stderr_bytes = proc.communicate()
        
        if proc.returncode == 0:
            print("Successfully installed packages!")
            show_alert("Successfully installed required packages!", title="RevitMCP Setup")
            return True, "Packages installed successfully"
        else:
            stderr_decoded = stderr_bytes.decode(sys.getfilesystemencoding() or 'utf-8', errors='ignore').strip()
            error_msg = "Failed to install packages. Error: {}".format(stderr_decoded)
            print(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = "Exception while installing packages: {}".format(e)
        print(error_msg)
        return False, error_msg

PACKAGE_TO_IMPORT_MAP = {
    "google-generativeai": "google.generativeai"
    # Add other mappings if needed in the future, e.g., "package-name": "actual_import_name"
}

def _check_and_install_packages(python_exe, packages):
    """Check for packages and install them if missing."""
    missing_packages = []
    
    for pkg in packages:
        pkg_name_for_import = PACKAGE_TO_IMPORT_MAP.get(pkg, pkg.replace('-', '_'))
        script_content = "try:\n    import {}\nexcept ImportError:\n    exit(1)".format(pkg_name_for_import)
        temp_file_handle, temp_file_path = tempfile.mkstemp(suffix=".py")
        
        try:
            os.close(temp_file_handle)
            with open(temp_file_path, 'w') as f:
                f.write(script_content)
            
            proc = subprocess.Popen([python_exe, temp_file_path], 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  creationflags=subprocess_creation_flags)
            proc.communicate()
            
            if proc.returncode != 0:
                missing_packages.append(pkg)
                
        except Exception as e:
            print("Error checking package {}: {}".format(pkg, e))
            missing_packages.append(pkg)
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
    
    if missing_packages:
        print("Missing packages: {}".format(', '.join(missing_packages)))
        success, msg = _install_packages_automatically(python_exe, missing_packages)
        if not success:
            return False, msg
    
    return True, "All packages available"

# Test block for when script is run directly (e.g. for development)
# This part won't run when imported by pyRevit button scripts.
if __name__ == "__main__":
    print("RevitMCP UI Manager - Direct Test Mode (from within lib/RevitMCP_UI)")
    print("---------------------------------------------------------------------")
    print("LIB_ROOT: {}".format(LIB_ROOT))
    print("External Server Script: {}".format(EXTERNAL_SERVER_SCRIPT_PATH))
    print("---------------------------------------------------------------------")
    print("Attempting to find suitable CPython...")
    
    found_python = find_cpython_executable()
    if found_python:
        print("Found suitable Python for testing: {}".format(found_python))
        print("To test server start/stop, uncomment the lines below.")
        # print("\n--- Simulating Server Start ---")
        # start_external_server()
        # if SERVER_PROCESS:
        #     print("Server presumably running (PID: {}). Check console output from external server.".format(SERVER_PROCESS.pid))
        #     input("Press Enter to stop server...")
        #     stop_external_server()
        # else:
        #     print("Server did not start. Check error messages above.")
    else:
        print("Could not find a suitable Python executable for testing the server start.")
        print("Please configure CPYTHON_EXECUTABLE_OVERRIDE or ensure Python 3.7+ with Flask & Requests is in PATH.")

    print("\nTest mode finished.")

