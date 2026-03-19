# RevitMCP: Element-related HTTP routes
# -*- coding: UTF-8 -*-

import difflib
import re
import unicodedata

import System
from pyrevit import routes, script, DB
from System.Collections.Generic import List


def _coerce_text(value):
    if value is None:
        return ""

    try:
        text = str(value)
    except Exception:
        return ""

    text = text.replace(u"\u00A0", " ").replace(u"\u2007", " ").replace(u"\u202F", " ")
    return unicodedata.normalize("NFKC", text)


def _collapse_whitespace(value):
    return re.sub(r"\s+", " ", _coerce_text(value)).strip()


def _normalize_category_key(value):
    text = _collapse_whitespace(value).lower()
    if text.startswith("ost_"):
        text = text[4:]
    return re.sub(r"[^a-z0-9]+", "", text)


def _get_built_in_category_lookup():
    lookup = {}
    try:
        category_names = list(System.Enum.GetNames(DB.BuiltInCategory))
    except Exception:
        category_names = [name for name in dir(DB.BuiltInCategory) if name.startswith("OST_")]

    for category_name in category_names:
        if not hasattr(DB.BuiltInCategory, category_name):
            continue
        built_in_category = getattr(DB.BuiltInCategory, category_name)
        lookup.setdefault(_normalize_category_key(category_name), built_in_category)
        lookup.setdefault(_normalize_category_key(category_name[4:]), built_in_category)

    return lookup


def _get_document_category_lookup(doc):
    lookup = {}
    if not doc:
        return lookup

    try:
        for category in doc.Settings.Categories:
            category_name = getattr(category, "Name", None)
            normalized_key = _normalize_category_key(category_name)
            if not normalized_key:
                continue

            built_in_category = None
            try:
                built_in_category = System.Enum.ToObject(DB.BuiltInCategory, category.Id.IntegerValue)
            except Exception:
                built_in_category = None

            lookup.setdefault(normalized_key, []).append(
                {
                    "name": category_name,
                    "built_in_category": built_in_category,
                }
            )
    except Exception:
        return lookup

    return lookup


def _suggest_category_names(doc, category_name, limit=5):
    normalized_query = _normalize_category_key(category_name)
    if not normalized_query or not doc:
        return []

    suggestions = []
    seen = set()

    try:
        for category in doc.Settings.Categories:
            actual_name = getattr(category, "Name", None)
            normalized_candidate = _normalize_category_key(actual_name)
            if not actual_name or not normalized_candidate or actual_name in seen:
                continue

            seen.add(actual_name)
            score = difflib.SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
            if normalized_query in normalized_candidate:
                score += 0.15
            suggestions.append((score, actual_name))
    except Exception:
        return []

    suggestions.sort(key=lambda item: (-item[0], item[1]))
    return [name for score, name in suggestions if score >= 0.35][:limit]


def _resolve_built_in_category(category_name, route_logger, doc=None):
    if not category_name:
        return None

    raw_name = _collapse_whitespace(category_name)
    if hasattr(DB.BuiltInCategory, raw_name):
        return getattr(DB.BuiltInCategory, raw_name)

    normalized_key = _normalize_category_key(raw_name)
    if not normalized_key:
        return None

    document_category_lookup = _get_document_category_lookup(doc)
    document_matches = document_category_lookup.get(normalized_key, [])
    for match in document_matches:
        built_in_category = match.get("built_in_category")
        if built_in_category is not None:
            if match.get("name") != raw_name:
                route_logger.info(
                    "Interpreted category '%s' as document category '%s'.",
                    category_name,
                    match.get("name"),
                )
            return built_in_category

    built_in_lookup = _get_built_in_category_lookup()
    built_in_category = built_in_lookup.get(normalized_key)
    if built_in_category is not None:
        route_logger.info("Resolved category '%s' via normalized BuiltInCategory lookup.", category_name)
        return built_in_category

    if not raw_name.upper().startswith("OST_"):
        possible_ost = "OST_" + re.sub(r"[^A-Za-z0-9]+", "", raw_name)
        if hasattr(DB.BuiltInCategory, possible_ost):
            route_logger.info("Interpreted category '%s' as '%s'.", category_name, possible_ost)
            return getattr(DB.BuiltInCategory, possible_ost)

    return None


def _find_parameter(element, param_name):
    # First try direct lookup by displayed parameter name.
    p = element.LookupParameter(param_name)
    if p:
        return p

    # Then try built-in enum name conversion.
    try:
        enum_name = param_name.replace(" ", "_").upper()
        if hasattr(DB.BuiltInParameter, enum_name):
            return element.get_Parameter(getattr(DB.BuiltInParameter, enum_name))
    except Exception:
        pass

    # Fallback to manual scan with case-insensitive matching.
    target_name = str(param_name or "").strip().lower()
    for item in element.Parameters:
        if item and item.Definition and item.Definition.Name:
            if item.Definition.Name == param_name:
                return item
            if str(item.Definition.Name).strip().lower() == target_name:
                return item

    return None


def _get_parameter_display_value(param, doc):
    if not param or not param.HasValue:
        return "Not available"

    try:
        if param.StorageType == DB.StorageType.String:
            return param.AsString() or ""

        if param.StorageType == DB.StorageType.Double:
            return param.AsValueString() or str(param.AsDouble())

        if param.StorageType == DB.StorageType.Integer:
            return str(param.AsInteger())

        if param.StorageType == DB.StorageType.ElementId:
            elem_id = param.AsElementId()
            if elem_id != DB.ElementId.InvalidElementId:
                ref_elem = doc.GetElement(elem_id)
                if ref_elem:
                    name = getattr(ref_elem, "Name", None)
                    return name if name else str(elem_id.IntegerValue)
                return str(elem_id.IntegerValue)
            return "None"

        return param.AsValueString() or ""
    except Exception:
        return "Not available"


def _get_parameter_typed_value(param, doc):
    typed_value = {
        "display_value": _get_parameter_display_value(param, doc),
        "storage_type": None,
        "has_value": bool(param and getattr(param, "HasValue", False)),
        "is_numeric": False,
    }

    if not param:
        return typed_value

    try:
        typed_value["storage_type"] = str(param.StorageType)
    except Exception:
        typed_value["storage_type"] = None

    if not getattr(param, "HasValue", False):
        return typed_value

    try:
        if param.StorageType == DB.StorageType.Double:
            typed_value["is_numeric"] = True
            typed_value["numeric_value"] = float(param.AsDouble())
        elif param.StorageType == DB.StorageType.Integer:
            typed_value["is_numeric"] = True
            typed_value["numeric_value"] = int(param.AsInteger())
    except Exception:
        typed_value["is_numeric"] = False
        typed_value.pop("numeric_value", None)

    return typed_value


def _is_meaningful_value(value):
    text = "" if value is None else str(value).strip()
    if not text:
        return False
    if text.lower() in ("not available", "none", "null"):
        return False
    return True


def _parse_length_to_internal_feet(value):
    value_str = _collapse_whitespace(value)
    if not value_str:
        raise ValueError("Length value is empty.")

    if "'" in value_str or '"' in value_str:
        feet = 0.0
        inches = 0.0

        if "'" in value_str:
            feet_part = value_str.split("'")[0].strip()
            feet = float(feet_part) if feet_part else 0.0

        if '"' in value_str:
            inches_part = value_str
            if "'" in value_str:
                inches_part = value_str.split("'")[1]
            inches_part = inches_part.replace('"', '').strip()
            inches = float(inches_part) if inches_part else 0.0

        return feet + (inches / 12.0)

    normalized_value = value_str.lower()
    unit_match = re.match(
        r"^([-+]?\d*\.?\d+)\s*(millimeters|millimeter|mm|centimeters|centimeter|cm|meters|meter|m|feet|foot|ft|inches|inch|in)?$",
        normalized_value,
    )
    if not unit_match:
        return float(value_str)

    magnitude = float(unit_match.group(1))
    unit = unit_match.group(2)
    if not unit:
        return magnitude

    if unit in ("millimeters", "millimeter", "mm"):
        return magnitude / 304.8
    if unit in ("centimeters", "centimeter", "cm"):
        return magnitude / 30.48
    if unit in ("meters", "meter", "m"):
        return magnitude / 0.3048
    if unit in ("inches", "inch", "in"):
        return magnitude / 12.0
    if unit in ("feet", "foot", "ft"):
        return magnitude

    return magnitude


def _set_parameter_value(param, new_value):
    if param.StorageType == DB.StorageType.String:
        param.Set(str(new_value))
        return True, None

    if param.StorageType == DB.StorageType.Double:
        try:
            param.Set(_parse_length_to_internal_feet(new_value))
            return True, None
        except Exception:
            return False, "Could not convert '{}' to number".format(new_value)

    if param.StorageType == DB.StorageType.Integer:
        try:
            param.Set(int(float(new_value)))
            return True, None
        except Exception:
            return False, "Could not convert '{}' to integer".format(new_value)

    return False, "Unsupported parameter type: {}".format(param.StorageType)


def _normalize_element_ids(raw_ids):
    """Parse incoming element IDs to a list of valid DB.ElementId values."""
    valid_ids = List[DB.ElementId]()
    requested_count = 0
    invalid_ids = []

    if raw_ids is None:
        return valid_ids, requested_count, invalid_ids

    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]

    for raw_id in raw_ids:
        requested_count += 1
        try:
            element_id_int = int(str(raw_id).strip())
            if element_id_int > 0:
                valid_ids.Add(DB.ElementId(element_id_int))
            else:
                invalid_ids.append(str(raw_id))
        except Exception:
            invalid_ids.append(str(raw_id))

    return valid_ids, requested_count, invalid_ids


def _normalize_filter_operator(operator):
    alias_map = {
        None: "equals",
        "": "equals",
        "equals": "equals",
        "==": "equals",
        "contains": "contains",
        "not_equals": "not_equals",
        "not equal": "not_equals",
        "!=": "not_equals",
        "starts_with": "starts_with",
        "ends_with": "ends_with",
        "greater_than": "greater_than",
        ">": "greater_than",
        "greater_than_or_equal": "greater_than_or_equal",
        ">=": "greater_than_or_equal",
        "less_than": "less_than",
        "<": "less_than",
        "less_than_or_equal": "less_than_or_equal",
        "<=": "less_than_or_equal",
    }
    return alias_map.get(str(operator or "").strip().lower())


def _is_numeric_operator(operator):
    return operator in ("greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal")


def _compare_numeric_values(candidate_value, expected_value, operator):
    if operator == "greater_than":
        return candidate_value > expected_value
    if operator == "greater_than_or_equal":
        return candidate_value >= expected_value
    if operator == "less_than":
        return candidate_value < expected_value
    if operator == "less_than_or_equal":
        return candidate_value <= expected_value
    return False


def _evaluate_parameter_filter(param, expected_value, operator, doc):
    normalized_operator = _normalize_filter_operator(operator)
    if not normalized_operator:
        return False, "Unsupported filter operator '{}'.".format(operator)

    if not param:
        return False, None

    param_name = "Unknown Parameter"
    try:
        if param.Definition and param.Definition.Name:
            param_name = param.Definition.Name
    except Exception:
        pass

    if _is_numeric_operator(normalized_operator):
        if not getattr(param, "HasValue", False):
            return False, None

        if param.StorageType == DB.StorageType.Double:
            try:
                candidate_value = float(param.AsDouble())
                expected_numeric = _parse_length_to_internal_feet(expected_value)
            except Exception:
                return (
                    False,
                    "Could not parse numeric filter value '{}'. Use a plain number or an explicit length such as 2000 mm, 2 m, or 6' 6\".".format(
                        expected_value
                    ),
                )
            return _compare_numeric_values(candidate_value, expected_numeric, normalized_operator), None

        if param.StorageType == DB.StorageType.Integer:
            try:
                candidate_value = int(param.AsInteger())
                expected_numeric = float(_collapse_whitespace(expected_value))
            except Exception:
                return (
                    False,
                    "Could not parse numeric filter value '{}'. Integer filters require a numeric value.".format(
                        expected_value
                    ),
                )
            return _compare_numeric_values(float(candidate_value), float(expected_numeric), normalized_operator), None

        return (
            False,
            "Parameter '{}' is not numeric/filterable with operator '{}'.".format(param_name, normalized_operator),
        )

    current_value = _get_parameter_display_value(param, doc)
    current_text = str(current_value or "")
    expected_text = str(expected_value)

    current_cmp = current_text.lower()
    expected_cmp = expected_text.lower()

    if normalized_operator == "equals":
        return current_cmp == expected_cmp, None
    if normalized_operator == "contains":
        return expected_cmp in current_cmp, None
    if normalized_operator == "not_equals":
        return current_cmp != expected_cmp, None
    if normalized_operator == "starts_with":
        return current_cmp.startswith(expected_cmp), None
    if normalized_operator == "ends_with":
        return current_cmp.endswith(expected_cmp), None

    return False, "Unsupported filter operator '{}'.".format(operator)


def _append_parameter_property(properties, typed_properties, param_name, param, doc, populated_only=False):
    display_value = _get_parameter_display_value(param, doc) if param else "Not available"
    if populated_only and not _is_meaningful_value(display_value):
        return

    properties[param_name] = display_value
    typed_properties[param_name] = _get_parameter_typed_value(param, doc)


def _get_element_identity(element, doc):
    family_name = "Not available"
    type_name = "Not available"

    try:
        symbol = getattr(element, "Symbol", None)
    except Exception:
        symbol = None

    try:
        if not symbol and doc and hasattr(element, "GetTypeId"):
            type_id = element.GetTypeId()
            if type_id and type_id != DB.ElementId.InvalidElementId:
                symbol = doc.GetElement(type_id)
    except Exception:
        symbol = symbol if symbol else None

    try:
        if symbol:
            if hasattr(symbol, "Name") and symbol.Name:
                type_name = symbol.Name
            family = getattr(symbol, "Family", None)
            if family and hasattr(family, "Name") and family.Name:
                family_name = family.Name
    except Exception:
        pass

    display_name = None
    try:
        display_name = getattr(element, "Name", None)
    except Exception:
        display_name = None

    if not display_name:
        if type_name != "Not available":
            display_name = type_name
        else:
            display_name = str(element.Id.IntegerValue)

    return display_name, family_name, type_name


def _build_element_summary(element, doc):
    category_name = "No Category"
    try:
        if element.Category and element.Category.Name:
            category_name = element.Category.Name
    except Exception:
        pass

    display_name, family_name, type_name = _get_element_identity(element, doc)

    summary = {
        "element_id": str(element.Id.IntegerValue),
        "name": display_name,
        "category": category_name
    }

    if family_name != "Not available":
        summary["family_name"] = family_name
    if type_name != "Not available":
        summary["type_name"] = type_name
    if family_name != "Not available" and type_name != "Not available":
        summary["family_and_type"] = "{} : {}".format(family_name, type_name)

    try:
        summary["class_name"] = element.GetType().Name
    except Exception:
        pass

    return summary


def register_routes(api):
    """Register all element-related routes with the API"""

    @api.route('/views/active/info', methods=['GET'])
    def handle_get_active_view_info(request):
        route_logger = script.get_logger()

        try:
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})

            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            active_view = uidoc.ActiveView

            if not active_view:
                return routes.Response(status=503, data={"error": "No active Revit view"})

            associated_level = None
            try:
                gen_level = getattr(active_view, "GenLevel", None)
                if gen_level and hasattr(gen_level, "Name") and gen_level.Name:
                    associated_level = gen_level.Name
            except Exception:
                associated_level = None

            if not associated_level:
                try:
                    level_id = getattr(active_view, "LevelId", DB.ElementId.InvalidElementId)
                    if level_id and level_id != DB.ElementId.InvalidElementId:
                        level = doc.GetElement(level_id)
                        if level and hasattr(level, "Name") and level.Name:
                            associated_level = level.Name
                except Exception:
                    associated_level = None

            view_info = {
                "id": str(active_view.Id.IntegerValue),
                "name": active_view.Name,
                "type": str(active_view.ViewType),
                "scale": int(getattr(active_view, "Scale", 0) or 0),
                "is_template": bool(getattr(active_view, "IsTemplate", False)),
                "can_be_printed": bool(getattr(active_view, "CanBePrinted", False))
            }

            if associated_level:
                view_info["associated_level"] = associated_level

            try:
                view_family = getattr(active_view, "ViewFamily", None)
                if view_family is not None:
                    view_info["family"] = str(view_family)
            except Exception:
                pass

            try:
                detail_level = getattr(active_view, "DetailLevel", None)
                if detail_level is not None:
                    view_info["detail_level"] = str(detail_level)
            except Exception:
                pass

            try:
                display_style = getattr(active_view, "DisplayStyle", None)
                if display_style is not None:
                    view_info["display_style"] = str(display_style)
            except Exception:
                pass

            return {
                "status": "success",
                "message": "Retrieved active view metadata.",
                "doc": {
                    "title": doc.Title,
                    "path": doc.PathName
                },
                "view": view_info
            }

        except Exception as e:
            route_logger.critical("Error in /views/active/info: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    @api.route('/views/active/elements', methods=['POST'])
    def handle_get_active_view_elements(request):
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else {}
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            category_names = payload.get('category_names', []) or []
            if isinstance(category_names, str):
                category_names = [category_names]
            elif not isinstance(category_names, list):
                return routes.Response(status=400, data={"error": "'category_names' must be a list of strings"})

            try:
                limit = int(payload.get('limit', 200))
            except Exception:
                limit = 200
            limit = max(1, min(2000, limit))

            requested_categories = [_normalize_category_key(name) for name in category_names if str(name or "").strip()]

            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})

            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            active_view = uidoc.ActiveView

            collector = DB.FilteredElementCollector(doc, active_view.Id).WhereElementIsNotElementType()

            element_ids = []
            elements = []
            total_count = 0

            for element in collector:
                try:
                    category_name = element.Category.Name if element.Category and element.Category.Name else ""
                except Exception:
                    category_name = ""

                if requested_categories and _normalize_category_key(category_name) not in requested_categories:
                    continue

                total_count += 1
                if len(element_ids) >= limit:
                    continue

                element_ids.append(str(element.Id.IntegerValue))
                elements.append(_build_element_summary(element, doc))

            return {
                "status": "success",
                "message": "Found {} matching elements in the active view.".format(total_count),
                "view": {
                    "id": str(active_view.Id.IntegerValue),
                    "name": active_view.Name,
                    "type": str(active_view.ViewType)
                },
                "category_filters": category_names,
                "limit": limit,
                "total_count": total_count,
                "returned_count": len(element_ids),
                "truncated": total_count > len(element_ids),
                "element_ids": element_ids,
                "elements": elements
            }

        except Exception as e:
            route_logger.critical("Error in /views/active/elements: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    @api.route('/selection/active', methods=['POST'])
    def handle_get_active_selection(request):
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else {}
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            try:
                limit = int(payload.get('limit', 200))
            except Exception:
                limit = 200
            limit = max(1, min(2000, limit))

            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})

            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document
            selected_ids = uidoc.Selection.GetElementIds()

            element_ids = []
            elements = []
            total_count = 0

            for elem_id in selected_ids:
                total_count += 1
                if len(element_ids) >= limit:
                    continue

                element = doc.GetElement(elem_id)
                if not element:
                    continue

                element_ids.append(str(elem_id.IntegerValue))
                elements.append(_build_element_summary(element, doc))

            return {
                "status": "success",
                "message": "Read {} elements from the current Revit selection.".format(total_count),
                "limit": limit,
                "total_count": total_count,
                "returned_count": len(element_ids),
                "truncated": total_count > len(element_ids),
                "element_ids": element_ids,
                "elements": elements
            }

        except Exception as e:
            route_logger.critical("Error in /selection/active: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    @api.route('/families/types', methods=['POST'])
    def handle_list_family_types(request):
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else {}
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            category_names = payload.get('category_names', []) or []
            if isinstance(category_names, str):
                category_names = [category_names]
            elif not isinstance(category_names, list):
                return routes.Response(status=400, data={"error": "'category_names' must be a list of strings"})

            family_name_contains = str(payload.get('family_name_contains') or "").strip().lower()
            type_name_contains = str(payload.get('type_name_contains') or "").strip().lower()

            try:
                limit = int(payload.get('limit', 150))
            except Exception:
                limit = 150
            limit = max(1, min(2000, limit))

            requested_categories = [_normalize_category_key(name) for name in category_names if str(name or "").strip()]

            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})

            doc = current_uiapp.ActiveUIDocument.Document
            symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).ToElements()

            family_types = []
            total_count = 0

            for symbol in symbols:
                try:
                    family = getattr(symbol, "Family", None)
                    family_name = family.Name if family and hasattr(family, "Name") and family.Name else ""
                    type_name = symbol.Name if hasattr(symbol, "Name") and symbol.Name else ""
                    category = getattr(symbol, "Category", None)
                    category_name = category.Name if category and hasattr(category, "Name") and category.Name else ""

                    if requested_categories and _normalize_category_key(category_name) not in requested_categories:
                        continue
                    if family_name_contains and family_name_contains not in family_name.lower():
                        continue
                    if type_name_contains and type_name_contains not in type_name.lower():
                        continue

                    total_count += 1
                    if len(family_types) >= limit:
                        continue

                    family_types.append({
                        "symbol_id": str(symbol.Id.IntegerValue),
                        "category": category_name or "No Category",
                        "family_name": family_name or "Unnamed Family",
                        "type_name": type_name or "Unnamed Type",
                        "family_and_type": "{} : {}".format(family_name or "Unnamed Family", type_name or "Unnamed Type"),
                        "is_active": bool(getattr(symbol, "IsActive", False))
                    })
                except Exception:
                    continue

            return {
                "status": "success",
                "message": "Matched {} family types in the current document.".format(total_count),
                "category_filters": category_names,
                "family_name_contains": payload.get('family_name_contains'),
                "type_name_contains": payload.get('type_name_contains'),
                "limit": limit,
                "total_count": total_count,
                "returned_count": len(family_types),
                "truncated": total_count > len(family_types),
                "family_types": family_types
            }

        except Exception as e:
            route_logger.critical("Error in /families/types: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

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
            doc = current_uiapp.ActiveUIDocument.Document

            # Category validation and element collection
            built_in_category = _resolve_built_in_category(category_name_payload, route_logger, doc=doc)
            if not built_in_category:
                route_logger.error("Invalid category_name: '{}'. Not a recognized BuiltInCategory.".format(category_name_payload))
                return routes.Response(
                    status=400,
                    data={
                        "error": "Invalid category_name: '{}'.".format(category_name_payload),
                        "suggestions": _suggest_category_names(doc, category_name_payload),
                    },
                )

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

    @api.route('/select_elements_by_id', methods=['POST'])
    def handle_select_elements_by_id(request):
        """Select provided element IDs in the active document."""
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            raw_ids = payload.get('element_ids')
            if not raw_ids:
                return routes.Response(status=400, data={"error": "Missing 'element_ids'"})

            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active Revit UI document"})

            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document

            candidate_ids, requested_count, invalid_ids = _normalize_element_ids(raw_ids)
            valid_existing_ids = List[DB.ElementId]()
            selected_ids_processed = []

            for elem_id in candidate_ids:
                if doc.GetElement(elem_id):
                    valid_existing_ids.Add(elem_id)
                    selected_ids_processed.append(str(elem_id.IntegerValue))

            uidoc.Selection.SetElementIds(List[DB.ElementId]())
            uidoc.Selection.SetElementIds(valid_existing_ids)

            try:
                uidoc.RefreshActiveView()
            except Exception:
                pass

            return {
                "status": "success",
                "message": "Selected {} elements.".format(valid_existing_ids.Count),
                "requested_count": requested_count,
                "selected_count": valid_existing_ids.Count,
                "invalid_ids": invalid_ids,
                "selected_ids_processed": selected_ids_processed
            }

        except Exception as e:
            route_logger.critical("Error in /select_elements_by_id: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    @api.route('/select_elements_focused', methods=['POST'])
    def handle_select_elements_focused(request):
        """
        Focused selection route used by external server.
        Currently mirrors /select_elements_by_id behavior and keeps selection active.
        """
        return handle_select_elements_by_id(request)

    @api.route('/elements/filter', methods=['POST'])
    def handle_filter_elements(request):
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            category_name = payload.get('category_name')
            if not category_name:
                return routes.Response(status=400, data={"error": "Missing 'category_name'"})

            level_name = payload.get('level_name')
            parameter_filters = payload.get('parameters', [])

            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})

            doc = current_uiapp.ActiveUIDocument.Document

            built_in_category = _resolve_built_in_category(category_name, route_logger, doc=doc)
            if not built_in_category:
                return routes.Response(
                    status=400,
                    data={
                        "error": "Invalid category_name: '{}'.".format(category_name),
                        "suggestions": _suggest_category_names(doc, category_name),
                    },
                )

            collector = DB.FilteredElementCollector(doc).OfCategory(built_in_category).WhereElementIsNotElementType()

            if level_name:
                levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
                target_level = None
                for level in levels:
                    if level.Name == level_name or level.Name.lower() == str(level_name).lower():
                        target_level = level
                        break

                if not target_level:
                    level_names = [lvl.Name for lvl in levels]
                    return routes.Response(
                        status=400,
                        data={
                            "error": "Level '{}' not found".format(level_name),
                            "available_levels": level_names[:50]
                        }
                    )

                collector = collector.WherePasses(DB.ElementLevelFilter(target_level.Id))

            elements = collector.ToElements()
            route_logger.info("Found {} elements before parameter filtering".format(len(elements)))

            filtered_elements = []
            filter_error = None
            for element in elements:
                include_element = True

                for param_filter in parameter_filters:
                    param_name = param_filter.get('name')
                    expected_value = param_filter.get('value')
                    condition = param_filter.get('operator') or param_filter.get('condition') or 'equals'

                    if not param_name or expected_value is None:
                        continue

                    param = _find_parameter(element, param_name)
                    matched, filter_error = _evaluate_parameter_filter(param, expected_value, condition, doc)
                    if filter_error:
                        break

                    if not matched:
                        include_element = False
                        break

                if filter_error:
                    return routes.Response(status=400, data={"error": filter_error})

                if include_element:
                    filtered_elements.append(element)

            element_ids = [str(elem.Id.IntegerValue) for elem in filtered_elements]

            return {
                "status": "success",
                "message": "Found {} elements matching filter criteria.".format(len(element_ids)),
                "count": len(element_ids),
                "category": category_name,
                "level": level_name if level_name else "Any",
                "parameter_filters": parameter_filters,
                "element_ids": element_ids
            }

        except Exception as e:
            route_logger.critical("Error in /elements/filter: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    @api.route('/elements/get_properties', methods=['POST'])
    def handle_get_element_properties(request):
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            element_ids_list = payload.get('element_ids')
            if not element_ids_list:
                return routes.Response(status=400, data={"error": "Missing 'element_ids'"})

            parameter_names = payload.get('parameter_names', [])
            include_all_parameters = bool(payload.get('include_all_parameters', False))
            populated_only = bool(payload.get('populated_only', False))

            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})

            doc = current_uiapp.ActiveUIDocument.Document
            results = []

            for id_str in element_ids_list:
                try:
                    element = doc.GetElement(DB.ElementId(int(id_str)))
                    if not element:
                        results.append({"element_id": id_str, "error": "Element not found", "properties": {}, "typed_properties": {}})
                        continue

                    properties = {}
                    typed_properties = {}

                    if include_all_parameters:
                        # Discover instance parameters first.
                        for p in element.Parameters:
                            try:
                                if not p or not p.Definition or not p.Definition.Name:
                                    continue
                                pname = p.Definition.Name
                                _append_parameter_property(properties, typed_properties, pname, p, doc, populated_only=populated_only)
                            except Exception:
                                continue

                        # Include type parameters as fallback discovery source.
                        try:
                            symbol = getattr(element, "Symbol", None)
                            if symbol:
                                for p in symbol.Parameters:
                                    try:
                                        if not p or not p.Definition or not p.Definition.Name:
                                            continue
                                        pname = p.Definition.Name
                                        pvalue = _get_parameter_display_value(p, doc)
                                        if populated_only and not _is_meaningful_value(pvalue):
                                            continue
                                        if pname not in properties or not _is_meaningful_value(properties.get(pname)):
                                            _append_parameter_property(
                                                properties,
                                                typed_properties,
                                                pname,
                                                p,
                                                doc,
                                                populated_only=populated_only,
                                            )
                                    except Exception:
                                        continue
                        except Exception:
                            pass

                    elif not parameter_names:
                        category_name = element.Category.Name if element.Category else ""
                        common_params = ["Level", "Family and Type", "Comments"]
                        if category_name == "Windows":
                            common_params.extend(["Sill Height", "Head Height", "Width", "Height"])
                        elif category_name == "Doors":
                            common_params.extend(["Width", "Height", "Finish"])
                        elif category_name == "Walls":
                            common_params.extend(["Base Constraint", "Top Constraint", "Height"])
                        names_to_use = common_params
                    else:
                        names_to_use = parameter_names

                    if not include_all_parameters:
                        for param_name in names_to_use:
                            param = _find_parameter(element, param_name)
                            _append_parameter_property(properties, typed_properties, param_name, param, doc)

                    # Enrich with stable, human-readable identity values.
                    try:
                        if hasattr(element, "Symbol") and element.Symbol:
                            symbol = element.Symbol
                            family = symbol.Family
                            properties["Family Name"] = family.Name if family else "Not available"
                            properties["Type Name"] = symbol.Name
                            if family and symbol.Name:
                                properties["Family and Type"] = "{} : {}".format(family.Name, symbol.Name)
                    except Exception:
                        pass

                    properties["Element_Name"] = getattr(element, 'Name', 'No Name')
                    properties["Category"] = element.Category.Name if element.Category else "No Category"
                    properties["available_parameter_names"] = sorted(
                        [k for k, v in properties.items() if _is_meaningful_value(v) and k not in ("available_parameter_names", "Element_Name", "Category")]
                    )

                    results.append({"element_id": id_str, "properties": properties, "typed_properties": typed_properties})

                except Exception as elem_error:
                    route_logger.warning("Error processing element {}: {}".format(id_str, elem_error))
                    results.append({"element_id": id_str, "error": str(elem_error), "properties": {}, "typed_properties": {}})

            return {
                "status": "success",
                "message": "Retrieved properties for {} elements".format(len(results)),
                "count": len(results),
                "elements": results
            }

        except Exception as e:
            route_logger.critical("Error in /elements/get_properties: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

    @api.route('/elements/update_parameters', methods=['POST'])
    def handle_update_element_parameters(request):
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            updates_list = payload.get('updates')
            if not updates_list:
                return routes.Response(status=400, data={"error": "Missing 'updates' list"})

            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active UI document"})

            doc = current_uiapp.ActiveUIDocument.Document
            results = []

            transaction = DB.Transaction(doc, "Update Element Parameters")
            transaction.Start()
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
                        element = doc.GetElement(DB.ElementId(int(element_id_str)))
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
                            param = _find_parameter(element, param_name)
                            if not param:
                                errors[param_name] = "Parameter not found"
                                continue

                            if param.IsReadOnly:
                                errors[param_name] = "Parameter is read-only"
                                continue

                            ok, err = _set_parameter_value(param, new_value)
                            if ok:
                                updated_params.append(param_name)
                            else:
                                errors[param_name] = err

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

                transaction.Commit()
            except Exception as transaction_error:
                transaction.RollBack()
                return routes.Response(status=500, data={"error": "Transaction failed", "details": str(transaction_error)})

            success_count = len([r for r in results if r["status"] == "success"])
            partial_count = len([r for r in results if r["status"] == "partial"])
            error_count = len([r for r in results if r["status"] == "error"])

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
            route_logger.critical("Error in /elements/update_parameters: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})
