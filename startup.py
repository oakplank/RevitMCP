# startup.py - Lightweight coordinator

from pyrevit import routes, script
from pyrevit import DB
import sys
import os

logger = script.get_logger()
logger.info("RevitMCP startup script executing...")

try:
    # Initialize API namespace
    api = routes.API("revit-mcp-v1")
    logger.info("pyRevit routes API 'revit-mcp-v1' initialized.")

    # Add extension directory to Python path
    extension_dir = os.path.dirname(__file__)
    lib_dir = os.path.join(extension_dir, 'lib')
    routes_dir = os.path.join(lib_dir, 'routes')
    
    logger.info("Extension directory: {}".format(extension_dir))
    logger.info("Lib directory: {}".format(lib_dir))
    logger.info("Routes directory: {}".format(routes_dir))
    logger.info("Routes directory exists: {}".format(os.path.exists(routes_dir)))
    
    if lib_dir not in sys.path:
        sys.path.append(lib_dir)
        logger.info("Added lib directory to Python path: {}".format(lib_dir))

    # Import and register route modules
    try:
        logger.info("Attempting to import route modules...")
        from routes import (
            project_routes,
            sheet_routes,
            element_routes,
            schema_routes
        )
        logger.info("Route modules imported successfully")
        
        # Register each module's routes
        project_routes.register_routes(api)
        logger.info("Project routes registered successfully")
        
        sheet_routes.register_routes(api)
        logger.info("Sheet routes registered successfully")
        
        element_routes.register_routes(api)
        logger.info("Element routes registered successfully")

        schema_routes.register_routes(api)
        logger.info("Schema routes registered successfully")
        
    except ImportError as ie:
        logger.error("Error importing route modules: {}".format(ie), exc_info=True)
        logger.info("Falling back to minimal routes...")
        
        # Minimal fallback - just project_info route for testing
        @api.route('/project_info', methods=['GET'])
        def handle_get_project_info_fallback(request):
            route_logger = script.get_logger()
            try:
                current_uiapp = __revit__
                if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                    return routes.Response(status=503, data={"error": "No active UI document"})
                doc = current_uiapp.ActiveUIDocument.Document
                project_info = doc.ProjectInformation
                return {
                    "project_name": project_info.Name,
                    "project_number": project_info.Number,
                    "file_path": doc.PathName,
                    "fallback_mode": True
                }
            except Exception as e:
                return routes.Response(status=500, data={"error": str(e)})
        
        logger.info("Fallback route registered")
        
    logger.info("All route modules loaded successfully")

except Exception as e:
    logger.error("Error during RevitMCP startup.py execution: {}".format(e), exc_info=True)

logger.info("RevitMCP startup script finished.") 
