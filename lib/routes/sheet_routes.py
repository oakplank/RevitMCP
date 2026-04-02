# RevitMCP: Sheet and view-related HTTP routes
# -*- coding: UTF-8 -*-

from pyrevit import routes, script, DB
import sys
import os

def register_routes(api):
    """Register all sheet-related routes with the API"""
    
    @api.route('/sheets/place_view', methods=['POST'])
    def handle_place_view_on_sheet(request):
        """
        Place a view on a new sheet by view name.
        
        Expected payload: {
            "view_name": "Detail 1", 
            "exact_match": false (optional, defaults to false for fuzzy matching)
        }
        """
        route_logger = script.get_logger()
        
        try:
            # Import the sheet placement tool
            lib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'RevitMCP_Tools')
            if lib_dir not in sys.path:
                sys.path.append(lib_dir)
            
            from sheet_placement_tool import place_view_on_new_sheet
            
            # Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            view_name = payload.get('view_name')
            if not view_name:
                return routes.Response(status=400, data={"error": "Missing 'view_name' in request"})
            
            exact_match = payload.get('exact_match', False)
            
            # Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            route_logger.info("Attempting to place view '{}' on new sheet (exact_match: {})".format(view_name, exact_match))
            
            # Call the sheet placement function
            result = place_view_on_new_sheet(doc, view_name, route_logger, exact_match)
            
            if result.get("status") == "success":
                route_logger.info("Successfully placed view '{}' on sheet '{}'".format(
                    result.get("view_name"), result.get("sheet_number")))
                return result
            elif result.get("status") == "multiple_matches":
                route_logger.info("Multiple views found for '{}': {}".format(
                    view_name, [v["name"] for v in result.get("matching_views", [])]))
                return routes.Response(status=300, data=result)  # 300 Multiple Choices
            else:
                route_logger.warning("Failed to place view '{}': {}".format(view_name, result.get("message")))
                return routes.Response(status=400, data=result)
                
        except ImportError as ie:
            route_logger.error("Error importing sheet_placement_tool: {}".format(ie), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Failed to import sheet placement tool", 
                "details": str(ie)
            })
        except Exception as e:
            route_logger.critical("Error in place_view_on_sheet: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Internal server error", 
                "details": str(e)
            })

    @api.route('/sheets/list_views', methods=['GET'])
    def handle_list_views(request):
        """
        List all views in the current document that can be placed on sheets.
        
        Returns a list of views with their names, types, and IDs for reference.
        """
        route_logger = script.get_logger()
        
        try:
            # Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            # Import needed modules
            lib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'RevitMCP_Tools')
            if lib_dir not in sys.path:
                sys.path.append(lib_dir)
            
            from sheet_placement_tool import get_view_type_name
            
            # Collect all views
            views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
            
            view_list = []
            for view in views:
                try:
                    if not hasattr(view, 'Name') or not view.Name:
                        continue
                    
                    # Skip template views and sheets
                    if hasattr(view, 'IsTemplate') and view.IsTemplate:
                        continue
                    
                    if hasattr(view, 'ViewType') and view.ViewType == DB.ViewType.DrawingSheet:
                        continue
                    
                    # Check if view can be printed (generally means it can be placed on sheets)
                    can_be_placed = getattr(view, 'CanBePrinted', True)
                    
                    # Check if already placed on a sheet
                    is_on_sheet = False
                    sheet_name = None
                    if hasattr(view, 'Sheet') and view.Sheet and view.Sheet.Id != DB.ElementId.InvalidElementId:
                        is_on_sheet = True
                        sheet_name = getattr(view.Sheet, 'Name', 'Unknown Sheet')
                    
                    view_info = {
                        "name": view.Name,
                        "type": get_view_type_name(view, route_logger),
                        "id": str(view.Id.IntegerValue),
                        "can_be_placed": can_be_placed,
                        "is_on_sheet": is_on_sheet,
                        "sheet_name": sheet_name
                    }
                    
                    view_list.append(view_info)
                    
                except Exception as view_error:
                    route_logger.warning("Error processing view: {}".format(view_error))
                    continue
            
            # Sort by view type, then by name
            view_list.sort(key=lambda x: (x["type"], x["name"]))
            
            route_logger.info("Found {} views in document".format(len(view_list)))
            
            return {
                "status": "success",
                "message": "Found {} views".format(len(view_list)),
                "count": len(view_list),
                "views": view_list
            }
            
        except Exception as e:
            route_logger.critical("Error in list_views: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Internal server error", 
                "details": str(e)
            }) 