# RevitMCP: Project-related HTTP routes
# -*- coding: UTF-8 -*-
#
# Handlers declare `doc` so pyRevit's Routes framework injects it on the UI
# thread (see https://docs.pyrevitlabs.io/reference/pyrevit/routes/server/handler/).

from pyrevit import routes, script


def register_routes(api):
    """Register all project-related routes with the API"""

    @api.route('/project_info', methods=['GET'])
    def handle_get_project_info(doc, request):
        """Returns basic information about the current Revit project."""
        route_logger = script.get_logger()

        if doc is None:
            return routes.Response(
                status=503,
                data={"error": "No active Revit document. Open a project and retry."},
            )

        try:
            project_info = doc.ProjectInformation
            if not project_info:
                route_logger.warning("ProjectInformation not available on the active document.")
                return routes.Response(
                    status=500,
                    data={"error": "Could not retrieve ProjectInformation from the active document."},
                )

            data_to_return = {
                "project_name": project_info.Name,
                "project_number": project_info.Number,
                "organization_name": project_info.OrganizationName,
                "building_name": project_info.BuildingName,
                "client_name": project_info.ClientName,
                "status": project_info.Status,
                "file_path": doc.PathName,
            }
            route_logger.info("Retrieved project info for: {}".format(doc.PathName or "Unsaved Project"))
            return data_to_return

        except Exception as e:
            route_logger.error("Unexpected error in /project_info: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data={"error": "Internal server error retrieving project info.", "details": str(e)},
            )
