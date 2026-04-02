import re

from RevitMCP_ExternalServer.tools.context_tools import resolve_revit_targets_internal
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


GET_ACTIVE_SELECTION_TOOL_NAME = "get_active_selection"
GET_ELEMENTS_BY_CATEGORY_TOOL_NAME = "get_elements_by_category"
SELECT_ELEMENTS_TOOL_NAME = "select_elements_by_id"
SELECT_STORED_ELEMENTS_TOOL_NAME = "select_stored_elements"
LIST_STORED_ELEMENTS_TOOL_NAME = "list_stored_elements"
FILTER_ELEMENTS_TOOL_NAME = "filter_elements"
FILTER_STORED_ELEMENTS_BY_PARAMETER_TOOL_NAME = "filter_stored_elements_by_parameter"
GET_ELEMENT_PROPERTIES_TOOL_NAME = "get_element_properties"
UPDATE_ELEMENT_PARAMETERS_TOOL_NAME = "update_element_parameters"

FILTER_STRING_OPERATORS = ["contains", "equals", "not_equals", "starts_with", "ends_with"]
FILTER_NUMERIC_OPERATORS = ["greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"]
FILTER_OPERATORS = FILTER_STRING_OPERATORS + FILTER_NUMERIC_OPERATORS
FILTER_MULTI_MATCH_MODES = ["any", "all"]


def get_active_selection_handler(services, limit: int = 200, **_kwargs) -> dict:
    safe_limit = max(1, min(2000, int(limit if limit is not None else 200)))
    services.logger.info("MCP Tool executed: %s with limit=%s", GET_ACTIVE_SELECTION_TOOL_NAME, safe_limit)

    result = services.revit_client.call_listener(
        command_path="/selection/active",
        method="POST",
        payload_data={"limit": safe_limit},
    )

    if result.get("status") == "success" and result.get("element_ids"):
        stored_as, result_handle = services.result_store.store_elements(
            "active_selection",
            result.get("element_ids", []),
            result.get("returned_count", len(result.get("element_ids", []))),
        )
        result["stored_as"] = stored_as
        result["result_handle"] = result_handle
        result["storage_message"] = "Selection snapshot stored as '{}' ({})".format(stored_as, result_handle)

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status",
            "message",
            "stored_as",
            "result_handle",
            "storage_message",
            "total_count",
            "returned_count",
            "truncated",
            "limit",
        ],
    )


def get_elements_by_category_handler(services, category_name: str, **_kwargs) -> dict:
    services.logger.info("MCP Tool executed: %s with category_name: %s", GET_ELEMENTS_BY_CATEGORY_TOOL_NAME, category_name)
    result = services.revit_client.call_listener(
        command_path="/get_elements_by_category",
        method="POST",
        payload_data={"category_name": category_name},
    )

    if result.get("status") == "error" and "Invalid category_name" in str(result.get("message", "")):
        suggestions = resolve_revit_targets_internal(services, {"category_name": category_name})
        result["suggestions"] = suggestions
        resolved_category = suggestions.get("resolved", {}).get("category_name")
        if resolved_category:
            result["message"] = "{} Did you mean '{}' ?".format(result.get("message", ""), resolved_category)

    if result.get("status") == "success" and "element_ids" in result:
        storage_key, result_handle = services.result_store.store_elements(
            category_name,
            result["element_ids"],
            result.get("count", len(result["element_ids"])),
        )
        result["stored_as"] = storage_key
        result["result_handle"] = result_handle
        result["storage_message"] = (
            f"Results stored as '{storage_key}' ({result_handle}) - use select_stored_elements with "
            "category_name or result_handle"
        )

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["stored_as", "result_handle", "storage_message", "count", "category", "status", "message"],
    )


def select_elements_by_id_handler(
    services,
    element_ids: list[str] = None,
    result_handle: str = None,
    **_kwargs,
) -> dict:
    services.logger.info("MCP Tool executed: %s", SELECT_ELEMENTS_TOOL_NAME)
    resolved_ids, _record, resolve_error = services.result_store.resolve_element_ids(
        element_ids=element_ids,
        result_handle=result_handle,
    )
    if resolve_error:
        return resolve_error

    services.logger.info(
        "select_elements_by_id_handler using %s IDs%s",
        len(resolved_ids),
        " from handle '{}'".format(result_handle) if result_handle else "",
    )

    if isinstance(resolved_ids, str):
        services.logger.warning(
            "select_elements_by_id_handler: element_ids was a string ('%s'), converting to list.",
            resolved_ids,
        )
        processed_element_ids = [resolved_ids]
    elif isinstance(resolved_ids, list) and all(isinstance(element_id, str) for element_id in resolved_ids):
        processed_element_ids = resolved_ids
    elif isinstance(resolved_ids, list):
        services.logger.warning(
            "select_elements_by_id_handler: element_ids list contained non-string items: %s. Attempting conversion.",
            resolved_ids,
        )
        try:
            processed_element_ids = [str(element_id) for element_id in resolved_ids]
        except Exception as conversion_error:
            services.logger.error(
                "select_elements_by_id_handler: Failed to convert all items in element_ids to string: %s",
                conversion_error,
            )
            return {
                "status": "error",
                "message": "Invalid format for element_ids. All IDs must be strings. Received: {}".format(resolved_ids),
            }
    else:
        services.logger.error(
            "select_elements_by_id_handler: invalid element_ids type %s value %s",
            type(resolved_ids),
            resolved_ids,
        )
        return {
            "status": "error",
            "message": "Invalid input type for element_ids. Expected string or list of strings. Received: {}".format(
                type(resolved_ids)
            ),
        }

    result = services.revit_client.call_listener(
        command_path="/select_elements_by_id",
        method="POST",
        payload_data={"element_ids": processed_element_ids},
    )
    if result.get("status") == "success" and result_handle:
        result["result_handle"] = result_handle
    return services.result_store.compact_result_payload(result)


def select_stored_elements_handler(
    services,
    category_name: str = None,
    result_handle: str = None,
    **_kwargs,
) -> dict:
    services.logger.info(
        "MCP Tool executed: %s with category_name: %s, result_handle: %s",
        SELECT_STORED_ELEMENTS_TOOL_NAME,
        category_name,
        result_handle,
    )

    stored_data = None
    normalized_category = None
    if result_handle:
        stored_data = services.result_store.get_result_by_handle(result_handle)
        if not stored_data:
            return {
                "status": "error",
                "message": "No stored elements found for result_handle '{}'.".format(result_handle),
                "available_categories": list(services.result_store.element_storage.keys()),
            }
        normalized_category = stored_data.get("storage_key", stored_data.get("category", "unknown"))
    elif category_name:
        normalized_category = category_name.lower().replace("ost_", "").replace(" ", "_")
        stored_data = services.result_store.get_stored_elements(normalized_category)
    else:
        return {"status": "error", "message": "Provide either category_name or result_handle."}

    if not stored_data and category_name:
        available_keys = list(services.result_store.element_storage.keys())
        potential_matches = [key for key in available_keys if key.startswith(normalized_category)]
        if potential_matches:
            best_match = potential_matches[-1]
            stored_data = services.result_store.get_stored_elements(best_match)
            services.logger.info("Found partial match: '%s' for category '%s'", best_match, category_name)
        else:
            fuzzy_matches = [key for key in available_keys if normalized_category in key]
            if fuzzy_matches:
                best_match = fuzzy_matches[-1]
                stored_data = services.result_store.get_stored_elements(best_match)
                services.logger.info("Found fuzzy match: '%s' for category '%s'", best_match, category_name)

    if not stored_data:
        available_keys = list(services.result_store.element_storage.keys())
        return {
            "status": "error",
            "message": "No stored elements found for category '{}'. Available stored categories: {}".format(
                category_name or result_handle,
                available_keys,
            ),
            "available_categories": available_keys,
            "suggestion": "Try using list_stored_elements to see all available categories, or use the exact storage key name.",
        }

    element_ids = stored_data["element_ids"]
    total_elements = len(element_ids)
    services.logger.info("Using %s stored element IDs for category '%s'", total_elements, category_name)

    if total_elements > services.config.max_elements_for_selection:
        services.logger.warning(
            "Selection aborted: %s elements exceeds safe limit of %s",
            total_elements,
            services.config.max_elements_for_selection,
        )
        return {
            "status": "limit_exceeded",
            "message": (
                f"Selection would include {total_elements} elements which exceeds the safe limit of "
                f"{services.config.max_elements_for_selection}."
            ),
            "suggestion": "Please narrow your criteria (e.g., filter by level or parameter) before selecting.",
            "stored_count": stored_data.get("count", total_elements),
            "stored_key": stored_data.get("category", category_name),
            "selection_limit": services.config.max_elements_for_selection,
        }

    result = services.revit_client.call_listener(
        command_path="/select_elements_focused",
        method="POST",
        payload_data={"element_ids": element_ids},
    )
    if result.get("status") == "error":
        if services.revit_client.is_route_not_defined(result, "/select_elements_focused") or "select_elements_focused" in str(
            result.get("message", "")
        ):
            services.logger.warning(
                "Route '/select_elements_focused' is not available on the active Revit API. Falling back to '/select_elements_by_id'."
            )
            fallback_result = services.revit_client.call_listener(
                command_path="/select_elements_by_id",
                method="POST",
                payload_data={"element_ids": element_ids},
            )
            if fallback_result.get("status") == "success":
                fallback_result["approach_note"] = "Fallback selection used because focused selection route was unavailable"
            result = fallback_result

    if result.get("status") == "success":
        result["source"] = "stored_{}".format(category_name or normalized_category)
        result["stored_count"] = stored_data["count"]
        result["stored_at"] = stored_data["timestamp"]
        result["matched_key"] = stored_data.get("category", "unknown")
        result["result_handle"] = stored_data.get("result_handle")
        result["approach_note"] = "Focused selection - elements should remain active for user operations"

    return services.result_store.compact_result_payload(result)


def list_stored_elements_handler(services, **_kwargs) -> dict:
    services.logger.info("MCP Tool executed: %s", LIST_STORED_ELEMENTS_TOOL_NAME)
    stored_categories = services.result_store.list_stored_categories()
    return {
        "status": "success",
        "message": "Found {} stored categories".format(len(stored_categories)),
        "stored_categories": stored_categories,
        "total_categories": len(stored_categories),
    }


def filter_elements_handler(
    services,
    category_name: str,
    level_name: str = None,
    parameters: list = None,
    **_kwargs,
) -> dict:
    services.logger.info(
        "MCP Tool executed: %s with category: %s, level: %s, parameters: %s",
        FILTER_ELEMENTS_TOOL_NAME,
        category_name,
        level_name,
        parameters,
    )

    normalized_parameters = []
    for parameter in parameters or []:
        if not isinstance(parameter, dict):
            return {"status": "error", "message": "Each parameter filter must be an object."}

        normalized_parameter = dict(parameter)
        raw_operator = normalized_parameter.get("operator", normalized_parameter.get("condition"))
        normalized_operator = _normalize_filter_operator(raw_operator)
        if raw_operator is not None and normalized_operator is None:
            return {
                "status": "error",
                "message": "Unsupported filter operator '{}'. Supported operators: {}.".format(
                    raw_operator,
                    ", ".join(FILTER_OPERATORS),
                ),
            }
        normalized_parameter["condition"] = normalized_operator or "equals"
        normalized_parameters.append(normalized_parameter)

    parameters = normalized_parameters

    resolution = resolve_revit_targets_internal(
        services,
        {
            "category_name": category_name,
            "level_name": level_name,
            "parameter_names": [
                parameter.get("name")
                for parameter in (parameters or [])
                if isinstance(parameter, dict) and parameter.get("name")
            ],
        },
    )
    if resolution.get("status") != "error":
        resolved_payload = resolution.get("resolved", {})
        if resolved_payload.get("category_name"):
            category_name = resolved_payload["category_name"]
        if resolved_payload.get("level_name"):
            level_name = resolved_payload["level_name"]
        param_map = resolved_payload.get("parameter_names", {})
        if param_map and isinstance(parameters, list):
            for parameter in parameters:
                if isinstance(parameter, dict) and parameter.get("name") in param_map:
                    mapped = param_map[parameter["name"]]
                    resolved_name = mapped.get("resolved_name", parameter["name"])
                    confidence = float(mapped.get("confidence", 0.0))
                    if confidence >= services.config.min_confidence_for_parameter_remap:
                        parameter["name"] = resolved_name
                    else:
                        services.logger.info(
                            "Skipping low-confidence parameter remap for '%s' -> '%s' (confidence=%s)",
                            parameter["name"],
                            resolved_name,
                            confidence,
                        )

    payload = {"category_name": category_name}
    if level_name:
        payload["level_name"] = level_name
    if parameters:
        payload["parameters"] = parameters

    result = services.revit_client.call_listener(command_path="/elements/filter", method="POST", payload_data=payload)

    if result.get("status") == "error":
        error_message = str(result.get("message", ""))
        if "Invalid category_name" in error_message or "Level '" in error_message:
            resolver_input = {
                "category_name": category_name,
                "level_name": level_name,
                "parameter_names": [
                    parameter.get("name")
                    for parameter in (parameters or [])
                    if isinstance(parameter, dict) and parameter.get("name")
                ],
            }
            suggestions = resolve_revit_targets_internal(services, resolver_input)
            result["suggestions"] = suggestions
            if "Invalid category_name" in error_message:
                resolved_category = suggestions.get("resolved", {}).get("category_name")
                alt_categories = suggestions.get("alternatives", {}).get("category_name", [])
                if resolved_category:
                    result["message"] = "{} Did you mean '{}' ?".format(error_message, resolved_category)
                elif alt_categories:
                    result["message"] = "{} Available categories include: {}".format(error_message, ", ".join(alt_categories[:10]))
            if "Level '" in error_message:
                resolved_level = suggestions.get("resolved", {}).get("level_name")
                alt_levels = suggestions.get("alternatives", {}).get("level_name", [])
                if resolved_level:
                    result["message"] = "{} Did you mean level '{}' ?".format(result.get("message", error_message), resolved_level)
                elif alt_levels:
                    result["message"] = "{} Available levels include: {}".format(
                        result.get("message", error_message),
                        ", ".join(alt_levels[:10]),
                    )

    if result.get("status") == "error" and services.revit_client.is_route_not_defined(result, "/elements/filter"):
        if not level_name and not parameters:
            services.logger.warning(
                "Route '/elements/filter' missing. Falling back to '/get_elements_by_category' for category-only request."
            )
            result = services.revit_client.call_listener(
                command_path="/get_elements_by_category",
                method="POST",
                payload_data={"category_name": category_name},
            )
        else:
            return {
                "status": "error",
                "error_type": "route_not_defined",
                "message": "The active Revit route set does not support '/elements/filter'. Reload/update the Revit extension to use advanced filtering.",
            }

    if result.get("status") == "success" and "element_ids" in result:
        storage_key = category_name.lower().replace("ost_", "").replace(" ", "_")
        if level_name:
            storage_key += f"_level_{level_name.lower()}"
        if parameters:
            storage_key += "_filtered"

        stored_key, result_handle = services.result_store.store_elements(
            storage_key,
            result["element_ids"],
            result.get("count", len(result["element_ids"])),
        )
        result["stored_as"] = stored_key
        result["result_handle"] = result_handle
        result["storage_message"] = (
            f"Filtered results stored as '{stored_key}' ({result_handle}) - use select_stored_elements with "
            "category_name or result_handle"
        )

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["stored_as", "result_handle", "storage_message", "count", "category", "status", "message"],
    )


def _collapse_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "").replace(u"\u00A0", " ")).strip()


def _normalize_filter_operator(operator):
    alias_map = {
        None: "contains",
        "": "contains",
        "contains": "contains",
        "equals": "equals",
        "==": "equals",
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
    return operator in FILTER_NUMERIC_OPERATORS


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


def _matches_filter_value(candidate_value, expected_value, operator="contains", case_sensitive=False, typed_value=None):
    candidate = "" if candidate_value in (None, "Not available") else str(candidate_value)
    expected = "" if expected_value is None else str(expected_value)
    normalized_operator = _normalize_filter_operator(operator)
    if not normalized_operator:
        return False, "Unsupported filter operator '{}'. Supported operators: {}.".format(
            operator,
            ", ".join(FILTER_OPERATORS),
        )

    if _is_numeric_operator(normalized_operator):
        numeric_candidate = None
        storage_type = None
        if isinstance(typed_value, dict):
            storage_type = typed_value.get("storage_type")
            if typed_value.get("is_numeric") and typed_value.get("numeric_value") is not None:
                numeric_candidate = float(typed_value.get("numeric_value"))

        if numeric_candidate is None:
            return False, "Parameter value is not numeric/filterable with operator '{}'.".format(normalized_operator)

        try:
            if storage_type == "Double":
                expected_numeric = _parse_length_to_internal_feet(expected)
            else:
                expected_numeric = float(_collapse_whitespace(expected))
        except Exception:
            return (
                False,
                "Could not parse numeric filter value '{}'. Use a plain number or an explicit length such as 2000 mm, 2 m, or 6' 6\".".format(
                    expected
                ),
            )

        return _compare_numeric_values(numeric_candidate, float(expected_numeric), normalized_operator), None

    if not case_sensitive:
        candidate_cmp = candidate.lower()
        expected_cmp = expected.lower()
    else:
        candidate_cmp = candidate
        expected_cmp = expected

    if normalized_operator in ("contains",):
        return expected_cmp in candidate_cmp, None
    if normalized_operator in ("equals", "=="):
        return candidate_cmp == expected_cmp, None
    if normalized_operator in ("not_equals", "!=", "not equal"):
        return candidate_cmp != expected_cmp, None
    if normalized_operator in ("starts_with",):
        return candidate_cmp.startswith(expected_cmp), None
    if normalized_operator in ("ends_with",):
        return candidate_cmp.endswith(expected_cmp), None
    return False, "Unsupported filter operator '{}'.".format(operator)


def _normalize_filter_values(value=None, values=None) -> list[str]:
    normalized_values = []
    if value is not None:
        normalized_values.append(str(value))
    if isinstance(values, list):
        normalized_values.extend([str(item) for item in values if item is not None])

    deduped_values = []
    seen = set()
    for candidate in normalized_values:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped_values.append(candidate)
    return deduped_values


def filter_stored_elements_by_parameter_handler(
    services,
    parameter_name: str,
    value: str = None,
    values: list[str] = None,
    operator: str = "contains",
    match_mode: str = "any",
    result_handle: str = None,
    category_name: str = None,
    batch_size: int = None,
    case_sensitive: bool = False,
    **_kwargs,
) -> dict:
    services.logger.info(
        (
            "MCP Tool executed: %s (parameter=%s, operator=%s, value=%s, values=%s, match_mode=%s, "
            "result_handle=%s, category_name=%s, batch_size=%s)"
        ),
        FILTER_STORED_ELEMENTS_BY_PARAMETER_TOOL_NAME,
        parameter_name,
        operator,
        value,
        values,
        match_mode,
        result_handle,
        category_name,
        batch_size,
    )

    normalized_operator = _normalize_filter_operator(operator)
    filter_values = _normalize_filter_values(value=value, values=values)
    normalized_match_mode = str(match_mode or "any").strip().lower()
    if not parameter_name or not filter_values:
        return {"status": "error", "message": "parameter_name and either value or values are required."}
    if not normalized_operator:
        return {
            "status": "error",
            "message": "Unsupported filter operator '{}'. Supported operators: {}.".format(
                operator,
                ", ".join(FILTER_OPERATORS),
            ),
        }
    if normalized_match_mode not in FILTER_MULTI_MATCH_MODES:
        return {
            "status": "error",
            "message": "Unsupported match_mode '{}'. Supported values: {}.".format(
                match_mode,
                ", ".join(FILTER_MULTI_MATCH_MODES),
            ),
        }
    operator = normalized_operator

    parameter_resolution = resolve_revit_targets_internal(services, {"parameter_names": [parameter_name]})
    param_map = parameter_resolution.get("resolved", {}).get("parameter_names", {})
    if parameter_name in param_map:
        mapped = param_map[parameter_name]
        confidence = float(mapped.get("confidence", 0.0))
        if confidence >= services.config.min_confidence_for_parameter_remap:
            parameter_name = mapped.get("resolved_name", parameter_name)

    resolved_ids, record, resolve_error = services.result_store.resolve_element_ids(
        element_ids=None,
        result_handle=result_handle,
        category_name=category_name,
    )
    if resolve_error:
        return resolve_error

    total_ids = len(resolved_ids)
    if total_ids == 0:
        return {"status": "success", "count": 0, "message": "No source elements available for server-side filtering."}

    if batch_size is None:
        inferred_batch_size = 1000 if total_ids >= 5000 else services.config.default_server_filter_batch_size
    else:
        inferred_batch_size = int(batch_size)

    safe_batch_size = max(20, min(1000, int(inferred_batch_size)))
    total_batches = int((total_ids + safe_batch_size - 1) / safe_batch_size)

    matched_ids = []
    matched_samples = []

    for batch_index, start in enumerate(range(0, total_ids, safe_batch_size), 1):
        batch_ids = resolved_ids[start : start + safe_batch_size]
        batch_result = services.revit_client.call_listener(
            command_path="/elements/get_properties",
            method="POST",
            payload_data={"element_ids": batch_ids, "parameter_names": [parameter_name]},
        )

        if batch_result.get("status") == "error":
            if services.revit_client.is_route_not_defined(batch_result, "/elements/get_properties"):
                return {
                    "status": "error",
                    "error_type": "route_not_defined",
                    "message": "The active Revit route set does not support '/elements/get_properties'. Reload/update the Revit extension to enable server-side filtering.",
                }
            return batch_result

        elements = batch_result.get("elements", []) or []
        for element_data in elements:
            element_id = str(element_data.get("element_id", "")).strip()
            properties = element_data.get("properties", {}) or {}
            typed_properties = element_data.get("typed_properties", {}) or {}
            current_value = properties.get(parameter_name, "Not available")
            typed_value = typed_properties.get(parameter_name, {})
            match_results = []
            for filter_value in filter_values:
                matched, match_error = _matches_filter_value(
                    current_value,
                    filter_value,
                    operator=operator,
                    case_sensitive=case_sensitive,
                    typed_value=typed_value,
                )
                if match_error:
                    return {
                        "status": "error",
                        "message": match_error,
                        "parameter_name": parameter_name,
                        "operator": operator,
                    }
                match_results.append(bool(matched))

            matched = any(match_results) if normalized_match_mode == "any" else all(match_results)
            if matched:
                matched_ids.append(element_id)
                if len(matched_samples) < services.config.max_records_in_response:
                    matched_samples.append({"element_id": element_id, parameter_name: current_value})

        if batch_index == 1 or batch_index % 5 == 0 or batch_index == total_batches:
            services.logger.info(
                "Server-side filter progress: batch %s/%s, processed=%s/%s, matched=%s",
                batch_index,
                total_batches,
                min(start + len(batch_ids), total_ids),
                total_ids,
                len(matched_ids),
            )

    source_key = record.get("storage_key") if isinstance(record, dict) else services.result_store.normalize_storage_key(category_name or "elements")
    parameter_key = services.result_store.normalize_storage_key(parameter_name)
    filtered_storage_seed = "{}_{}_filtered".format(source_key, parameter_key)
    stored_key, new_result_handle = services.result_store.store_elements(filtered_storage_seed, matched_ids, len(matched_ids))

    result = {
        "status": "success",
        "count": len(matched_ids),
        "source_count": total_ids,
        "processed_count": total_ids,
        "parameter_name": parameter_name,
        "operator": operator,
        "value": str(filter_values[0]) if len(filter_values) == 1 else None,
        "values": filter_values,
        "match_mode": normalized_match_mode,
        "case_sensitive": bool(case_sensitive),
        "matched_sample": matched_samples,
        "element_ids": matched_ids,
        "stored_as": stored_key,
        "result_handle": new_result_handle,
        "storage_message": "Filtered results stored as '{}' ({}) - use select_stored_elements with result_handle".format(
            stored_key,
            new_result_handle,
        ),
        "message": "Server-side parameter filtering matched {} of {} source elements.".format(len(matched_ids), total_ids),
    }
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "stored_as",
            "result_handle",
            "storage_message",
            "count",
            "source_count",
            "processed_count",
            "status",
            "message",
            "parameter_name",
            "operator",
            "value",
            "values",
            "match_mode",
        ],
    )


def get_element_properties_handler(
    services,
    element_ids: list[str] = None,
    parameter_names: list[str] = None,
    result_handle: str = None,
    include_all_parameters: bool = False,
    populated_only: bool = False,
    **_kwargs,
) -> dict:
    resolved_ids, _record, resolve_error = services.result_store.resolve_element_ids(
        element_ids=element_ids,
        result_handle=result_handle,
    )
    if resolve_error:
        return resolve_error

    requested_count = len(resolved_ids)
    truncated_for_safety = False
    if requested_count > services.config.max_elements_for_property_read:
        resolved_ids = resolved_ids[: services.config.max_elements_for_property_read]
        truncated_for_safety = True
        services.logger.warning(
            "%s requested %s elements; limiting property read to first %s for safety",
            GET_ELEMENT_PROPERTIES_TOOL_NAME,
            requested_count,
            services.config.max_elements_for_property_read,
        )

    services.logger.info("MCP Tool executed: %s with %s elements", GET_ELEMENT_PROPERTIES_TOOL_NAME, len(resolved_ids))

    payload = {"element_ids": resolved_ids}
    if parameter_names:
        payload["parameter_names"] = parameter_names
    if include_all_parameters:
        payload["include_all_parameters"] = True
    if populated_only:
        payload["populated_only"] = True

    result = services.revit_client.call_listener(
        command_path="/elements/get_properties",
        method="POST",
        payload_data=payload,
    )
    if result.get("status") == "error" and services.revit_client.is_route_not_defined(result, "/elements/get_properties"):
        return {
            "status": "error",
            "error_type": "route_not_defined",
            "message": "The active Revit route set does not support '/elements/get_properties'. Reload/update the Revit extension to enable property reads.",
        }
    if result.get("status") == "success" and result_handle:
        result["result_handle"] = result_handle
    if result.get("status") == "success" and truncated_for_safety:
        result["requested_count"] = requested_count
        result["processed_count"] = len(resolved_ids)
        result["truncated_for_safety"] = True
        result["message"] = (
            "Retrieved properties for {} elements (safety-capped from {}). Narrow with filter_elements for "
            "full-accuracy bulk analysis."
        ).format(len(resolved_ids), requested_count)
    return services.result_store.compact_result_payload(result)


def update_element_parameters_handler(
    services,
    updates: list[dict] = None,
    element_ids: list[str] = None,
    result_handle: str = None,
    parameter_name: str = None,
    new_value: str = None,
    **_kwargs,
) -> dict:
    services.logger.info("MCP Tool executed: %s", UPDATE_ELEMENT_PARAMETERS_TOOL_NAME)
    normalized_updates: list[dict] = []

    if updates:
        if not isinstance(updates, list) or not updates:
            return {"status": "error", "message": "'updates' must be a non-empty list of update payloads."}

        for update in updates:
            if not isinstance(update, dict):
                return {"status": "error", "message": "Each update must be an object with element_id and parameters."}
            element_id = str(update.get("element_id", "")).strip()
            parameters = update.get("parameters")
            if not element_id or not parameters:
                return {"status": "error", "message": "Each update requires element_id and parameters."}
            if not isinstance(parameters, dict) or not parameters:
                return {"status": "error", "message": "'parameters' must be a non-empty object of parameter/value pairs."}
            normalized_updates.append({"element_id": element_id, "parameters": parameters})

    elif (element_ids or result_handle) and parameter_name and new_value is not None:
        resolved_ids, _record, resolve_error = services.result_store.resolve_element_ids(
            element_ids=element_ids,
            result_handle=result_handle,
        )
        if resolve_error:
            return resolve_error
        if not isinstance(resolved_ids, list) or not resolved_ids:
            return {"status": "error", "message": "'element_ids' must be a non-empty list when using the simplified form."}
        parameter_name = str(parameter_name).strip()
        if not parameter_name:
            return {"status": "error", "message": "parameter_name cannot be empty."}
        normalized_value = str(new_value)
        for element_id in resolved_ids:
            normalized_element_id = str(element_id).strip()
            if not normalized_element_id:
                return {"status": "error", "message": "All element_ids must be non-empty strings."}
            normalized_updates.append({"element_id": normalized_element_id, "parameters": {parameter_name: normalized_value}})
    else:
        return {"status": "error", "message": "Provide either 'updates' or (element_ids, parameter_name, new_value)."}

    services.logger.info("Prepared %s parameter update(s) for execution.", len(normalized_updates))

    if parameter_name:
        parameter_resolution = resolve_revit_targets_internal(services, {"parameter_names": [parameter_name]})
        param_map = parameter_resolution.get("resolved", {}).get("parameter_names", {})
        if parameter_name in param_map:
            mapped = param_map[parameter_name]
            confidence = float(mapped.get("confidence", 0.0))
            if confidence >= services.config.min_confidence_for_parameter_remap:
                parameter_name = mapped.get("resolved_name", parameter_name)

    result = services.revit_client.call_listener(
        command_path="/elements/update_parameters",
        method="POST",
        payload_data={"updates": normalized_updates},
    )
    if result.get("status") == "error" and services.revit_client.is_route_not_defined(result, "/elements/update_parameters"):
        return {
            "status": "error",
            "error_type": "route_not_defined",
            "message": "The active Revit route set does not support '/elements/update_parameters'. Reload/update the Revit extension to enable parameter updates.",
        }
    if result.get("status") == "success" and result_handle:
        result["result_handle"] = result_handle
    return services.result_store.compact_result_payload(result)


def build_element_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=GET_ACTIVE_SELECTION_TOOL_NAME,
            description=(
                "Returns a bounded snapshot of the current Revit selection. Successful results are stored for "
                "follow-on selection or property reads."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of selected elements to return and store. Default 200.",
                    }
                },
            },
            handler=get_active_selection_handler,
        ),
        ToolDefinition(
            name=GET_ELEMENTS_BY_CATEGORY_TOOL_NAME,
            description=(
                "Retrieves and stores all elements in the current Revit model for the specified category. Use this "
                "ONLY when the user wants to find or get elements."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "category_name": {"type": "string", "description": "The name of the Revit category to retrieve."}
                },
                "required": ["category_name"],
            },
            handler=get_elements_by_category_handler,
        ),
        ToolDefinition(
            name=SELECT_ELEMENTS_TOOL_NAME,
            description="DEPRECATED - Prefer select_stored_elements. Selects elements by exact IDs or by a stored result_handle.",
            json_schema={
                "type": "object",
                "properties": {
                    "element_ids": {"type": "array", "items": {"type": "string"}},
                    "result_handle": {"type": "string"},
                },
            },
            handler=select_elements_by_id_handler,
        ),
        ToolDefinition(
            name=SELECT_STORED_ELEMENTS_TOOL_NAME,
            description="Selects elements previously retrieved by get_elements_by_category or filter_elements. Prefer using result_handle to avoid passing large element lists.",
            json_schema={
                "type": "object",
                "properties": {
                    "category_name": {"type": "string"},
                    "result_handle": {"type": "string"},
                },
            },
            handler=select_stored_elements_handler,
        ),
        ToolDefinition(
            name=LIST_STORED_ELEMENTS_TOOL_NAME,
            description="Lists all currently stored element categories and their counts. Use this to see what elements are available for selection using select_stored_elements.",
            json_schema={"type": "object", "properties": {}},
            handler=list_stored_elements_handler,
        ),
        ToolDefinition(
            name=FILTER_ELEMENTS_TOOL_NAME,
            description=(
                "Filters elements by category, level, and parameter conditions. Supports string operators plus "
                "numeric range operators for numeric and length parameters."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "category_name": {"type": "string"},
                    "level_name": {"type": "string"},
                    "parameters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                                "operator": {
                                    "type": "string",
                                    "enum": FILTER_OPERATORS,
                                    "description": (
                                        "Preferred comparison operator. For numeric and length parameters, use "
                                        "greater_than, greater_than_or_equal, less_than, or less_than_or_equal."
                                    ),
                                },
                                "condition": {
                                    "type": "string",
                                    "enum": FILTER_OPERATORS,
                                    "description": "Legacy alias for operator. The same values are supported.",
                                },
                            },
                            "required": ["name", "value"],
                        },
                    },
                },
                "required": ["category_name"],
            },
            handler=filter_elements_handler,
        ),
        ToolDefinition(
            name=FILTER_STORED_ELEMENTS_BY_PARAMETER_TOOL_NAME,
            description=(
                "Filters a previously stored element set using server-side batched parameter reads. Supports the "
                "same string and numeric operators as filter_elements, accepts one or many comparison values, and "
                "is intended for narrowing stored results before selection."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "result_handle": {"type": "string"},
                    "category_name": {"type": "string"},
                    "parameter_name": {"type": "string"},
                    "value": {"type": "string", "description": "Single comparison value. Use values for bulk matching."},
                    "values": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Multiple comparison values to evaluate in one server-side pass.",
                    },
                    "operator": {
                        "type": "string",
                        "enum": FILTER_OPERATORS,
                        "description": (
                            "Comparison operator. Numeric and length parameters support greater_than, "
                            "greater_than_or_equal, less_than, and less_than_or_equal."
                        ),
                    },
                    "match_mode": {
                        "type": "string",
                        "enum": FILTER_MULTI_MATCH_MODES,
                        "description": "How to evaluate values when multiple comparison values are supplied.",
                    },
                    "batch_size": {"type": "integer"},
                    "case_sensitive": {"type": "boolean"},
                },
                "required": ["parameter_name"],
            },
            handler=filter_stored_elements_by_parameter_handler,
        ),
        ToolDefinition(
            name=GET_ELEMENT_PROPERTIES_TOOL_NAME,
            description="Gets parameter values for specified elements. Prefer result_handle over raw element_ids for large result sets.",
            json_schema={
                "type": "object",
                "properties": {
                    "element_ids": {"type": "array", "items": {"type": "string"}},
                    "result_handle": {"type": "string"},
                    "parameter_names": {"type": "array", "items": {"type": "string"}},
                    "include_all_parameters": {"type": "boolean"},
                    "populated_only": {"type": "boolean"},
                },
            },
            handler=get_element_properties_handler,
        ),
        ToolDefinition(
            name=UPDATE_ELEMENT_PARAMETERS_TOOL_NAME,
            description="Updates parameter values for elements. Prefer result_handle + parameter_name + new_value for bulk updates after filtering.",
            json_schema={
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "element_id": {"type": "string"},
                                "parameters": {"type": "object"},
                            },
                            "required": ["element_id", "parameters"],
                        },
                    },
                    "element_ids": {"type": "array", "items": {"type": "string"}},
                    "result_handle": {"type": "string"},
                    "parameter_name": {"type": "string"},
                    "new_value": {"type": "string"},
                },
            },
            handler=update_element_parameters_handler,
        ),
    ]
