from RevitMCP_ExternalServer.core.runtime_config import bounded_int
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


OVERRIDE_ELEMENT_GRAPHICS_TOOL_NAME = "override_element_graphics"
DELETE_ELEMENTS_TOOL_NAME = "delete_elements"


def _resolve_requested_element_ids(services, element_ids=None, result_handle: str = None, category_name: str = None):
    resolved_ids, record, error = services.result_store.resolve_element_ids(
        element_ids=element_ids,
        result_handle=result_handle,
        category_name=category_name,
    )
    if error:
        return None, None, error
    return resolved_ids or [], record, None


def override_element_graphics_handler(
    services,
    element_ids: list[str] = None,
    result_handle: str = None,
    category_name: str = None,
    color: dict = None,
    transparency: int = None,
    halftone: bool = None,
    reset: bool = False,
    focus: bool = False,
    refresh_view: bool = True,
    **_kwargs,
) -> dict:
    resolved_ids, record, error = _resolve_requested_element_ids(
        services,
        element_ids=element_ids,
        result_handle=result_handle,
        category_name=category_name,
    )
    if error:
        return error

    if not resolved_ids:
        return {"status": "error", "message": "No element IDs resolved for graphics override."}

    payload = {
        "element_ids": resolved_ids,
        "reset": bool(reset),
        "focus": bool(focus),
        "refresh_view": bool(refresh_view),
    }
    if color is not None:
        payload["color"] = color
    if transparency is not None:
        payload["transparency"] = bounded_int(transparency, 0, min_value=0, max_value=100)
    if halftone is not None:
        payload["halftone"] = bool(halftone)

    services.logger.info(
        "MCP Tool executed: %s with %s resolved element IDs (handle=%s, category=%s, reset=%s)",
        OVERRIDE_ELEMENT_GRAPHICS_TOOL_NAME,
        len(resolved_ids),
        result_handle,
        category_name,
        reset,
    )

    result = services.revit_client.call_listener(
        command_path="/elements/override_graphics",
        method="POST",
        payload_data=payload,
    )

    if record:
        result["source_result_handle"] = record.get("result_handle")
        result["source_category"] = record.get("category")

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status",
            "message",
            "view",
            "applied_count",
            "reset",
            "focus_result",
            "refresh_result",
            "source_result_handle",
            "source_category",
        ],
    )


def delete_elements_handler(
    services,
    element_ids: list[str] = None,
    result_handle: str = None,
    category_name: str = None,
    dry_run: bool = True,
    confirm_delete: bool = False,
    max_count: int = 25,
    unpin_before_delete: bool = False,
    deletion_mode: str = "individual",
    **_kwargs,
) -> dict:
    resolved_ids, record, error = _resolve_requested_element_ids(
        services,
        element_ids=element_ids,
        result_handle=result_handle,
        category_name=category_name,
    )
    if error:
        return error

    if not resolved_ids:
        return {"status": "error", "message": "No element IDs resolved for deletion."}

    safe_max_count = bounded_int(max_count, 25, min_value=1, max_value=500)
    normalized_deletion_mode = str(deletion_mode or "individual").strip().lower()
    if normalized_deletion_mode not in ("individual", "batch"):
        normalized_deletion_mode = "individual"
    services.logger.info(
        "MCP Tool executed: %s with %s resolved element IDs (dry_run=%s, confirm_delete=%s, max_count=%s, unpin_before_delete=%s, deletion_mode=%s)",
        DELETE_ELEMENTS_TOOL_NAME,
        len(resolved_ids),
        dry_run,
        confirm_delete,
        safe_max_count,
        unpin_before_delete,
        normalized_deletion_mode,
    )

    result = services.revit_client.call_listener(
        command_path="/elements/delete",
        method="POST",
        payload_data={
            "element_ids": resolved_ids,
            "dry_run": bool(dry_run),
            "confirm_delete": bool(confirm_delete),
            "max_count": safe_max_count,
            "unpin_before_delete": bool(unpin_before_delete),
            "deletion_mode": normalized_deletion_mode,
        },
    )

    if record:
        result["source_result_handle"] = record.get("result_handle")
        result["source_category"] = record.get("category")

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status",
            "message",
            "candidate_count",
            "deleted_input_count",
            "deleted_total_count",
            "dry_run",
            "confirm_delete",
            "unpin_before_delete",
            "deletion_mode",
            "max_count",
            "source_result_handle",
            "source_category",
            "next_step",
            "failed",
            "skipped",
            "unpinned_ids",
        ],
    )


def build_element_operation_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=OVERRIDE_ELEMENT_GRAPHICS_TOOL_NAME,
            description=(
                "Applies or resets per-element graphic overrides in the active Revit view. Accepts explicit "
                "element_ids, a result_handle from filter/get tools, or a stored category_name. Supports RGB color, "
                "surface transparency, halftone, reset, and optional focus."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "element_ids": {"type": "array", "items": {"type": "string"}},
                    "result_handle": {"type": "string"},
                    "category_name": {"type": "string"},
                    "color": {
                        "type": "object",
                        "properties": {
                            "r": {"type": "integer"},
                            "g": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "description": "RGB color components from 0 to 255.",
                    },
                    "transparency": {
                        "type": "integer",
                        "description": "Surface transparency from 0 opaque to 100 fully transparent.",
                    },
                    "halftone": {"type": "boolean"},
                    "reset": {
                        "type": "boolean",
                        "description": "When true, clears existing element overrides in the active view.",
                    },
                    "focus": {
                        "type": "boolean",
                        "description": "When true, calls Revit ShowElements for the operated elements after applying overrides.",
                    },
                    "refresh_view": {
                        "type": "boolean",
                        "description": "When true, refreshes the active view after applying overrides. Default true.",
                    },
                },
            },
            handler=override_element_graphics_handler,
        ),
        ToolDefinition(
            name=DELETE_ELEMENTS_TOOL_NAME,
            description=(
                "Deletes elements from the Revit model with safeguards. Accepts explicit element_ids, a result_handle, "
                "or a stored category_name. Defaults to dry_run=true; actual deletion requires dry_run=false and "
                "confirm_delete=true, and is limited by max_count."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "element_ids": {"type": "array", "items": {"type": "string"}},
                    "result_handle": {"type": "string"},
                    "category_name": {"type": "string"},
                    "dry_run": {
                        "type": "boolean",
                        "description": "When true, only reports what would be deleted. Default true.",
                    },
                    "confirm_delete": {
                        "type": "boolean",
                        "description": "Must be true together with dry_run=false to actually delete elements.",
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "Maximum number of input elements allowed for deletion. Default 25, max 500.",
                    },
                    "unpin_before_delete": {
                        "type": "boolean",
                        "description": (
                            "When true, attempts to unpin each input element inside the delete transaction before "
                            "deleting. Useful for pinned curtain panels and other pinned instances."
                        ),
                    },
                    "deletion_mode": {
                        "type": "string",
                        "enum": ["individual", "batch"],
                        "description": (
                            "individual deletes one input per transaction and reports per-element failures. "
                            "batch deletes all inputs in one transaction. Default individual."
                        ),
                    },
                },
            },
            handler=delete_elements_handler,
        ),
    ]
