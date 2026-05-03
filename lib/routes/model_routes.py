# RevitMCP: Model analysis HTTP routes
# -*- coding: UTF-8 -*-

from pyrevit import routes, script, DB

from routes.json_safety import sanitize_for_json


try:
    STRING_TYPES = (basestring,)
except NameError:
    STRING_TYPES = (str,)


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default


def _bounded_int(value, default, min_value=None, max_value=None):
    try:
        number = int(value)
    except Exception:
        number = default
    if min_value is not None:
        number = max(min_value, number)
    if max_value is not None:
        number = min(max_value, number)
    return number


def _safe_name(value):
    try:
        text = str(value)
    except Exception:
        return ""
    return text


def _collector_count(collector):
    try:
        return int(collector.GetElementCount())
    except Exception:
        try:
            return len(list(collector))
        except Exception:
            return 0


def _parameter_text(parameter, doc):
    if not parameter:
        return None
    try:
        if not parameter.HasValue:
            return None
    except Exception:
        pass

    try:
        value_string = parameter.AsValueString()
        if value_string:
            return _safe_name(value_string)
    except Exception:
        pass

    try:
        storage_type = parameter.StorageType
    except Exception:
        storage_type = None

    try:
        if storage_type == DB.StorageType.String:
            return _safe_name(parameter.AsString())
        if storage_type == DB.StorageType.Integer:
            return _safe_name(parameter.AsInteger())
        if storage_type == DB.StorageType.Double:
            return _safe_name(parameter.AsDouble())
        if storage_type == DB.StorageType.ElementId:
            element_id = parameter.AsElementId()
            if element_id and element_id != DB.ElementId.InvalidElementId:
                element = doc.GetElement(element_id)
                if element and getattr(element, "Name", None):
                    return _safe_name(element.Name)
                return _safe_name(element_id.IntegerValue)
    except Exception:
        return None

    return None


def _get_type_summary(element, doc):
    type_id = None
    try:
        type_id = element.GetTypeId()
    except Exception:
        type_id = None

    if not type_id or type_id == DB.ElementId.InvalidElementId:
        return None, None

    element_type = doc.GetElement(type_id)
    if not element_type:
        return None, None

    type_name = _safe_name(getattr(element_type, "Name", None))
    family_name = ""

    try:
        family_name = _safe_name(element_type.FamilyName)
    except Exception:
        family_name = ""

    if not family_name:
        try:
            family = getattr(element_type, "Family", None)
            if family:
                family_name = _safe_name(family.Name)
        except Exception:
            family_name = ""

    if not family_name:
        try:
            parameter = element_type.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
            family_name = _parameter_text(parameter, doc) or ""
        except Exception:
            family_name = ""

    return family_name, type_name


def _get_element_level_name(element, doc):
    level_id = None
    try:
        level_id = getattr(element, "LevelId", None)
    except Exception:
        level_id = None

    if level_id and level_id != DB.ElementId.InvalidElementId:
        try:
            level = doc.GetElement(level_id)
            if level and getattr(level, "Name", None):
                return _safe_name(level.Name)
        except Exception:
            pass

    built_in_params = [
        "FAMILY_LEVEL_PARAM",
        "INSTANCE_REFERENCE_LEVEL_PARAM",
        "SCHEDULE_LEVEL_PARAM",
        "LEVEL_PARAM",
        "WALL_BASE_CONSTRAINT",
        "ROOM_LEVEL_ID",
        "STAIRS_BASE_LEVEL_PARAM",
        "ROOF_CONSTRAINT_LEVEL_PARAM",
    ]

    for param_name in built_in_params:
        try:
            if not hasattr(DB.BuiltInParameter, param_name):
                continue
            parameter = element.get_Parameter(getattr(DB.BuiltInParameter, param_name))
            if not parameter:
                continue
            param_level_id = parameter.AsElementId()
            if param_level_id and param_level_id != DB.ElementId.InvalidElementId:
                level = doc.GetElement(param_level_id)
                if level and getattr(level, "Name", None):
                    return _safe_name(level.Name)
        except Exception:
            continue

    return None


def register_routes(api):
    @api.route('/model/statistics', methods=['GET', 'POST'])
    def handle_analyze_model_statistics(doc, request=None):
        route_logger = script.get_logger()

        try:
            payload = {}
            if request is not None and hasattr(request, 'data') and isinstance(request.data, dict):
                payload = request.data

            include_detailed_types = _coerce_bool(payload.get('include_detailed_types'), default=True)
            include_levels = _coerce_bool(payload.get('include_levels'), default=True)
            top_n = _bounded_int(payload.get('top_n'), 25, min_value=1, max_value=200)

            elements = list(DB.FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements())
            total_elements = len(elements)
            total_types = _collector_count(DB.FilteredElementCollector(doc).WhereElementIsElementType())
            total_views = 0
            try:
                for view in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements():
                    if not getattr(view, "IsTemplate", False):
                        total_views += 1
            except Exception:
                total_views = 0

            total_view_templates = 0
            try:
                for view in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements():
                    if getattr(view, "IsTemplate", False):
                        total_view_templates += 1
            except Exception:
                total_view_templates = 0

            total_sheets = _collector_count(DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet))
            total_levels = _collector_count(DB.FilteredElementCollector(doc).OfClass(DB.Level))
            total_rooms = 0
            try:
                room_category = getattr(DB.BuiltInCategory, "OST_Rooms")
                total_rooms = _collector_count(
                    DB.FilteredElementCollector(doc).OfCategory(room_category).WhereElementIsNotElementType()
                )
            except Exception:
                total_rooms = 0

            total_loaded_families = _collector_count(DB.FilteredElementCollector(doc).OfClass(DB.Family))

            category_stats = {}
            model_family_names = set()
            level_counts = {}

            for element in elements:
                try:
                    category = element.Category
                    category_name = _safe_name(category.Name) if category and category.Name else "Uncategorized"
                except Exception:
                    category_name = "Uncategorized"

                if category_name not in category_stats:
                    category_stats[category_name] = {
                        "category_name": category_name,
                        "element_count": 0,
                        "type_count": 0,
                        "family_count": 0,
                        "_types": {},
                        "_type_names": set(),
                        "_family_names": set(),
                    }

                category_record = category_stats[category_name]
                category_record["element_count"] += 1

                family_name, type_name = _get_type_summary(element, doc)
                if family_name:
                    model_family_names.add(family_name)
                    category_record["_family_names"].add(family_name)
                if type_name:
                    category_record["_type_names"].add(type_name)
                if family_name or type_name:
                    type_key = (family_name or "", type_name or "")
                    if type_key not in category_record["_types"]:
                        category_record["_types"][type_key] = {
                            "family_name": family_name or "",
                            "type_name": type_name or "",
                            "instance_count": 0,
                        }
                    category_record["_types"][type_key]["instance_count"] += 1

                if include_levels:
                    level_name = _get_element_level_name(element, doc)
                    if level_name:
                        level_counts[level_name] = level_counts.get(level_name, 0) + 1

            categories = []
            for category_record in category_stats.values():
                type_records = list(category_record["_types"].values())
                type_records.sort(key=lambda item: (-item["instance_count"], item["family_name"], item["type_name"]))
                family_names = set()
                type_names = set()
                try:
                    family_names = set(category_record.get("_family_names", set()))
                    type_names = set(category_record.get("_type_names", set()))
                except Exception:
                    family_names = set()
                    type_names = set()

                public_record = {
                    "category_name": category_record["category_name"],
                    "element_count": category_record["element_count"],
                    "type_count": len(type_names),
                    "family_count": len(family_names),
                }
                if include_detailed_types:
                    public_record["types"] = type_records[:top_n]
                    public_record["types_total"] = len(type_records)
                    public_record["types_truncated"] = len(type_records) > top_n
                categories.append(public_record)

            categories.sort(key=lambda item: (-item["element_count"], item["category_name"]))

            levels = []
            if include_levels:
                try:
                    revit_levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements())
                    revit_levels.sort(key=lambda level: getattr(level, "Elevation", 0.0))
                    for level in revit_levels:
                        level_name = _safe_name(level.Name)
                        levels.append({
                            "level_name": level_name,
                            "elevation_internal_feet": float(getattr(level, "Elevation", 0.0)),
                            "element_count": int(level_counts.get(level_name, 0)),
                        })
                except Exception as level_error:
                    route_logger.warning("Failed to build model level statistics: {}".format(level_error))

            result = {
                "status": "success",
                "message": "Analyzed model with {} elements across {} categories.".format(
                    total_elements,
                    len(categories),
                ),
                "project_name": _safe_name(doc.Title),
                "document_path": _safe_name(doc.PathName),
                "summary": {
                    "total_elements": total_elements,
                    "total_types": total_types,
                    "total_loaded_families": total_loaded_families,
                    "total_instance_families": len(model_family_names),
                    "total_views": total_views,
                    "total_view_templates": total_view_templates,
                    "total_sheets": total_sheets,
                    "total_levels": total_levels,
                    "total_rooms": total_rooms,
                    "total_categories": len(categories),
                },
                "category_count": len(categories),
                "categories": categories[:top_n],
                "categories_total": len(categories),
                "categories_truncated": len(categories) > top_n,
                "levels": levels,
                "options": {
                    "include_detailed_types": include_detailed_types,
                    "include_levels": include_levels,
                    "top_n": top_n,
                },
            }
            return sanitize_for_json(result)

        except Exception as e:
            route_logger.error("Error in /model/statistics: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while analyzing model statistics.",
                    "details": str(e),
                }),
            )
