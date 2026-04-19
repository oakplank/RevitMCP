# startup.py - Lightweight coordinator

from pyrevit import routes, script
import sys
import os

# ---- File logger for debugging (written to Documents/RevitMCP/) ----
import traceback

_log_dir = os.path.join(os.path.expanduser("~"), "Documents", "RevitMCP", "server_logs")
_log_path = os.path.join(_log_dir, "pyrevit_startup.log")

def _flog(msg):
    try:
        if not os.path.exists(_log_dir):
            os.makedirs(_log_dir)
        with open(_log_path, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass

_flog("=" * 60)
_flog("RevitMCP startup.py executing...")

logger = script.get_logger()
if logger:
    logger.info("RevitMCP startup script executing...")

try:
    # Initialize API namespace
    api = routes.API("revit-mcp-v1")
    _flog("API 'revit-mcp-v1' created OK")

    # Resolve extension directory safely (handles missing __file__ in IronPython)
    try:
        _this_file = __file__
        extension_dir = os.path.dirname(os.path.abspath(_this_file))
    except NameError:
        # __file__ not available - search known paths
        _flog("__file__ not defined, searching known paths...")
        _candidates = [
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                         "pyRevit", "Extensions", "RevitMCP.extension"),
        ]
        extension_dir = None
        for _c in _candidates:
            if os.path.exists(_c):
                extension_dir = _c
                break
        if extension_dir is None:
            raise RuntimeError("Cannot locate RevitMCP.extension directory")

    lib_dir    = os.path.join(extension_dir, "lib")
    routes_dir = os.path.join(lib_dir, "routes")

    _flog("extension_dir: {}".format(extension_dir))
    _flog("lib_dir exists: {}".format(os.path.exists(lib_dir)))
    _flog("routes_dir exists: {}".format(os.path.exists(routes_dir)))

    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
        _flog("Added lib_dir to sys.path")

    # ---- Register route modules one by one ----
    registered = []
    failed     = []

    def _try_register(module_name, register_fn):
        try:
            register_fn(api)
            registered.append(module_name)
            _flog("  [OK] {}".format(module_name))
        except Exception as _e:
            failed.append(module_name)
            _flog("  [FAIL] {}: {}".format(module_name, traceback.format_exc()))

    try:
        from routes import project_routes
        _flog("Imported project_routes OK")
        _try_register("project_routes", project_routes.register_routes)
    except Exception as _e:
        _flog("Import project_routes FAILED: {}".format(traceback.format_exc()))
        failed.append("project_routes")

    try:
        from routes import sheet_routes
        _flog("Imported sheet_routes OK")
        _try_register("sheet_routes", sheet_routes.register_routes)
    except Exception as _e:
        _flog("Import sheet_routes FAILED: {}".format(traceback.format_exc()))
        failed.append("sheet_routes")

    try:
        from routes import element_routes
        _flog("Imported element_routes OK")
        _try_register("element_routes", element_routes.register_routes)
    except Exception as _e:
        _flog("Import element_routes FAILED: {}".format(traceback.format_exc()))
        failed.append("element_routes")

    try:
        from routes import schema_routes
        _flog("Imported schema_routes OK")
        _try_register("schema_routes", schema_routes.register_routes)
    except Exception as _e:
        _flog("Import schema_routes FAILED: {}".format(traceback.format_exc()))
        failed.append("schema_routes")

    _flog("Registered: {}".format(registered))
    _flog("Failed:     {}".format(failed))

    # ---- Minimal fallback if everything failed ----
    if not registered:
        _flog("All modules failed - registering fallback /project_info route")
        try:
            @api.route('/project_info', methods=['GET'])
            def handle_get_project_info_fallback(request):
                try:
                    uiapp = __revit__
                    doc = uiapp.ActiveUIDocument.Document
                    pi = doc.ProjectInformation
                    return {
                        "project_name": pi.Name,
                        "project_number": pi.Number,
                        "file_path": doc.PathName,
                        "fallback_mode": True
                    }
                except Exception as _ex:
                    return routes.Response(status=500, data={"error": str(_ex)})
            _flog("Fallback route /project_info registered OK")
        except Exception as _fe:
            _flog("Fallback route FAILED: {}".format(traceback.format_exc()))

except Exception as e:
    _flog("CRITICAL ERROR in startup.py: {}".format(traceback.format_exc()))
    if logger:
        logger.error("RevitMCP startup error: {}".format(e))

_flog("startup.py finished.")
if logger:
    logger.info("RevitMCP startup script finished.")
