import difflib
import re

from RevitMCP_ExternalServer.core.runtime_config import bounded_int
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


REVIT_INFO_TOOL_NAME = "get_revit_project_info"
LIST_FAMILY_TYPES_TOOL_NAME = "list_family_types"
GET_SCHEMA_CONTEXT_TOOL_NAME = "get_revit_schema_context"
RESOLVE_TARGETS_TOOL_NAME = "resolve_revit_targets"


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _best_match(term: str, candidates: list[str], fuzzy_cutoff: float = 0.5):
    if not term or not candidates:
        return None, [], 0.0

    term = str(term).strip()
    normalized_term = _normalize_label(term)
    normalized_map = {}
    for candidate in candidates:
        normalized_map.setdefault(_normalize_label(candidate), []).append(candidate)

    if normalized_term in normalized_map:
        choice = normalized_map[normalized_term][0]
        return choice, [], 1.0

    contains_matches = [candidate for candidate in candidates if normalized_term and normalized_term in _normalize_label(candidate)]
    if contains_matches:
        primary = contains_matches[0]
        alternatives = contains_matches[1:6]
        return primary, alternatives, 0.85

    fuzzy_matches = difflib.get_close_matches(term, candidates, n=6, cutoff=fuzzy_cutoff)
    if fuzzy_matches:
        primary = fuzzy_matches[0]
        alternatives = fuzzy_matches[1:6]
        score = difflib.SequenceMatcher(None, term.lower(), primary.lower()).ratio()
        return primary, alternatives, score

    return None, [], 0.0


def get_revit_project_info_handler(services, **_kwargs) -> dict:
    services.logger.info("MCP Tool executed: %s", REVIT_INFO_TOOL_NAME)
    return services.revit_client.call_listener(command_path="/project_info", method="GET")


def list_family_types_handler(
    services,
    category_names: list[str] = None,
    family_name_contains: str = None,
    type_name_contains: str = None,
    limit: int = 150,
    **_kwargs,
) -> dict:
    safe_limit = bounded_int(limit, 150, min_value=1, max_value=2000)
    normalized_categories = category_names if isinstance(category_names, list) else []
    services.logger.info(
        "MCP Tool executed: %s with %s category filters, family_name_contains=%s, type_name_contains=%s, limit=%s",
        LIST_FAMILY_TYPES_TOOL_NAME,
        len(normalized_categories),
        family_name_contains,
        type_name_contains,
        safe_limit,
    )

    result = services.revit_client.call_listener(
        command_path="/families/types",
        method="POST",
        payload_data={
            "category_names": normalized_categories,
            "family_name_contains": family_name_contains,
            "type_name_contains": type_name_contains,
            "limit": safe_limit,
        },
    )
    return services.result_store.compact_result_payload(
        result,
        preserve_keys=["status", "message", "total_count", "returned_count", "truncated", "limit"],
    )


def get_revit_schema_context_handler(services, force_refresh: bool = False, **_kwargs) -> dict:
    services.logger.info("MCP Tool executed: %s (force_refresh=%s)", GET_SCHEMA_CONTEXT_TOOL_NAME, force_refresh)

    project_info = services.revit_client.call_listener(command_path="/project_info", method="GET")
    if project_info.get("status") == "error":
        return project_info

    doc_fingerprint = "{}|{}|{}".format(
        project_info.get("file_path", ""),
        project_info.get("project_name", ""),
        project_info.get("project_number", ""),
    )

    if not force_refresh:
        cached = services.result_store.get_cached_schema_context(doc_fingerprint)
        if cached:
            return cached

    context_result = services.revit_client.call_listener(command_path="/schema/context", method="GET")
    if context_result.get("status") == "error":
        if services.revit_client.is_route_not_defined(context_result, "/schema/context"):
            context_result["message"] = (
                "Route '/schema/context' is not available. Reload Revit to register new schema routes, "
                "or update extension files."
            )
        return context_result

    services.result_store.set_cached_schema_context(doc_fingerprint, context_result)
    result = dict(context_result)
    result["cache"] = {"status": "refreshed", "doc_fingerprint": doc_fingerprint}
    return services.result_store.compact_result_payload(result)


def resolve_revit_targets_internal(services, query_terms: dict = None) -> dict:
    context_result = get_revit_schema_context_handler(services, force_refresh=False)
    if context_result.get("status") == "error":
        return context_result

    schema = context_result.get("schema", {})
    built_in_categories = schema.get("built_in_categories", []) or []
    document_categories = schema.get("document_categories", []) or []
    levels = schema.get("levels", []) or []
    family_names = schema.get("family_names", []) or []
    type_names = schema.get("type_names", []) or []
    parameter_names = schema.get("parameter_names", []) or []

    query_terms = query_terms or {}
    category_term = query_terms.get("category_name")
    level_term = query_terms.get("level_name")
    family_term = query_terms.get("family_name")
    type_term = query_terms.get("type_name")
    parameter_terms = query_terms.get("parameter_names", []) or []

    if isinstance(parameter_terms, str):
        parameter_terms = [parameter_terms]
    elif not isinstance(parameter_terms, list):
        parameter_terms = []

    for key in ("parameter_name", "parameter"):
        legacy_term = query_terms.get(key)
        if isinstance(legacy_term, str) and legacy_term.strip():
            parameter_terms.append(legacy_term.strip())

    seen_terms = set()
    normalized_parameter_terms = []
    for parameter_term in parameter_terms:
        parameter_term_str = str(parameter_term).strip()
        if not parameter_term_str:
            continue
        parameter_key = parameter_term_str.lower()
        if parameter_key in seen_terms:
            continue
        seen_terms.add(parameter_key)
        normalized_parameter_terms.append(parameter_term_str)
    parameter_terms = normalized_parameter_terms

    resolution = {
        "status": "success",
        "resolved": {},
        "alternatives": {},
        "confidence": {},
        "context_doc": context_result.get("doc", {}),
    }

    if category_term:
        category_candidates = list(set(document_categories + built_in_categories))
        resolved_category, alternatives, confidence = _best_match(category_term, category_candidates)
        if resolved_category:
            resolution["resolved"]["category_name"] = resolved_category
            resolution["confidence"]["category_name"] = round(confidence, 3)
            if alternatives:
                resolution["alternatives"]["category_name"] = alternatives
        else:
            resolution["status"] = "partial"
            resolution["alternatives"]["category_name"] = category_candidates[:25]

    if level_term:
        resolved_level, alternatives, confidence = _best_match(level_term, levels)
        if resolved_level:
            resolution["resolved"]["level_name"] = resolved_level
            resolution["confidence"]["level_name"] = round(confidence, 3)
            if alternatives:
                resolution["alternatives"]["level_name"] = alternatives
        else:
            resolution["status"] = "partial"
            resolution["alternatives"]["level_name"] = levels[:25]

    if family_term:
        resolved_family, alternatives, confidence = _best_match(family_term, family_names)
        if resolved_family:
            resolution["resolved"]["family_name"] = resolved_family
            resolution["confidence"]["family_name"] = round(confidence, 3)
            if alternatives:
                resolution["alternatives"]["family_name"] = alternatives
        else:
            resolution["status"] = "partial"
            resolution["alternatives"]["family_name"] = family_names[:25]

    if type_term:
        resolved_type, alternatives, confidence = _best_match(type_term, type_names)
        if resolved_type:
            resolution["resolved"]["type_name"] = resolved_type
            resolution["confidence"]["type_name"] = round(confidence, 3)
            if alternatives:
                resolution["alternatives"]["type_name"] = alternatives
        else:
            resolution["status"] = "partial"
            resolution["alternatives"]["type_name"] = type_names[:25]

    if parameter_terms:
        resolved_params = {}
        unresolved_params = {}
        for parameter_name in parameter_terms:
            resolved_param, alternatives, confidence = _best_match(
                parameter_name,
                parameter_names,
                fuzzy_cutoff=max(0.5, services.config.min_confidence_for_parameter_remap),
            )
            if resolved_param and confidence >= services.config.min_confidence_for_parameter_remap:
                resolved_params[parameter_name] = {
                    "resolved_name": resolved_param,
                    "confidence": round(confidence, 3),
                }
                if alternatives:
                    unresolved_params[parameter_name] = alternatives
            else:
                resolution["status"] = "partial"
                unresolved_params[parameter_name] = parameter_names[:25]
        resolution["resolved"]["parameter_names"] = resolved_params
        if unresolved_params:
            resolution["alternatives"]["parameter_names"] = unresolved_params

    return services.result_store.compact_result_payload(resolution)


def resolve_revit_targets_handler(services, query_terms: dict, **_kwargs) -> dict:
    services.logger.info("MCP Tool executed: %s with query_terms=%s", RESOLVE_TARGETS_TOOL_NAME, query_terms)
    if not isinstance(query_terms, dict):
        return {"status": "error", "message": "query_terms must be an object."}
    return resolve_revit_targets_internal(services, query_terms)


def build_context_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=REVIT_INFO_TOOL_NAME,
            description=(
                "Retrieves detailed information about the currently open Revit project, such as project name, "
                "file path, Revit version, Revit build number, and active document title."
            ),
            json_schema={"type": "object", "properties": {}},
            handler=get_revit_project_info_handler,
        ),
        ToolDefinition(
            name=LIST_FAMILY_TYPES_TOOL_NAME,
            description=(
                "Lists loaded family types in the current document with category, family name, type name, and "
                "symbol id. Useful for discovery before creation or auditing."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "category_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional category names to filter family types.",
                    },
                    "family_name_contains": {
                        "type": "string",
                        "description": "Optional substring match against the family name.",
                    },
                    "type_name_contains": {
                        "type": "string",
                        "description": "Optional substring match against the type name.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of matching family types to return. Default 150.",
                    },
                },
            },
            handler=list_family_types_handler,
        ),
        ToolDefinition(
            name=GET_SCHEMA_CONTEXT_TOOL_NAME,
            description=(
                "Returns canonical Revit schema context (exact levels, category names, family/type names, "
                "common parameter names). Use this before filtering or parameter updates."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "force_refresh": {
                        "type": "boolean",
                        "description": "If true, refresh schema context from Revit even if cached.",
                    }
                },
            },
            handler=get_revit_schema_context_handler,
        ),
        ToolDefinition(
            name=RESOLVE_TARGETS_TOOL_NAME,
            description=(
                "Resolves user terms (category/level/family/type/parameter names) to exact Revit names with "
                "confidence and alternatives. Always call this before filter_elements or update_element_parameters."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "query_terms": {
                        "type": "object",
                        "properties": {
                            "category_name": {"type": "string"},
                            "level_name": {"type": "string"},
                            "family_name": {"type": "string"},
                            "type_name": {"type": "string"},
                            "parameter_names": {"type": "array", "items": {"type": "string"}},
                        },
                    }
                },
                "required": ["query_terms"],
            },
            handler=resolve_revit_targets_handler,
        ),
    ]
