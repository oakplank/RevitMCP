# RevitMCP: Schedule-related HTTP routes
# -*- coding: UTF-8 -*-

from pyrevit import routes, script, DB

from routes.json_safety import sanitize_for_json, to_safe_ascii_text
from routes.revit_compat import get_element_id_text, get_element_id_value, make_element_id


try:
    STRING_TYPES = (basestring,)
except NameError:
    STRING_TYPES = (str,)


FILTER_TYPE_ALIASES = {
    "equals": ["Equal"],
    "equal": ["Equal"],
    "not_equals": ["NotEqual"],
    "not_equal": ["NotEqual"],
    "greater_than": ["GreaterThan"],
    "greater_than_or_equal": ["GreaterThanOrEqual"],
    "less_than": ["LessThan"],
    "less_than_or_equal": ["LessThanOrEqual"],
    "contains": ["Contains"],
    "not_contains": ["NotContains"],
    "begins_with": ["BeginsWith", "BeginsWith"],
    "starts_with": ["BeginsWith"],
    "not_begins_with": ["NotBeginsWith"],
    "not_starts_with": ["NotBeginsWith"],
    "ends_with": ["EndsWith"],
    "not_ends_with": ["NotEndsWith"],
    "has_parameter": ["HasParameter"],
    "has_value": ["HasValue"],
    "has_no_value": ["HasNoValue"],
}

NO_VALUE_FILTER_TYPES = set(["HasParameter", "HasValue", "HasNoValue"])

SETTING_MAP = {
    "is_itemized": "IsItemized",
    "show_grand_total": "ShowGrandTotal",
    "show_grand_total_count": "ShowGrandTotalCount",
    "show_grand_total_title": "ShowGrandTotalTitle",
    "grand_total_title": "GrandTotalTitle",
    "include_linked_files": "IncludeLinkedFiles",
    "show_headers": "ShowHeaders",
    "show_title": "ShowTitle",
    "show_grid_lines": "ShowGridLines",
}


def _safe_text(value):
    return to_safe_ascii_text(value)


def _normalize_text(value):
    return _safe_text(value).strip().lower()


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


def _coerce_int(value, default=0, min_value=None, max_value=None):
    try:
        number = int(value if value is not None else default)
    except Exception:
        number = int(default)
    if min_value is not None:
        number = max(min_value, number)
    if max_value is not None:
        number = min(max_value, number)
    return number


def _payload_from_request(request):
    if request is not None and hasattr(request, "data") and isinstance(request.data, dict):
        return request.data
    return {}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _id_integer_value(element_id):
    return get_element_id_value(element_id)


def _id_text(element_id):
    return get_element_id_text(element_id)


def _new_element_id(value):
    try:
        return make_element_id(DB, value)
    except Exception:
        return None


def _enum_text(value):
    if value is None:
        return None
    try:
        return _safe_text(value.ToString())
    except Exception:
        return _safe_text(value)


def _enum_member(enum_type, aliases):
    for alias in _as_list(aliases):
        if not alias:
            continue
        raw = str(alias).strip()
        candidates = [
            raw,
            raw.replace(" ", ""),
            raw.replace("_", ""),
            raw[:1].upper() + raw[1:],
        ]
        lowered = raw.replace(" ", "").replace("_", "").lower()
        for candidate in candidates:
            try:
                return getattr(enum_type, candidate)
            except Exception:
                pass
        try:
            for member_name in dir(enum_type):
                if member_name.startswith("_"):
                    continue
                if member_name.replace("_", "").lower() == lowered:
                    return getattr(enum_type, member_name)
        except Exception:
            pass
    return None


def _category_summary(category):
    if not category:
        return None
    return {
        "id": _id_text(getattr(category, "Id", None)),
        "name": _safe_text(getattr(category, "Name", "")),
    }


def _schedule_placements_by_schedule_id(doc):
    placements = {}
    try:
        instances = DB.FilteredElementCollector(doc).OfClass(DB.ScheduleSheetInstance).ToElements()
    except Exception:
        instances = []

    for instance in instances:
        try:
            schedule_id_text = _id_text(instance.ScheduleId)
        except Exception:
            schedule_id_text = None
        if not schedule_id_text:
            continue

        sheet_summary = {
            "schedule_sheet_instance_id": _id_text(getattr(instance, "Id", None)),
            "sheet_id": None,
            "sheet_number": None,
            "sheet_name": None,
        }
        try:
            sheet = doc.GetElement(instance.OwnerViewId)
            if sheet:
                sheet_summary["sheet_id"] = _id_text(getattr(sheet, "Id", None))
                sheet_summary["sheet_number"] = _safe_text(getattr(sheet, "SheetNumber", ""))
                sheet_summary["sheet_name"] = _safe_text(getattr(sheet, "Name", ""))
        except Exception:
            pass

        if schedule_id_text not in placements:
            placements[schedule_id_text] = []
        placements[schedule_id_text].append(sheet_summary)
    return placements


def _iter_categories(doc):
    try:
        for category in doc.Settings.Categories:
            yield category
    except Exception:
        return


def _find_category(doc, category_name=None, category_id=None):
    if category_id:
        wanted_id = str(category_id).strip()
        for category in _iter_categories(doc):
            if _id_text(getattr(category, "Id", None)) == wanted_id:
                return category, None
        return None, "Category id '{}' was not found in this document.".format(wanted_id)

    if not category_name:
        return None, "Provide category_name or category_id."

    raw_name = str(category_name).strip()
    normalized_name = _normalize_text(raw_name)
    matches = []

    if raw_name.startswith("OST_") and hasattr(DB.BuiltInCategory, raw_name):
        try:
            category = doc.Settings.Categories.get_Item(getattr(DB.BuiltInCategory, raw_name))
            if category:
                return category, None
        except Exception:
            pass

    for category in _iter_categories(doc):
        category_text = _normalize_text(getattr(category, "Name", ""))
        if category_text == normalized_name:
            matches.append(category)

    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, "Multiple categories match '{}'. Use category_id.".format(raw_name)

    partial_matches = []
    for category in _iter_categories(doc):
        category_text = _normalize_text(getattr(category, "Name", ""))
        if normalized_name and normalized_name in category_text:
            partial_matches.append(category)

    if len(partial_matches) == 1:
        return partial_matches[0], None
    if len(partial_matches) > 1:
        return None, "Multiple categories contain '{}': {}. Use category_id.".format(
            raw_name,
            ", ".join([_safe_text(category.Name) for category in partial_matches[:12]]),
        )

    return None, "Category '{}' was not found.".format(raw_name)


def _all_schedules(doc):
    schedules = []
    try:
        for schedule in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule).ToElements():
            schedules.append(schedule)
    except Exception:
        schedules = []
    return schedules


def _schedule_name_exists(doc, name):
    normalized = _normalize_text(name)
    for schedule in _all_schedules(doc):
        if _normalize_text(getattr(schedule, "Name", "")) == normalized:
            return True
    return False


def _unique_schedule_name(doc, base_name):
    if not _schedule_name_exists(doc, base_name):
        return base_name
    index = 1
    while index < 1000:
        candidate = "{} ({})".format(base_name, index)
        if not _schedule_name_exists(doc, candidate):
            return candidate
        index += 1
    return "{} ({})".format(base_name, index)


def _definition_category(doc, definition):
    category_id = None
    try:
        category_id = definition.CategoryId
    except Exception:
        return None
    category_id_text = _id_text(category_id)
    for category in _iter_categories(doc):
        if _id_text(getattr(category, "Id", None)) == category_id_text:
            return category
    return None


def _safe_get_count(definition, method_name):
    try:
        return int(getattr(definition, method_name)())
    except Exception:
        return 0


def _read_definition_settings(definition):
    settings = {}
    for public_key, property_name in SETTING_MAP.items():
        try:
            settings[public_key] = getattr(definition, property_name)
        except Exception:
            pass
    return settings


def _apply_definition_settings(definition, settings):
    applied = []
    if not isinstance(settings, dict):
        return applied

    for public_key, property_name in SETTING_MAP.items():
        if public_key not in settings:
            continue
        try:
            setattr(definition, property_name, settings.get(public_key))
            applied.append(public_key)
        except Exception:
            pass
    return applied


def _schedule_summary(schedule, doc, placements_by_schedule_id=None):
    definition = None
    try:
        definition = schedule.Definition
    except Exception:
        definition = None

    category = _definition_category(doc, definition) if definition else None
    schedule_id = _id_text(getattr(schedule, "Id", None))
    placements = []
    if placements_by_schedule_id is not None:
        placements = placements_by_schedule_id.get(schedule_id, []) or []
    summary = {
        "id": schedule_id,
        "name": _safe_text(getattr(schedule, "Name", "")),
        "view_type": _enum_text(getattr(schedule, "ViewType", None)),
        "is_template": bool(getattr(schedule, "IsTemplate", False)),
        "category": _category_summary(category),
        "placed_on_sheet_count": len(placements),
    }
    if placements:
        summary["placements"] = placements
    if definition:
        summary["field_count"] = _safe_get_count(definition, "GetFieldCount")
        summary["filter_count"] = _safe_get_count(definition, "GetFilterCount")
        summary["sort_group_field_count"] = _safe_get_count(definition, "GetSortGroupFieldCount")
        try:
            summary["is_key_schedule"] = bool(definition.IsKeySchedule)
        except Exception:
            pass
        try:
            summary["is_material_takeoff"] = bool(definition.IsMaterialTakeoff)
        except Exception:
            pass
    try:
        summary["is_titleblock_revision_schedule"] = bool(schedule.IsTitleblockRevisionSchedule)
    except Exception:
        pass
    return summary


def _find_schedule_by_id(doc, schedule_id):
    element_id = _new_element_id(schedule_id)
    if not element_id:
        return None
    try:
        schedule = doc.GetElement(element_id)
        if isinstance(schedule, DB.ViewSchedule):
            return schedule
    except Exception:
        return None
    return None


def _find_schedules_by_name(doc, schedule_name, exact_match=False):
    query = _normalize_text(schedule_name)
    if not query:
        return []
    matches = []
    for schedule in _all_schedules(doc):
        candidate = _normalize_text(getattr(schedule, "Name", ""))
        if exact_match and candidate == query:
            matches.append(schedule)
        elif not exact_match and query in candidate:
            matches.append(schedule)
    return matches


def _resolve_schedule(doc, payload):
    schedule_id = payload.get("schedule_id") or payload.get("id")
    schedule_name = payload.get("schedule_name") or payload.get("name")
    exact_match = _coerce_bool(payload.get("exact_match"), default=False)

    if schedule_id:
        schedule = _find_schedule_by_id(doc, schedule_id)
        if schedule:
            return schedule, None
        return None, {
            "status": "error",
            "error": "Schedule id '{}' was not found.".format(schedule_id),
        }

    if not schedule_name:
        return None, {
            "status": "error",
            "error": "Provide schedule_id or schedule_name.",
        }

    matches = _find_schedules_by_name(doc, schedule_name, exact_match=exact_match)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, {
            "status": "multiple_matches",
            "message": "Multiple schedules match '{}'. Retry with schedule_id.".format(_safe_text(schedule_name)),
            "matching_schedules": [_schedule_summary(schedule, doc) for schedule in matches[:25]],
        }
    return None, {
        "status": "error",
        "error": "Schedule '{}' was not found.".format(_safe_text(schedule_name)),
    }


def _field_id_key(field_id):
    return _id_text(field_id) or _safe_text(field_id)


def _schedule_field_name(field, doc=None):
    try:
        return _safe_text(field.GetName())
    except Exception:
        pass
    try:
        return _safe_text(field.GetName(doc))
    except Exception:
        pass
    try:
        return _safe_text(field.ColumnHeading)
    except Exception:
        return ""


def _call_bool_method(obj, method_name):
    try:
        return bool(getattr(obj, method_name)())
    except Exception:
        return None


def _schedule_field_summary(field, doc, index=None):
    name = _schedule_field_name(field, doc)
    parameter_id = None
    try:
        parameter_id = field.ParameterId
    except Exception:
        parameter_id = None

    summary = {
        "index": index,
        "field_index": index,
        "field_id": _field_id_key(getattr(field, "FieldId", None)),
        "name": name,
        "column_heading": _safe_text(getattr(field, "ColumnHeading", "")),
        "is_hidden": bool(getattr(field, "IsHidden", False)),
        "field_type": _enum_text(getattr(field, "FieldType", None)),
        "parameter_id": _id_text(parameter_id),
    }
    try:
        summary["is_calculated_field"] = bool(field.IsCalculatedField)
    except Exception:
        pass
    try:
        summary["percentage_of_field_id"] = _field_id_key(field.PercentageOf)
    except Exception:
        pass
    try:
        summary["percentage_by_field_id"] = _field_id_key(field.PercentageBy)
    except Exception:
        pass
    try:
        spec_type_id = field.GetSpecTypeId()
        if spec_type_id:
            summary["spec_type_id"] = _safe_text(spec_type_id.TypeId)
    except Exception:
        pass
    for method_name, key in [
        ("CanFilter", "can_filter"),
        ("CanSort", "can_sort"),
        ("CanTotal", "can_total"),
        ("CanDisplayMinMax", "can_display_min_max"),
    ]:
        value = _call_bool_method(field, method_name)
        if value is not None:
            summary[key] = value
    try:
        summary["display_type"] = _enum_text(field.DisplayType)
    except Exception:
        pass
    return summary


def _collect_schedule_fields(definition, doc):
    fields = []
    try:
        field_order = list(definition.GetFieldOrder())
        for index, field_id in enumerate(field_order):
            try:
                field = definition.GetField(field_id)
                fields.append((field, _schedule_field_summary(field, doc, index)))
            except Exception:
                pass
    except Exception:
        try:
            count = int(definition.GetFieldCount())
        except Exception:
            count = 0
        for index in range(count):
            try:
                field = definition.GetField(index)
                fields.append((field, _schedule_field_summary(field, doc, index)))
            except Exception:
                pass
    return fields


def _schedulable_field_name(schedulable_field, doc):
    try:
        return _safe_text(schedulable_field.GetName(doc))
    except Exception:
        pass
    try:
        return _safe_text(schedulable_field.GetName())
    except Exception:
        return ""


def _schedulable_field_summary(schedulable_field, doc, index=None):
    parameter_id = None
    try:
        parameter_id = schedulable_field.ParameterId
    except Exception:
        parameter_id = None
    return {
        "index": index,
        "available_field_index": index,
        "schedulable_field_index": index,
        "name": _schedulable_field_name(schedulable_field, doc),
        "parameter_id": _id_text(parameter_id),
        "field_type": _enum_text(getattr(schedulable_field, "FieldType", None)),
    }


def _available_schedulable_fields(definition, doc):
    fields = []
    try:
        for index, schedulable_field in enumerate(list(definition.GetSchedulableFields())):
            fields.append((schedulable_field, _schedulable_field_summary(schedulable_field, doc, index)))
    except Exception:
        pass
    return fields


def _field_candidate_text(candidates, index_key):
    parts = []
    for _field, summary in candidates[:8]:
        parts.append(
            "{}={} name='{}' parameter_id={} field_type={}".format(
                index_key,
                summary.get(index_key, summary.get("index")),
                _safe_text(summary.get("name")),
                summary.get("parameter_id"),
                summary.get("field_type"),
            )
        )
    suffix = ""
    if len(candidates) > 8:
        suffix = " ... {} more".format(len(candidates) - 8)
    return "; ".join(parts) + suffix


def _field_spec_from_value(value):
    if isinstance(value, dict):
        return value
    return {"name": value}


def _find_schedule_field(definition, doc, field_spec):
    spec = _field_spec_from_value(field_spec)
    fields = _collect_schedule_fields(definition, doc)

    wanted_index = spec.get("field_index")
    if wanted_index is None and (
        spec.get("available_field_index") is None
        and spec.get("schedulable_field_index") is None
        and spec.get("name") is None
        and spec.get("field_name") is None
        and spec.get("parameter_id") is None
        and spec.get("field_id") is None
    ):
        wanted_index = spec.get("index")
    if wanted_index is not None:
        try:
            wanted = int(wanted_index)
        except Exception:
            return None, None, "Schedule field index '{}' is not an integer.".format(_safe_text(wanted_index))
        for field, summary in fields:
            if summary.get("field_index") == wanted:
                return field, summary, None
        return None, None, "Schedule field index '{}' was not found.".format(wanted)

    wanted_field_id = spec.get("field_id") or spec.get("id")
    if wanted_field_id is not None:
        wanted = str(wanted_field_id).strip()
        for field, summary in fields:
            if str(summary.get("field_id")) == wanted:
                return field, summary, None
        return None, None, "Schedule field id '{}' was not found.".format(wanted)

    wanted_parameter_id = spec.get("parameter_id")
    if wanted_parameter_id is not None:
        wanted = str(wanted_parameter_id).strip()
        matches = [(field, summary) for field, summary in fields if str(summary.get("parameter_id")) == wanted]
        if len(matches) == 1:
            return matches[0][0], matches[0][1], None
        if len(matches) > 1:
            return None, None, "Multiple schedule fields use parameter_id '{}'. Use field_id or field_index. Candidates: {}".format(
                wanted,
                _field_candidate_text(matches, "field_index"),
            )

    wanted_name = spec.get("name") or spec.get("field_name") or spec.get("column_heading")
    if wanted_name is None:
        return None, None, "Field spec requires name, field_name, field_id, or parameter_id."

    wanted = _normalize_text(wanted_name)
    exact_matches = []
    partial_matches = []
    for field, summary in fields:
        names = [
            _normalize_text(summary.get("name")),
            _normalize_text(summary.get("column_heading")),
        ]
        if wanted in names:
            exact_matches.append((field, summary))
        elif wanted and any(wanted in item for item in names):
            partial_matches.append((field, summary))

    if len(exact_matches) == 1:
        return exact_matches[0][0], exact_matches[0][1], None
    if len(exact_matches) > 1:
        return None, None, "Multiple schedule fields match '{}'. Use field_id or field_index. Candidates: {}".format(
            _safe_text(wanted_name),
            _field_candidate_text(exact_matches, "field_index"),
        )
    if len(partial_matches) == 1:
        return partial_matches[0][0], partial_matches[0][1], None
    if len(partial_matches) > 1:
        return None, None, "Multiple schedule fields contain '{}'. Use field_id or field_index. Candidates: {}".format(
            _safe_text(wanted_name),
            _field_candidate_text(partial_matches, "field_index"),
        )

    return None, None, "Schedule field '{}' was not found.".format(_safe_text(wanted_name))


def _find_schedulable_field(definition, doc, field_spec):
    spec = _field_spec_from_value(field_spec)
    available_fields = _available_schedulable_fields(definition, doc)

    wanted_index = spec.get("available_field_index")
    if wanted_index is None:
        wanted_index = spec.get("schedulable_field_index")
    if wanted_index is None and (
        spec.get("name") is None
        and spec.get("field_name") is None
        and spec.get("parameter_id") is None
        and spec.get("field_id") is None
    ):
        wanted_index = spec.get("index")
    if wanted_index is not None:
        try:
            wanted = int(wanted_index)
        except Exception:
            return None, None, "Available schedule field index '{}' is not an integer.".format(_safe_text(wanted_index))
        for field, summary in available_fields:
            if summary.get("available_field_index") == wanted:
                return field, summary, None
        return None, None, "Available schedule field index '{}' was not found.".format(wanted)

    wanted_parameter_id = spec.get("parameter_id")
    if wanted_parameter_id is not None:
        wanted = str(wanted_parameter_id).strip()
        matches = [
            (field, summary)
            for field, summary in available_fields
            if str(summary.get("parameter_id")) == wanted
        ]
        if len(matches) == 1:
            return matches[0][0], matches[0][1], None
        if len(matches) > 1:
            return None, None, "Multiple schedulable fields use parameter_id '{}'. Use available_field_index. Candidates: {}".format(
                wanted,
                _field_candidate_text(matches, "available_field_index"),
            )

    wanted_name = spec.get("name") or spec.get("field_name") or spec.get("column_heading")
    if wanted_name is None:
        return None, None, "Field spec requires name, field_name, or parameter_id."

    wanted = _normalize_text(wanted_name)
    exact_matches = []
    partial_matches = []
    for field, summary in available_fields:
        candidate = _normalize_text(summary.get("name"))
        if candidate == wanted:
            exact_matches.append((field, summary))
        elif wanted and wanted in candidate:
            partial_matches.append((field, summary))

    if len(exact_matches) == 1:
        return exact_matches[0][0], exact_matches[0][1], None
    if len(exact_matches) > 1:
        return None, None, "Multiple available schedule fields match '{}'. Use available_field_index. Candidates: {}".format(
            _safe_text(wanted_name),
            _field_candidate_text(exact_matches, "available_field_index"),
        )
    if len(partial_matches) == 1:
        return partial_matches[0][0], partial_matches[0][1], None
    if len(partial_matches) > 1:
        return None, None, "Multiple available schedule fields contain '{}'. Use available_field_index. Candidates: {}".format(
            _safe_text(wanted_name),
            _field_candidate_text(partial_matches, "available_field_index"),
        )

    return None, None, "Available schedule field '{}' was not found.".format(_safe_text(wanted_name))


def _add_schedule_field(definition, doc, field_spec, default_hidden=None):
    spec = _field_spec_from_value(field_spec)
    schedulable_field, _available_summary, error = _find_schedulable_field(definition, doc, spec)
    if error:
        return None, None, error
    try:
        field = definition.AddField(schedulable_field)
    except Exception as add_error:
        return None, None, "Could not add field '{}': {}".format(spec.get("name", spec), add_error)

    _apply_schedule_field_options(field, spec, default_hidden=default_hidden)
    return field, _schedule_field_summary(field, doc), None


def _apply_schedule_field_options(field, spec, default_hidden=None):
    hidden = spec.get("hidden")
    if hidden is None:
        hidden = spec.get("is_hidden")
    if hidden is None:
        hidden = default_hidden
    if hidden is not None:
        try:
            field.IsHidden = _coerce_bool(hidden, default=False)
        except Exception:
            pass

    column_heading = spec.get("column_heading")
    if column_heading is not None:
        try:
            field.ColumnHeading = str(column_heading)
        except Exception:
            pass
    elif spec.get("name") is not None:
        try:
            field.ColumnHeading = str(spec.get("name"))
        except Exception:
            pass


def _ensure_schedule_field(definition, doc, field_spec, hidden_when_added=True):
    field, summary, error = _find_schedule_field(definition, doc, field_spec)
    if field:
        return field, summary, None
    return _add_schedule_field(definition, doc, field_spec, default_hidden=hidden_when_added)


def _calculated_field_kind(spec):
    raw_kind = (
        spec.get("kind")
        or spec.get("calculation_type")
        or spec.get("field_type")
        or spec.get("type")
        or ""
    )
    normalized = _normalize_text(raw_kind)
    if normalized in ("", "formula", "calculated", "calculatedvalue"):
        return "formula", None
    if normalized in ("percentage", "percent"):
        return "percentage", None
    return None, "Unsupported calculated field kind '{}'. Use 'formula' or 'percentage'.".format(
        _safe_text(raw_kind)
    )


def _calculated_formula_text(spec):
    for key in ("formula", "expression", "formula_text"):
        if spec.get(key) is not None:
            return _safe_text(spec.get(key))
    return ""


def _add_calculated_schedule_field(definition, doc, field_spec):
    if not isinstance(field_spec, dict):
        return None, None, "Calculated field spec must be an object."

    spec = dict(field_spec)
    kind, kind_error = _calculated_field_kind(spec)
    if kind_error:
        return None, None, kind_error

    formula_text = _calculated_formula_text(spec)
    if kind == "formula" and formula_text:
        return None, None, (
            "Revit API 2024 exposes ScheduleFieldType.Formula but does not expose a public formula text setter. "
            "Cannot assign formula '{}'. Use a writable project/shared parameter workflow for computed values "
            "that must be scheduled, or create the formula field manually in Revit."
        ).format(formula_text)

    try:
        if kind == "percentage":
            field = definition.AddField(DB.ScheduleFieldType.Percentage)
        else:
            field = definition.AddField(DB.ScheduleFieldType.Formula)
    except Exception as add_error:
        return None, None, "Could not add {} calculated field '{}': {}".format(
            kind,
            _safe_text(spec.get("name") or spec.get("column_heading") or ""),
            add_error,
        )

    _apply_schedule_field_options(field, spec, default_hidden=None)

    if kind == "percentage":
        percentage_of_spec = spec.get("percentage_of") or spec.get("of")
        if percentage_of_spec is None:
            return None, None, "Percentage calculated field requires percentage_of."
        percentage_of_field, _summary, error = _ensure_schedule_field(definition, doc, percentage_of_spec, hidden_when_added=False)
        if error:
            return None, None, "Could not resolve percentage_of field: {}".format(error)
        try:
            field.PercentageOf = percentage_of_field.FieldId
        except Exception as error:
            return None, None, "Could not set percentage_of field: {}".format(error)

        percentage_by_spec = spec.get("percentage_by") or spec.get("by")
        if percentage_by_spec is not None:
            percentage_by_field, _summary, error = _ensure_schedule_field(definition, doc, percentage_by_spec, hidden_when_added=False)
            if error:
                return None, None, "Could not resolve percentage_by field: {}".format(error)
            try:
                field.PercentageBy = percentage_by_field.FieldId
            except Exception as error:
                return None, None, "Could not set percentage_by field: {}".format(error)

    return field, _schedule_field_summary(field, doc), None


def _filter_field_spec(filter_spec):
    if not isinstance(filter_spec, dict):
        return {"name": filter_spec}
    if "field" in filter_spec:
        return filter_spec.get("field")
    field_spec = {}
    for key in [
        "field_id",
        "field_index",
        "available_field_index",
        "schedulable_field_index",
        "field_name",
        "parameter_id",
        "name",
        "column_heading",
    ]:
        if key in filter_spec:
            field_spec[key] = filter_spec.get(key)
    if "field_name" in field_spec and "name" not in field_spec:
        field_spec["name"] = field_spec["field_name"]
    return field_spec


def _filter_type_from_spec(filter_spec):
    raw_operator = None
    if isinstance(filter_spec, dict):
        raw_operator = filter_spec.get("operator") or filter_spec.get("filter_type") or filter_spec.get("condition")
    raw_operator = raw_operator or "equals"
    normalized = str(raw_operator).strip().lower()
    aliases = FILTER_TYPE_ALIASES.get(normalized, [raw_operator])
    filter_type = _enum_member(DB.ScheduleFilterType, aliases)
    if filter_type is None:
        return None, "Unsupported schedule filter operator '{}'. Supported operators: {}.".format(
            raw_operator,
            ", ".join(sorted(FILTER_TYPE_ALIASES.keys())),
        )
    return filter_type, None


def _filter_type_name(filter_type):
    return _enum_text(filter_type) or ""


def _filter_value_candidates(filter_spec, filter_type):
    filter_type_name = _filter_type_name(filter_type)
    if filter_type_name in NO_VALUE_FILTER_TYPES:
        try:
            return [(DB.ScheduleFilter(filter_spec["field_id"], filter_type), {"value_type": None, "value": None})], None
        except Exception as error:
            return [], "Could not create no-value schedule filter: {}".format(error)

    if "value" not in filter_spec:
        return [], "Filter '{}' requires a value.".format(filter_type_name)

    raw_value = filter_spec.get("value")
    value_type = str(filter_spec.get("value_type") or "").strip().lower()
    field_id = filter_spec["field_id"]
    candidates = []

    def add_candidate(candidate_value, candidate_type):
        try:
            schedule_filter = DB.ScheduleFilter(field_id, filter_type, candidate_value)
            candidates.append((schedule_filter, {"value_type": candidate_type, "value": _safe_text(candidate_value)}))
        except Exception:
            pass

    if isinstance(raw_value, dict) and raw_value.get("element_id") is not None:
        element_id = _new_element_id(raw_value.get("element_id"))
        if element_id:
            add_candidate(element_id, "element_id")
    elif value_type == "element_id":
        element_id = _new_element_id(raw_value)
        if element_id:
            add_candidate(element_id, "element_id")
    elif value_type in ("integer", "int"):
        try:
            add_candidate(int(raw_value), "integer")
        except Exception:
            pass
    elif value_type in ("number", "double", "float"):
        try:
            add_candidate(float(raw_value), "double")
        except Exception:
            pass
    elif value_type == "string":
        add_candidate(str(raw_value), "string")
    else:
        if isinstance(raw_value, bool):
            add_candidate(int(raw_value), "integer")
        elif isinstance(raw_value, int):
            add_candidate(int(raw_value), "integer")
        elif isinstance(raw_value, float):
            add_candidate(float(raw_value), "double")
        raw_text = str(raw_value)
        add_candidate(raw_text, "string")
        try:
            add_candidate(int(raw_text), "integer")
        except Exception:
            pass
        try:
            add_candidate(float(raw_text), "double")
        except Exception:
            pass
        element_id = _new_element_id(raw_text)
        if element_id:
            add_candidate(element_id, "element_id")

    if not candidates:
        return [], "Could not create a schedule filter value from '{}'.".format(_safe_text(raw_value))
    return candidates, None


def _schedule_filter_summary(schedule_filter, definition, doc, index=None, fields_by_id=None):
    fields_by_id = fields_by_id or {}
    field_id = None
    try:
        field_id = schedule_filter.FieldId
    except Exception:
        field_id = None
    field_id_text = _field_id_key(field_id)
    value = None
    value_type = None

    value_checks = [
        ("IsStringValue", "GetStringValue", "string"),
        ("IsIntegerValue", "GetIntegerValue", "integer"),
        ("IsDoubleValue", "GetDoubleValue", "double"),
        ("IsElementIdValue", "GetElementIdValue", "element_id"),
    ]
    for flag_name, method_name, candidate_type in value_checks:
        flag = None
        try:
            flag_attr = getattr(schedule_filter, flag_name)
            flag = bool(flag_attr() if callable(flag_attr) else flag_attr)
        except Exception:
            flag = None
        if flag is False:
            continue
        try:
            candidate = getattr(schedule_filter, method_name)()
            if candidate_type == "element_id":
                element_id_text = _id_text(candidate)
                element_name = None
                try:
                    element = doc.GetElement(candidate)
                    if element and getattr(element, "Name", None):
                        element_name = _safe_text(element.Name)
                except Exception:
                    pass
                value = {"element_id": element_id_text, "name": element_name}
            else:
                value = candidate
            value_type = candidate_type
            break
        except Exception:
            continue

    field_summary = fields_by_id.get(field_id_text)
    return {
        "index": index,
        "field_id": field_id_text,
        "field_name": field_summary.get("name") if field_summary else None,
        "filter_type": _enum_text(getattr(schedule_filter, "FilterType", None)),
        "value_type": value_type,
        "value": value,
    }


def _schedule_filters(definition, doc):
    fields_by_id = {}
    for _field, field_summary in _collect_schedule_fields(definition, doc):
        fields_by_id[str(field_summary.get("field_id"))] = field_summary

    filters = []
    count = _safe_get_count(definition, "GetFilterCount")
    for index in range(count):
        try:
            schedule_filter = definition.GetFilter(index)
            filters.append(_schedule_filter_summary(schedule_filter, definition, doc, index, fields_by_id))
        except Exception:
            pass
    return filters


def _add_or_set_filter(definition, doc, filter_spec, mode="add", index=None):
    if not isinstance(filter_spec, dict):
        return None, "Filter spec must be an object."

    field, field_summary, field_error = _ensure_schedule_field(
        definition,
        doc,
        _filter_field_spec(filter_spec),
        hidden_when_added=True,
    )
    if field_error:
        return None, field_error

    filter_type, type_error = _filter_type_from_spec(filter_spec)
    if type_error:
        return None, type_error

    prepared_spec = dict(filter_spec)
    prepared_spec["field_id"] = field.FieldId
    candidates, value_error = _filter_value_candidates(prepared_spec, filter_type)
    if value_error:
        return None, value_error

    last_error = None
    for schedule_filter, value_summary in candidates:
        try:
            if mode == "set":
                definition.SetFilter(int(index), schedule_filter)
                target_index = int(index)
            elif mode == "insert":
                definition.InsertFilter(int(index), schedule_filter)
                target_index = int(index)
            else:
                definition.AddFilter(schedule_filter)
                target_index = _safe_get_count(definition, "GetFilterCount") - 1
            summary = _schedule_filter_summary(schedule_filter, definition, doc, target_index)
            summary["field_name"] = field_summary.get("name")
            summary["value_type"] = value_summary.get("value_type")
            summary["value"] = value_summary.get("value")
            return summary, None
        except Exception as error:
            last_error = error
    return None, "Could not apply schedule filter on '{}': {}".format(field_summary.get("name"), last_error)


def _clear_filters(definition):
    removed = 0
    count = _safe_get_count(definition, "GetFilterCount")
    for index in range(count - 1, -1, -1):
        try:
            definition.RemoveFilter(index)
            removed += 1
        except Exception:
            pass
    return removed


def _remove_filter_indexes(definition, indexes):
    removed = []
    for raw_index in sorted([int(index) for index in indexes], reverse=True):
        try:
            definition.RemoveFilter(raw_index)
            removed.append(raw_index)
        except Exception:
            pass
    return removed


def _sort_field_spec(sort_spec):
    if not isinstance(sort_spec, dict):
        return {"name": sort_spec}
    if "field" in sort_spec:
        return sort_spec.get("field")
    field_spec = {}
    for key in [
        "field_id",
        "field_index",
        "available_field_index",
        "schedulable_field_index",
        "field_name",
        "parameter_id",
        "name",
        "column_heading",
    ]:
        if key in sort_spec:
            field_spec[key] = sort_spec.get(key)
    if "field_name" in field_spec and "name" not in field_spec:
        field_spec["name"] = field_spec["field_name"]
    return field_spec


def _schedule_sort_summary(sort_group_field, doc, index=None, fields_by_id=None):
    fields_by_id = fields_by_id or {}
    field_id = None
    try:
        field_id = sort_group_field.FieldId
    except Exception:
        field_id = None
    field_id_text = _field_id_key(field_id)
    field_summary = fields_by_id.get(field_id_text)
    summary = {
        "index": index,
        "field_id": field_id_text,
        "field_name": field_summary.get("name") if field_summary else None,
        "sort_order": _enum_text(getattr(sort_group_field, "SortOrder", None)),
    }
    for prop_name, key in [
        ("ShowHeader", "show_header"),
        ("ShowFooter", "show_footer"),
        ("ShowBlankLine", "show_blank_line"),
        ("ShowFooterTitle", "show_footer_title"),
        ("ShowFooterCount", "show_footer_count"),
    ]:
        try:
            summary[key] = bool(getattr(sort_group_field, prop_name))
        except Exception:
            pass
    return summary


def _schedule_sort_group_fields(definition, doc):
    fields_by_id = {}
    for _field, field_summary in _collect_schedule_fields(definition, doc):
        fields_by_id[str(field_summary.get("field_id"))] = field_summary

    sort_fields = []
    count = _safe_get_count(definition, "GetSortGroupFieldCount")
    for index in range(count):
        try:
            sort_group_field = definition.GetSortGroupField(index)
            sort_fields.append(_schedule_sort_summary(sort_group_field, doc, index, fields_by_id))
        except Exception:
            pass
    return sort_fields


def _build_sort_group_field(definition, doc, sort_spec):
    if not isinstance(sort_spec, dict):
        sort_spec = {"name": sort_spec}
    field, field_summary, field_error = _ensure_schedule_field(
        definition,
        doc,
        _sort_field_spec(sort_spec),
        hidden_when_added=False,
    )
    if field_error:
        return None, None, field_error

    try:
        sort_group_field = DB.ScheduleSortGroupField(field.FieldId)
    except Exception as error:
        return None, None, "Could not create sort/group field '{}': {}".format(field_summary.get("name"), error)

    order_text = str(sort_spec.get("order") or sort_spec.get("sort_order") or "ascending").strip().lower()
    order_member = None
    if order_text in ("desc", "descending"):
        order_member = _enum_member(DB.ScheduleSortOrder, ["Descending"])
    elif order_text in ("asc", "ascending"):
        order_member = _enum_member(DB.ScheduleSortOrder, ["Ascending"])
    if order_member is not None:
        try:
            sort_group_field.SortOrder = order_member
        except Exception:
            pass

    prop_map = {
        "show_header": "ShowHeader",
        "show_footer": "ShowFooter",
        "show_blank_line": "ShowBlankLine",
        "show_footer_title": "ShowFooterTitle",
        "show_footer_count": "ShowFooterCount",
    }
    for public_key, property_name in prop_map.items():
        if public_key not in sort_spec:
            continue
        try:
            setattr(sort_group_field, property_name, _coerce_bool(sort_spec.get(public_key), default=False))
        except Exception:
            pass
    return sort_group_field, field_summary, None


def _add_or_set_sort_group_field(definition, doc, sort_spec, mode="add", index=None):
    sort_group_field, field_summary, error = _build_sort_group_field(definition, doc, sort_spec)
    if error:
        return None, error
    try:
        if mode == "set":
            definition.SetSortGroupField(int(index), sort_group_field)
            target_index = int(index)
        elif mode == "insert":
            definition.InsertSortGroupField(int(index), sort_group_field)
            target_index = int(index)
        else:
            definition.AddSortGroupField(sort_group_field)
            target_index = _safe_get_count(definition, "GetSortGroupFieldCount") - 1
        summary = _schedule_sort_summary(sort_group_field, doc, target_index)
        summary["field_name"] = field_summary.get("name")
        return summary, None
    except Exception as apply_error:
        return None, "Could not apply sort/group field '{}': {}".format(field_summary.get("name"), apply_error)


def _clear_sort_group_fields(definition):
    removed = 0
    count = _safe_get_count(definition, "GetSortGroupFieldCount")
    for index in range(count - 1, -1, -1):
        try:
            definition.RemoveSortGroupField(index)
            removed += 1
        except Exception:
            pass
    return removed


def _remove_sort_group_indexes(definition, indexes):
    removed = []
    for raw_index in sorted([int(index) for index in indexes], reverse=True):
        try:
            definition.RemoveSortGroupField(raw_index)
            removed.append(raw_index)
        except Exception:
            pass
    return removed


def _schedule_details(schedule, doc, include_available_fields=False):
    definition = schedule.Definition
    fields = [summary for _field, summary in _collect_schedule_fields(definition, doc)]
    details = _schedule_summary(schedule, doc)
    details["settings"] = _read_definition_settings(definition)
    details["fields"] = fields
    details["filters"] = _schedule_filters(definition, doc)
    details["sort_group_fields"] = _schedule_sort_group_fields(definition, doc)
    if include_available_fields:
        details["available_fields"] = [summary for _field, summary in _available_schedulable_fields(definition, doc)]
    return details


def _unique_column_key(base_name, used_names):
    base = _safe_text(base_name or "").strip() or "Column"
    if base not in used_names:
        used_names[base] = 1
        return base
    used_names[base] += 1
    return "{} #{}".format(base, used_names[base])


def _get_schedule_cell_text(schedule, section_type, row_index, column_index):
    try:
        return _safe_text(schedule.GetCellText(section_type, row_index, column_index))
    except Exception:
        pass

    try:
        section_data = schedule.GetTableData().GetSectionData(section_type)
        return _safe_text(section_data.GetCellText(row_index, column_index))
    except Exception:
        return ""


def _row_looks_like_header(columns, raw_cells):
    if not raw_cells or not columns:
        return False

    comparable_cells = []
    comparable_names = []
    for index, column in enumerate(columns):
        if index >= len(raw_cells):
            break
        cell_text = _normalize_text(raw_cells[index])
        if not cell_text:
            continue
        comparable_cells.append(cell_text)
        names = [
            _normalize_text(column.get("column_heading")),
            _normalize_text(column.get("name")),
            _normalize_text(column.get("unique_name")),
        ]
        comparable_names.append(names)

    if len(comparable_cells) < 2:
        return False

    matches = 0
    for index, cell_text in enumerate(comparable_cells):
        if cell_text in comparable_names[index]:
            matches += 1

    return matches >= max(2, int(len(comparable_cells) * 0.6))


def _schedule_visible_columns(schedule, doc, column_count):
    definition = schedule.Definition
    visible_fields = [
        summary
        for _field, summary in _collect_schedule_fields(definition, doc)
        if not summary.get("is_hidden")
    ]
    columns = []
    used_names = {}

    for column_index in range(column_count):
        field_summary = visible_fields[column_index] if column_index < len(visible_fields) else {}
        display_name = field_summary.get("column_heading") or field_summary.get("name") or "Column {}".format(column_index + 1)
        unique_name = _unique_column_key(display_name, used_names)
        column = {
            "column_index": column_index,
            "name": field_summary.get("name") or display_name,
            "column_heading": field_summary.get("column_heading") or display_name,
            "unique_name": unique_name,
            "field_id": field_summary.get("field_id"),
            "field_index": field_summary.get("field_index"),
            "parameter_id": field_summary.get("parameter_id"),
            "is_hidden": False,
        }
        columns.append(column)
    return columns


def _read_schedule_rows(schedule, doc, max_rows=2000, include_empty_rows=False, include_header_rows=False):
    try:
        table_data = schedule.GetTableData()
        body = table_data.GetSectionData(DB.SectionType.Body)
        row_count = int(body.NumberOfRows)
        column_count = int(body.NumberOfColumns)
    except Exception as error:
        return None, None, "Could not read schedule table data: {}".format(error)

    max_rows = max(1, min(10000, int(max_rows)))
    columns = _schedule_visible_columns(schedule, doc, column_count)
    rows = []
    truncated = False
    skipped_header_rows = 0

    for row_index in range(row_count):
        if len(rows) >= max_rows:
            truncated = True
            break

        raw_cells = []
        values = {}
        for column in columns:
            cell_text = _get_schedule_cell_text(schedule, DB.SectionType.Body, row_index, column["column_index"])
            raw_cells.append(cell_text)
            values[column["unique_name"]] = cell_text

        if not include_header_rows and _row_looks_like_header(columns, raw_cells):
            skipped_header_rows += 1
            continue

        if not include_empty_rows and not any(str(cell or "").strip() for cell in raw_cells):
            continue

        rows.append({
            "row_index": row_index,
            "values": values,
            "cells": raw_cells,
        })

    metadata = {
        "body_row_count": row_count,
        "body_column_count": column_count,
        "returned_count": len(rows),
        "max_rows": max_rows,
        "truncated": truncated,
        "skipped_header_rows": skipped_header_rows,
        "include_header_rows": bool(include_header_rows),
    }
    return columns, rows, metadata


def _column_index_from_spec(columns, field_spec):
    spec = _field_spec_from_value(field_spec)
    if not isinstance(spec, dict):
        return None, "Column spec must be a string or object."

    wanted_column_index = spec.get("column_index")
    if wanted_column_index is not None:
        try:
            wanted = int(wanted_column_index)
        except Exception:
            return None, "column_index '{}' is not an integer.".format(_safe_text(wanted_column_index))
        for column in columns:
            if column.get("column_index") == wanted:
                return wanted, None
        return None, "column_index '{}' was not found.".format(wanted)

    wanted_field_id = spec.get("field_id") or spec.get("id")
    if wanted_field_id is not None:
        wanted = str(wanted_field_id).strip()
        matches = [column for column in columns if str(column.get("field_id")) == wanted]
        if len(matches) == 1:
            return matches[0]["column_index"], None
        if len(matches) > 1:
            return None, "Multiple visible columns use field_id '{}'. Use column_index.".format(wanted)
        return None, "Visible column with field_id '{}' was not found.".format(wanted)

    wanted_field_index = spec.get("field_index")
    if wanted_field_index is not None:
        try:
            wanted = int(wanted_field_index)
        except Exception:
            return None, "field_index '{}' is not an integer.".format(_safe_text(wanted_field_index))
        matches = [column for column in columns if column.get("field_index") == wanted]
        if len(matches) == 1:
            return matches[0]["column_index"], None
        if len(matches) > 1:
            return None, "Multiple visible columns use field_index '{}'. Use column_index.".format(wanted)
        return None, "Visible column with field_index '{}' was not found.".format(wanted)

    wanted_parameter_id = spec.get("parameter_id")
    if wanted_parameter_id is not None:
        wanted = str(wanted_parameter_id).strip()
        matches = [column for column in columns if str(column.get("parameter_id")) == wanted]
        if len(matches) == 1:
            return matches[0]["column_index"], None
        if len(matches) > 1:
            return None, "Multiple visible columns use parameter_id '{}'. Use column_index or field_id.".format(wanted)
        return None, "Visible column with parameter_id '{}' was not found.".format(wanted)

    wanted_name = spec.get("name") or spec.get("field_name") or spec.get("column_heading") or spec.get("unique_name")
    if wanted_name is None:
        return None, "Column spec requires name, field_name, column_heading, field_id, field_index, or column_index."

    wanted = _normalize_text(wanted_name)
    exact_matches = []
    partial_matches = []
    for column in columns:
        names = [
            _normalize_text(column.get("name")),
            _normalize_text(column.get("column_heading")),
            _normalize_text(column.get("unique_name")),
        ]
        if wanted in names:
            exact_matches.append(column)
        elif wanted and any(wanted in item for item in names):
            partial_matches.append(column)

    if len(exact_matches) == 1:
        return exact_matches[0]["column_index"], None
    if len(exact_matches) > 1:
        return None, "Multiple visible columns match '{}'. Use column_index or field_id.".format(_safe_text(wanted_name))
    if len(partial_matches) == 1:
        return partial_matches[0]["column_index"], None
    if len(partial_matches) > 1:
        return None, "Multiple visible columns contain '{}'. Use column_index or field_id.".format(_safe_text(wanted_name))
    return None, "Visible column '{}' was not found.".format(_safe_text(wanted_name))


def _parse_quantity(value):
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(",", "")
    match = None
    try:
        import re
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    except Exception:
        match = None
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _key_text(key_tuple):
    return " | ".join([_safe_text(item) for item in key_tuple])


def _aggregate_schedule_rows(schedule, doc, key_fields, quantity_field=None, max_rows=5000):
    columns, rows, metadata = _read_schedule_rows(
        schedule,
        doc,
        max_rows=max_rows,
        include_empty_rows=False,
        include_header_rows=False,
    )
    if isinstance(metadata, STRING_TYPES):
        return None, metadata

    key_column_indexes = []
    for key_field in key_fields:
        column_index, column_error = _column_index_from_spec(columns, key_field)
        if column_error:
            return None, column_error
        key_column_indexes.append(column_index)

    quantity_column_index = None
    if quantity_field:
        quantity_column_index, quantity_error = _column_index_from_spec(columns, quantity_field)
        if quantity_error:
            return None, quantity_error

    aggregates = {}
    total_quantity = 0.0
    data_row_count = 0

    for row in rows:
        cells = row.get("cells", [])
        key_values = []
        for column_index in key_column_indexes:
            key_values.append(_safe_text(cells[column_index] if column_index < len(cells) else ""))
        if not any(value.strip() for value in key_values):
            continue

        if quantity_column_index is not None:
            raw_quantity = cells[quantity_column_index] if quantity_column_index < len(cells) else ""
            quantity = _parse_quantity(raw_quantity)
            if quantity is None:
                quantity = 0.0
        else:
            raw_quantity = "1"
            quantity = 1.0

        key_tuple = tuple(key_values)
        key = _key_text(key_tuple)
        if key not in aggregates:
            aggregates[key] = {
                "key": key,
                "key_values": list(key_tuple),
                "quantity": 0.0,
                "row_count": 0,
                "rows": [],
            }
        aggregates[key]["quantity"] += quantity
        aggregates[key]["row_count"] += 1
        aggregates[key]["rows"].append({
            "row_index": row.get("row_index"),
            "quantity": quantity,
            "raw_quantity": raw_quantity,
        })
        total_quantity += quantity
        data_row_count += 1

    return {
        "schedule": _schedule_summary(schedule, doc),
        "columns": columns,
        "metadata": metadata,
        "key_fields": key_fields,
        "quantity_field": quantity_field,
        "quantity_mode": "field" if quantity_column_index is not None else "row_count",
        "total_quantity": total_quantity,
        "data_row_count": data_row_count,
        "aggregates": aggregates,
    }, None


def _resolve_named_schedule_list(doc, names, exact_match=False):
    schedules = []
    errors = []
    seen_ids = set()
    for name in _as_list(names):
        if not name:
            continue
        matches = _find_schedules_by_name(doc, name, exact_match=exact_match)
        if not matches:
            errors.append("Schedule '{}' was not found.".format(_safe_text(name)))
            continue
        for schedule in matches:
            schedule_id = _id_text(schedule.Id)
            if schedule_id not in seen_ids:
                schedules.append(schedule)
                seen_ids.add(schedule_id)
    return schedules, errors


def _validate_schedule_name_for_create(doc, name, uniquify_name):
    final_name = str(name or "").strip()
    if not final_name:
        return None, "schedule_name is required."
    if _schedule_name_exists(doc, final_name):
        if uniquify_name:
            return _unique_schedule_name(doc, final_name), None
        return None, "A schedule named '{}' already exists. Provide a different name or set uniquify_name=true.".format(
            _safe_text(final_name)
        )
    return final_name, None


def _audit_field_specs_from_payload(definition, doc, payload):
    raw_fields = _as_list(payload.get("fields"))
    max_fields = _coerce_int(payload.get("max_fields"), default=24, min_value=1, max_value=250)

    if raw_fields:
        return raw_fields[:max_fields], len(raw_fields)

    available_fields = _available_schedulable_fields(definition, doc)
    contains_text = _normalize_text(payload.get("field_name_contains"))
    selected = []
    selected_keys = set()

    def add_available_field(schedulable_field, summary):
        key = "{}|{}".format(summary.get("available_field_index"), summary.get("parameter_id"))
        if key in selected_keys:
            return
        selected_keys.add(key)
        selected.append({
            "available_field_index": summary.get("available_field_index"),
            "name": summary.get("name"),
            "parameter_id": summary.get("parameter_id"),
        })

    if contains_text:
        for schedulable_field, summary in available_fields:
            if contains_text in _normalize_text(summary.get("name")):
                add_available_field(schedulable_field, summary)
                if len(selected) >= max_fields:
                    break
        return selected, len(available_fields)

    preferred_names = [
        "Count",
        "Mark",
        "Type Mark",
        "Level",
        "Family and Type",
        "Material: Name",
        "Material: Mark",
        "Material: Description",
        "Material: Area",
        "Material: Volume",
        "Width",
        "Height",
        "Side 1",
        "Side 2",
        "Part Number",
        "Install Level",
        "Comments",
        "Workset",
    ]
    for preferred_name in preferred_names:
        preferred_normalized = _normalize_text(preferred_name)
        for schedulable_field, summary in available_fields:
            if _normalize_text(summary.get("name")) == preferred_normalized:
                add_available_field(schedulable_field, summary)
                break
        if len(selected) >= max_fields:
            return selected, len(available_fields)

    for schedulable_field, summary in available_fields:
        add_available_field(schedulable_field, summary)
        if len(selected) >= max_fields:
            break
    return selected, len(available_fields)


def _audit_filter_operators_from_payload(payload):
    operators = payload.get("filter_operators")
    if operators:
        return [str(operator).strip() for operator in _as_list(operators) if str(operator).strip()]
    return [
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "begins_with",
        "ends_with",
        "greater_than",
        "less_than",
        "has_value",
        "has_no_value",
    ]


def _audit_filter_spec_for_field(field_summary, operator):
    filter_spec = {
        "field_id": field_summary.get("field_id"),
        "operator": operator,
    }
    if operator not in ("has_parameter", "has_value", "has_no_value"):
        if operator in ("greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"):
            filter_spec["value"] = "1"
        elif operator in ("contains", "not_contains", "begins_with", "not_begins_with", "ends_with", "not_ends_with"):
            filter_spec["value"] = "A"
            filter_spec["value_type"] = "string"
        else:
            filter_spec["value"] = "1"
    return filter_spec


def _audit_schedule_capabilities(doc, payload):
    category, category_error = _find_category(
        doc,
        category_name=payload.get("category_name"),
        category_id=payload.get("category_id"),
    )
    if category_error:
        return routes.Response(status=400, data=sanitize_for_json({"status": "error", "error": category_error}))

    schedule_kind = str(payload.get("schedule_kind") or payload.get("schedule_type") or "").strip().lower()
    is_material_takeoff = _coerce_bool(payload.get("is_material_takeoff"), default=False)
    if schedule_kind in ("material_takeoff", "material takeoff", "takeoff"):
        is_material_takeoff = True
    schedule_kind_label = "material_takeoff" if is_material_takeoff else "schedule"

    include_filter_tests = _coerce_bool(payload.get("include_filter_tests"), default=True)
    include_sort_tests = _coerce_bool(payload.get("include_sort_tests"), default=True)
    include_settings_tests = _coerce_bool(payload.get("include_settings_tests"), default=True)
    include_row_read = _coerce_bool(payload.get("include_row_read"), default=True)
    max_filter_tests = _coerce_int(payload.get("max_filter_tests"), default=120, min_value=0, max_value=1000)

    transaction = None
    transaction_started = False
    rolled_back = False
    try:
        transaction = DB.Transaction(doc, "RevitMCP Audit Schedule Capabilities")
        transaction.Start()
        transaction_started = True

        if is_material_takeoff:
            schedule = DB.ViewSchedule.CreateMaterialTakeoff(doc, category.Id)
        else:
            schedule = DB.ViewSchedule.CreateSchedule(doc, category.Id)
        schedule.Name = _unique_schedule_name(doc, "__RevitMCP_CAPABILITY_AUDIT__")
        definition = schedule.Definition

        try:
            doc.Regenerate()
        except Exception:
            pass

        field_specs, available_field_count = _audit_field_specs_from_payload(definition, doc, payload)
        field_tests = []
        added_field_summaries = []

        for field_spec in field_specs:
            field_test = {
                "requested": field_spec,
                "can_add": False,
                "error": None,
            }
            field, summary, field_error = _add_schedule_field(definition, doc, field_spec)
            if field_error:
                field_test["error"] = field_error
            else:
                field_test["can_add"] = True
                field_test["field"] = summary
                added_field_summaries.append(summary)
            field_tests.append(field_test)

        filter_tests = []
        if include_filter_tests and max_filter_tests > 0:
            operators = _audit_filter_operators_from_payload(payload)
            tested_count = 0
            for field_summary in added_field_summaries:
                if tested_count >= max_filter_tests:
                    break
                for operator in operators:
                    if tested_count >= max_filter_tests:
                        break
                    tested_count += 1
                    filter_spec = _audit_filter_spec_for_field(field_summary, operator)
                    filter_test = {
                        "field": field_summary,
                        "operator": operator,
                        "supported": False,
                        "error": None,
                    }
                    summary, filter_error = _add_or_set_filter(definition, doc, filter_spec, mode="add")
                    if filter_error:
                        filter_test["error"] = filter_error
                    else:
                        filter_test["supported"] = True
                        filter_test["filter"] = summary
                        try:
                            definition.RemoveFilter(int(summary.get("index")))
                        except Exception as remove_error:
                            filter_test["remove_error"] = _safe_text(remove_error)
                    filter_tests.append(filter_test)

        sort_tests = []
        if include_sort_tests:
            for field_summary in added_field_summaries:
                sort_test = {
                    "field": field_summary,
                    "supported": False,
                    "error": None,
                }
                summary, sort_error = _add_or_set_sort_group_field(
                    definition,
                    doc,
                    {"field_id": field_summary.get("field_id"), "order": "ascending"},
                    mode="add",
                )
                if sort_error:
                    sort_test["error"] = sort_error
                else:
                    sort_test["supported"] = True
                    sort_test["sort_group_field"] = summary
                    try:
                        definition.RemoveSortGroupField(int(summary.get("index")))
                    except Exception as remove_error:
                        sort_test["remove_error"] = _safe_text(remove_error)
                sort_tests.append(sort_test)

        settings_tests = []
        if include_settings_tests:
            settings_probe = {
                "is_itemized": True,
                "show_grand_total": True,
                "show_grand_total_count": True,
                "show_grand_total_title": True,
                "grand_total_title": "Audit Total",
                "include_linked_files": False,
                "show_headers": True,
                "show_title": False,
                "show_grid_lines": True,
            }
            applied = _apply_definition_settings(definition, settings_probe)
            for key in sorted(settings_probe.keys()):
                settings_tests.append({
                    "setting": key,
                    "requested_value": settings_probe[key],
                    "supported": key in applied,
                })

        row_read_test = None
        if include_row_read:
            columns, rows_read, metadata = _read_schedule_rows(
                schedule,
                doc,
                max_rows=3,
                include_empty_rows=False,
                include_header_rows=False,
            )
            if isinstance(metadata, STRING_TYPES):
                row_read_test = {"supported": False, "error": metadata}
            else:
                row_read_test = {
                    "supported": True,
                    "columns_sample": columns[:12],
                    "rows_sample": rows_read[:3],
                    "metadata": metadata,
                }

        summary = {
            "available_field_count": available_field_count,
            "fields_tested": len(field_tests),
            "fields_added": len([item for item in field_tests if item.get("can_add")]),
            "filters_tested": len(filter_tests),
            "filters_supported": len([item for item in filter_tests if item.get("supported")]),
            "sorts_tested": len(sort_tests),
            "sorts_supported": len([item for item in sort_tests if item.get("supported")]),
            "settings_tested": len(settings_tests),
            "settings_supported": len([item for item in settings_tests if item.get("supported")]),
        }

        result = {
            "status": "success",
            "message": "Audited schedule capabilities for category '{}' using rollback-only temporary {}.".format(
                _safe_text(category.Name),
                schedule_kind_label,
            ),
            "audit_mode": "rollback_transaction",
            "rolled_back": False,
            "category": _category_summary(category),
            "schedule_kind": schedule_kind_label,
            "can_create": True,
            "temporary_schedule": _schedule_summary(schedule, doc),
            "summary": summary,
            "field_tests": field_tests,
            "filter_tests": filter_tests,
            "sort_tests": sort_tests,
            "settings_tests": settings_tests,
            "row_read_test": row_read_test,
            "limitations": [
                "Probe results are specific to this Revit version, document, category, and schedule kind.",
                "The transaction is rolled back, so no temporary schedule should remain in the model.",
                "Filter support is tested with representative sample values; user-specific values can still fail.",
            ],
        }

        transaction.RollBack()
        transaction_started = False
        rolled_back = True
        result["rolled_back"] = True
        return sanitize_for_json(result)
    except Exception as error:
        if transaction and transaction_started:
            try:
                transaction.RollBack()
                rolled_back = True
            except Exception:
                rolled_back = False
        return routes.Response(
            status=500,
            data=sanitize_for_json({
                "status": "error",
                "error": "Internal server error while auditing schedule capabilities.",
                "details": str(error),
                "audit_mode": "rollback_transaction",
                "rolled_back": rolled_back,
                "category": _category_summary(category),
                "schedule_kind": schedule_kind_label,
                "can_create": False,
            }),
        )


def register_routes(api):
    @api.route('/schedules/list', methods=['GET', 'POST'])
    def handle_list_schedules(doc, request=None):
        route_logger = script.get_logger()
        try:
            payload = _payload_from_request(request)
            schedule_name = payload.get("schedule_name") or payload.get("name") or payload.get("search")
            exact_match = _coerce_bool(payload.get("exact_match"), default=False)
            try:
                limit = int(payload.get("limit", 200))
            except Exception:
                limit = 200
            limit = max(1, min(1000, limit))

            schedules = _all_schedules(doc)
            if schedule_name:
                schedules = _find_schedules_by_name(doc, schedule_name, exact_match=exact_match)
            schedules.sort(key=lambda schedule: _safe_text(getattr(schedule, "Name", "")).lower())
            placements_by_schedule_id = _schedule_placements_by_schedule_id(doc)

            result = {
                "status": "success",
                "message": "Found {} schedule(s).".format(len(schedules)),
                "schedules": [
                    _schedule_summary(schedule, doc, placements_by_schedule_id)
                    for schedule in schedules[:limit]
                ],
                "count": min(len(schedules), limit),
                "schedules_total": len(schedules),
                "schedules_truncated": len(schedules) > limit,
                "limit": limit,
            }
            return sanitize_for_json(result)
        except Exception as e:
            route_logger.error("Error in /schedules/list: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while listing schedules.",
                    "details": str(e),
                }),
            )

    @api.route('/schedules/info', methods=['POST'])
    def handle_get_schedule_info(doc, request):
        route_logger = script.get_logger()
        try:
            payload = _payload_from_request(request)
            include_available_fields = _coerce_bool(payload.get("include_available_fields"), default=False)
            schedule, error = _resolve_schedule(doc, payload)
            if error:
                status = 300 if error.get("status") == "multiple_matches" else 400
                return routes.Response(status=status, data=sanitize_for_json(error))

            result = {
                "status": "success",
                "message": "Retrieved schedule '{}'.".format(_safe_text(schedule.Name)),
                "schedule": _schedule_details(schedule, doc, include_available_fields=include_available_fields),
            }
            return sanitize_for_json(result)
        except Exception as e:
            route_logger.error("Error in /schedules/info: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while reading schedule info.",
                    "details": str(e),
                }),
            )

    @api.route('/schedules/available_fields', methods=['POST'])
    def handle_list_schedule_available_fields(doc, request):
        route_logger = script.get_logger()
        try:
            payload = _payload_from_request(request)
            schedule, error = _resolve_schedule(doc, payload)
            if error:
                status = 300 if error.get("status") == "multiple_matches" else 400
                return routes.Response(status=status, data=sanitize_for_json(error))

            fields = [
                summary
                for _field, summary in _available_schedulable_fields(schedule.Definition, doc)
            ]
            result = {
                "status": "success",
                "message": "Found {} available field(s) for schedule '{}'.".format(len(fields), _safe_text(schedule.Name)),
                "schedule": _schedule_summary(schedule, doc),
                "available_fields": fields,
                "count": len(fields),
            }
            return sanitize_for_json(result)
        except Exception as e:
            route_logger.error("Error in /schedules/available_fields: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while listing schedule fields.",
                    "details": str(e),
                }),
            )

    @api.route('/schedules/rows', methods=['POST'])
    def handle_get_schedule_rows(doc, request):
        route_logger = script.get_logger()
        try:
            payload = _payload_from_request(request)
            schedule, error = _resolve_schedule(doc, payload)
            if error:
                status = 300 if error.get("status") == "multiple_matches" else 400
                return routes.Response(status=status, data=sanitize_for_json(error))

            try:
                max_rows = int(payload.get("max_rows", 2000))
            except Exception:
                max_rows = 2000
            include_empty_rows = _coerce_bool(payload.get("include_empty_rows"), default=False)
            include_header_rows = _coerce_bool(payload.get("include_header_rows"), default=False)
            columns, rows, metadata = _read_schedule_rows(
                schedule,
                doc,
                max_rows=max_rows,
                include_empty_rows=include_empty_rows,
                include_header_rows=include_header_rows,
            )
            if isinstance(metadata, STRING_TYPES):
                return routes.Response(status=400, data=sanitize_for_json({"status": "error", "error": metadata}))

            result = {
                "status": "success",
                "message": "Read {} row(s) from schedule '{}'.".format(len(rows), _safe_text(schedule.Name)),
                "schedule": _schedule_summary(schedule, doc),
                "columns": columns,
                "rows": rows,
                "metadata": metadata,
            }
            return sanitize_for_json(result)
        except Exception as e:
            route_logger.error("Error in /schedules/rows: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while reading schedule rows.",
                    "details": str(e),
                }),
            )

    @api.route('/schedules/audit_capabilities', methods=['POST'])
    def handle_audit_schedule_capabilities(doc, request):
        route_logger = script.get_logger()
        try:
            payload = _payload_from_request(request)
            return _audit_schedule_capabilities(doc, payload)
        except Exception as e:
            route_logger.error("Error in /schedules/audit_capabilities: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while auditing schedule capabilities.",
                    "details": str(e),
                }),
            )

    @api.route('/schedules/compare', methods=['POST'])
    def handle_compare_schedules(doc, request):
        route_logger = script.get_logger()
        try:
            payload = _payload_from_request(request)
            key_fields = _as_list(payload.get("key_fields"))
            if not key_fields:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({"status": "error", "error": "key_fields is required."}),
                )

            overall_payload = {
                "schedule_id": payload.get("overall_schedule_id"),
                "schedule_name": payload.get("overall_schedule_name"),
                "exact_match": _coerce_bool(payload.get("exact_match"), default=False),
            }
            overall_schedule, overall_error = _resolve_schedule(doc, overall_payload)
            if overall_error:
                status = 300 if overall_error.get("status") == "multiple_matches" else 400
                return routes.Response(status=status, data=sanitize_for_json(overall_error))

            release_schedules = []
            release_errors = []
            seen_ids = set([_id_text(overall_schedule.Id)])

            for schedule_id in _as_list(payload.get("release_schedule_ids")):
                schedule = _find_schedule_by_id(doc, schedule_id)
                if not schedule:
                    release_errors.append("Release schedule id '{}' was not found.".format(_safe_text(schedule_id)))
                    continue
                schedule_id_text = _id_text(schedule.Id)
                if schedule_id_text not in seen_ids:
                    release_schedules.append(schedule)
                    seen_ids.add(schedule_id_text)

            named_schedules, named_errors = _resolve_named_schedule_list(
                doc,
                payload.get("release_schedule_names"),
                exact_match=_coerce_bool(payload.get("exact_match"), default=False),
            )
            release_errors.extend(named_errors)
            for schedule in named_schedules:
                schedule_id_text = _id_text(schedule.Id)
                if schedule_id_text not in seen_ids:
                    release_schedules.append(schedule)
                    seen_ids.add(schedule_id_text)

            name_contains = payload.get("release_schedule_name_contains") or payload.get("schedule_name_contains")
            if name_contains:
                contains_matches = _find_schedules_by_name(doc, name_contains, exact_match=False)
                for schedule in contains_matches:
                    schedule_id_text = _id_text(schedule.Id)
                    if schedule_id_text not in seen_ids:
                        release_schedules.append(schedule)
                        seen_ids.add(schedule_id_text)

            exclude_names = [
                _normalize_text(name)
                for name in _as_list(payload.get("exclude_schedule_names"))
                if name
            ]
            if exclude_names:
                kept = []
                for schedule in release_schedules:
                    schedule_name = _normalize_text(schedule.Name)
                    if any(exclude_name in schedule_name for exclude_name in exclude_names):
                        continue
                    kept.append(schedule)
                release_schedules = kept

            placements_by_schedule_id = _schedule_placements_by_schedule_id(doc)
            if _coerce_bool(payload.get("release_schedules_on_sheets_only"), default=False):
                release_schedules = [
                    schedule
                    for schedule in release_schedules
                    if placements_by_schedule_id.get(_id_text(schedule.Id))
                ]

            if not release_schedules:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "No release schedules were resolved. Provide release_schedule_ids, release_schedule_names, or release_schedule_name_contains.",
                        "schedule_errors": release_errors,
                    }),
                )

            try:
                max_rows_per_schedule = int(payload.get("max_rows_per_schedule", 5000))
            except Exception:
                max_rows_per_schedule = 5000
            try:
                max_issues = int(payload.get("max_issues", 200))
            except Exception:
                max_issues = 200
            max_issues = max(1, min(1000, max_issues))

            quantity_field = payload.get("quantity_field")
            overall_analysis, overall_analysis_error = _aggregate_schedule_rows(
                overall_schedule,
                doc,
                key_fields,
                quantity_field=quantity_field,
                max_rows=max_rows_per_schedule,
            )
            schedule_errors = list(release_errors)
            if overall_analysis_error:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "Could not analyze Overall schedule: {}".format(overall_analysis_error),
                    }),
                )

            release_aggregates = {}
            duplicate_keys = {}
            per_schedule = []

            for schedule in release_schedules:
                analysis, analysis_error = _aggregate_schedule_rows(
                    schedule,
                    doc,
                    key_fields,
                    quantity_field=quantity_field,
                    max_rows=max_rows_per_schedule,
                )
                if analysis_error:
                    schedule_errors.append(
                        "{}: {}".format(_safe_text(schedule.Name), _safe_text(analysis_error))
                    )
                    continue

                per_schedule.append({
                    "schedule": _schedule_summary(schedule, doc, placements_by_schedule_id),
                    "total_quantity": analysis["total_quantity"],
                    "data_row_count": analysis["data_row_count"],
                    "key_count": len(analysis["aggregates"]),
                    "truncated": bool(analysis["metadata"].get("truncated")),
                })

                for key, aggregate in analysis["aggregates"].items():
                    if key not in release_aggregates:
                        release_aggregates[key] = {
                            "key": key,
                            "key_values": aggregate["key_values"],
                            "quantity": 0.0,
                            "row_count": 0,
                            "schedules": {},
                        }
                    release_aggregates[key]["quantity"] += aggregate["quantity"]
                    release_aggregates[key]["row_count"] += aggregate["row_count"]
                    release_aggregates[key]["schedules"][_safe_text(schedule.Name)] = {
                        "schedule_id": _id_text(schedule.Id),
                        "quantity": aggregate["quantity"],
                        "row_count": aggregate["row_count"],
                    }

            overall_aggregates = overall_analysis["aggregates"]
            all_keys = sorted(set(list(overall_aggregates.keys()) + list(release_aggregates.keys())))
            missing_from_release = []
            extra_in_release = []
            quantity_mismatches = []

            for key in all_keys:
                overall_record = overall_aggregates.get(key)
                release_record = release_aggregates.get(key)
                overall_quantity = overall_record.get("quantity", 0.0) if overall_record else 0.0
                release_quantity = release_record.get("quantity", 0.0) if release_record else 0.0
                delta = release_quantity - overall_quantity
                if overall_record and not release_record:
                    missing_from_release.append({
                        "key": key,
                        "key_values": overall_record.get("key_values", []),
                        "overall_quantity": overall_quantity,
                        "release_quantity": 0.0,
                        "delta": delta,
                    })
                elif release_record and not overall_record:
                    extra_in_release.append({
                        "key": key,
                        "key_values": release_record.get("key_values", []),
                        "overall_quantity": 0.0,
                        "release_quantity": release_quantity,
                        "delta": delta,
                        "release_schedules": release_record.get("schedules", {}),
                    })
                elif abs(delta) > 0.000001:
                    quantity_mismatches.append({
                        "key": key,
                        "key_values": overall_record.get("key_values", []),
                        "overall_quantity": overall_quantity,
                        "release_quantity": release_quantity,
                        "delta": delta,
                        "release_schedules": release_record.get("schedules", {}),
                    })

                if release_record and len(release_record.get("schedules", {})) > 1:
                    duplicate_keys[key] = {
                        "key": key,
                        "key_values": release_record.get("key_values", []),
                        "release_quantity": release_quantity,
                        "release_schedules": release_record.get("schedules", {}),
                    }

            duplicate_list = list(duplicate_keys.values())
            duplicate_list.sort(key=lambda item: item["key"])
            missing_from_release.sort(key=lambda item: item["key"])
            extra_in_release.sort(key=lambda item: item["key"])
            quantity_mismatches.sort(key=lambda item: (-abs(item["delta"]), item["key"]))

            release_total = sum(item.get("total_quantity", 0.0) for item in per_schedule)
            result = {
                "status": "success",
                "message": "Compared {} release schedule(s) against Overall schedule '{}'.".format(
                    len(per_schedule),
                    _safe_text(overall_schedule.Name),
                ),
                "overall_schedule": _schedule_summary(overall_schedule, doc, placements_by_schedule_id),
                "release_schedules": [item["schedule"] for item in per_schedule],
                "key_fields": key_fields,
                "quantity_field": quantity_field,
                "quantity_mode": overall_analysis.get("quantity_mode"),
                "totals": {
                    "overall_quantity": overall_analysis["total_quantity"],
                    "release_quantity": release_total,
                    "delta": release_total - overall_analysis["total_quantity"],
                },
                "per_schedule": per_schedule,
                "duplicate_keys_across_release_schedules": duplicate_list[:max_issues],
                "duplicate_keys_total": len(duplicate_list),
                "missing_from_release": missing_from_release[:max_issues],
                "missing_from_release_total": len(missing_from_release),
                "extra_in_release": extra_in_release[:max_issues],
                "extra_in_release_total": len(extra_in_release),
                "quantity_mismatches": quantity_mismatches[:max_issues],
                "quantity_mismatches_total": len(quantity_mismatches),
                "schedule_errors": schedule_errors,
                "max_issues": max_issues,
            }
            return sanitize_for_json(result)
        except Exception as e:
            route_logger.error("Error in /schedules/compare: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while comparing schedules.",
                    "details": str(e),
                }),
            )

    @api.route('/schedules/delete', methods=['POST'])
    def handle_delete_schedule(doc, request):
        route_logger = script.get_logger()
        transaction = None
        try:
            payload = _payload_from_request(request)
            schedule, error = _resolve_schedule(doc, payload)
            if error:
                status = 300 if error.get("status") == "multiple_matches" else 400
                return routes.Response(status=status, data=sanitize_for_json(error))

            dry_run = _coerce_bool(payload.get("dry_run"), default=True)
            confirm_delete = _coerce_bool(payload.get("confirm_delete"), default=False)
            placements_by_schedule_id = _schedule_placements_by_schedule_id(doc)
            candidate = _schedule_summary(schedule, doc, placements_by_schedule_id)

            if dry_run:
                return sanitize_for_json({
                    "status": "dry_run",
                    "message": "Schedule '{}' is a candidate for deletion.".format(_safe_text(schedule.Name)),
                    "candidate_count": 1,
                    "candidate": candidate,
                    "candidate_id": candidate.get("id"),
                    "dry_run": True,
                    "confirm_delete": confirm_delete,
                    "next_step": "Call again with dry_run=false and confirm_delete=true to delete this schedule.",
                })

            if not confirm_delete:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "Schedule deletion requires confirm_delete=true. Run with dry_run=true first to inspect the candidate.",
                        "candidate_count": 1,
                        "candidate": candidate,
                        "dry_run": False,
                        "confirm_delete": False,
                    }),
                )

            schedule_id = schedule.Id
            schedule_name = _safe_text(schedule.Name)
            schedule_id_text = _id_text(schedule_id)
            transaction = DB.Transaction(doc, "RevitMCP Delete Schedule")
            transaction.Start()
            deleted_ids = doc.Delete(schedule_id)
            transaction.Commit()
            transaction = None

            deleted_id_values = []
            try:
                for deleted_id in deleted_ids:
                    deleted_id_values.append(_id_text(deleted_id))
            except Exception:
                deleted_id_values = []

            return sanitize_for_json({
                "status": "success",
                "message": "Deleted schedule '{}'.".format(schedule_name),
                "deleted_schedule": candidate,
                "deleted_input_id": schedule_id_text,
                "deleted_input_count": 1,
                "deleted_total_count": len(deleted_id_values),
                "deleted_ids": deleted_id_values,
                "dry_run": False,
                "confirm_delete": True,
            })
        except Exception as e:
            if transaction:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
            route_logger.error("Error in /schedules/delete: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while deleting schedule.",
                    "details": str(e),
                }),
            )

    @api.route('/schedules/create', methods=['POST'])
    def handle_create_schedule(doc, request):
        route_logger = script.get_logger()
        transaction = None
        try:
            payload = _payload_from_request(request)
            schedule_name = payload.get("schedule_name") or payload.get("name")
            uniquify_name = _coerce_bool(payload.get("uniquify_name"), default=False)
            final_name, name_error = _validate_schedule_name_for_create(doc, schedule_name, uniquify_name)
            if name_error:
                return routes.Response(status=400, data=sanitize_for_json({"status": "error", "error": name_error}))

            category, category_error = _find_category(
                doc,
                category_name=payload.get("category_name"),
                category_id=payload.get("category_id"),
            )
            if category_error:
                return routes.Response(status=400, data=sanitize_for_json({"status": "error", "error": category_error}))

            fields = _as_list(payload.get("fields"))
            calculated_fields = _as_list(payload.get("calculated_fields") or payload.get("add_calculated_fields"))
            filters = _as_list(payload.get("filters"))
            sort_fields = _as_list(payload.get("sort_fields") or payload.get("sort_group_fields"))
            settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
            schedule_kind = str(payload.get("schedule_kind") or payload.get("schedule_type") or "").strip().lower()
            is_material_takeoff = _coerce_bool(payload.get("is_material_takeoff"), default=False)
            if schedule_kind in ("material_takeoff", "material takeoff", "takeoff"):
                is_material_takeoff = True

            transaction = DB.Transaction(doc, "RevitMCP Create Schedule")
            transaction.Start()

            if is_material_takeoff:
                try:
                    schedule = DB.ViewSchedule.CreateMaterialTakeoff(doc, category.Id)
                except Exception as material_takeoff_error:
                    raise Exception(
                        "Could not create material takeoff schedule for category '{}': {}".format(
                            _safe_text(category.Name),
                            material_takeoff_error,
                        )
                    )
            else:
                schedule = DB.ViewSchedule.CreateSchedule(doc, category.Id)
            schedule.Name = final_name
            definition = schedule.Definition

            added_fields = []
            for field_spec in fields:
                field, summary, field_error = _add_schedule_field(definition, doc, field_spec)
                if field_error:
                    raise Exception(field_error)
                added_fields.append(summary)

            added_calculated_fields = []
            for field_spec in calculated_fields:
                field, summary, field_error = _add_calculated_schedule_field(definition, doc, field_spec)
                if field_error:
                    raise Exception(field_error)
                added_calculated_fields.append(summary)

            applied_settings = _apply_definition_settings(definition, settings)

            added_filters = []
            for filter_spec in filters:
                summary, filter_error = _add_or_set_filter(definition, doc, filter_spec, mode="add")
                if filter_error:
                    raise Exception(filter_error)
                added_filters.append(summary)

            added_sort_fields = []
            for sort_spec in sort_fields:
                summary, sort_error = _add_or_set_sort_group_field(definition, doc, sort_spec, mode="add")
                if sort_error:
                    raise Exception(sort_error)
                added_sort_fields.append(summary)

            transaction.Commit()
            transaction = None

            result = {
                "status": "success",
                "message": "Created schedule '{}'.".format(_safe_text(schedule.Name)),
                "schedule": _schedule_details(schedule, doc, include_available_fields=False),
                "schedule_kind": "material_takeoff" if is_material_takeoff else "schedule",
                "added_fields": added_fields,
                "added_calculated_fields": added_calculated_fields,
                "added_filters": added_filters,
                "added_sort_group_fields": added_sort_fields,
                "applied_settings": applied_settings,
            }
            return sanitize_for_json(result)
        except Exception as e:
            if transaction:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
            route_logger.error("Error in /schedules/create: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while creating schedule.",
                    "details": str(e),
                }),
            )

    @api.route('/schedules/update', methods=['POST'])
    def handle_update_schedule(doc, request):
        route_logger = script.get_logger()
        transaction = None
        try:
            payload = _payload_from_request(request)
            schedule, error = _resolve_schedule(doc, payload)
            if error:
                status = 300 if error.get("status") == "multiple_matches" else 400
                return routes.Response(status=status, data=sanitize_for_json(error))

            transaction = DB.Transaction(doc, "RevitMCP Update Schedule")
            transaction.Start()

            definition = schedule.Definition
            changes = {
                "renamed": False,
                "added_fields": [],
                "added_calculated_fields": [],
                "removed_fields": [],
                "removed_filter_indexes": [],
                "added_filters": [],
                "updated_filters": [],
                "removed_sort_group_indexes": [],
                "added_sort_group_fields": [],
                "updated_sort_group_fields": [],
                "cleared_filters": 0,
                "cleared_sort_group_fields": 0,
                "applied_settings": [],
            }

            new_name = payload.get("new_name")
            if new_name:
                new_name = str(new_name).strip()
                if _normalize_text(new_name) != _normalize_text(schedule.Name) and _schedule_name_exists(doc, new_name):
                    raise Exception("A schedule named '{}' already exists.".format(_safe_text(new_name)))
                old_name = _safe_text(schedule.Name)
                schedule.Name = new_name
                changes["renamed"] = True
                changes["old_name"] = old_name
                changes["new_name"] = _safe_text(schedule.Name)

            for field_spec in _as_list(payload.get("add_fields")):
                field, summary, field_error = _add_schedule_field(definition, doc, field_spec)
                if field_error:
                    raise Exception(field_error)
                changes["added_fields"].append(summary)

            for field_spec in _as_list(payload.get("add_calculated_fields") or payload.get("calculated_fields")):
                field, summary, field_error = _add_calculated_schedule_field(definition, doc, field_spec)
                if field_error:
                    raise Exception(field_error)
                changes["added_calculated_fields"].append(summary)

            for field_spec in _as_list(payload.get("remove_fields")):
                field, summary, field_error = _find_schedule_field(definition, doc, field_spec)
                if field_error:
                    raise Exception(field_error)
                try:
                    definition.RemoveField(field.FieldId)
                    changes["removed_fields"].append(summary)
                except Exception as remove_error:
                    raise Exception("Could not remove field '{}': {}".format(summary.get("name"), remove_error))

            settings = payload.get("settings")
            if isinstance(settings, dict):
                changes["applied_settings"] = _apply_definition_settings(definition, settings)

            if _coerce_bool(payload.get("clear_filters"), default=False):
                changes["cleared_filters"] = _clear_filters(definition)

            remove_filter_indexes = payload.get("remove_filter_indexes")
            if remove_filter_indexes:
                changes["removed_filter_indexes"] = _remove_filter_indexes(definition, _as_list(remove_filter_indexes))

            if _coerce_bool(payload.get("replace_filters"), default=False):
                changes["cleared_filters"] = _clear_filters(definition)

            for filter_update in _as_list(payload.get("filter_updates")):
                if not isinstance(filter_update, dict) or filter_update.get("index") is None:
                    raise Exception("Each filter update requires an index.")
                summary, filter_error = _add_or_set_filter(
                    definition,
                    doc,
                    filter_update,
                    mode="set",
                    index=filter_update.get("index"),
                )
                if filter_error:
                    raise Exception(filter_error)
                changes["updated_filters"].append(summary)

            for filter_spec in _as_list(payload.get("filters") or payload.get("add_filters")):
                summary, filter_error = _add_or_set_filter(definition, doc, filter_spec, mode="add")
                if filter_error:
                    raise Exception(filter_error)
                changes["added_filters"].append(summary)

            if _coerce_bool(payload.get("clear_sorting"), default=False):
                changes["cleared_sort_group_fields"] = _clear_sort_group_fields(definition)

            remove_sort_indexes = payload.get("remove_sort_group_indexes") or payload.get("remove_sort_indexes")
            if remove_sort_indexes:
                changes["removed_sort_group_indexes"] = _remove_sort_group_indexes(definition, _as_list(remove_sort_indexes))

            if _coerce_bool(payload.get("replace_sorting"), default=False):
                changes["cleared_sort_group_fields"] = _clear_sort_group_fields(definition)

            for sort_update in _as_list(payload.get("sort_group_updates") or payload.get("sort_updates")):
                if not isinstance(sort_update, dict) or sort_update.get("index") is None:
                    raise Exception("Each sort/group update requires an index.")
                summary, sort_error = _add_or_set_sort_group_field(
                    definition,
                    doc,
                    sort_update,
                    mode="set",
                    index=sort_update.get("index"),
                )
                if sort_error:
                    raise Exception(sort_error)
                changes["updated_sort_group_fields"].append(summary)

            for sort_spec in _as_list(payload.get("sort_fields") or payload.get("sort_group_fields") or payload.get("add_sort_fields")):
                summary, sort_error = _add_or_set_sort_group_field(definition, doc, sort_spec, mode="add")
                if sort_error:
                    raise Exception(sort_error)
                changes["added_sort_group_fields"].append(summary)

            transaction.Commit()
            transaction = None

            result = {
                "status": "success",
                "message": "Updated schedule '{}'.".format(_safe_text(schedule.Name)),
                "schedule": _schedule_details(schedule, doc, include_available_fields=False),
                "changes": changes,
            }
            return sanitize_for_json(result)
        except Exception as e:
            if transaction:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
            route_logger.error("Error in /schedules/update: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while updating schedule.",
                    "details": str(e),
                }),
            )
