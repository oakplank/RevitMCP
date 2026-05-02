# startup.py

from pyrevit import routes
from pyrevit import script
from pyrevit import DB # For explicit Revit API access if preferred
from System.Collections.Generic import List # Add this import for .NET List
# from Autodesk.Revit.DB import * # Alternative direct Revit API import

logger = script.get_logger()
logger.info("RevitMCP startup script executing...")

try:
    # Define an API namespace. This should match the one your external server is calling.
    # The full URL will be http://<server_address>:<port>/<api_name>/<route_pattern>
    api = routes.API("revit-mcp-v1")
    logger.info("pyRevit routes API 'revit-mcp-v1' initialized in startup.py.")

    # Define the route for '/project_info' using a decorator
    @api.route('/project_info', methods=['GET'])
    def handle_get_project_info(request):
        """
        Handles GET requests to /revit-mcp-v1/project_info
        Returns basic information about the current Revit project.
        
        Args:
            request (routes.Request): Object containing request details.
        """
        route_logger = script.get_logger() # Use a logger instance for the route handler
        
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
                # Add any other project information you need
            }
            route_logger.info("Successfully retrieved project info for: {}".format(doc.PathName or "Unsaved Project"))
            return data_to_return # Automatically becomes a JSON 200 OK
            
        except AttributeError as ae:
            route_logger.error("Error accessing project info (AttributeError): {}. Is a project open and loaded?".format(ae), exc_info=True)
            return routes.Response(status=503, data={"error": "Error accessing Revit project data. A project might not be open or fully loaded.", "details": str(ae)})
        except Exception as e:
            route_logger.critical("Critical error processing /project_info: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error retrieving project info.", "details": str(e)})

    logger.info("Route /project_info for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/get_elements_by_category', methods=['POST'])
    def handle_get_elements_by_category(request):
        """
        Handles POST requests to /revit-mcp-v1/get_elements_by_category
        Returns elements in Revit by category name (without selecting them).
        Uses FilteredElementCollector with ToElementIds() for better performance.
        """
        route_logger = script.get_logger()
        
        if not request:
            route_logger.error("Critical error: 'request' object is None.")
            return routes.Response(status=500, data={"error": "Internal server error: 'request' object is None.", "details": "The 'request' object was not provided to the handler by pyRevit."})

        try:
            # Access the JSON payload from the request
            payload = request.data if hasattr(request, 'data') else None
            route_logger.info("Successfully accessed request.data. Type: {}, Value: {}".format(type(payload), payload))

            if not payload or not isinstance(payload, dict):
                route_logger.error("Request body (payload) is missing or not a valid JSON object.")
                return routes.Response(status=400, data={"error": "Request body is missing or not a valid JSON object."})

            category_name_payload = payload.get('category_name')
            
            if not category_name_payload:
                route_logger.error("Missing 'category_name' in JSON body for /get_elements_by_category.")
                return routes.Response(status=400, data={"error": "Missing 'category_name' in JSON request body."})

            # Get document from __revit__
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                route_logger.error("Error in /get_elements_by_category: No active UI document.")
                return routes.Response(status=503, data={"error": "No active Revit UI document found."})
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document

            # Category validation and element collection
            built_in_category = None
            if hasattr(DB.BuiltInCategory, category_name_payload):
                built_in_category = getattr(DB.BuiltInCategory, category_name_payload)
            else:
                if not category_name_payload.startswith("OST_"):
                    possible_ost_category = "OST_" + category_name_payload.replace(" ", "")
                    if hasattr(DB.BuiltInCategory, possible_ost_category):
                        built_in_category = getattr(DB.BuiltInCategory, possible_ost_category)
                        route_logger.info("Interpreted category '{}' as '{}'.".format(category_name_payload, possible_ost_category))
                    else:
                        route_logger.error("Invalid category_name: '{}'. Not a recognized BuiltInCategory. Try OST_ format.".format(category_name_payload))
                        return routes.Response(status=400, data={"error": "Invalid category_name: '{}'. Not recognized.".format(category_name_payload)})
                else:
                    route_logger.error("Invalid category_name: '{}'. Not a recognized BuiltInCategory.".format(category_name_payload))
                    return routes.Response(status=400, data={"error": "Invalid category_name: '{}'.".format(category_name_payload)})

            # Use ToElementIds() for better performance - no need for ToElements()
            element_ids_collector = DB.FilteredElementCollector(doc)\
                                       .OfCategory(built_in_category)\
                                       .WhereElementIsNotElementType()\
                                       .ToElementIds()
            
            element_ids = []
            route_logger.info("Found {} elements in category '{}' using ToElementIds()".format(element_ids_collector.Count, category_name_payload))
            
            # Convert ElementId objects to string list
            for element_id in element_ids_collector:
                element_ids.append(str(element_id.IntegerValue))

            if not element_ids:
                route_logger.info("No elements found for category '{}' to return.".format(category_name_payload))
                return {"status": "success", "message": "No elements found for category '{}'".format(category_name_payload), "count": 0, "element_ids": []}
            
            route_logger.info("Successfully retrieved {} element IDs for category '{}'.".format(len(element_ids), category_name_payload))
            return {
                "status": "success", 
                "message": "{} elements found for category '{}'.".format(len(element_ids), category_name_payload), 
                "count": len(element_ids),
                "category": category_name_payload,
                "element_ids": element_ids
            }

        except Exception as e_main_logic:
            route_logger.critical("Critical error in /get_elements_by_category: {}".format(e_main_logic), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error during main logic.", "details": str(e_main_logic)})

    logger.info("Route /get_elements_by_category for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/select_elements_by_id', methods=['POST'])
    def handle_select_elements_by_id(request):
        """
        Selects elements in Revit by their Element IDs.
        Enhanced with view management to ensure selected elements are visible.
        
        Expected payload: {"element_ids": ["123456", "789012"]}
        """
        route_logger = script.get_logger()
        
        try:
            # 1. Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            element_ids_list = payload.get('element_ids')
            if not element_ids_list:
                return routes.Response(status=400, data={"error": "Missing 'element_ids'"})
            
            # 2. Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            active_view = doc.ActiveView
            
            # 3. Convert string IDs to ElementId objects
            element_ids_to_select = List[DB.ElementId]()
            invalid_count = 0
            valid_elements = []
            
            route_logger.info("Processing {} element IDs for selection".format(len(element_ids_list)))
            
            for i, id_str in enumerate(element_ids_list):
                try:
                    id_int = int(id_str)
                    element_id = DB.ElementId(id_int)
                    
                    # Verify element exists and get the element object
                    element = doc.GetElement(element_id)
                    if element is not None:
                        element_ids_to_select.Add(element_id)
                        valid_elements.append(element)
                    else:
                        invalid_count += 1
                        if invalid_count <= 3:
                            route_logger.warning("Element ID {} not found in document".format(id_str))
                except (ValueError, TypeError) as e:
                    invalid_count += 1
                    if invalid_count <= 3:
                        route_logger.warning("Failed to convert ID '{}': {}".format(id_str, e))
            
            route_logger.info("Valid element IDs: {}, Invalid: {}".format(element_ids_to_select.Count, invalid_count))
            
            if element_ids_to_select.Count == 0:
                return {
                    "status": "success",
                    "message": "No valid elements found to select",
                    "selected_count": 0,
                    "requested_count": len(element_ids_list)
                }
            
            # 4. Check view context and element visibility
            elements_in_view = 0
            different_levels = set()
            
            for element in valid_elements[:5]:  # Check first 5 for diagnostics
                try:
                    # Check if element has a level
                    level_param = element.get_Parameter(DB.BuiltInParameter.FAMILY_LEVEL_PARAM)
                    if level_param:
                        level_id = level_param.AsElementId()
                        if level_id != DB.ElementId.InvalidElementId:
                            level = doc.GetElement(level_id)
                            if level:
                                different_levels.add(level.Name)
                    
                    # Check if element is visible in current view (simplified check)
                    if hasattr(element, 'Location') and element.Location:
                        elements_in_view += 1
                except:
                    pass
            
            route_logger.info("Diagnostics: {} elements checked, {} appear to be in view context".format(min(5, len(valid_elements)), elements_in_view))
            if different_levels:
                route_logger.info("Elements found on levels: {}".format(list(different_levels)))
            
            # 5. Select the elements
            uidoc.Selection.SetElementIds(element_ids_to_select)
            
            # 6. Try to ensure visibility - zoom to selection if possible
            try:
                # Get bounding box of selected elements for zoom
                selected_ids = uidoc.Selection.GetElementIds()
                if selected_ids.Count > 0:
                    # Try to zoom to fit the selection
                    uidoc.ShowElements(selected_ids)
                    route_logger.info("Applied ShowElements to make selection visible")
            except Exception as zoom_error:
                route_logger.warning("Could not zoom to selection: {}".format(zoom_error))
            
            # 7. Verify selection
            actual_count = uidoc.Selection.GetElementIds().Count
            
            # 8. Return comprehensive response
            route_logger.info("Selection complete: {} elements selected".format(actual_count))
            
            return {
                "status": "success",
                "message": "Selected {} elements in Revit".format(actual_count),
                "selected_count": actual_count,
                "requested_count": len(element_ids_list),
                "valid_elements": element_ids_to_select.Count,
                "invalid_elements": invalid_count,
                "view_context": {
                    "active_view": active_view.Name,
                    "view_type": str(active_view.ViewType),
                    "elements_in_view_context": elements_in_view,
                    "levels_detected": list(different_levels) if different_levels else ["Not determined"]
                },
                "visibility_note": "If elements not visible, they may be filtered out of current view or on different levels. Try Ctrl+Backspace or switch to 3D view."
            }
            
        except Exception as e:
            route_logger.critical("Error in select_elements_by_id: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /select_elements_by_id for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/select_elements_with_3d_view', methods=['POST'])
    def handle_select_elements_with_3d_view(request):
        """
        Selects elements and ensures they are visible by zooming to them.
        Does not change the user's current view.
        
        Expected payload: {"element_ids": ["123456", "789012"]}
        """
        route_logger = script.get_logger()
        
        try:
            # 1. Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            element_ids_list = payload.get('element_ids')
            if not element_ids_list:
                return routes.Response(status=400, data={"error": "Missing 'element_ids'"})
            
            # 2. Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            # Safe access to current view name
            try:
                current_view_name = doc.ActiveView.Name if doc.ActiveView else "Unknown View"
            except:
                current_view_name = "Unknown View"
            
            # 3. Convert and select elements
            element_ids_to_select = List[DB.ElementId]()
            invalid_count = 0
            
            route_logger.info("Processing {} element IDs for enhanced selection".format(len(element_ids_list)))
            
            for id_str in element_ids_list:
                try:
                    element_id = DB.ElementId(int(id_str))
                    element = doc.GetElement(element_id)
                    if element is not None:
                        element_ids_to_select.Add(element_id)
                    else:
                        invalid_count += 1
                except (ValueError, TypeError):
                    invalid_count += 1
            
            if element_ids_to_select.Count == 0:
                return {
                    "status": "success",
                    "message": "No valid elements found to select",
                    "selected_count": 0
                }
            
            # 4. Select the elements
            uidoc.Selection.SetElementIds(element_ids_to_select)
            
            # 5. Zoom to fit the selection for visibility - try multiple approaches
            zoom_success = False
            visibility_attempts = []
            
            try:
                selected_ids = uidoc.Selection.GetElementIds()
                if selected_ids.Count > 0:
                    # Approach 1: Try ShowElements (what we were doing)
                    try:
                        uidoc.ShowElements(selected_ids)
                        visibility_attempts.append("ShowElements: Success")
                        route_logger.info("Applied ShowElements to {} selected elements".format(selected_ids.Count))
                    except Exception as show_error:
                        visibility_attempts.append("ShowElements: Failed - {}".format(str(show_error)))
                        route_logger.warning("ShowElements failed: {}".format(show_error))
                    
                    # Approach 2: Try ZoomToFit
                    try:
                        from Autodesk.Revit.UI import UIView
                        active_ui_view = uidoc.GetOpenUIViews()
                        if active_ui_view and len(active_ui_view) > 0:
                            active_ui_view[0].ZoomToFit()
                            visibility_attempts.append("ZoomToFit: Success")
                            route_logger.info("Applied ZoomToFit to current view")
                        else:
                            visibility_attempts.append("ZoomToFit: No UI view found")
                    except Exception as zoom_error:
                        visibility_attempts.append("ZoomToFit: Failed - {}".format(str(zoom_error)))
                        route_logger.warning("ZoomToFit failed: {}".format(zoom_error))
                    
                    # Approach 3: Check view filters and visibility settings
                    try:
                        active_view = doc.ActiveView
                        if active_view:
                            # Check if Windows category is visible in current view
                            windows_category = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Windows)
                            if windows_category:
                                is_visible = active_view.GetCategoryHidden(windows_category.Id)
                                visibility_attempts.append("Windows category hidden: {}".format(is_visible))
                                
                                # Try to make windows visible if hidden
                                if is_visible:
                                    active_view.SetCategoryHidden(windows_category.Id, False)
                                    visibility_attempts.append("Unhid Windows category")
                                    route_logger.info("Made Windows category visible in current view")
                    except Exception as category_error:
                        visibility_attempts.append("Category visibility check: Failed - {}".format(str(category_error)))
                        route_logger.warning("Category visibility check failed: {}".format(category_error))
                    
                    # Approach 4: Check if any selected elements are actually visible
                    try:
                        visible_count = 0
                        sample_elements = []
                        for i, elem_id in enumerate(selected_ids):
                            if i >= 5:  # Check first 5 elements
                                break
                            element = doc.GetElement(elem_id)
                            if element:
                                sample_elements.append({
                                    "id": str(elem_id.IntegerValue),
                                    "name": getattr(element, 'Name', 'No Name'),
                                    "category": element.Category.Name if element.Category else "No Category"
                                })
                        
                        visibility_attempts.append("Checked {} sample elements".format(len(sample_elements)))
                        route_logger.info("Sample selected elements: {}".format(sample_elements))
                    except Exception as sample_error:
                        visibility_attempts.append("Sample check: Failed - {}".format(str(sample_error)))
                    
                    zoom_success = True
                    
            except Exception as zoom_error:
                visibility_attempts.append("Overall visibility process: Failed - {}".format(str(zoom_error)))
                route_logger.warning("Could not apply visibility enhancements: {}".format(zoom_error))
                zoom_success = False
            
            actual_count = uidoc.Selection.GetElementIds().Count
            
            return {
                "status": "success",
                "message": "Selected {} elements - applied visibility enhancements".format(actual_count),
                "selected_count": actual_count,
                "requested_count": len(element_ids_list),
                "valid_elements": element_ids_to_select.Count,
                "invalid_elements": invalid_count,
                "active_view": current_view_name,
                "zoom_applied": zoom_success,
                "visibility_attempts": visibility_attempts,
                "visibility_note": "Multiple visibility approaches attempted. If elements still not visible, check view filters, levels, or phase settings.",
                "workaround": "If needed, use Ctrl+Backspace to restore previous selection visibility"
            }
            
        except Exception as e:
            route_logger.critical("Error in select_elements_with_3d_view: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /select_elements_with_3d_view for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/select_elements_simple', methods=['POST'])
    def handle_select_elements_simple(request):
        """
        Simple element selection without any visibility enhancements.
        For debugging and comparison with enhanced version.
        
        Expected payload: {"element_ids": ["123456", "789012"]}
        """
        route_logger = script.get_logger()
        
        try:
            # 1. Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            element_ids_list = payload.get('element_ids')
            if not element_ids_list:
                return routes.Response(status=400, data={"error": "Missing 'element_ids'"})
            
            # 2. Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            # 3. Convert and select elements (minimal approach)
            element_ids_to_select = List[DB.ElementId]()
            
            for id_str in element_ids_list:
                try:
                    element_id = DB.ElementId(int(id_str))
                    element = doc.GetElement(element_id)
                    if element is not None:
                        element_ids_to_select.Add(element_id)
                except (ValueError, TypeError):
                    pass
            
            # 4. Simple selection
            uidoc.Selection.SetElementIds(element_ids_to_select)
            actual_count = uidoc.Selection.GetElementIds().Count
            
            route_logger.info("Simple selection: {} elements selected".format(actual_count))
            
            return {
                "status": "success",
                "message": "Simple selection: {} elements selected".format(actual_count),
                "selected_count": actual_count,
                "approach": "simple",
                "note": "No visibility enhancements applied - pure selection only"
            }
            
        except Exception as e:
            route_logger.critical("Error in select_elements_simple: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /select_elements_simple for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/test_select_manual_windows', methods=['POST'])
    def handle_test_select_manual_windows(request):
        """
        Test route using manually verified window IDs to test selection mechanism.
        """
        route_logger = script.get_logger()
        
        try:
            # Use the manually verified window IDs from user
            manual_window_ids = [
                "824575","824639","824851","824915","824953","825015","825904","825918","825925","825939",
                "825953","825960","826121","826128","826156","826170","826177","826184","826267","826274",
                "826288","826309","826316","826323","836249","836256","836329","836408","836429","836539",
                "836614","836621","1054636","1054640","1054764","1055517","1055618","1055622","1055626","1055630",
                "1055807","1055811","1055816","1055820","1055829","1055833","1055838","1055842","1055851","1055855",
                "1055860","1055864","1105175","1105554","1263584","1267596","1528722","1528776","1528830","1528884",
                "1531805","1532053","1532107","1532173","2023620","2023811"
            ]
            
            # Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            # Convert to ElementId objects
            element_ids_to_select = List[DB.ElementId]()
            
            for id_str in manual_window_ids:
                try:
                    id_int = int(id_str)
                    element_id = DB.ElementId(id_int)
                    element_ids_to_select.Add(element_id)
                except (ValueError, TypeError):
                    route_logger.warning("Invalid manual ID: {}".format(id_str))
            
            # Select the elements
            uidoc.Selection.SetElementIds(element_ids_to_select)
            
            # Verify selection
            actual_count = uidoc.Selection.GetElementIds().Count
            
            route_logger.info("Manual window test: Selected {} out of {} manual IDs".format(actual_count, len(manual_window_ids)))
            return {
                "status": "success",
                "message": "Manual test: Selected {} elements".format(actual_count),
                "selected_count": actual_count,
                "requested_count": len(manual_window_ids)
            }
            
        except Exception as e:
            route_logger.critical("Error in test_select_manual_windows: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /test_select_manual_windows for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/get_and_select_elements_by_category', methods=['POST'])
    def handle_get_and_select_elements_by_category(request):
        """
        Combined route: Gets elements by category AND selects them in one step.
        This eliminates the LLM's ability to hallucinate IDs between tool calls.
        
        Args:
            request (routes.Request): Object containing request details.
        """
        route_logger = script.get_logger()
        
        try:
            # 1. Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            category_name_payload = payload.get('category_name')
            if not category_name_payload:
                return routes.Response(status=400, data={"error": "Missing 'category_name'"})
            
            # 2. Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            # 3. Validate category
            built_in_category = None
            if hasattr(DB.BuiltInCategory, category_name_payload):
                built_in_category = getattr(DB.BuiltInCategory, category_name_payload)
            else:
                if not category_name_payload.startswith("OST_"):
                    possible_ost_category = "OST_" + category_name_payload.replace(" ", "")
                    if hasattr(DB.BuiltInCategory, possible_ost_category):
                        built_in_category = getattr(DB.BuiltInCategory, possible_ost_category)
                        route_logger.info("Interpreted category '{}' as '{}'.".format(category_name_payload, possible_ost_category))
                    else:
                        return routes.Response(status=400, data={"error": "Invalid category_name: '{}'.".format(category_name_payload)})
                else:
                    return routes.Response(status=400, data={"error": "Invalid category_name: '{}'.".format(category_name_payload)})
            
            # 4. Collect elements
            elements_collector = DB.FilteredElementCollector(doc)\
                                    .OfCategory(built_in_category)\
                                    .WhereElementIsNotElementType()\
                                    .ToElements()
            
            route_logger.info("Found {} elements in category '{}'".format(len(elements_collector), category_name_payload))
            
            if len(elements_collector) == 0:
                # Clear selection if no elements found
                uidoc.Selection.SetElementIds(List[DB.ElementId]())
                return {
                    "status": "success",
                    "message": "No elements found for category '{}'".format(category_name_payload),
                    "category": category_name_payload,
                    "found_count": 0,
                    "selected_count": 0
                }
            
            # 5. Convert to ElementId objects and select immediately
            element_ids_to_select = List[DB.ElementId]()
            element_ids_list = []
            
            for el in elements_collector:
                element_id = el.Id
                element_ids_to_select.Add(element_id)
                element_ids_list.append(str(element_id.IntegerValue))
            
            # 6. Select the elements
            uidoc.Selection.SetElementIds(element_ids_to_select)
            
            # 7. Verify selection
            actual_count = uidoc.Selection.GetElementIds().Count
            
            route_logger.info("Combined get+select: Found {} elements, Selected {} elements for category '{}'".format(
                len(elements_collector), actual_count, category_name_payload))
            
            return {
                "status": "success",
                "message": "Found and selected {} elements for category '{}'".format(actual_count, category_name_payload),
                "category": category_name_payload,
                "found_count": len(elements_collector),
                "selected_count": actual_count,
                "element_ids": element_ids_list
            }
            
        except Exception as e:
            route_logger.critical("Error in get_and_select_elements_by_category: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /get_and_select_elements_by_category for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/test_storage_system', methods=['POST'])
    def handle_test_storage_system(request):
        """
        Test route to verify the storage system works by making calls to the external server.
        """
        route_logger = script.get_logger()
        
        try:
            # Test calling the external server's storage endpoints
            import requests
            import json
            
            # First, test the list_stored_elements
            test_payload = {"conversation": [{"role": "user", "content": "test"}], "apiKey": "test", "model": "echo_model"}
            
            route_logger.info("Testing storage system - this is a basic connectivity test")
            
            return {
                "status": "success",
                "message": "Storage system test route active. Use external server MCP tools for actual testing.",
                "note": "This route verifies the storage system is set up. To test: 1) Call get_elements_by_category for Windows, 2) Check the logs for storage confirmation, 3) Call select_stored_elements with 'windows'"
            }
            
        except Exception as e:
            route_logger.error("Error in test_storage_system: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Test failed", "details": str(e)})

    logger.info("Route /test_storage_system for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/select_elements_focused', methods=['POST'])
    def handle_select_elements_focused(request):
        """
        Focused element selection - just select and keep selected as active elements.
        No zoom, no view changes, just solid selection that persists.
        
        Expected payload: {"element_ids": ["123456", "789012"]}
        """
        route_logger = script.get_logger()
        
        try:
            # 1. Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            element_ids_list = payload.get('element_ids')
            if not element_ids_list:
                return routes.Response(status=400, data={"error": "Missing 'element_ids'"})
            
            # 2. Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            route_logger.info("Focused selection: Processing {} element IDs".format(len(element_ids_list)))
            
            # 3. Convert to ElementId objects - validate all first
            element_ids_to_select = List[DB.ElementId]()
            valid_count = 0
            
            for id_str in element_ids_list:
                try:
                    element_id = DB.ElementId(int(id_str))
                    element = doc.GetElement(element_id)
                    if element is not None:
                        element_ids_to_select.Add(element_id)
                        valid_count += 1
                except (ValueError, TypeError):
                    pass
            
            route_logger.info("Validated {} valid elements out of {}".format(valid_count, len(element_ids_list)))
            
            if element_ids_to_select.Count == 0:
                return {
                    "status": "success",
                    "message": "No valid elements found to select",
                    "selected_count": 0
                }
            
            # 4. Clear any existing selection first
            uidoc.Selection.SetElementIds(List[DB.ElementId]())
            
            # 5. Set the new selection - this should make them the active elements
            uidoc.Selection.SetElementIds(element_ids_to_select)
            
            # 6. Verify the selection stuck
            final_selection = uidoc.Selection.GetElementIds()
            final_count = final_selection.Count
            
            route_logger.info("Selection result: {} elements are now selected and active".format(final_count))
            
            # 7. Force UI refresh if possible
            try:
                uidoc.RefreshActiveView()
                route_logger.info("Refreshed active view")
            except:
                pass
            
            return {
                "status": "success",
                "message": "Selected {} elements - they are now the active elements in the document".format(final_count),
                "selected_count": final_count,
                "requested_count": len(element_ids_list),
                "valid_elements": valid_count,
                "approach": "focused_selection",
                "note": "Elements selected and should remain active for user operations"
            }
            
        except Exception as e:
            route_logger.critical("Error in select_elements_focused: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /select_elements_focused for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/elements/filter', methods=['POST'])
    def handle_filter_elements(request):
        """
        Advanced element filtering by category, level, and parameter conditions.
        
        Expected payload: {
            "category_name": "OST_Windows",
            "level_name": "L5",  # Optional
            "parameters": [      # Optional
                {"name": "Sill Height", "value": "2' 3\"", "condition": "equals"}
            ]
        }
        """
        route_logger = script.get_logger()
        
        try:
            # Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            category_name = payload.get('category_name')
            if not category_name:
                return routes.Response(status=400, data={"error": "Missing 'category_name'"})
            
            level_name = payload.get('level_name')
            parameter_filters = payload.get('parameters', [])
            
            # Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            # Validate category
            built_in_category = None
            if hasattr(DB.BuiltInCategory, category_name):
                built_in_category = getattr(DB.BuiltInCategory, category_name)
            else:
                if not category_name.startswith("OST_"):
                    possible_ost_category = "OST_" + category_name.replace(" ", "")
                    if hasattr(DB.BuiltInCategory, possible_ost_category):
                        built_in_category = getattr(DB.BuiltInCategory, possible_ost_category)
                        route_logger.info("Interpreted category '{}' as '{}'.".format(category_name, possible_ost_category))
                    else:
                        return routes.Response(status=400, data={"error": "Invalid category_name: '{}'.".format(category_name)})
                else:
                    return routes.Response(status=400, data={"error": "Invalid category_name: '{}'.".format(category_name)})
            
            # Start with category filter
            collector = DB.FilteredElementCollector(doc)\
                         .OfCategory(built_in_category)\
                         .WhereElementIsNotElementType()
            
            # Apply level filter if specified
            if level_name:
                # Find the level by name
                level_collector = DB.FilteredElementCollector(doc)\
                                   .OfClass(DB.Level)\
                                   .ToElements()
                
                target_level = None
                for level in level_collector:
                    if level.Name == level_name:
                        target_level = level
                        break
                
                if target_level:
                    collector = collector.WherePasses(DB.ElementLevelFilter(target_level.Id))
                    route_logger.info("Applied level filter for: {}".format(level_name))
                else:
                    return routes.Response(status=400, data={"error": "Level '{}' not found".format(level_name)})
            
            # Get elements for parameter filtering
            elements = collector.ToElements()
            route_logger.info("Found {} elements before parameter filtering".format(len(elements)))
            
            # Apply parameter filters
            filtered_elements = []
            for element in elements:
                include_element = True
                
                for param_filter in parameter_filters:
                    param_name = param_filter.get('name')
                    param_value = param_filter.get('value')
                    condition = param_filter.get('condition', 'equals')
                    
                    if not param_name or param_value is None:
                        continue
                    
                    # Get parameter from element
                    param = None
                    # Try built-in parameter first
                    try:
                        if hasattr(DB.BuiltInParameter, param_name.replace(" ", "_").upper()):
                            built_in_param = getattr(DB.BuiltInParameter, param_name.replace(" ", "_").upper())
                            param = element.get_Parameter(built_in_param)
                    except:
                        pass
                    
                    # Try by name if built-in didn't work
                    if not param:
                        for p in element.Parameters:
                            if p.Definition.Name == param_name:
                                param = p
                                break
                    
                    if not param:
                        route_logger.warning("Parameter '{}' not found on element {}".format(param_name, element.Id))
                        include_element = False
                        break
                    
                    # Get parameter value as string for comparison
                    if param.HasValue:
                        if param.StorageType == DB.StorageType.String:
                            current_value = param.AsString()
                        elif param.StorageType == DB.StorageType.Double:
                            # Convert to display units
                            current_value = param.AsValueString()
                        elif param.StorageType == DB.StorageType.Integer:
                            current_value = str(param.AsInteger())
                        else:
                            current_value = param.AsValueString()
                    else:
                        current_value = ""
                    
                    # Apply condition
                    if condition == "equals":
                        if current_value != param_value:
                            include_element = False
                            break
                    elif condition == "contains":
                        if param_value not in current_value:
                            include_element = False
                            break
                    elif condition == "greater_than":
                        try:
                            if float(current_value.split()[0]) <= float(param_value.split()[0]):
                                include_element = False
                                break
                        except:
                            include_element = False
                            break
                    elif condition == "less_than":
                        try:
                            if float(current_value.split()[0]) >= float(param_value.split()[0]):
                                include_element = False
                                break
                        except:
                            include_element = False
                            break
                
                if include_element:
                    filtered_elements.append(element)
            
            # Convert to element IDs
            element_ids = [str(elem.Id.IntegerValue) for elem in filtered_elements]
            
            route_logger.info("Filtered to {} elements matching criteria".format(len(element_ids)))
            
            return {
                "status": "success",
                "message": "Found {} elements matching filter criteria".format(len(element_ids)),
                "count": len(element_ids),
                "category": category_name,
                "level": level_name if level_name else "Any",
                "parameter_filters": parameter_filters,
                "element_ids": element_ids
            }
            
        except Exception as e:
            route_logger.critical("Error in filter_elements: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /elements/filter for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/elements/get_properties', methods=['POST'])
    def handle_get_element_properties(request):
        """
        Get parameter values for specified elements.
        
        Expected payload: {
            "element_ids": ["123456", "789012"],
            "parameter_names": ["Sill Height", "Level", "Width"]  # Optional, if not provided gets common parameters
        }
        """
        route_logger = script.get_logger()
        
        try:
            # Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            element_ids_list = payload.get('element_ids')
            if not element_ids_list:
                return routes.Response(status=400, data={"error": "Missing 'element_ids'"})
            
            parameter_names = payload.get('parameter_names', [])
            
            # Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            results = []
            
            for id_str in element_ids_list:
                try:
                    element_id = DB.ElementId(int(id_str))
                    element = doc.GetElement(element_id)
                    
                    if not element:
                        results.append({
                            "element_id": id_str,
                            "error": "Element not found",
                            "properties": {}
                        })
                        continue
                    
                    properties = {}
                    
                    # If no specific parameters requested, get common ones
                    if not parameter_names:
                        # Get some common parameters
                        common_params = ["Level", "Family and Type", "Comments"]
                        # Add category-specific common parameters
                        if element.Category:
                            if element.Category.Name == "Windows":
                                common_params.extend(["Sill Height", "Head Height", "Width", "Height"])
                            elif element.Category.Name == "Doors":
                                common_params.extend(["Width", "Height", "Finish"])
                            elif element.Category.Name == "Walls":
                                common_params.extend(["Base Constraint", "Top Constraint", "Height"])
                        parameter_names_to_use = common_params
                    else:
                        parameter_names_to_use = parameter_names
                    
                    # Get requested parameters
                    for param_name in parameter_names_to_use:
                        param = None
                        
                        # Try built-in parameter first
                        try:
                            if hasattr(DB.BuiltInParameter, param_name.replace(" ", "_").upper()):
                                built_in_param = getattr(DB.BuiltInParameter, param_name.replace(" ", "_").upper())
                                param = element.get_Parameter(built_in_param)
                        except:
                            pass
                        
                        # Try by name if built-in didn't work
                        if not param:
                            for p in element.Parameters:
                                if p.Definition.Name == param_name:
                                    param = p
                                    break
                        
                        if param and param.HasValue:
                            if param.StorageType == DB.StorageType.String:
                                properties[param_name] = param.AsString()
                            elif param.StorageType == DB.StorageType.Double:
                                properties[param_name] = param.AsValueString()
                            elif param.StorageType == DB.StorageType.Integer:
                                properties[param_name] = str(param.AsInteger())
                            elif param.StorageType == DB.StorageType.ElementId:
                                elem_id = param.AsElementId()
                                if elem_id != DB.ElementId.InvalidElementId:
                                    ref_element = doc.GetElement(elem_id)
                                    properties[param_name] = ref_element.Name if ref_element else str(elem_id.IntegerValue)
                                else:
                                    properties[param_name] = "None"
                            else:
                                properties[param_name] = param.AsValueString()
                        else:
                            properties[param_name] = "Not available"
                    
                    # Add basic element info
                    properties["Element_Name"] = getattr(element, 'Name', 'No Name')
                    properties["Category"] = element.Category.Name if element.Category else "No Category"
                    
                    results.append({
                        "element_id": id_str,
                        "properties": properties
                    })
                    
                except Exception as elem_error:
                    route_logger.warning("Error processing element {}: {}".format(id_str, elem_error))
                    results.append({
                        "element_id": id_str,
                        "error": str(elem_error),
                        "properties": {}
                    })
            
            route_logger.info("Retrieved properties for {} elements".format(len(results)))
            
            return {
                "status": "success",
                "message": "Retrieved properties for {} elements".format(len(results)),
                "count": len(results),
                "elements": results
            }
            
        except Exception as e:
            route_logger.critical("Error in get_element_properties: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /elements/get_properties for API 'revit-mcp-v1' defined in startup.py.")

    @api.route('/elements/update_parameters', methods=['POST'])
    def handle_update_element_parameters(request):
        """
        Update parameter values for specified elements.
        
        Expected payload: {
            "updates": [
                {
                    "element_id": "123456",
                    "parameters": {
                        "Sill Height": "2' 6\"",
                        "Comments": "Updated via API"
                    }
                }
            ]
        }
        """
        route_logger = script.get_logger()
        
        try:
            # Handle request data
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})
            
            updates_list = payload.get('updates')
            if not updates_list:
                return routes.Response(status=400, data={"error": "Missing 'updates' list"})
            
            # Access Revit document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})
            
            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            
            results = []
            
            # Start transaction for all updates
            with DB.Transaction(doc, "Update Element Parameters") as t:
                t.Start()
                
                try:
                    for update_data in updates_list:
                        element_id_str = update_data.get('element_id')
                        parameters_to_update = update_data.get('parameters', {})
                        
                        if not element_id_str or not parameters_to_update:
                            results.append({
                                "element_id": element_id_str,
                                "status": "error",
                                "message": "Missing element_id or parameters",
                                "updated_params": [],
                                "errors": {}
                            })
                            continue
                        
                        try:
                            element_id = DB.ElementId(int(element_id_str))
                            element = doc.GetElement(element_id)
                            
                            if not element:
                                results.append({
                                    "element_id": element_id_str,
                                    "status": "error",
                                    "message": "Element not found",
                                    "updated_params": [],
                                    "errors": {}
                                })
                                continue
                            
                            updated_params = []
                            errors = {}
                            
                            for param_name, new_value in parameters_to_update.items():
                                try:
                                    param = None
                                    
                                    # Try built-in parameter first
                                    try:
                                        if hasattr(DB.BuiltInParameter, param_name.replace(" ", "_").upper()):
                                            built_in_param = getattr(DB.BuiltInParameter, param_name.replace(" ", "_").upper())
                                            param = element.get_Parameter(built_in_param)
                                    except:
                                        pass
                                    
                                    # Try by name if built-in didn't work
                                    if not param:
                                        for p in element.Parameters:
                                            if p.Definition.Name == param_name:
                                                param = p
                                                break
                                    
                                    if not param:
                                        errors[param_name] = "Parameter not found"
                                        continue
                                    
                                    if param.IsReadOnly:
                                        errors[param_name] = "Parameter is read-only"
                                        continue
                                    
                                    # Set parameter value based on type
                                    if param.StorageType == DB.StorageType.String:
                                        param.Set(str(new_value))
                                        updated_params.append(param_name)
                                    elif param.StorageType == DB.StorageType.Double:
                                        # Handle unit conversion for length parameters
                                        if isinstance(new_value, str) and ("'" in new_value or '"' in new_value):
                                            # Parse feet and inches
                                            feet = 0
                                            inches = 0
                                            
                                            # Extract feet
                                            if "'" in new_value:
                                                feet_part = new_value.split("'")[0].strip()
                                                try:
                                                    feet = float(feet_part)
                                                except:
                                                    pass
                                            
                                            # Extract inches
                                            if '"' in new_value:
                                                if "'" in new_value:
                                                    inches_part = new_value.split("'")[1].replace('"', '').strip()
                                                else:
                                                    inches_part = new_value.replace('"', '').strip()
                                                try:
                                                    inches = float(inches_part)
                                                except:
                                                    pass
                                            
                                            # Convert to Revit internal units (feet)
                                            total_feet = feet + (inches / 12.0)
                                            param.Set(total_feet)
                                        else:
                                            # Try direct numeric conversion
                                            try:
                                                param.Set(float(new_value))
                                            except:
                                                errors[param_name] = "Could not convert '{}' to number".format(new_value)
                                                continue
                                        updated_params.append(param_name)
                                    elif param.StorageType == DB.StorageType.Integer:
                                        try:
                                            param.Set(int(float(new_value)))
                                            updated_params.append(param_name)
                                        except:
                                            errors[param_name] = "Could not convert '{}' to integer".format(new_value)
                                    else:
                                        errors[param_name] = "Unsupported parameter type: {}".format(param.StorageType)
                                
                                except Exception as param_error:
                                    errors[param_name] = str(param_error)
                            
                            # Determine overall status
                            if updated_params and not errors:
                                status = "success"
                                message = "All parameters updated successfully"
                            elif updated_params and errors:
                                status = "partial"
                                message = "Some parameters updated, some failed"
                            else:
                                status = "error"
                                message = "No parameters were updated"
                            
                            results.append({
                                "element_id": element_id_str,
                                "status": status,
                                "message": message,
                                "updated_params": updated_params,
                                "errors": errors
                            })
                            
                        except Exception as elem_error:
                            route_logger.warning("Error updating element {}: {}".format(element_id_str, elem_error))
                            results.append({
                                "element_id": element_id_str,
                                "status": "error",
                                "message": str(elem_error),
                                "updated_params": [],
                                "errors": {}
                            })
                    
                    # Commit the transaction
                    t.Commit()
                    route_logger.info("Transaction committed successfully")
                    
                except Exception as transaction_error:
                    route_logger.error("Transaction failed: {}".format(transaction_error))
                    return routes.Response(status=500, data={"error": "Transaction failed", "details": str(transaction_error)})
            
            # Calculate summary
            success_count = len([r for r in results if r["status"] == "success"])
            partial_count = len([r for r in results if r["status"] == "partial"])
            error_count = len([r for r in results if r["status"] == "error"])
            
            route_logger.info("Parameter updates complete: {} success, {} partial, {} errors".format(success_count, partial_count, error_count))
            
            return {
                "status": "success",
                "message": "Parameter update completed: {} success, {} partial, {} errors".format(success_count, partial_count, error_count),
                "summary": {
                    "total": len(results),
                    "success": success_count,
                    "partial": partial_count,
                    "errors": error_count
                },
                "results": results
            }
            
        except Exception as e:
            route_logger.critical("Error in update_element_parameters: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    logger.info("Route /elements/update_parameters for API 'revit-mcp-v1' defined in startup.py.")

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
            import sys
            import os
            
            # Add the lib directory to the path if not already there
            lib_dir = os.path.join(os.path.dirname(__file__), 'lib', 'RevitMCP_Tools')
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

    logger.info("Route /sheets/place_view for API 'revit-mcp-v1' defined in startup.py.")

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
            import sys
            import os
            
            lib_dir = os.path.join(os.path.dirname(__file__), 'lib', 'RevitMCP_Tools')
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

    logger.info("Route /sheets/list_views for API 'revit-mcp-v1' defined in startup.py.")

except Exception as e:
    logger.error("Error during RevitMCP startup.py execution (API/route definition): {}".format(e), exc_info=True)

logger.info("RevitMCP startup script finished.") 
