# RevitMCP: Project-related HTTP routes
# -*- coding: UTF-8 -*-

from pyrevit import routes, script

def register_routes(api):
    """Register all project-related routes with the API"""
    
    @api.route('/project_info', methods=['GET'])
    def handle_get_project_info(request):
        """
        Handles GET requests to /revit-mcp-v1/project_info
        Returns basic information about the current Revit project.
        
        Args:
            request (routes.Request): Object containing request details.
        """
        route_logger = script.get_logger()
        
        try:
            # __revit__ is a global object provided by pyRevit in the script's execution context.
            # It gives access to the Revit UIApplication object.
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                route_logger.error("Error accessing project info: No active UI document.")
                return routes.Response(status=503, data={"error": "No active Revit UI document found. Is a project open?"})

            doc = current_uiapp.ActiveUIDocument.Document
            if not doc:
                route_logger.error("Error accessing project info: No active document.")
                return routes.Response(status=503, data={"error": "No active Revit project document found."})
                
            project_info = doc.ProjectInformation
            if not project_info:
                route_logger.error("Error accessing project info: ProjectInformation is not available.")
                return routes.Response(status=500, data={"error": "Could not retrieve ProjectInformation from the active document."})

            data_to_return = {
                "project_name": project_info.Name,
                "project_number": project_info.Number,
                "organization_name": project_info.OrganizationName,
                "building_name": project_info.BuildingName,
                "client_name": project_info.ClientName,
                "status": project_info.Status,
                "file_path": doc.PathName,
            }
            route_logger.info("Successfully retrieved project info for: {}".format(doc.PathName or "Unsaved Project"))
            return data_to_return
            
        except AttributeError as ae:
            route_logger.error("Error accessing project info (AttributeError): {}. Is a project open and loaded?".format(ae), exc_info=True)
            return routes.Response(status=503, data={"error": "Error accessing Revit project data. A project might not be open or fully loaded.", "details": str(ae)})
        except Exception as e:
            route_logger.critical("Critical error processing /project_info: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error retrieving project info.", "details": str(e)}) 