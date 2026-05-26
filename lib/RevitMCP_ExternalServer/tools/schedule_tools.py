from RevitMCP_ExternalServer.core.runtime_config import bounded_int
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


LIST_SCHEDULES_TOOL_NAME = "list_schedules"
GET_SCHEDULE_INFO_TOOL_NAME = "get_schedule_info"
LIST_SCHEDULE_AVAILABLE_FIELDS_TOOL_NAME = "list_schedule_available_fields"
GET_SCHEDULE_ROWS_TOOL_NAME = "get_schedule_rows"
COMPARE_SCHEDULES_TOOL_NAME = "compare_schedules"
DUPLICATE_SCHEDULE_TOOL_NAME = "duplicate_schedule"
DELETE_SCHEDULE_TOOL_NAME = "delete_schedule"
CREATE_SCHEDULE_TOOL_NAME = "create_schedule"
UPDATE_SCHEDULE_TOOL_NAME = "update_schedule"
AUDIT_SCHEDULE_CAPABILITIES_TOOL_NAME = "audit_schedule_capabilities"


def _schedule_identifier_payload(schedule_id: str = None, schedule_name: str = None, exact_match: bool = False) -> dict:
    payload = {"exact_match": bool(exact_match)}
    if schedule_id:
        payload["schedule_id"] = str(schedule_id)
    if schedule_name:
        payload["schedule_name"] = schedule_name
    return payload


def _missing_route_result(command_path: str) -> dict:
    return {
        "status": "error",
        "error_type": "route_not_defined",
        "message": (
            "The active Revit route set does not support '{}'. Reload/update the RevitMCP extension "
            "inside Revit to enable schedule tools."
        ).format(command_path),
    }


def _call_schedule_route(services, command_path: str, payload: dict) -> dict:
    result = services.revit_client.call_listener(
        command_path=command_path,
        method="POST",
        payload_data=payload,
    )
    if result.get("status") == "error" and services.revit_client.is_route_not_defined(result, command_path):
        return _missing_route_result(command_path)
    return result


def list_schedules_handler(
    services,
    schedule_name: str = None,
    exact_match: bool = False,
    limit: int = 200,
    **_kwargs,
) -> dict:
    safe_limit = bounded_int(limit, 200, min_value=1, max_value=1000)
    payload = {"exact_match": bool(exact_match), "limit": safe_limit}
    if schedule_name:
        payload["schedule_name"] = schedule_name

    services.logger.info(
        "MCP Tool executed: %s with schedule_name=%s exact_match=%s limit=%s",
        LIST_SCHEDULES_TOOL_NAME,
        schedule_name,
        exact_match,
        safe_limit,
    )
    result = _call_schedule_route(services, "/schedules/list", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["status", "message", "schedules", "count", "schedules_total", "schedules_truncated", "limit"],
    )


def get_schedule_info_handler(
    services,
    schedule_id: str = None,
    schedule_name: str = None,
    exact_match: bool = False,
    include_available_fields: bool = False,
    **_kwargs,
) -> dict:
    if not schedule_id and not schedule_name:
        return {
            "status": "error",
            "message": "Provide either schedule_id or schedule_name. Use list_schedules to discover schedule IDs.",
        }

    payload = _schedule_identifier_payload(schedule_id, schedule_name, exact_match)
    payload["include_available_fields"] = bool(include_available_fields)
    services.logger.info(
        "MCP Tool executed: %s with schedule_id=%s schedule_name=%s exact_match=%s",
        GET_SCHEDULE_INFO_TOOL_NAME,
        schedule_id,
        schedule_name,
        exact_match,
    )
    result = _call_schedule_route(services, "/schedules/info", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["status", "message", "schedule", "matching_schedules"],
    )


def list_schedule_available_fields_handler(
    services,
    schedule_id: str = None,
    schedule_name: str = None,
    exact_match: bool = False,
    **_kwargs,
) -> dict:
    if not schedule_id and not schedule_name:
        return {
            "status": "error",
            "message": "Provide either schedule_id or schedule_name. Use list_schedules to discover schedule IDs.",
        }

    payload = _schedule_identifier_payload(schedule_id, schedule_name, exact_match)
    services.logger.info(
        "MCP Tool executed: %s with schedule_id=%s schedule_name=%s",
        LIST_SCHEDULE_AVAILABLE_FIELDS_TOOL_NAME,
        schedule_id,
        schedule_name,
    )
    result = _call_schedule_route(services, "/schedules/available_fields", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["status", "message", "schedule", "available_fields", "count", "matching_schedules"],
    )


def get_schedule_rows_handler(
    services,
    schedule_id: str = None,
    schedule_name: str = None,
    exact_match: bool = False,
    max_rows: int = 2000,
    include_empty_rows: bool = False,
    include_header_rows: bool = False,
    **_kwargs,
) -> dict:
    if not schedule_id and not schedule_name:
        return {
            "status": "error",
            "message": "Provide either schedule_id or schedule_name. Use list_schedules to discover schedule IDs.",
        }

    safe_max_rows = bounded_int(max_rows, 2000, min_value=1, max_value=10000)
    payload = _schedule_identifier_payload(schedule_id, schedule_name, exact_match)
    payload["max_rows"] = safe_max_rows
    payload["include_empty_rows"] = bool(include_empty_rows)
    payload["include_header_rows"] = bool(include_header_rows)
    services.logger.info(
        "MCP Tool executed: %s with schedule_id=%s schedule_name=%s max_rows=%s",
        GET_SCHEDULE_ROWS_TOOL_NAME,
        schedule_id,
        schedule_name,
        safe_max_rows,
    )
    result = _call_schedule_route(services, "/schedules/rows", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["status", "message", "schedule", "columns", "rows", "metadata", "matching_schedules"],
    )


def compare_schedules_handler(
    services,
    overall_schedule_id: str = None,
    overall_schedule_name: str = None,
    release_schedule_ids: list = None,
    release_schedule_names: list = None,
    release_schedule_name_contains: str = None,
    release_schedules_on_sheets_only: bool = False,
    exclude_schedule_names: list = None,
    key_fields: list = None,
    quantity_field=None,
    exact_match: bool = False,
    max_rows_per_schedule: int = 5000,
    max_issues: int = 200,
    **_kwargs,
) -> dict:
    if not overall_schedule_id and not overall_schedule_name:
        return {"status": "error", "message": "Provide overall_schedule_id or overall_schedule_name."}
    if not key_fields:
        return {
            "status": "error",
            "message": "key_fields is required. Use the column(s) that identify a part, e.g. Part Number or Material: Mark.",
        }
    if not release_schedule_ids and not release_schedule_names and not release_schedule_name_contains:
        return {
            "status": "error",
            "message": "Provide release_schedule_ids, release_schedule_names, or release_schedule_name_contains.",
        }

    payload = {
        "exact_match": bool(exact_match),
        "release_schedules_on_sheets_only": bool(release_schedules_on_sheets_only),
        "key_fields": key_fields,
        "max_rows_per_schedule": bounded_int(max_rows_per_schedule, 5000, min_value=1, max_value=10000),
        "max_issues": bounded_int(max_issues, 200, min_value=1, max_value=1000),
    }
    if overall_schedule_id:
        payload["overall_schedule_id"] = str(overall_schedule_id)
    if overall_schedule_name:
        payload["overall_schedule_name"] = overall_schedule_name
    if release_schedule_ids:
        payload["release_schedule_ids"] = [str(schedule_id) for schedule_id in release_schedule_ids]
    if release_schedule_names:
        payload["release_schedule_names"] = release_schedule_names
    if release_schedule_name_contains:
        payload["release_schedule_name_contains"] = release_schedule_name_contains
    if exclude_schedule_names:
        payload["exclude_schedule_names"] = exclude_schedule_names
    if quantity_field:
        payload["quantity_field"] = quantity_field

    services.logger.info(
        "MCP Tool executed: %s with overall=%s release_contains=%s",
        COMPARE_SCHEDULES_TOOL_NAME,
        overall_schedule_id or overall_schedule_name,
        release_schedule_name_contains,
    )
    result = _call_schedule_route(services, "/schedules/compare", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status",
            "message",
            "overall_schedule",
            "release_schedules",
            "totals",
            "per_schedule",
            "duplicate_keys_across_release_schedules",
            "missing_from_release",
            "extra_in_release",
            "quantity_mismatches",
            "schedule_errors",
        ],
    )


def duplicate_schedule_handler(
    services,
    schedule_id: str = None,
    schedule_name: str = None,
    new_name: str = None,
    exact_match: bool = False,
    uniquify_name: bool = True,
    **_kwargs,
) -> dict:
    if not schedule_id and not schedule_name:
        return {
            "status": "error",
            "message": "Provide either schedule_id or schedule_name. Use list_schedules to discover schedule IDs.",
        }

    payload = {
        "duplicate_option": "duplicate",
        "exact_match": bool(exact_match),
        "uniquify_name": bool(uniquify_name),
    }
    if schedule_id:
        payload["view_id"] = str(schedule_id)
    if schedule_name:
        payload["view_name"] = schedule_name
    if new_name:
        payload["new_name"] = new_name

    services.logger.info(
        "MCP Tool executed: %s with schedule_id=%s schedule_name=%s new_name=%s",
        DUPLICATE_SCHEDULE_TOOL_NAME,
        schedule_id,
        schedule_name,
        new_name,
    )
    result = services.revit_client.call_listener(
        command_path="/views/duplicate",
        method="POST",
        payload_data=payload,
    )
    if result.get("status") == "error" and services.revit_client.is_route_not_defined(result, "/views/duplicate"):
        return _missing_route_result("/views/duplicate")
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["status", "message", "source_view", "new_view", "matching_views"],
    )


def delete_schedule_handler(
    services,
    schedule_id: str = None,
    schedule_name: str = None,
    exact_match: bool = False,
    dry_run: bool = True,
    confirm_delete: bool = False,
    **_kwargs,
) -> dict:
    if not schedule_id and not schedule_name:
        return {
            "status": "error",
            "message": "Provide either schedule_id or schedule_name. Use list_schedules to discover schedule IDs.",
        }

    payload = _schedule_identifier_payload(schedule_id, schedule_name, exact_match)
    payload["dry_run"] = bool(dry_run)
    payload["confirm_delete"] = bool(confirm_delete)

    services.logger.info(
        "MCP Tool executed: %s with schedule_id=%s schedule_name=%s dry_run=%s confirm_delete=%s",
        DELETE_SCHEDULE_TOOL_NAME,
        schedule_id,
        schedule_name,
        dry_run,
        confirm_delete,
    )
    result = _call_schedule_route(services, "/schedules/delete", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status",
            "message",
            "candidate_count",
            "candidate",
            "candidate_id",
            "deleted_schedule",
            "deleted_input_id",
            "deleted_input_count",
            "deleted_total_count",
            "deleted_ids",
            "dry_run",
            "confirm_delete",
            "next_step",
            "matching_schedules",
        ],
    )


def create_schedule_handler(
    services,
    schedule_name: str,
    category_name: str = None,
    category_id: str = None,
    schedule_kind: str = None,
    is_material_takeoff: bool = False,
    fields: list = None,
    calculated_fields: list = None,
    filters: list = None,
    sort_fields: list = None,
    settings: dict = None,
    uniquify_name: bool = False,
    **_kwargs,
) -> dict:
    if not schedule_name:
        return {"status": "error", "message": "schedule_name is required."}
    if not category_name and not category_id:
        return {"status": "error", "message": "Provide category_name or category_id."}

    payload = {
        "schedule_name": schedule_name,
        "uniquify_name": bool(uniquify_name),
        "fields": fields or [],
        "calculated_fields": calculated_fields or [],
        "filters": filters or [],
        "sort_fields": sort_fields or [],
        "settings": settings or {},
    }
    if schedule_kind:
        payload["schedule_kind"] = schedule_kind
    if is_material_takeoff:
        payload["is_material_takeoff"] = True
    if category_name:
        payload["category_name"] = category_name
    if category_id:
        payload["category_id"] = str(category_id)

    services.logger.info(
        "MCP Tool executed: %s with schedule_name=%s category_name=%s category_id=%s",
        CREATE_SCHEDULE_TOOL_NAME,
        schedule_name,
        category_name,
        category_id,
    )
    result = _call_schedule_route(services, "/schedules/create", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status",
            "message",
            "schedule",
            "added_fields",
            "added_calculated_fields",
            "added_filters",
            "added_sort_group_fields",
        ],
    )


def update_schedule_handler(
    services,
    schedule_id: str = None,
    schedule_name: str = None,
    exact_match: bool = False,
    new_name: str = None,
    add_fields: list = None,
    add_calculated_fields: list = None,
    calculated_fields: list = None,
    remove_fields: list = None,
    filters: list = None,
    add_filters: list = None,
    replace_filters: bool = False,
    clear_filters: bool = False,
    filter_updates: list = None,
    remove_filter_indexes: list = None,
    sort_fields: list = None,
    sort_group_fields: list = None,
    replace_sorting: bool = False,
    clear_sorting: bool = False,
    sort_group_updates: list = None,
    remove_sort_group_indexes: list = None,
    settings: dict = None,
    **_kwargs,
) -> dict:
    if not schedule_id and not schedule_name:
        return {
            "status": "error",
            "message": "Provide either schedule_id or schedule_name. Use list_schedules to discover schedule IDs.",
        }

    payload = _schedule_identifier_payload(schedule_id, schedule_name, exact_match)
    operations = {
        "new_name": new_name,
        "add_fields": add_fields,
        "add_calculated_fields": add_calculated_fields or calculated_fields,
        "remove_fields": remove_fields,
        "filters": filters,
        "add_filters": add_filters,
        "replace_filters": replace_filters,
        "clear_filters": clear_filters,
        "filter_updates": filter_updates,
        "remove_filter_indexes": remove_filter_indexes,
        "sort_fields": sort_fields,
        "sort_group_fields": sort_group_fields,
        "replace_sorting": replace_sorting,
        "clear_sorting": clear_sorting,
        "sort_group_updates": sort_group_updates,
        "remove_sort_group_indexes": remove_sort_group_indexes,
        "settings": settings,
    }
    has_operation = False
    for key, value in operations.items():
        if value is None:
            continue
        if isinstance(value, bool) and not value:
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        payload[key] = value
        has_operation = True

    if not has_operation:
        return {
            "status": "error",
            "message": "Provide at least one schedule update operation.",
        }

    services.logger.info(
        "MCP Tool executed: %s with schedule_id=%s schedule_name=%s",
        UPDATE_SCHEDULE_TOOL_NAME,
        schedule_id,
        schedule_name,
    )
    result = _call_schedule_route(services, "/schedules/update", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["status", "message", "schedule", "changes", "matching_schedules"],
    )


def audit_schedule_capabilities_handler(
    services,
    category_name: str = None,
    category_id: str = None,
    schedule_kind: str = None,
    is_material_takeoff: bool = False,
    fields: list = None,
    field_name_contains: str = None,
    filter_operators: list = None,
    max_fields: int = 24,
    max_filter_tests: int = 120,
    include_filter_tests: bool = True,
    include_sort_tests: bool = True,
    include_settings_tests: bool = True,
    include_row_read: bool = True,
    **_kwargs,
) -> dict:
    if not category_name and not category_id:
        return {"status": "error", "message": "Provide category_name or category_id."}

    payload = {
        "fields": fields or [],
        "max_fields": bounded_int(max_fields, 24, min_value=1, max_value=250),
        "max_filter_tests": bounded_int(max_filter_tests, 120, min_value=0, max_value=1000),
        "include_filter_tests": bool(include_filter_tests),
        "include_sort_tests": bool(include_sort_tests),
        "include_settings_tests": bool(include_settings_tests),
        "include_row_read": bool(include_row_read),
    }
    if category_name:
        payload["category_name"] = category_name
    if category_id:
        payload["category_id"] = str(category_id)
    if schedule_kind:
        payload["schedule_kind"] = schedule_kind
    if is_material_takeoff:
        payload["is_material_takeoff"] = True
    if field_name_contains:
        payload["field_name_contains"] = field_name_contains
    if filter_operators:
        payload["filter_operators"] = [str(operator) for operator in filter_operators]

    services.logger.info(
        "MCP Tool executed: %s with category_name=%s category_id=%s schedule_kind=%s",
        AUDIT_SCHEDULE_CAPABILITIES_TOOL_NAME,
        category_name,
        category_id,
        schedule_kind,
    )
    result = _call_schedule_route(services, "/schedules/audit_capabilities", payload)
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status",
            "message",
            "audit_mode",
            "rolled_back",
            "category",
            "schedule_kind",
            "can_create",
            "summary",
            "field_tests",
            "filter_tests",
            "sort_tests",
            "settings_tests",
            "row_read_test",
            "limitations",
        ],
    )


def build_schedule_tools() -> list[ToolDefinition]:
    field_spec_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Schedule field/parameter name, e.g. Mark or Family and Type."},
            "field_name": {"type": "string", "description": "Alias for name."},
            "field_id": {"type": "string", "description": "Existing schedule field ID from get_schedule_info."},
            "field_index": {"type": "integer", "description": "Existing schedule field index from get_schedule_info."},
            "available_field_index": {
                "type": "integer",
                "description": "Stable index from list_schedule_available_fields. Use this when names or parameter IDs are ambiguous.",
            },
            "schedulable_field_index": {"type": "integer", "description": "Alias for available_field_index."},
            "column_index": {"type": "integer", "description": "Visible table column index from get_schedule_rows."},
            "parameter_id": {"type": "string", "description": "Parameter ElementId from available field listings."},
            "column_heading": {"type": "string", "description": "Optional column heading to apply when adding a field."},
            "hidden": {"type": "boolean", "description": "Whether an added field should be hidden."},
        },
    }
    flexible_field_schema = dict(field_spec_schema)
    flexible_field_schema["description"] = (
        "Schedule field spec. Handlers also accept plain string field names, but object form is preferred "
        "for provider compatibility."
    )
    filter_schema = {
        "type": "object",
        "properties": {
            "field": field_spec_schema,
            "field_name": {"type": "string"},
            "field_id": {"type": "string"},
            "field_index": {"type": "integer"},
            "available_field_index": {"type": "integer"},
            "schedulable_field_index": {"type": "integer"},
            "parameter_id": {"type": "string"},
            "operator": {
                "type": "string",
                "enum": [
                    "equals",
                    "not_equals",
                    "greater_than",
                    "greater_than_or_equal",
                    "less_than",
                    "less_than_or_equal",
                    "contains",
                    "not_contains",
                    "begins_with",
                    "not_begins_with",
                    "ends_with",
                    "not_ends_with",
                    "has_parameter",
                    "has_value",
                    "has_no_value",
                ],
            },
            "value": {
                "type": "string",
                "description": "Filter comparison value. Use value_type='element_id' when Revit expects an ElementId.",
            },
            "value_type": {
                "type": "string",
                "enum": ["string", "integer", "double", "element_id"],
            },
            "index": {"type": "integer", "description": "Existing filter index when updating a filter."},
        },
    }
    sort_schema = {
        "type": "object",
        "properties": {
            "field": flexible_field_schema,
            "field_name": {"type": "string"},
            "field_id": {"type": "string"},
            "field_index": {"type": "integer"},
            "available_field_index": {"type": "integer"},
            "schedulable_field_index": {"type": "integer"},
            "parameter_id": {"type": "string"},
            "order": {"type": "string", "enum": ["ascending", "descending", "asc", "desc"]},
            "show_header": {"type": "boolean"},
            "show_footer": {"type": "boolean"},
            "show_blank_line": {"type": "boolean"},
            "show_footer_title": {"type": "boolean"},
            "show_footer_count": {"type": "boolean"},
            "index": {"type": "integer", "description": "Existing sort/group index when updating sorting."},
        },
    }
    calculated_field_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Visible calculated field heading/name, e.g. DLO Width.",
            },
            "column_heading": {"type": "string", "description": "Optional explicit column heading."},
            "kind": {
                "type": "string",
                "enum": ["formula", "percentage"],
                "description": "Calculated field kind. Percentage fields are fully supported by Revit API; formula text assignment is not exposed in Revit 2024.",
            },
            "calculation_type": {
                "type": "string",
                "enum": ["formula", "percentage"],
                "description": "Alias for kind.",
            },
            "field_type": {
                "type": "string",
                "enum": ["Formula", "Percentage", "formula", "percentage"],
                "description": "Alias for kind.",
            },
            "formula": {
                "type": "string",
                "description": "Formula text. Revit 2024 API does not expose a public setter; supplying this returns an explicit unsupported error.",
            },
            "expression": {
                "type": "string",
                "description": "Alias for formula.",
            },
            "percentage_of": {
                "description": "Field spec for the numeric field to calculate percentages of.",
                **flexible_field_schema,
            },
            "percentage_by": {
                "description": "Optional grouped field spec to calculate percentages within a group.",
                **flexible_field_schema,
            },
            "hidden": {"type": "boolean", "description": "Whether the added calculated field should be hidden."},
        },
    }
    settings_schema = {
        "type": "object",
        "properties": {
            "is_itemized": {"type": "boolean"},
            "show_grand_total": {"type": "boolean"},
            "show_grand_total_count": {"type": "boolean"},
            "show_grand_total_title": {"type": "boolean"},
            "grand_total_title": {"type": "string"},
            "include_linked_files": {"type": "boolean"},
            "show_headers": {"type": "boolean"},
            "show_title": {"type": "boolean"},
            "show_grid_lines": {"type": "boolean"},
        },
    }

    return [
        ToolDefinition(
            name=LIST_SCHEDULES_TOOL_NAME,
            description=(
                "Lists Revit schedules in the current project. Optionally filter by schedule_name; returns IDs, "
                "names, categories, field counts, filter counts, and sort/group counts."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "schedule_name": {"type": "string", "description": "Optional schedule name or partial name to search."},
                    "exact_match": {"type": "boolean", "description": "Whether schedule_name must match exactly. Default false."},
                    "limit": {"type": "integer", "description": "Maximum schedules to return. Default 200, max 1000."},
                },
            },
            handler=list_schedules_handler,
        ),
        ToolDefinition(
            name=GET_SCHEDULE_INFO_TOOL_NAME,
            description=(
                "Returns a complete schedule definition snapshot by schedule_id or schedule_name: fields/parameters, "
                "visible/hidden state, filters, sort/group settings, and schedule settings. Prefer schedule_id after "
                "calling list_schedules."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "schedule_id": {"type": "string", "description": "Schedule ElementId. Preferred when known."},
                    "schedule_name": {"type": "string", "description": "Schedule name or partial name."},
                    "exact_match": {"type": "boolean", "description": "Whether schedule_name must match exactly. Default false."},
                    "include_available_fields": {
                        "type": "boolean",
                        "description": "Also include all fields that could be added to this schedule. Default false.",
                    },
                },
            },
            handler=get_schedule_info_handler,
        ),
        ToolDefinition(
            name=LIST_SCHEDULE_AVAILABLE_FIELDS_TOOL_NAME,
            description=(
                "Lists parameters/fields that can be added to an existing schedule. Use this before create_schedule "
                "or update_schedule when field names are ambiguous. The returned available_field_index is the safest "
                "selector when names or parameter IDs collide."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "schedule_id": {"type": "string"},
                    "schedule_name": {"type": "string"},
                    "exact_match": {"type": "boolean"},
                },
            },
            handler=list_schedule_available_fields_handler,
        ),
        ToolDefinition(
            name=GET_SCHEDULE_ROWS_TOOL_NAME,
            description=(
                "Reads visible table rows from a Revit schedule, returning visible columns with column_index and "
                "row cell values. Use this to inspect the actual schedule output, not just the definition."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "schedule_id": {"type": "string"},
                    "schedule_name": {"type": "string"},
                    "exact_match": {"type": "boolean"},
                    "max_rows": {"type": "integer", "description": "Maximum body rows to return. Default 2000, max 10000."},
                    "include_empty_rows": {"type": "boolean"},
                    "include_header_rows": {
                        "type": "boolean",
                        "description": "When true, include Revit's header echo row if it appears in the body section. Default false.",
                    },
                },
            },
            handler=get_schedule_rows_handler,
        ),
        ToolDefinition(
            name=COMPARE_SCHEDULES_TOOL_NAME,
            description=(
                "Compares release schedules against an Overall schedule using actual schedule rows. Groups by "
                "key_fields, sums quantity_field when provided, and reports duplicates across release schedules, "
                "missing keys, extra keys, and quantity mismatches. Use this for release schedule quantity audits."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "overall_schedule_id": {"type": "string"},
                    "overall_schedule_name": {"type": "string"},
                    "release_schedule_ids": {"type": "array", "items": {"type": "string"}},
                    "release_schedule_names": {"type": "array", "items": {"type": "string"}},
                    "release_schedule_name_contains": {
                        "type": "string",
                        "description": "Find release schedules by partial name, e.g. MR- 2.04.",
                    },
                    "release_schedules_on_sheets_only": {
                        "type": "boolean",
                        "description": "When true, only compare schedules placed on sheets.",
                    },
                    "exclude_schedule_names": {"type": "array", "items": {"type": "string"}},
                    "key_fields": {
                        "type": "array",
                        "items": field_spec_schema,
                        "description": (
                            "Fields that identify a part. Handlers also accept plain strings, e.g. ['Part Number']."
                        ),
                    },
                    "quantity_field": {
                        "type": "string",
                        "description": "Visible field to sum, e.g. Quantity or Count. If omitted, each row counts as 1.",
                    },
                    "exact_match": {"type": "boolean"},
                    "max_rows_per_schedule": {"type": "integer"},
                    "max_issues": {"type": "integer"},
                },
            },
            handler=compare_schedules_handler,
        ),
        ToolDefinition(
            name=DUPLICATE_SCHEDULE_TOOL_NAME,
            description=(
                "Duplicates an existing Revit schedule by schedule_id or schedule_name and optionally renames it. "
                "Use this to create diagnostic copies of material takeoffs or release schedules before changing "
                "itemization, sorting, or filters."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "schedule_id": {"type": "string", "description": "Schedule ElementId. Preferred when known."},
                    "schedule_name": {"type": "string", "description": "Schedule name or partial name."},
                    "new_name": {"type": "string", "description": "Optional name for the duplicated schedule."},
                    "exact_match": {"type": "boolean"},
                    "uniquify_name": {"type": "boolean", "description": "Append a number if new_name already exists. Default true."},
                },
            },
            handler=duplicate_schedule_handler,
        ),
        ToolDefinition(
            name=DELETE_SCHEDULE_TOOL_NAME,
            description=(
                "Deletes a Revit schedule with safeguards. Defaults to dry_run=true; actual deletion requires "
                "dry_run=false and confirm_delete=true. Dry run returns sheet placement info so scheduled views "
                "on sheets are visible before deletion."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "schedule_id": {"type": "string", "description": "Schedule ElementId. Preferred when known."},
                    "schedule_name": {"type": "string", "description": "Schedule name or partial name."},
                    "exact_match": {"type": "boolean"},
                    "dry_run": {
                        "type": "boolean",
                        "description": "When true, only reports what would be deleted. Default true.",
                    },
                    "confirm_delete": {
                        "type": "boolean",
                        "description": "Must be true together with dry_run=false to actually delete the schedule.",
                    },
                },
            },
            handler=delete_schedule_handler,
        ),
        ToolDefinition(
            name=CREATE_SCHEDULE_TOOL_NAME,
            description=(
                "Creates a new Revit schedule for a category, names it, and optionally adds fields, filters, sorting, "
                "and schedule settings. Supports regular schedules and material takeoffs. Filter fields that are not "
                "visible can be added as hidden fields."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "schedule_name": {"type": "string"},
                    "category_name": {"type": "string", "description": "Revit category name, e.g. Doors, Windows, Rooms."},
                    "category_id": {"type": "string", "description": "Category ElementId. Use when category name is ambiguous."},
                    "schedule_kind": {
                        "type": "string",
                        "enum": ["schedule", "material_takeoff"],
                        "description": "Use material_takeoff when fields like Material: Mark are required.",
                    },
                    "is_material_takeoff": {
                        "type": "boolean",
                        "description": "Alias for schedule_kind='material_takeoff'.",
                    },
                    "fields": {"type": "array", "items": flexible_field_schema},
                    "calculated_fields": {"type": "array", "items": calculated_field_schema},
                    "filters": {"type": "array", "items": filter_schema},
                    "sort_fields": {"type": "array", "items": sort_schema},
                    "settings": settings_schema,
                    "uniquify_name": {
                        "type": "boolean",
                        "description": "When true, appends a number if schedule_name already exists. Default false.",
                    },
                },
                "required": ["schedule_name"],
            },
            handler=create_schedule_handler,
        ),
        ToolDefinition(
            name=UPDATE_SCHEDULE_TOOL_NAME,
            description=(
                "Updates an existing Revit schedule by ID or name. Supports renaming, adding/removing fields, "
                "adding/replacing/updating/removing filters, updating sorting/grouping, and changing schedule settings."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "schedule_id": {"type": "string"},
                    "schedule_name": {"type": "string"},
                    "exact_match": {"type": "boolean"},
                    "new_name": {"type": "string"},
                    "add_fields": {"type": "array", "items": flexible_field_schema},
                    "add_calculated_fields": {"type": "array", "items": calculated_field_schema},
                    "calculated_fields": {
                        "type": "array",
                        "items": calculated_field_schema,
                        "description": "Alias for add_calculated_fields.",
                    },
                    "remove_fields": {"type": "array", "items": flexible_field_schema},
                    "filters": {
                        "type": "array",
                        "items": filter_schema,
                        "description": "Filters to add. When replace_filters=true, this becomes the complete new filter set.",
                    },
                    "add_filters": {"type": "array", "items": filter_schema},
                    "replace_filters": {"type": "boolean"},
                    "clear_filters": {"type": "boolean"},
                    "filter_updates": {
                        "type": "array",
                        "items": filter_schema,
                        "description": "Filter specs with index to replace existing filters in place.",
                    },
                    "remove_filter_indexes": {"type": "array", "items": {"type": "integer"}},
                    "sort_fields": {
                        "type": "array",
                        "items": sort_schema,
                        "description": "Sort/group fields to add. When replace_sorting=true, this becomes the complete new sort set.",
                    },
                    "sort_group_fields": {"type": "array", "items": sort_schema},
                    "replace_sorting": {"type": "boolean"},
                    "clear_sorting": {"type": "boolean"},
                    "sort_group_updates": {"type": "array", "items": sort_schema},
                    "remove_sort_group_indexes": {"type": "array", "items": {"type": "integer"}},
                    "settings": settings_schema,
                },
            },
            handler=update_schedule_handler,
        ),
        ToolDefinition(
            name=AUDIT_SCHEDULE_CAPABILITIES_TOOL_NAME,
            description=(
                "Runs a rollback-only schedule capability probe for a category. Creates a temporary schedule inside "
                "a Revit transaction, tests fields, filters, sort/group settings, schedule settings, optional row "
                "reading, and rolls back so the model is left unchanged. Use before complex autonomous schedule "
                "creation or updates."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "category_name": {"type": "string", "description": "Revit category name, e.g. Windows, Doors."},
                    "category_id": {"type": "string", "description": "Category ElementId. Use when category name is ambiguous."},
                    "schedule_kind": {
                        "type": "string",
                        "enum": ["schedule", "material_takeoff"],
                        "description": "Use material_takeoff to probe material fields like Material: Mark and Material: Area.",
                    },
                    "is_material_takeoff": {"type": "boolean", "description": "Alias for schedule_kind='material_takeoff'."},
                    "fields": {
                        "type": "array",
                        "items": flexible_field_schema,
                        "description": "Optional target fields to probe. If omitted, representative available fields are tested.",
                    },
                    "field_name_contains": {
                        "type": "string",
                        "description": "Optional case-insensitive substring used to choose available fields to test.",
                    },
                    "filter_operators": {
                        "type": "array",
                        "items": {"type": "string", "enum": filter_schema["properties"]["operator"]["enum"]},
                        "description": "Optional filter operators to probe. Defaults to representative string, numeric, and value-presence operators.",
                    },
                    "max_fields": {
                        "type": "integer",
                        "description": "Maximum fields to test when fields is omitted. Default 24, max 250.",
                    },
                    "max_filter_tests": {
                        "type": "integer",
                        "description": "Maximum field/operator filter combinations to test. Default 120, max 1000.",
                    },
                    "include_filter_tests": {"type": "boolean", "description": "Default true."},
                    "include_sort_tests": {"type": "boolean", "description": "Default true."},
                    "include_settings_tests": {"type": "boolean", "description": "Default true."},
                    "include_row_read": {"type": "boolean", "description": "Default true."},
                },
            },
            handler=audit_schedule_capabilities_handler,
        ),
    ]
