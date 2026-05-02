# RevitMCP: This script runs in pyRevit (IronPython).
# -*- coding: UTF-8 -*-
"""
Sheet Placement Tool - handles creating sheets and placing views with viewports.
"""

try:
    import Autodesk
    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        FamilySymbol,
        ViewSheet,
        View,
        ViewFamily,
        ViewFamilyType,
        ViewType,
        BuiltInCategory,
        Transaction,
        ElementId,
        Viewport,
        XYZ,
        BoundingBoxUV,
        UV
    )
    from Autodesk.Revit.Creation import Application
    REVIT_API_AVAILABLE = True
except ImportError:
    print("ERROR (sheet_placement_tool): Revit API modules not found. This script must run in Revit.")
    REVIT_API_AVAILABLE = False
    # Placeholder for non-Revit environments
    FilteredElementCollector = None
    FamilySymbol = None
    ViewSheet = None
    View = None
    ViewFamily = None
    ViewFamilyType = None
    ViewType = None
    BuiltInCategory = None
    Transaction = None
    ElementId = None
    Viewport = None
    XYZ = None
    BoundingBoxUV = None
    UV = None


def find_views_by_name(doc, view_name, logger, exact_match=False):
    """
    Find views by name with fuzzy matching capability.
    
    Args:
        doc: Revit Document
        view_name (str): Name of the view to search for
        logger: Logger instance
        exact_match (bool): Whether to require exact name match
    
    Returns:
        list: List of matching View objects
    """
    if not doc or not view_name:
        logger.error("SheetPlacementTool: Invalid document or view name provided")
        return []
    
    try:
        # Collect all views in the document
        views = FilteredElementCollector(doc).OfClass(View).ToElements()
        matching_views = []
        
        view_name_lower = view_name.lower().strip()
        
        for view in views:
            if not hasattr(view, 'Name') or not view.Name:
                continue
                
            view_name_actual = view.Name.strip()
            
            if exact_match:
                if view_name_actual.lower() == view_name_lower:
                    matching_views.append(view)
            else:
                # Fuzzy matching - check if search term is contained in view name
                if view_name_lower in view_name_actual.lower():
                    matching_views.append(view)
        
        logger.info("SheetPlacementTool: Found {} matching view(s) for '{}'".format(len(matching_views), view_name))
        return matching_views
        
    except Exception as e:
        logger.error("SheetPlacementTool: Error finding views: {}".format(e), exc_info=True)
        return []


def get_titleblock_family_symbols(doc, logger):
    """
    Get available titleblock family symbols for sheet creation.
    
    Args:
        doc: Revit Document
        logger: Logger instance
    
    Returns:
        list: List of FamilySymbol objects that are titleblocks
    """
    try:
        # Collect all titleblock family symbols
        titleblocks = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_TitleBlocks)\
            .OfClass(FamilySymbol)\
            .ToElements()
        
        # Filter to only active/loaded symbols
        active_titleblocks = [tb for tb in titleblocks if tb.IsActive]
        
        logger.info("SheetPlacementTool: Found {} active titleblock family symbols".format(len(active_titleblocks)))
        return active_titleblocks
        
    except Exception as e:
        logger.error("SheetPlacementTool: Error getting titleblocks: {}".format(e), exc_info=True)
        return []


def find_next_sheet_number(doc, view_type_name, logger):
    """
    Find the next available sheet number based on existing sheets of similar type.
    
    Args:
        doc: Revit Document
        view_type_name (str): Type of view to base numbering on (e.g., "Detail", "Section", "Plan")
        logger: Logger instance
    
    Returns:
        str: Next available sheet number
    """
    try:
        # Get all existing sheets
        sheets = FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()
        
        # Extract sheet numbers and look for patterns
        sheet_numbers = []
        view_type_prefix = view_type_name.upper()[:1]  # D for Detail, S for Section, P for Plan, etc.
        
        for sheet in sheets:
            if hasattr(sheet, 'SheetNumber') and sheet.SheetNumber:
                sheet_num = sheet.SheetNumber.strip()
                sheet_numbers.append(sheet_num)
        
        logger.debug("SheetPlacementTool: Found {} existing sheets".format(len(sheet_numbers)))
        
        # Look for existing patterns with this view type prefix
        matching_numbers = []
        for num in sheet_numbers:
            if num.startswith(view_type_prefix):
                try:
                    # Extract numeric part after prefix
                    numeric_part = ''.join(filter(str.isdigit, num))
                    if numeric_part:
                        matching_numbers.append(int(numeric_part))
                except:
                    continue
        
        if matching_numbers:
            next_num = max(matching_numbers) + 1
            next_sheet_number = "{}{:03d}".format(view_type_prefix, next_num)
        else:
            # No existing sheets of this type, start with 001
            next_sheet_number = "{}{:03d}".format(view_type_prefix, 1)
        
        logger.info("SheetPlacementTool: Next sheet number: {}".format(next_sheet_number))
        return next_sheet_number
        
    except Exception as e:
        logger.error("SheetPlacementTool: Error finding next sheet number: {}".format(e), exc_info=True)
        return "S001"  # Fallback


def create_new_sheet(doc, sheet_number, sheet_name, titleblock_symbol, logger):
    """
    Create a new sheet with the specified parameters.
    
    Args:
        doc: Revit Document
        sheet_number (str): Sheet number
        sheet_name (str): Sheet name
        titleblock_symbol: FamilySymbol for titleblock
        logger: Logger instance
    
    Returns:
        ViewSheet: Created sheet or None if failed
    """
    try:
        # Create the sheet
        new_sheet = ViewSheet.Create(doc, titleblock_symbol.Id)
        
        if new_sheet:
            # Set sheet number and name
            new_sheet.SheetNumber = sheet_number
            new_sheet.Name = sheet_name
            
            logger.info("SheetPlacementTool: Created sheet '{}' - '{}'".format(sheet_number, sheet_name))
            return new_sheet
        else:
            logger.error("SheetPlacementTool: Failed to create sheet")
            return None
            
    except Exception as e:
        logger.error("SheetPlacementTool: Error creating sheet: {}".format(e), exc_info=True)
        return None


def get_sheet_center_point(sheet, logger):
    """
    Calculate the center point of a sheet for viewport placement.
    
    Args:
        sheet: ViewSheet object
        logger: Logger instance
    
    Returns:
        XYZ: Center point coordinates
    """
    try:
        # ViewSheet.Outline is a BoundingBoxUV (sheet space is 2-D), so its
        # Min/Max are UV objects exposing .U/.V — not XYZ with .X/.Y. The
        # final viewport placement still wants an XYZ, so we map U->X, V->Y
        # and pin Z to zero.
        outline = sheet.Outline
        if outline:
            min_point = outline.Min
            max_point = outline.Max

            center_u = (min_point.U + max_point.U) / 2.0
            center_v = (min_point.V + max_point.V) / 2.0
            center_point = XYZ(center_u, center_v, 0.0)

            logger.debug("SheetPlacementTool: Sheet center point: ({}, {})".format(center_u, center_v))
            return center_point
        else:
            # Fallback to a typical sheet center
            center_point = XYZ(0.5, 0.5, 0.0)
            logger.warning("SheetPlacementTool: Could not get sheet outline, using fallback center point")
            return center_point
            
    except Exception as e:
        logger.error("SheetPlacementTool: Error calculating sheet center: {}".format(e), exc_info=True)
        # Fallback center point
        return XYZ(0.5, 0.5, 0.0)


def place_view_on_sheet(doc, view, sheet, location_point, logger):
    """
    Place a view on a sheet as a viewport.
    
    Args:
        doc: Revit Document
        view: View to place
        sheet: ViewSheet to place view on
        location_point: XYZ point for viewport location
        logger: Logger instance
    
    Returns:
        Viewport: Created viewport or None if failed
    """
    try:
        # Pre-check that Revit will allow this placement. Catches dependent
        # views, already-placed views, view types that can't be sheeted
        # (legends with restrictions, schedules in some cases, etc.) before
        # we hit Viewport.Create with a generic exception.
        try:
            can_add = Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id)
        except Exception:
            can_add = True  # If the API call itself fails, fall through and let Create's exception speak

        if not can_add:
            already_on_sheet_name = None
            try:
                if hasattr(view, 'Sheet') and view.Sheet and view.Sheet.Id != ElementId.InvalidElementId:
                    already_on_sheet_name = view.Sheet.Name
            except Exception:
                already_on_sheet_name = None

            reason = (
                "already placed on sheet '{}'".format(already_on_sheet_name)
                if already_on_sheet_name
                else "Revit refused the placement (view type may not be eligible for this sheet)"
            )
            logger.warning(
                "SheetPlacementTool: Cannot place view '{}' on sheet '{}': {}".format(
                    view.Name, sheet.Name, reason,
                )
            )
            return None

        viewport = Viewport.Create(doc, sheet.Id, view.Id, location_point)

        if viewport:
            logger.info("SheetPlacementTool: Placed view '{}' on sheet '{}'".format(view.Name, sheet.Name))
            return viewport
        else:
            logger.warning("SheetPlacementTool: Viewport.Create returned None for view '{}'".format(view.Name))
            return None

    except Exception as e:
        logger.error("SheetPlacementTool: Error placing view on sheet: {}".format(e), exc_info=True)
        return None


def get_view_type_name(view, logger):
    """
    Get a human-readable name for the view type.
    
    Args:
        view: View object
        logger: Logger instance
    
    Returns:
        str: View type name
    """
    try:
        if hasattr(view, 'ViewType'):
            view_type = view.ViewType
            
            # Map common view types to readable names
            type_mapping = {
                ViewType.Detail: "Detail",
                ViewType.Section: "Section",
                ViewType.Elevation: "Elevation",
                ViewType.FloorPlan: "Plan",
                ViewType.CeilingPlan: "Ceiling Plan",
                ViewType.ThreeD: "3D View",
                ViewType.Schedule: "Schedule",
                ViewType.DrawingSheet: "Sheet",
                ViewType.Report: "Report",
                ViewType.DraftingView: "Drafting",
                ViewType.Legend: "Legend",
                ViewType.EngineeringPlan: "Engineering Plan",
                ViewType.AreaPlan: "Area Plan"
            }
            
            return type_mapping.get(view_type, str(view_type))
        else:
            return "Unknown"
            
    except Exception as e:
        logger.error("SheetPlacementTool: Error getting view type: {}".format(e), exc_info=True)
        return "Unknown"


def _find_target_sheet(doc, sheet_id=None, sheet_name=None, exact_match=False, logger=None):
    """Look up an existing ViewSheet by id or name.

    Returns (sheet, error_dict). If both are None, the caller should create a new sheet.
    """
    if sheet_id not in (None, "", 0, "0"):
        try:
            sheet_id_int = int(str(sheet_id).strip())
        except Exception:
            return None, {
                "status": "error",
                "message": "target_sheet_id must be an integer element id, got '{}'".format(sheet_id),
            }
        element = doc.GetElement(ElementId(sheet_id_int))
        if not element:
            return None, {
                "status": "error",
                "message": "No element with id {}.".format(sheet_id_int),
                "target_sheet_id": str(sheet_id_int),
            }
        if not isinstance(element, ViewSheet):
            return None, {
                "status": "error",
                "message": "Element {} is not a ViewSheet.".format(sheet_id_int),
                "target_sheet_id": str(sheet_id_int),
            }
        return element, None

    if sheet_name:
        sheets = list(FilteredElementCollector(doc).OfClass(ViewSheet).ToElements())
        sheet_name_str = str(sheet_name).strip()
        if exact_match:
            matches = [s for s in sheets if s.Name == sheet_name_str or s.SheetNumber == sheet_name_str]
        else:
            needle = sheet_name_str.lower()
            matches = [
                s for s in sheets
                if needle in s.Name.lower() or needle in s.SheetNumber.lower()
            ]
        if not matches:
            return None, {
                "status": "error",
                "message": "No sheets found matching '{}' (searched name and sheet number).".format(sheet_name_str),
                "target_sheet_name": sheet_name_str,
            }
        if len(matches) > 1:
            return None, {
                "status": "multiple_matches",
                "message": "Multiple sheets matched '{}'. Disambiguate by retrying with target_sheet_id.".format(sheet_name_str),
                "target_sheet_name": sheet_name_str,
                "matching_sheets": [
                    {"name": s.Name, "number": s.SheetNumber, "id": str(s.Id.IntegerValue)}
                    for s in matches
                ],
            }
        return matches[0], None

    return None, None


def _is_titleblock_symbol(symbol):
    try:
        category = getattr(symbol, "Category", None)
        if not category or not getattr(category, "Id", None):
            return False
        return category.Id.IntegerValue == int(BuiltInCategory.OST_TitleBlocks)
    except Exception:
        return False


def _titleblock_label(symbol):
    family_name = ""
    try:
        family = getattr(symbol, "Family", None)
        family_name = family.Name if family and getattr(family, "Name", None) else ""
    except Exception:
        family_name = ""
    type_name = getattr(symbol, "Name", "") or ""
    if family_name and type_name:
        return "{} : {}".format(family_name, type_name)
    return type_name or family_name


def _find_titleblock(doc, titleblock_id=None, titleblock_name=None, exact_match=False, logger=None):
    """Look up a titleblock FamilySymbol by id or name.

    Returns (symbol, error_dict). If both inputs are None, the caller should
    fall back to the first available titleblock (existing default behavior).
    """
    if titleblock_id not in (None, "", 0, "0"):
        try:
            tb_id_int = int(str(titleblock_id).strip())
        except Exception:
            return None, {
                "status": "error",
                "message": "titleblock_id must be an integer element id, got '{}'".format(titleblock_id),
            }
        element = doc.GetElement(ElementId(tb_id_int))
        if not element:
            return None, {
                "status": "error",
                "message": "No element with id {}.".format(tb_id_int),
                "titleblock_id": str(tb_id_int),
            }
        if not isinstance(element, FamilySymbol) or not _is_titleblock_symbol(element):
            actual_category = ""
            try:
                actual_category = element.Category.Name if element.Category else ""
            except Exception:
                actual_category = ""
            return None, {
                "status": "error",
                "message": "Element {} is not a titleblock FamilySymbol (category: '{}'). Discover titleblocks via list_family_types(category_names=[\"Title Blocks\"]).".format(
                    tb_id_int, actual_category
                ),
                "titleblock_id": str(tb_id_int),
            }
        return element, None

    if titleblock_name:
        name_str = str(titleblock_name).strip()
        if not name_str:
            return None, None

        symbols = [
            s for s in FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements()
            if _is_titleblock_symbol(s)
        ]

        def _match(symbol):
            label = _titleblock_label(symbol)
            family_name = ""
            try:
                family_name = symbol.Family.Name if symbol.Family else ""
            except Exception:
                family_name = ""
            type_name = getattr(symbol, "Name", "") or ""
            candidates = [label, family_name, type_name]
            if exact_match:
                return name_str in candidates
            needle = name_str.lower()
            return any(needle in (c or "").lower() for c in candidates)

        matches = [s for s in symbols if _match(s)]
        if not matches:
            return None, {
                "status": "error",
                "message": "No titleblock found matching '{}'. Discover via list_family_types(category_names=[\"Title Blocks\"]).".format(name_str),
                "titleblock_name": name_str,
            }
        if len(matches) > 1:
            return None, {
                "status": "multiple_matches",
                "message": "Multiple titleblocks matched '{}'. Disambiguate by retrying with titleblock_id.".format(name_str),
                "titleblock_name": name_str,
                "matching_titleblocks": [
                    {
                        "id": str(s.Id.IntegerValue),
                        "family_name": (s.Family.Name if s.Family else ""),
                        "type_name": getattr(s, "Name", ""),
                        "label": _titleblock_label(s),
                    }
                    for s in matches
                ],
            }
        return matches[0], None

    return None, None


def place_view_on_new_sheet(doc, view_name, logger, exact_match=False, view_id=None,
                             target_sheet_id=None, target_sheet_name=None,
                             titleblock_id=None, titleblock_name=None):
    """
    Find a view (by name or id) and place it on a sheet.

    By default a new sheet is created using the first available titleblock.
    Use titleblock_id (or titleblock_name) to specify a different one — discover
    available titleblocks with list_family_types(category_names=["Title Blocks"]).
    Use target_sheet_id (or target_sheet_name) to place onto an existing sheet
    instead of creating one (titleblock_* is then irrelevant).

    Args:
        doc: Revit Document
        view_name (str): Name of the view to place. Ignored when view_id is provided.
        logger: Logger instance
        exact_match (bool): Whether to require exact name match for view_name,
            target_sheet_name, and titleblock_name.
        view_id (str|int|None): Element ID of the view. Takes precedence over view_name.
        target_sheet_id (str|int|None): Element ID of an existing sheet to place onto.
        target_sheet_name (str|None): Name (or sheet number) of an existing sheet to place onto.
        titleblock_id (str|int|None): Element ID of a titleblock FamilySymbol to use
            for newly-created sheets. Takes precedence over titleblock_name.
        titleblock_name (str|None): Family or type name of a titleblock to use for
            newly-created sheets. Ignored if target_sheet_* is supplied.

    Returns:
        dict: Result dictionary with status and details. Sets sheet_was_created=true/false.
    """
    if not REVIT_API_AVAILABLE:
        return {"status": "error", "message": "Revit API not available"}

    try:
        if view_id not in (None, "", 0, "0"):
            try:
                view_id_int = int(str(view_id).strip())
            except Exception:
                return {
                    "status": "error",
                    "message": "view_id must be an integer element id, got '{}'".format(view_id),
                }
            element = doc.GetElement(ElementId(view_id_int))
            if not element:
                return {
                    "status": "error",
                    "message": "No view found with id {}.".format(view_id_int),
                    "view_id": str(view_id_int),
                }
            if not hasattr(element, "ViewType"):
                return {
                    "status": "error",
                    "message": "Element {} exists but is not a view (got {}).".format(
                        view_id_int, type(element).__name__
                    ),
                    "view_id": str(view_id_int),
                }
            matching_views = [element]
            view_name = element.Name
        else:
            matching_views = find_views_by_name(doc, view_name, logger, exact_match)

        if not matching_views:
            return {
                "status": "error",
                "message": "No views found matching '{}'".format(view_name),
                "view_name": view_name
            }

        if len(matching_views) > 1:
            # Revit permits duplicate view names across types, and dependent
            # views share their parent's name. When the caller can't be made
            # unique by name, they should retry with view_id.
            return {
                "status": "multiple_matches",
                "message": "Multiple views found matching '{}'. Disambiguate by retrying with view_id.".format(view_name),
                "view_name": view_name,
                "exact_match": bool(exact_match),
                "matching_views": [
                    {"name": v.Name, "type": get_view_type_name(v, logger), "id": str(v.Id.IntegerValue)}
                    for v in matching_views
                ],
            }

        # Single view found - proceed with placement
        view_to_place = matching_views[0]
        view_type_name = get_view_type_name(view_to_place, logger)

        # If caller pointed at an existing sheet, look it up before opening a transaction.
        existing_sheet = None
        if target_sheet_id or target_sheet_name:
            existing_sheet, sheet_error = _find_target_sheet(
                doc,
                sheet_id=target_sheet_id,
                sheet_name=target_sheet_name,
                exact_match=exact_match,
                logger=logger,
            )
            if sheet_error:
                return sheet_error

        # Titleblock + sheet number/name only matter when creating a new sheet.
        titleblock = None
        sheet_number = None
        sheet_name_for_new = None
        if existing_sheet is None:
            if titleblock_id or titleblock_name:
                titleblock, titleblock_error = _find_titleblock(
                    doc,
                    titleblock_id=titleblock_id,
                    titleblock_name=titleblock_name,
                    exact_match=exact_match,
                    logger=logger,
                )
                if titleblock_error:
                    return titleblock_error
            else:
                titleblocks = get_titleblock_family_symbols(doc, logger)
                if not titleblocks:
                    return {
                        "status": "error",
                        "message": "No titleblock family symbols found. Cannot create sheet.",
                        "view_name": view_name,
                    }
                titleblock = titleblocks[0]
            sheet_number = find_next_sheet_number(doc, view_type_name, logger)
            sheet_name_for_new = "{} - {}".format(view_type_name, view_to_place.Name)
        elif titleblock_id or titleblock_name:
            logger.warning(
                "SheetPlacementTool: titleblock_* ignored because target_sheet_* was supplied; existing sheet keeps its current titleblock."
            )

        transaction_label = "Place View on Existing Sheet" if existing_sheet else "Place View on New Sheet"
        with Transaction(doc, transaction_label) as t:
            t.Start()

            try:
                if existing_sheet is not None:
                    target_sheet = existing_sheet
                else:
                    target_sheet = create_new_sheet(doc, sheet_number, sheet_name_for_new, titleblock, logger)
                    if not target_sheet:
                        t.RollBack()
                        return {
                            "status": "error",
                            "message": "Failed to create new sheet",
                            "view_name": view_name,
                        }

                center_point = get_sheet_center_point(target_sheet, logger)

                viewport = place_view_on_sheet(doc, view_to_place, target_sheet, center_point, logger)
                if not viewport:
                    t.RollBack()
                    already_on_sheet = None
                    try:
                        if hasattr(view_to_place, 'Sheet') and view_to_place.Sheet and view_to_place.Sheet.Id != ElementId.InvalidElementId:
                            already_on_sheet = {
                                "id": str(view_to_place.Sheet.Id.IntegerValue),
                                "name": view_to_place.Sheet.Name,
                                "number": view_to_place.Sheet.SheetNumber,
                            }
                    except Exception:
                        already_on_sheet = None
                    return {
                        "status": "error",
                        "message": (
                            "Revit refused to place view '{}' on the sheet. {}".format(
                                view_to_place.Name,
                                "It is already placed on sheet '{} - {}'.".format(
                                    already_on_sheet["number"], already_on_sheet["name"]
                                ) if already_on_sheet else
                                "Likely cause: dependent view, ineligible view type, or already-placed view."
                            )
                        ),
                        "view_name": view_to_place.Name,
                        "view_id": str(view_to_place.Id.IntegerValue),
                        "already_on_sheet": already_on_sheet,
                    }

                t.Commit()

                sheet_was_created = existing_sheet is None
                result = {
                    "status": "success",
                    "view_name": view_to_place.Name,
                    "view_type": view_type_name,
                    "sheet_id": str(target_sheet.Id.IntegerValue),
                    "sheet_number": target_sheet.SheetNumber,
                    "sheet_name": target_sheet.Name,
                    "sheet_was_created": sheet_was_created,
                    "viewport_id": str(viewport.Id.IntegerValue),
                }
                if sheet_was_created:
                    result["message"] = "Successfully placed view '{}' on new sheet '{}'".format(
                        view_to_place.Name, target_sheet.SheetNumber
                    )
                    result["titleblock_used"] = {
                        "id": str(titleblock.Id.IntegerValue),
                        "family_name": titleblock.Family.Name if titleblock.Family else "",
                        "type_name": getattr(titleblock, "Name", ""),
                        "label": _titleblock_label(titleblock),
                    }
                else:
                    result["message"] = "Successfully placed view '{}' on existing sheet '{} - {}'".format(
                        view_to_place.Name, target_sheet.SheetNumber, target_sheet.Name
                    )
                return result

            except Exception as transaction_error:
                t.RollBack()
                logger.error("SheetPlacementTool: Transaction failed: {}".format(transaction_error), exc_info=True)
                return {
                    "status": "error",
                    "message": "Transaction failed: {}".format(str(transaction_error)),
                    "view_name": view_name,
                }
        
    except Exception as e:
        logger.error("SheetPlacementTool: Error in place_view_on_new_sheet: {}".format(e), exc_info=True)
        return {
            "status": "error",
            "message": "Unexpected error: {}".format(str(e)),
            "view_name": view_name
        } 