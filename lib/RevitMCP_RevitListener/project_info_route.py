# Required imports
from pyrevit import routes
from pyrevit import script
# Import DB for Revit API access if you need to be explicit,
# otherwise __revit__ global will provide access.
# from pyrevit import DB
# from Autodesk.Revit.DB import * # Alternative direct Revit API import

# Define an API namespace. This should match the one your external server is calling.
# The full URL will be http://<server_address>:<port>/<api_name>/<route_pattern>
api = routes.API("revit-mcp-v1")

# Define the route for '/project_info' using a decorator
@api.route('/project_info', methods=['GET'])
def handle_get_project_info(request_data):
    """
    Handles GET requests to /revit-mcp-v1/project_info
    Returns basic information about the current Revit project.
    
    Args:
        request_data (routes.Request): Object containing request details. Not used in this simple GET.
    """
    logger = script.get_logger()
    
    try:
        # __revit__ is a global object provided by pyRevit in the script's execution context.
        # It gives access to the Revit UIApplication object.
        if not hasattr(__revit__, 'ActiveUIDocument') or not __revit__.ActiveUIDocument:
            logger.error("Error accessing project info: No active UI document.")
            return routes.Response(status=503, data={"error": "No active Revit UI document found. Is a project open?"})

        doc = __revit__.ActiveUIDocument.Document
        if not doc:
            logger.error("Error accessing project info: No active document.")
            return routes.Response(status=503, data={"error": "No active Revit project document found."})
            
        project_info = doc.ProjectInformation
        if not project_info:
            logger.error("Error accessing project info: ProjectInformation is not available.")
            return routes.Response(status=500, data={"error": "Could not retrieve ProjectInformation from the active document."})

        data_to_return = {
            "project_name": project_info.Name,
            "project_number": project_info.Number,
            "organization_name": project_info.OrganizationName,
            "building_name": project_info.BuildingName,
            "client_name": project_info.ClientName,
            "status": project_info.Status,
            "file_path": doc.PathName,
            # Add any other project information you need
        }
        logger.info("Successfully retrieved project info for: {}".format(doc.PathName or "Unsaved Project"))
        # pyRevit routes expects a dictionary or a routes.Response object for the return.
        # A dictionary will be automatically converted to a JSON response with a 200 OK status.
        return data_to_return
    except AttributeError as ae:
        # This can happen if no project is open or if the Revit API structure is unexpected
        logger.error("Error accessing project info (AttributeError): {}. Is a project open and loaded?".format(ae))
        return routes.Response(status=503, data={"error": "Error accessing Revit project data. A project might not be open or fully loaded.", "details": str(ae)})
    except Exception as e:
        logger.critical("Critical error processing /project_info: {}".format(e), exc_info=True)
        # Return an error response
        return routes.Response(status=500, data={"error": "Internal server error retrieving project info.", "details": str(e)})

# Example of how to activate the server if it's not done automatically by pyRevit
# This might be better placed in a script that runs on Revit startup for your extension,
# or if your "Launch RevitMCP.pushbutton" handles it.
# For now, this is commented out as pyRevit often handles server activation.
# if __name__ == '__main__':
#     try:
#         server = routes.get_active_server()
#         if not server:
#             logger.info("pyRevit routes server not active. Attempting to activate...")
#             routes.activate_server()
#             logger.info("pyRevit routes server activated.")
#         else:
#             logger.info("pyRevit routes server is already active.")
#     except Exception as e:
#         logger.error("Failed to ensure pyRevit routes server is active: {}".format(e))

# You can define more routes in this file if they belong to the same 'revit-mcp-v1' API
# e.g.
# @api.route('/another_endpoint', methods=['POST'])
# def handle_another_endpoint(request_data):
#     # ... your logic ...
#     return {"message": "Processed another_endpoint"} 