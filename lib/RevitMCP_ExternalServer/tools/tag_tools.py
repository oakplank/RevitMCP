"""MCP tool wrappers for tag / room-stamp operations.

Built on the HTTP routes in lib/routes/tag_routes.py:
  - /tags/by_id
  - /tags/all_in_view
  - /tags/rooms
"""
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


TAG_ELEMENTS_BY_ID_TOOL_NAME = "tag_elements_by_id"
TAG_ALL_IN_VIEW_TOOL_NAME = "tag_all_in_view"
TAG_ROOMS_TOOL_NAME = "tag_rooms"


def _resolve_requested_element_ids(services, element_ids=None, result_handle: str = None, category_name: str = None):
    resolved_ids, record, error = services.result_store.resolve_element_ids(
        element_ids=element_ids,
        result_handle=result_handle,
        category_name=category_name,
    )
    if error:
        return None, None, error
    return resolved_ids or [], record, None


def tag_elements_by_id_handler(
    services,
    element_ids: list[str] = None,
    result_handle: str = None,
    category_name: str = None,
    add_leader: bool = False,
    refresh_view: bool = True,
    **_kwargs,
) -> dict:
    resolved_ids, record, error = _resolve_requested_element_ids(
        services, element_ids=element_ids, result_handle=result_handle, category_name=category_name,
    )
    if error:
        return error
    if not resolved_ids:
        return {"status": "error", "message": "No element IDs resolved for tagging."}

    services.logger.info(
        "MCP Tool executed: %s with %s resolved element IDs (handle=%s, category=%s, leader=%s)",
        TAG_ELEMENTS_BY_ID_TOOL_NAME, len(resolved_ids), result_handle, category_name, add_leader,
    )

    payload = {
        "element_ids": resolved_ids,
        "add_leader": bool(add_leader),
        "refresh_view": bool(refresh_view),
    }

    result = services.revit_client.call_listener(
        command_path="/tags/by_id",
        method="POST",
        payload_data=payload,
    )

    if record:
        result["source_result_handle"] = record.get("result_handle")
        result["source_category"] = record.get("category")

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status", "message", "view",
            "applied_count", "applied",
            "failed_count", "failed",
            "invalid_ids",
            "source_result_handle", "source_category",
        ],
    )


def tag_all_in_view_handler(
    services,
    category_names: list[str] = None,
    add_leader: bool = False,
    refresh_view: bool = True,
    **_kwargs,
) -> dict:
    if not category_names or not isinstance(category_names, list):
        return {"status": "error", "message": "category_names list required (e.g. ['OST_Doors','OST_Windows'])."}

    services.logger.info(
        "MCP Tool executed: %s with categories=%s leader=%s",
        TAG_ALL_IN_VIEW_TOOL_NAME, category_names, add_leader,
    )

    payload = {
        "category_names": category_names,
        "add_leader": bool(add_leader),
        "refresh_view": bool(refresh_view),
    }

    result = services.revit_client.call_listener(
        command_path="/tags/all_in_view",
        method="POST",
        payload_data=payload,
    )

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status", "message", "view",
            "per_category",
            "applied_count", "failed_count",
            "skipped_already_tagged",
            "failed_sample",
        ],
    )


def tag_rooms_handler(
    services,
    room_ids: list[str] = None,
    all_in_view: bool = False,
    result_handle: str = None,
    refresh_view: bool = True,
    **_kwargs,
) -> dict:
    payload = {"refresh_view": bool(refresh_view)}

    if all_in_view:
        payload["all_in_view"] = True
    else:
        # Resolve room_ids via result_store the same way other tools do
        resolved_ids, record, error = _resolve_requested_element_ids(
            services, element_ids=room_ids, result_handle=result_handle,
        )
        if error:
            return error
        if not resolved_ids:
            return {"status": "error", "message": "No room IDs resolved (or set all_in_view=true)."}
        payload["room_ids"] = resolved_ids

    services.logger.info(
        "MCP Tool executed: %s with all_in_view=%s, %s room IDs",
        TAG_ROOMS_TOOL_NAME, all_in_view, len(payload.get("room_ids", [])),
    )

    result = services.revit_client.call_listener(
        command_path="/tags/rooms",
        method="POST",
        payload_data=payload,
    )

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status", "message", "view",
            "applied_count", "applied",
            "failed_count", "failed",
            "skipped_already_tagged",
        ],
    )


def build_tag_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=TAG_ELEMENTS_BY_ID_TOOL_NAME,
            description=(
                "Places category-appropriate tags (Beschriftungen) on explicit elements in the active Revit "
                "view. Accepts element_ids, a result_handle from filter/get tools, or a stored category_name. "
                "For each element a default tag family symbol from the matching tag category is used "
                "(OST_Walls -> OST_WallTags etc.). Room elements are auto-redirected to RoomTag creation. "
                "Use add_leader=true for tags with leader lines."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "element_ids": {"type": "array", "items": {"type": "string"}},
                    "result_handle": {"type": "string"},
                    "category_name": {"type": "string"},
                    "add_leader": {"type": "boolean", "description": "Tag with leader line. Default false."},
                    "refresh_view": {"type": "boolean", "description": "Refresh active view after tagging. Default true."},
                },
            },
            handler=tag_elements_by_id_handler,
        ),
        ToolDefinition(
            name=TAG_ALL_IN_VIEW_TOOL_NAME,
            description=(
                "Tags every untagged element of the given categories in the active view. Skips elements that "
                "already carry a tag in this view. Use this for bulk operations like 'tag all doors and windows "
                "in the EG floor plan'. Pass category_names as OST_* identifiers (e.g. ['OST_Doors','OST_Windows'])."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "category_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of OST_* category names (e.g. ['OST_Doors','OST_Windows']).",
                    },
                    "add_leader": {"type": "boolean", "description": "Tag with leader line. Default false."},
                    "refresh_view": {"type": "boolean", "description": "Refresh active view after tagging. Default true."},
                },
                "required": ["category_names"],
            },
            handler=tag_all_in_view_handler,
        ),
        ToolDefinition(
            name=TAG_ROOMS_TOOL_NAME,
            description=(
                "Places RoomTags (Raumstempel) on rooms in the active view. Either pass explicit room_ids "
                "(from get_elements_by_category(OST_Rooms) or filter_elements), or set all_in_view=true to tag "
                "every untagged room visible in the active view. Skips already-tagged rooms. Unplaced rooms "
                "(no location point) are reported as failed."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "room_ids": {"type": "array", "items": {"type": "string"}},
                    "result_handle": {"type": "string"},
                    "all_in_view": {
                        "type": "boolean",
                        "description": "When true, tag every untagged room in active view (room_ids ignored).",
                    },
                    "refresh_view": {"type": "boolean", "description": "Refresh active view after tagging. Default true."},
                },
            },
            handler=tag_rooms_handler,
        ),
    ]
