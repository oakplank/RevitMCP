# RevitMCP: This script runs in pyRevit (IronPython).
# -*- coding: UTF-8 -*-
"""
Tool for selecting elements in Revit.
"""

from revit_api_utils import get_bic_by_name # Import from the new utility file

try:
    import Autodesk
    from Autodesk.Revit.DB import ElementId, FilteredElementCollector # Added FilteredElementCollector
    from System.Collections.Generic import List # For List[ElementId]
except ImportError:
    print("ERROR (element_selection_tools): Revit API modules not found. This script must run in Revit.")
    # Define placeholders if necessary, though this tool is useless outside Revit
    class Autodesk:
        class Revit:
            class DB:
                class ElementId:
                    def __init__(self, id_val): pass
                class FilteredElementCollector:
                    def __init__(self, doc): pass
                    def OfCategory(self, bic): return self
                    def WhereElementIsNotElementType(self): return self
                    def ToElements(self): return []
    class List:
        def __init__(self, type_param): pass
        def Add(self, item): pass

def select_elements(doc, uidoc, element_id_strings, logger):
    """
    Selects one or more elements in Revit given a list of their ID strings,
    or a single ID string.

    Args:
        doc (Autodesk.Revit.DB.Document): The active Revit Document object.
        uidoc (Autodesk.Revit.UIDocument): The active Revit UIDocument object.
        element_id_strings (list[str] or str): A list of element IDs as strings, or a single ID string.
        logger: Logger instance for logging messages.

    Returns:
        tuple: (response_dict, status_code)
               response_dict contains {"status": "success/error", "message": "...", "selected_ids": [...], "failed_ids": [...]} bogged down in the details
               status_code is the HTTP status code (e.g., 200, 400, 404, 500).
    """
    if not doc or not uidoc:
        logger.error("ElementSelectionTool: Document or UIDocument is not available.")
        return {"status": "error", "message": "Revit document or UI document not accessible."}, 500

    # Safety layer: if a single string ID is passed, convert it to a list.
    if isinstance(element_id_strings, basestring): # basestring handles str and unicode in Py2/IronPython
        logger.warning("ElementSelectionTool: element_id_strings received as a single string ('{}'). Converting to list.".format(element_id_strings))
        element_id_strings = [element_id_strings]
    elif not isinstance(element_id_strings, list):
        logger.warning("ElementSelectionTool: element_id_strings is not a list or a string. Type: {}. Value: {}".format(type(element_id_strings), element_id_strings))
        return {"status": "error", "message": "Invalid input: Element IDs must be provided as a list of strings or a single string ID."}, 400

    if not element_id_strings: # Empty list after potential conversion
        logger.info("ElementSelectionTool: No element IDs provided for selection after processing input.")
        # uidoc.Selection.SetElementIds(List[ElementId]()) # Optionally clear selection
        # logger.info("ElementSelectionTool: Cleared current selection as no IDs were provided.")
        return {"status": "success", "message": "No element IDs provided to select.", "data": {"selected_ids_processed": [], "failed_ids_details": []}}, 200

    revit_ids_to_select = List[ElementId]()
    successfully_selected_ids_str = []
    failed_ids_details = [] 

    for id_str in element_id_strings:
        if not isinstance(id_str, basestring): # Ensure items in list are strings
            logger.warning("ElementSelectionTool: Non-string item found in element_ids list: {}. Skipping.".format(id_str))
            failed_ids_details.append({"id": str(id_str) if id_str is not None else "None", "reason": "Invalid item type in list (not a string)"})
            continue
        try:
            element_id_int = int(id_str)
            revit_el_id = ElementId(element_id_int)
            element = doc.GetElement(revit_el_id)
            if element:
                revit_ids_to_select.Add(revit_el_id)
                successfully_selected_ids_str.append(id_str)
            else:
                logger.warning("ElementSelectionTool: Element with ID '{}' not found.".format(id_str))
                failed_ids_details.append({"id": id_str, "reason": "Not found"})
        except ValueError:
            logger.warning("ElementSelectionTool: Invalid Element ID format: '{}'. Must be an integer.".format(id_str))
            failed_ids_details.append({"id": id_str, "reason": "Invalid format"})
        except Exception as e_conv:
            logger.error("ElementSelectionTool: Error processing ID '{}': {}".format(id_str, e_conv))
            failed_ids_details.append({"id": id_str, "reason": "Processing error: {}".format(e_conv)})

    try:
        if revit_ids_to_select.Count > 0:
            uidoc.Selection.SetElementIds(revit_ids_to_select)
            logger.info("ElementSelectionTool: Successfully set selection for {} elements.".format(revit_ids_to_select.Count))
        elif not failed_ids_details and not successfully_selected_ids_str:
            # This case should mean the input list was empty or became empty after filtering non-strings.
            # The initial check for an empty element_id_strings list (after potential single string conversion)
            # should catch this. If it reaches here, it implies no valid IDs were processed.
            uidoc.Selection.SetElementIds(List[ElementId]()) # Clear selection
            logger.info("ElementSelectionTool: No valid elements to select from the provided input. Selection cleared.")
        # If there were failures but also successes, the selection of successes has already been made.
        # If only failures and no successes, Count would be 0, selection is cleared (or not changed if originally empty).

        message_parts = []
        if successfully_selected_ids_str:
            message_parts.append("Successfully processed {} IDs for selection: {}.".format(len(successfully_selected_ids_str), ", ".join(successfully_selected_ids_str)))
        if failed_ids_details:
            failure_reasons_str = ", ".join(["'{}' ({})".format(f["id"], f["reason"]) for f in failed_ids_details])
            message_parts.append("Failed to process {} IDs: {}.".format(len(failed_ids_details), failure_reasons_str))
        
        final_message = " " + " ".join(message_parts) if message_parts else "No elements processed or an empty list was provided."
        response_status = "success"
        http_status = 200
        
        if failed_ids_details and not successfully_selected_ids_str:
            response_status = "error" 
            if all(f["reason"] == "Not found" for f in failed_ids_details):
                http_status = 404 # All IDs were valid format but not found
            else:
                http_status = 400 # Mix of issues, or all invalid format
        elif failed_ids_details: # Some successes, some failures
            response_status = "partial_success" # Custom status to indicate mixed results

        return {
            "status": response_status, 
            "message": final_message.strip(),
            "data": {
                "selected_ids_processed": successfully_selected_ids_str,
                "failed_ids_details": failed_ids_details
            }
        }, http_status

    except Exception as e_main:
        logger.error("ElementSelectionTool: Major error during selection process: %s", e_main, exc_info=True)
        return {"status": "error", "message": "A critical error occurred in Revit during the element selection process: {}".format(e_main)}, 500 

def select_by_category(doc, uidoc, category_name_str, logger):
    """
    Selects all elements in Revit belonging to a specified category.

    Args:
        doc (Autodesk.Revit.DB.Document): The active Revit Document object.
        uidoc (Autodesk.Revit.UIDocument): The active Revit UIDocument object.
        category_name_str (str): The name of the category (e.g., "Windows", "OST_Walls").
        logger: Logger instance for logging messages.

    Returns:
        tuple: (response_dict, status_code)
               response_dict contains {"status": "success/error", "message": "...", "selected_count": X}
               status_code is the HTTP status code.
    """
    if not doc or not uidoc:
        logger.error("ElementSelectionTool: Document or UIDocument is not available for select_by_category.")
        return {"status": "error", "message": "Revit document or UI document not accessible."}, 500

    logger.info("ElementSelectionTool: Attempting to select elements by category: '{}'.".format(category_name_str))

    built_in_category = get_bic_by_name(category_name_str, logger) # Use the imported function

    if not built_in_category:
        logger.warning("ElementSelectionTool: Category '{}' not found or not recognized.".format(category_name_str))
        return {"status": "error", "message": "Category '{}' not found or not recognized.".format(category_name_str)}, 400
    
    try:
        collector = FilteredElementCollector(doc).OfCategory(built_in_category).WhereElementIsNotElementType()
        elements_to_select = collector.ToElements()
        
        element_ids_to_select = List[ElementId]()
        for el in elements_to_select:
            element_ids_to_select.Add(el.Id)
        
        if element_ids_to_select.Count > 0:
            uidoc.Selection.SetElementIds(element_ids_to_select)
            count = element_ids_to_select.Count
            logger.info("ElementSelectionTool: Successfully selected {} elements of category '{}'.".format(count, category_name_str))
            return {"status": "success", "message": "Selected {} elements of category '{}'.".format(count, category_name_str), "data": {"selected_count": count, "category_selected": category_name_str}}, 200
        else:
            uidoc.Selection.SetElementIds(List[ElementId]()) # Clear selection if no elements found
            logger.info("ElementSelectionTool: No elements found for category '{}'. Selection cleared.".format(category_name_str))
            return {"status": "success", "message": "No elements found to select for category '{}'.".format(category_name_str), "data": {"selected_count": 0, "category_selected": category_name_str}}, 200

    except Exception as e:
        logger.error("ElementSelectionTool: Error during selection by category '{}': {}".format(category_name_str, e), exc_info=True)
        return {"status": "error", "message": "An error occurred while selecting elements by category '{}': {}".format(category_name_str, e)}, 500 