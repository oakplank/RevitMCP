# RevitMCP: This script runs in pyRevit (IronPython).
# -*- coding: UTF-8 -*-
"""
Defines the pyRevit Routes API for RevitMCP.
This handles HTTP requests on the Revit side, replacing the old listener.py.
"""

from pyrevit import routes, script
import json # For parsing request data if needed, though routes might handle it

# Import RevitMCP Tool modules
# Assuming they are in a subfolder RevitMCP_Tools relative to the extension's lib folder,
# or that pyRevit's path management makes them discoverable.
# If RevitMCP_Tools is at the same level as this file (in lib), the import is simpler.
try:
    from RevitMCP_Tools import project_info_tool
    from RevitMCP_Tools import element_selection_tools
    from RevitMCP_Tools import view_export_tool
    # from RevitMCP_Tools import revit_api_utils # If needed directly here, though tools use it
except ImportError as e:
    # This logger might not be fully configured if startup.py hasn't run script.get_logger() yet
    # but it's better than just print for pyRevit standard practice.
    initial_logger = script.get_logger()
    if initial_logger:
        initial_logger.error("Error importing RevitMCP_Tools in mcp_api_routes.py: {}. Check paths.".format(e))
    else:
        print("ERROR (mcp_api_routes.py): Error importing RevitMCP_Tools: {}. Check paths.".format(e))
    # Define stubs if imports fail, to prevent further load errors, though API will be non-functional
    class MockTool:
        def __getattr__(self, name):
            def mock_method(*args, **kwargs):
                return {"status": "error", "message": "Tool module not loaded: {}".format(name)}, 500
            return mock_method
    project_info_tool = MockTool()
    element_selection_tools = MockTool()
    view_export_tool = MockTool()

# Get a logger instance
logger = script.get_logger()
if not logger: # Fallback if get_logger returns None (e.g. during very early init)
    class PrintLogger:
        def info(self, msg): print("INFO: " + str(msg))
        def error(self, msg, exc_info=None): print("ERROR: " + str(msg) + (" (see console for exc)" if exc_info else ""))
        def warning(self, msg): print("WARN: " + str(msg))
        def debug(self, msg): print("DEBUG: " + str(msg))
    logger = PrintLogger()

# Define the API name (must be unique)
# This name will be part of the URL: e.g., http://localhost:48884/revit-mcp-v1/...
API_NAME = 'revit-mcp-v1'
try:
    mcp_api = routes.API(API_NAME)
    logger.info("pyRevit Routes API '{}' initialized for RevitMCP.".format(API_NAME))
except Exception as e_api_init:
    logger.error("Failed to initialize pyRevit Routes API '{}': {}".format(API_NAME, e_api_init), exc_info=True)
    # If API fails to init, subsequent @route decorators will fail. Define a dummy mcp_api.
    class DummyAPI:
        def route(self, *args, **kwargs):
            def decorator(func):
                logger.error("Attempted to register route for offline API ({}). Func: {}".format(API_NAME, func.__name__))
                return func # Return original func, it just won't be a route
            return decorator
    mcp_api = DummyAPI()


@mcp_api.route('/project_info', methods=['GET'])
def api_get_project_info(doc, app):
    """Handles /project_info GET requests."""
    logger.info("API Route Reached: GET /project_info (doc: {}, app: {})".format(doc is not None, app is not None))
    try:
        project_data = project_info_tool.get_project_information(doc, app)
        # get_project_information should return a dict. If it includes an error key, pass it through.
        if isinstance(project_data, dict) and "error" in project_data:
            logger.warning("Error reported by project_info_tool: {}".format(project_data.get("error")))
            # Assuming the tool sets its own appropriate status code if it formats an error response
            # For now, let's standardize to 500 if tool has error, or use tool's code if present
            status = project_data.get("status_code", 500) # Hypothetical status_code from tool
            return routes.make_response(data=project_data, status=status)
        
        logger.info("Successfully retrieved project info.")
        return routes.make_response(data=project_data, status=200)
    except Exception as e:
        logger.error("Exception in /project_info route: {}".format(e), exc_info=True)
        return routes.make_response(data={"status": "error", "message": "Server error in /project_info: {}".format(e)}, status=500)

@mcp_api.route('/select_elements_by_id', methods=['POST'])
def api_select_elements_by_id(request, doc, uidoc):
    """Handles /select_elements_by_id POST requests."""
    logger.info("API Route Reached: POST /select_elements_by_id (doc: {}, uidoc: {})".format(doc is not None, uidoc is not None))
    try:
        payload = request.data # .data assumes content type is parsed (e.g. application/json)
        if not isinstance(payload, dict):
            logger.warning("/select_elements_by_id: request.data was not a dict. Type: {}".format(type(payload)))
            # Try to parse if it's a string that looks like JSON (pyrevit routes might give raw string for some CTs)
            if isinstance(payload, basestring): # basestring for IronPython str/unicode
                try:
                    payload = json.loads(payload)
                except ValueError as ve:
                    logger.error("/select_elements_by_id: Failed to parse payload string as JSON: {}".format(ve))
                    return routes.make_response(data={"status": "error", "message": "Invalid JSON payload string."}, status=400)
            else:
                 return routes.make_response(data={"status": "error", "message": "Payload is not a valid JSON object."}, status=400)
        
        element_ids_list = payload.get("element_ids")

        if element_ids_list is None: # Check for presence of the key
            logger.warning("/select_elements_by_id: Missing 'element_ids' in payload.")
            return routes.make_response(data={"status": "error", "message": "Missing 'element_ids' in request payload."}, status=400)
        
        # Call the existing tool function
        # select_elements expects (doc, uidoc, element_id_strings, logger)
        # and returns (response_dict, status_code)
        response_data, status_code = element_selection_tools.select_elements(doc, uidoc, element_ids_list, logger)
        logger.info("/select_elements_by_id: Tool call completed. Status: {}, Response: {}".format(status_code, response_data.get('message','N/A')))
        return routes.make_response(data=response_data, status=status_code)
    except Exception as e:
        logger.error("Exception in /select_elements_by_id route: {}".format(e), exc_info=True)
        return routes.make_response(data={"status": "error", "message": "Server error in /select_elements_by_id: {}".format(e)}, status=500)

@mcp_api.route('/select_elements_by_category', methods=['POST'])
def api_select_elements_by_category(request, doc, uidoc):
    """Handles /select_elements_by_category POST requests."""
    logger.info("API Route Reached: POST /select_elements_by_category (doc: {}, uidoc: {})".format(doc is not None, uidoc is not None))
    try:
        payload = request.data
        if not isinstance(payload, dict):
            logger.warning("/select_elements_by_category: request.data was not a dict. Type: {}".format(type(payload)))
            if isinstance(payload, basestring):
                try:
                    payload = json.loads(payload)
                except ValueError as ve:
                    logger.error("/select_elements_by_category: Failed to parse payload string as JSON: {}".format(ve))
                    return routes.make_response(data={"status": "error", "message": "Invalid JSON payload string."}, status=400)
            else:
                return routes.make_response(data={"status": "error", "message": "Payload is not a valid JSON object."}, status=400)
        
        category_name = payload.get("category_name")

        if not category_name:
            logger.warning("/select_elements_by_category: Missing 'category_name' in payload.")
            return routes.make_response(data={"status": "error", "message": "Missing 'category_name' in request payload."}, status=400)
        
        # select_by_category expects (doc, uidoc, category_name_str, logger)
        # and returns (response_dict, status_code)
        response_data, status_code = element_selection_tools.select_by_category(doc, uidoc, category_name, logger)
        logger.info("/select_elements_by_category: Tool call completed. Status: {}, Response: {}".format(status_code, response_data.get('message','N/A')))
        return routes.make_response(data=response_data, status=status_code)
    except Exception as e:
        logger.error("Exception in /select_elements_by_category route: {}".format(e), exc_info=True)
        return routes.make_response(data={"status": "error", "message": "Server error in /select_elements_by_category: {}".format(e)}, status=500)

@mcp_api.route('/export_revit_view', methods=['POST'])
def api_export_revit_view(request, doc):
    """Handles /export_revit_view POST requests."""
    logger.info("API Route Reached: POST /export_revit_view (doc: {})".format(doc is not None))
    try:
        payload = request.data
        if not isinstance(payload, dict):
            logger.warning("/export_revit_view: request.data was not a dict. Type: {}".format(type(payload)))
            if isinstance(payload, basestring):
                try:
                    payload = json.loads(payload)
                except ValueError as ve:
                    logger.error("/export_revit_view: Failed to parse payload string as JSON: {}".format(ve))
                    return routes.make_response(data={"status": "error", "message": "Invalid JSON payload string."}, status=400)
            else:
                return routes.make_response(data={"status": "error", "message": "Payload is not a valid JSON object."}, status=400)
        
        view_name = payload.get("view_name")

        if not view_name:
            logger.warning("/export_revit_view: Missing 'view_name' in payload.")
            return routes.make_response(data={"status": "error", "message": "Missing 'view_name' in request payload."}, status=400)
        
        # export_named_view expects (doc, view_name_to_export, logger)
        # and returns (response_dict, status_code)
        response_data, status_code = view_export_tool.export_named_view(doc, view_name, logger)
        logger.info("/export_revit_view: Tool call completed. Status: {}, Response: {}".format(status_code, response_data.get('message','N/A')))
        return routes.make_response(data=response_data, status=status_code)
    except Exception as e:
        logger.error("Exception in /export_revit_view route: {}".format(e), exc_info=True)
        return routes.make_response(data={"status": "error", "message": "Server error in /export_revit_view: {}".format(e)}, status=500)

logger.info("RevitMCP API routes defined in mcp_api_routes.py. Waiting for pyRevit Routes Server to pick them up.") 