import difflib
import re
from collections import defaultdict

from RevitMCP_ExternalServer.core.runtime_config import bounded_int
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


GET_ACTIVE_VIEW_INFO_TOOL_NAME = "get_active_view_info"
GET_ACTIVE_VIEW_ELEMENTS_TOOL_NAME = "get_active_view_elements"
EXPORT_ACTIVE_VIEW_IMAGE_TOOL_NAME = "export_active_view_image"
PLACE_VIEW_ON_SHEET_TOOL_NAME = "place_view_on_sheet"
ACTIVATE_VIEW_TOOL_NAME = "activate_view"
DUPLICATE_VIEW_TOOL_NAME = "duplicate_view"
LIST_VIEWS_TOOL_NAME = "list_views"
ANALYZE_VIEW_NAMING_PATTERNS_TOOL_NAME = "analyze_view_naming_patterns"
SUGGEST_VIEW_NAME_CORRECTIONS_TOOL_NAME = "suggest_view_name_corrections"


def _collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_view_name(value: str) -> str:
    text = _collapse_spaces(value)
    text = re.sub(r"\s*-\s*", " - ", text)
    return _collapse_spaces(text)


def _view_name_signature(value: str) -> str:
    text = _normalize_view_name(value).upper()
    text = re.sub(r"\d+", "{#}", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _view_similarity(value_a: str, value_b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize_view_name(value_a).lower(), _normalize_view_name(value_b).lower()).ratio()


def _alpha_case_style(value: str) -> str:
    alpha = "".join(character for character in str(value or "") if character.isalpha())
    if not alpha:
        return "mixed"
    if alpha.upper() == alpha:
        return "upper"
    if alpha.lower() == alpha:
        return "lower"
    if alpha.title() == alpha:
        return "title"
    return "mixed"


def _apply_view_style_from_exemplar(source_name: str, exemplar_name: str) -> str:
    source = _normalize_view_name(source_name)
    exemplar = _normalize_view_name(exemplar_name)
    source_parts = re.findall(r"\d+|[A-Za-z]+|[^A-Za-z0-9]+", source)
    exemplar_parts = re.findall(r"\d+|[A-Za-z]+|[^A-Za-z0-9]+", exemplar)

    styled = []
    for index, part in enumerate(source_parts):
        if part.isalpha():
            exemplar_part = exemplar_parts[index] if index < len(exemplar_parts) else ""
            style = _alpha_case_style(exemplar_part)
            if style == "upper":
                styled.append(part.upper())
            elif style == "lower":
                styled.append(part.lower())
            elif style == "title":
                styled.append(part.title())
            else:
                styled.append(part)
        elif part.isdigit():
            styled.append(part)
        else:
            exemplar_separator = exemplar_parts[index] if index < len(exemplar_parts) else part
            if re.search(r"[^A-Za-z0-9]", exemplar_separator or ""):
                styled.append(exemplar_separator)
            else:
                styled.append(part)

    return _normalize_view_name("".join(styled))


def get_active_view_info_handler(services, **_kwargs) -> dict:
    services.logger.info("MCP Tool executed: %s", GET_ACTIVE_VIEW_INFO_TOOL_NAME)
    return services.revit_client.call_listener(command_path="/views/active/info", method="GET")


def get_active_view_elements_handler(
    services,
    category_names: list[str] = None,
    limit: int = 200,
    **_kwargs,
) -> dict:
    safe_limit = bounded_int(limit, 200, min_value=1, max_value=2000)
    normalized_categories = category_names if isinstance(category_names, list) else []
    services.logger.info(
        "MCP Tool executed: %s with %s category filters and limit=%s",
        GET_ACTIVE_VIEW_ELEMENTS_TOOL_NAME,
        len(normalized_categories),
        safe_limit,
    )

    result = services.revit_client.call_listener(
        command_path="/views/active/elements",
        method="POST",
        payload_data={"category_names": normalized_categories, "limit": safe_limit},
    )

    if result.get("status") == "success" and result.get("element_ids"):
        view_info = result.get("view", {}) if isinstance(result.get("view"), dict) else {}
        storage_seed = "active_view_{}".format(view_info.get("name", "current"))
        if len(normalized_categories) == 1:
            storage_seed = "{}_{}".format(storage_seed, normalized_categories[0])
        elif len(normalized_categories) > 1:
            storage_seed = "{}_filtered".format(storage_seed)

        stored_as, result_handle = services.result_store.store_elements(
            storage_seed,
            result.get("element_ids", []),
            result.get("returned_count", len(result.get("element_ids", []))),
        )
        result["stored_as"] = stored_as
        result["result_handle"] = result_handle
        result["storage_message"] = "Active view results stored as '{}' ({})".format(stored_as, result_handle)

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
            "view",
        ],
    )


def export_active_view_image_handler(
    services,
    pixel_size: int = 1600,
    format: str = "png",
    **_kwargs,
) -> dict:
    safe_pixel_size = bounded_int(pixel_size, 1600, min_value=256, max_value=4096)
    normalized_format = str(format or "png").strip().lower()
    if normalized_format not in ("png", "jpg", "jpeg", "bmp", "tif", "tiff"):
        normalized_format = "png"

    services.logger.info(
        "MCP Tool executed: %s with pixel_size=%s format=%s",
        EXPORT_ACTIVE_VIEW_IMAGE_TOOL_NAME,
        safe_pixel_size,
        normalized_format,
    )

    return services.revit_client.call_listener(
        command_path="/views/active/export_image",
        method="POST",
        payload_data={
            "capture_dir": services.config.capture_base_dir,
            "pixel_size": safe_pixel_size,
            "format": normalized_format,
        },
    )


def place_view_on_sheet_handler(
    services,
    view_name: str = None,
    view_id: str = None,
    target_sheet_id: str = None,
    target_sheet_name: str = None,
    titleblock_id: str = None,
    titleblock_name: str = None,
    exact_match: bool = False,
    **_kwargs,
) -> dict:
    services.logger.info(
        "MCP Tool executed: %s with view_name=%s, view_id=%s, target_sheet_id=%s, target_sheet_name=%s, titleblock_id=%s, titleblock_name=%s, exact_match=%s",
        PLACE_VIEW_ON_SHEET_TOOL_NAME,
        view_name,
        view_id,
        target_sheet_id,
        target_sheet_name,
        titleblock_id,
        titleblock_name,
        exact_match,
    )
    if not view_name and not view_id:
        return {
            "status": "error",
            "message": "Provide either view_name or view_id (use view_id when multiple views share a name).",
        }
    payload = {"exact_match": exact_match}
    if view_name:
        payload["view_name"] = view_name
    if view_id:
        payload["view_id"] = str(view_id)
    if target_sheet_id:
        payload["target_sheet_id"] = str(target_sheet_id)
    if target_sheet_name:
        payload["target_sheet_name"] = target_sheet_name
    if titleblock_id:
        payload["titleblock_id"] = str(titleblock_id)
    if titleblock_name:
        payload["titleblock_name"] = titleblock_name
    return services.revit_client.call_listener(
        command_path="/sheets/place_view",
        method="POST",
        payload_data=payload,
    )


def activate_view_handler(
    services,
    view_id: str = None,
    view_name: str = None,
    exact_match: bool = False,
    **_kwargs,
) -> dict:
    services.logger.info(
        "MCP Tool executed: %s with view_id=%s, view_name=%s, exact_match=%s",
        ACTIVATE_VIEW_TOOL_NAME,
        view_id,
        view_name,
        exact_match,
    )
    if not view_id and not view_name:
        return {
            "status": "error",
            "message": "Provide either view_id or view_name (use view_id when multiple views share a name).",
        }

    payload = {"exact_match": bool(exact_match)}
    if view_id:
        payload["view_id"] = str(view_id)
    if view_name:
        payload["view_name"] = view_name

    return services.revit_client.call_listener(
        command_path="/views/activate",
        method="POST",
        payload_data=payload,
    )


def duplicate_view_handler(
    services,
    view_id: str = None,
    view_name: str = None,
    duplicate_option: str = "duplicate",
    new_name: str = None,
    exact_match: bool = False,
    uniquify_name: bool = True,
    apply_template_id: str = None,
    activate: bool = False,
    **_kwargs,
) -> dict:
    normalized_option = str(duplicate_option or "duplicate").strip().lower()
    if normalized_option not in ["duplicate", "with_detailing", "as_dependent"]:
        return {
            "status": "error",
            "message": "duplicate_option must be one of: duplicate, with_detailing, as_dependent.",
        }

    payload = {
        "duplicate_option": normalized_option,
        "exact_match": bool(exact_match),
        "uniquify_name": bool(uniquify_name),
        "activate": bool(activate),
    }
    if view_id:
        payload["view_id"] = str(view_id)
    if view_name:
        payload["view_name"] = view_name
    if new_name:
        payload["new_name"] = new_name
    if apply_template_id:
        payload["apply_template_id"] = str(apply_template_id)

    services.logger.info(
        "MCP Tool executed: %s with view_id=%s, view_name=%s, duplicate_option=%s, new_name=%s",
        DUPLICATE_VIEW_TOOL_NAME,
        view_id,
        view_name,
        normalized_option,
        new_name,
    )

    return services.revit_client.call_listener(
        command_path="/views/duplicate",
        method="POST",
        payload_data=payload,
    )


def list_views_handler(services, **_kwargs) -> dict:
    services.logger.info("MCP Tool executed: %s", LIST_VIEWS_TOOL_NAME)
    result = services.revit_client.call_listener(command_path="/sheets/list_views", method="GET")
    return services.result_store.compact_result_payload(result, preserve_keys=["status", "message"])


def analyze_view_naming_patterns_internal(
    services,
    view_type_filter: list[str] = None,
    min_group_size: int = 6,
    outlier_similarity_threshold: float = 0.72,
) -> dict:
    views_result = services.revit_client.call_listener(command_path="/sheets/list_views", method="GET")
    if views_result.get("status") == "error":
        return views_result

    all_views = views_result.get("views", []) or []
    if not isinstance(all_views, list):
        return {"status": "error", "message": "Unexpected views payload from list_views."}

    allowed_types = set((view_type_filter or []))
    if allowed_types:
        working_views = [view for view in all_views if view.get("type") in allowed_types]
    else:
        working_views = all_views

    if not working_views:
        return {
            "status": "success",
            "message": "No views available for naming analysis with current filters.",
            "count": 0,
            "analysis": {"groups": [], "outliers": []},
        }

    by_type = defaultdict(list)
    for view in working_views:
        name = view.get("name")
        if not name:
            continue
        by_type[view.get("type", "Unknown")].append(view)

    groups = []
    outliers = []

    for view_type, type_views in by_type.items():
        by_signature = defaultdict(list)
        for view in type_views:
            signature = _view_name_signature(view.get("name", ""))
            by_signature[signature].append(view)

        signature_clusters = []
        for signature, members in by_signature.items():
            example_names = [member.get("name", "") for member in members[:3]]
            signature_clusters.append(
                {
                    "signature": signature,
                    "count": len(members),
                    "example_names": example_names,
                    "members": members,
                }
            )
        signature_clusters.sort(key=lambda cluster: cluster["count"], reverse=True)

        dominant_cluster = signature_clusters[0] if signature_clusters else None
        dominant_example = dominant_cluster["members"][0].get("name", "") if dominant_cluster else ""

        group_summary = {
            "view_type": view_type,
            "total_views": len(type_views),
            "cluster_count": len(signature_clusters),
            "dominant_patterns": [
                {
                    "signature": cluster["signature"],
                    "count": cluster["count"],
                    "example_names": cluster["example_names"],
                }
                for cluster in signature_clusters[:5]
            ],
            "outlier_count": 0,
        }

        if dominant_cluster and len(type_views) >= int(min_group_size):
            for cluster in signature_clusters:
                cluster_ratio = float(cluster["count"]) / float(len(type_views))
                weak_cluster = cluster["count"] == 1 or cluster_ratio < 0.08
                if not weak_cluster:
                    continue

                for member in cluster["members"]:
                    name = member.get("name", "")
                    similarity = _view_similarity(name, dominant_example) if dominant_example else 0.0
                    if similarity >= float(outlier_similarity_threshold) and cluster["count"] > 1:
                        continue
                    outliers.append(
                        {
                            "view_id": member.get("id"),
                            "name": name,
                            "view_type": view_type,
                            "detected_signature": cluster["signature"],
                            "nearest_signature": dominant_cluster["signature"],
                            "nearest_example": dominant_example,
                            "similarity_to_nearest": round(similarity, 3),
                            "reason": "Low-frequency naming pattern in this view type.",
                        }
                    )
                    group_summary["outlier_count"] += 1

        groups.append(group_summary)

    record = {
        "created_at": services.result_store._now_timestamp(),
        "filters": {
            "view_type_filter": sorted(list(allowed_types)) if allowed_types else [],
            "min_group_size": int(min_group_size),
            "outlier_similarity_threshold": float(outlier_similarity_threshold),
        },
        "views_total": len(working_views),
        "groups": groups,
        "outliers": outliers,
    }
    analysis_handle = services.result_store.store_view_analysis(record)

    outlier_sample_limit = max(10, services.config.max_outliers_in_response)
    result_payload = {
        "status": "success",
        "message": "Analyzed {} views across {} view-type groups; detected {} outliers.".format(
            len(working_views),
            len(groups),
            len(outliers),
        ),
        "analysis_handle": analysis_handle,
        "count": len(working_views),
        "groups": groups,
        "outliers_sample": outliers[:outlier_sample_limit],
        "outliers_total": len(outliers),
        "outliers_truncated": len(outliers) > outlier_sample_limit,
    }
    return services.result_store.compact_result_payload(
        result_payload,
        preserve_keys=["analysis_handle", "status", "message", "count", "outliers_total", "outliers_truncated"],
    )


def analyze_view_naming_patterns_handler(
    services,
    view_type_filter: list[str] = None,
    min_group_size: int = 6,
    outlier_similarity_threshold: float = 0.72,
    **_kwargs,
) -> dict:
    services.logger.info(
        "MCP Tool executed: %s (view_type_filter=%s, min_group_size=%s, outlier_similarity_threshold=%s)",
        ANALYZE_VIEW_NAMING_PATTERNS_TOOL_NAME,
        view_type_filter,
        min_group_size,
        outlier_similarity_threshold,
    )
    try:
        safe_group_size = max(3, min(30, int(min_group_size or 6)))
    except Exception:
        safe_group_size = 6

    try:
        safe_threshold = float(outlier_similarity_threshold if outlier_similarity_threshold is not None else 0.72)
    except Exception:
        safe_threshold = 0.72
    safe_threshold = max(0.45, min(0.95, safe_threshold))

    return analyze_view_naming_patterns_internal(
        services,
        view_type_filter=view_type_filter or [],
        min_group_size=safe_group_size,
        outlier_similarity_threshold=safe_threshold,
    )


def suggest_view_name_corrections_handler(
    services,
    analysis_handle: str,
    max_suggestions: int = 100,
    min_confidence: float = 0.6,
    **_kwargs,
) -> dict:
    services.logger.info(
        "MCP Tool executed: %s (analysis_handle=%s, max_suggestions=%s, min_confidence=%s)",
        SUGGEST_VIEW_NAME_CORRECTIONS_TOOL_NAME,
        analysis_handle,
        max_suggestions,
        min_confidence,
    )

    record = services.result_store.get_view_analysis(analysis_handle)
    if not record:
        return {"status": "error", "message": "Unknown analysis_handle '{}'".format(analysis_handle)}

    try:
        safe_max = max(1, min(300, int(max_suggestions or 100)))
    except Exception:
        safe_max = 100

    try:
        safe_min_confidence = max(0.0, min(1.0, float(min_confidence if min_confidence is not None else 0.6)))
    except Exception:
        safe_min_confidence = 0.6

    outliers = record.get("outliers", []) or []
    suggestions = []
    for outlier in outliers:
        current_name = outlier.get("name", "")
        exemplar = outlier.get("nearest_example", "")
        if not current_name or not exemplar:
            continue

        suggested_name = _apply_view_style_from_exemplar(current_name, exemplar)
        similarity = float(outlier.get("similarity_to_nearest", 0.0))
        confidence = round(max(0.0, min(0.99, similarity + 0.2)), 3)
        if confidence < safe_min_confidence:
            continue
        if suggested_name == current_name:
            continue

        suggestions.append(
            {
                "view_id": outlier.get("view_id"),
                "view_type": outlier.get("view_type"),
                "current_name": current_name,
                "suggested_name": suggested_name,
                "confidence": confidence,
                "reason": "Aligned casing/separator style with nearest in-group naming pattern.",
                "nearest_example": exemplar,
            }
        )

        if len(suggestions) >= safe_max:
            break

    result_payload = {
        "status": "success",
        "analysis_handle": analysis_handle,
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
        "message": "Generated {} rename suggestions from {} analyzed outliers.".format(
            len(suggestions),
            len(outliers),
        ),
    }
    return services.result_store.compact_result_payload(
        result_payload,
        preserve_keys=["status", "analysis_handle", "suggestion_count", "message"],
    )


def build_view_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=GET_ACTIVE_VIEW_INFO_TOOL_NAME,
            description=(
                "Returns metadata for the active Revit view, including name, type, scale, printability, and "
                "associated level when available."
            ),
            json_schema={"type": "object", "properties": {}},
            handler=get_active_view_info_handler,
        ),
        ToolDefinition(
            name=GET_ACTIVE_VIEW_ELEMENTS_TOOL_NAME,
            description=(
                "Returns a bounded snapshot of elements visible in the active Revit view. Optionally filter by "
                "category names. Successful results are stored for follow-on selection or property reads."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "category_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional category names to keep in the active-view scan.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of matching elements to return and store from the active view.",
                    },
                },
            },
            handler=get_active_view_elements_handler,
        ),
        ToolDefinition(
            name=EXPORT_ACTIVE_VIEW_IMAGE_TOOL_NAME,
            description=(
                "Exports the active Revit view to an image file in the local RevitMCP captures folder and returns "
                "an image artifact path. Use activate_view first when a specific view should be inspected."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "pixel_size": {
                        "type": "integer",
                        "description": "Target export pixel size. Default 1600, min 256, max 4096.",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["png", "jpg", "jpeg", "bmp", "tif", "tiff"],
                        "description": "Image format. Default png.",
                    },
                },
            },
            handler=export_active_view_image_handler,
        ),
        ToolDefinition(
            name=PLACE_VIEW_ON_SHEET_TOOL_NAME,
            description=(
                "Places a view on a sheet. Two modes: (1) creates a NEW sheet (default — pass titleblock_id or "
                "titleblock_name to control which titleblock is used; discover titleblocks via list_family_types("
                "category_names=['Title Blocks'])); (2) places onto an EXISTING sheet (pass target_sheet_id or "
                "target_sheet_name; titleblock_* is ignored). Identify the view by view_id (preferred when "
                "multiple views share a name, common with Area Plans and dependent views) or view_name (with "
                "optional fuzzy matching). To batch-sheet many views, the caller should loop this tool, picking "
                "the titleblock once via list_family_types and reusing the symbol_id across calls."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "view_name": {
                        "type": "string",
                        "description": "Name of the view to place. Ignored if view_id is supplied.",
                    },
                    "view_id": {
                        "type": "string",
                        "description": (
                            "Element ID of the view to place. Takes precedence over view_name. "
                            "Use this to disambiguate when multiple views share a name."
                        ),
                    },
                    "target_sheet_id": {
                        "type": "string",
                        "description": (
                            "Element ID of an existing sheet to place onto. When provided, no new sheet is "
                            "created. Takes precedence over target_sheet_name."
                        ),
                    },
                    "target_sheet_name": {
                        "type": "string",
                        "description": (
                            "Name or sheet number of an existing sheet to place onto. When provided, no new "
                            "sheet is created. Use target_sheet_id when multiple sheets share a name."
                        ),
                    },
                    "titleblock_id": {
                        "type": "string",
                        "description": (
                            "Element ID (symbol_id) of a titleblock FamilySymbol to use when creating a new "
                            "sheet. Discover available titleblocks via "
                            "list_family_types(category_names=['Title Blocks']). Takes precedence over "
                            "titleblock_name. Ignored if target_sheet_* is supplied."
                        ),
                    },
                    "titleblock_name": {
                        "type": "string",
                        "description": (
                            "Family or type name of a titleblock to use when creating a new sheet. Use "
                            "titleblock_id to disambiguate when multiple titleblocks share a name. Ignored "
                            "if target_sheet_* is supplied."
                        ),
                    },
                    "exact_match": {
                        "type": "boolean",
                        "description": "Whether to require exact match for view_name, target_sheet_name, and titleblock_name.",
                    },
                },
            },
            handler=place_view_on_sheet_handler,
        ),
        ToolDefinition(
            name=ACTIVATE_VIEW_TOOL_NAME,
            description=(
                "Switches the active Revit view. Identify the target by view_id (preferred) or view_name with "
                "optional exact matching. Use list_views first to discover view IDs, then get_active_view_elements "
                "to inspect what is visible after navigation."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "view_id": {
                        "type": "string",
                        "description": "Element ID of the view to activate. Preferred when names are ambiguous.",
                    },
                    "view_name": {
                        "type": "string",
                        "description": "Name or partial name of the view to activate. Ignored if view_id resolves.",
                    },
                    "exact_match": {
                        "type": "boolean",
                        "description": "Whether view_name must match exactly. Default false.",
                    },
                },
            },
            handler=activate_view_handler,
        ),
        ToolDefinition(
            name=DUPLICATE_VIEW_TOOL_NAME,
            description=(
                "Duplicates a Revit view. Identify the source by view_id, view_name, or omit both to duplicate the "
                "active view. Supports duplicate, with_detailing, and as_dependent modes, optional new_name, optional "
                "view template assignment, and optional activation of the new view."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "view_id": {
                        "type": "string",
                        "description": "Element ID of the source view. Preferred when names are ambiguous.",
                    },
                    "view_name": {
                        "type": "string",
                        "description": "Name or partial name of the source view. Ignored if view_id is supplied.",
                    },
                    "duplicate_option": {
                        "type": "string",
                        "enum": ["duplicate", "with_detailing", "as_dependent"],
                        "description": "How to duplicate the view. Default duplicate.",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "Optional name for the duplicated view.",
                    },
                    "exact_match": {
                        "type": "boolean",
                        "description": "Whether view_name must match exactly. Default false.",
                    },
                    "uniquify_name": {
                        "type": "boolean",
                        "description": "When true, appends a number if new_name already exists. Default true.",
                    },
                    "apply_template_id": {
                        "type": "string",
                        "description": "Optional view template Element ID to assign to the duplicated view.",
                    },
                    "activate": {
                        "type": "boolean",
                        "description": "When true, makes the duplicated view active after creation. Default false.",
                    },
                },
            },
            handler=duplicate_view_handler,
        ),
        ToolDefinition(
            name=LIST_VIEWS_TOOL_NAME,
            description=(
                "Lists all views in the current document that can be placed on sheets. Returns view names, types, "
                "IDs, and whether they're already placed on sheets. Use this to discover available views before "
                "placing them."
            ),
            json_schema={"type": "object", "properties": {}},
            handler=list_views_handler,
        ),
        ToolDefinition(
            name=ANALYZE_VIEW_NAMING_PATTERNS_TOOL_NAME,
            description="Dynamically analyzes view naming patterns by clustering names per view type and identifying likely outliers.",
            json_schema={
                "type": "object",
                "properties": {
                    "view_type_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of view types to limit analysis scope.",
                    },
                    "min_group_size": {
                        "type": "integer",
                        "description": "Minimum views in a type-group before outlier detection is applied.",
                    },
                    "outlier_similarity_threshold": {
                        "type": "number",
                        "description": "Similarity threshold (0-1) for outlier detection.",
                    },
                },
            },
            handler=analyze_view_naming_patterns_handler,
        ),
        ToolDefinition(
            name=SUGGEST_VIEW_NAME_CORRECTIONS_TOOL_NAME,
            description="Generates rename suggestions for outlier views from a previous naming analysis.",
            json_schema={
                "type": "object",
                "properties": {
                    "analysis_handle": {
                        "type": "string",
                        "description": "Required handle returned by analyze_view_naming_patterns.",
                    },
                    "max_suggestions": {
                        "type": "integer",
                        "description": "Maximum number of suggestions to return.",
                    },
                    "min_confidence": {
                        "type": "number",
                        "description": "Minimum confidence (0-1) for returned suggestions.",
                    },
                },
                "required": ["analysis_handle"],
            },
            handler=suggest_view_name_corrections_handler,
        ),
    ]
