# RevitMCP: Sheet and view-related HTTP routes
# -*- coding: UTF-8 -*-
#
# Handlers declare `doc`, `uidoc`, or `uiapp` as parameter names so pyRevit's
# Routes framework injects them on the UI thread (see
# https://docs.pyrevitlabs.io/reference/pyrevit/routes/server/handler/).

from pyrevit import routes, script, DB
import sys
import os

from routes.json_safety import sanitize_for_json, to_safe_ascii_text


def register_routes(api):
    """Register all sheet-related routes with the API"""

    def _require_doc(doc):
        if doc is None:
            return routes.Response(
                status=503,
                data={"error": "No active Revit document. Open a project and retry."},
            )
        return None

    @api.route('/sheets/place_view', methods=['POST'])
    def handle_place_view_on_sheet(doc, request):
        """
        Place a view on a new sheet by view name.

        Expected payload: {
            "view_name": "Detail 1",
            "exact_match": false (optional, defaults to false for fuzzy matching)
        }
        """
        route_logger = script.get_logger()

        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc

        try:
            lib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'RevitMCP_Tools')
            if lib_dir not in sys.path:
                sys.path.append(lib_dir)

            from sheet_placement_tool import place_view_on_new_sheet

            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            view_name = payload.get('view_name')
            view_id = payload.get('view_id')
            target_sheet_id = payload.get('target_sheet_id')
            target_sheet_name = payload.get('target_sheet_name')
            titleblock_id = payload.get('titleblock_id')
            titleblock_name = payload.get('titleblock_name')
            if not view_name and not view_id:
                return routes.Response(
                    status=400,
                    data={"error": "Provide either 'view_name' or 'view_id' in request"},
                )

            exact_match = payload.get('exact_match', False)

            route_logger.info(
                "Placing view (name='{}', id='{}') on sheet (target_sheet_id='{}', target_sheet_name='{}', titleblock_id='{}', titleblock_name='{}', exact_match={})".format(
                    to_safe_ascii_text(view_name) if view_name else None,
                    view_id,
                    target_sheet_id,
                    to_safe_ascii_text(target_sheet_name) if target_sheet_name else None,
                    titleblock_id,
                    to_safe_ascii_text(titleblock_name) if titleblock_name else None,
                    exact_match,
                )
            )

            result = place_view_on_new_sheet(
                doc, view_name, route_logger, exact_match,
                view_id=view_id,
                target_sheet_id=target_sheet_id,
                target_sheet_name=target_sheet_name,
                titleblock_id=titleblock_id,
                titleblock_name=titleblock_name,
            )

            placement_status = result.get("status")
            if placement_status == "success":
                route_logger.info("Successfully placed view '{}' on sheet '{}'".format(
                    to_safe_ascii_text(result.get("view_name")), result.get("sheet_number")))
                return sanitize_for_json(result)
            if placement_status == "multiple_matches":
                route_logger.info("Multiple views found for '{}': {}".format(
                    to_safe_ascii_text(view_name),
                    [to_safe_ascii_text(v["name"]) for v in result.get("matching_views", [])],
                ))
                return routes.Response(status=300, data=sanitize_for_json(result))

            route_logger.warning(
                "Failed to place view '{}': {}".format(
                    to_safe_ascii_text(view_name),
                    to_safe_ascii_text(result.get("message")),
                )
            )
            return routes.Response(status=400, data=sanitize_for_json(result))

        except ImportError as ie:
            route_logger.error("Error importing sheet_placement_tool: {}".format(ie), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Failed to import sheet placement tool",
                "details": str(ie)
            })
        except Exception as e:
            route_logger.error("Error in place_view_on_sheet: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Internal server error",
                "details": str(e)
            })

    @api.route('/sheets/list_views', methods=['GET'])
    def handle_list_views(doc, request):
        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc
        """
        List all views in the current document that can be placed on sheets.

        Returns a list of views with their names, types, and IDs for reference.
        """
        route_logger = script.get_logger()

        try:
            lib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'RevitMCP_Tools')
            if lib_dir not in sys.path:
                sys.path.append(lib_dir)

            from sheet_placement_tool import get_view_type_name

            views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()

            view_list = []
            for view in views:
                try:
                    if not hasattr(view, 'Name') or not view.Name:
                        continue

                    if hasattr(view, 'IsTemplate') and view.IsTemplate:
                        continue

                    if hasattr(view, 'ViewType') and view.ViewType == DB.ViewType.DrawingSheet:
                        continue

                    can_be_placed = getattr(view, 'CanBePrinted', True)

                    is_on_sheet = False
                    sheet_name = None
                    if hasattr(view, 'Sheet') and view.Sheet and view.Sheet.Id != DB.ElementId.InvalidElementId:
                        is_on_sheet = True
                        sheet_name = getattr(view.Sheet, 'Name', 'Unknown Sheet')

                    view_info = {
                        "name": to_safe_ascii_text(view.Name),
                        "type": get_view_type_name(view, route_logger),
                        "id": str(view.Id.IntegerValue),
                        "can_be_placed": can_be_placed,
                        "is_on_sheet": is_on_sheet,
                        "sheet_name": to_safe_ascii_text(sheet_name) if sheet_name else None
                    }

                    view_list.append(view_info)

                except Exception as view_error:
                    route_logger.warning("Error processing view: {}".format(view_error))
                    continue

            view_list.sort(key=lambda x: (x["type"], x["name"]))

            route_logger.info("Found {} views in document".format(len(view_list)))

            return sanitize_for_json({
                "status": "success",
                "message": "Found {} views".format(len(view_list)),
                "count": len(view_list),
                "views": view_list
            })

        except Exception as e:
            route_logger.error("Error in list_views: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Internal server error",
                "details": str(e)
            })
