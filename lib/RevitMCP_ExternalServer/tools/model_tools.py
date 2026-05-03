from RevitMCP_ExternalServer.core.runtime_config import bounded_int
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


ANALYZE_MODEL_STATISTICS_TOOL_NAME = "analyze_model_statistics"


def analyze_model_statistics_handler(
    services,
    include_detailed_types: bool = True,
    include_levels: bool = True,
    top_n: int = 25,
    **_kwargs,
) -> dict:
    safe_top_n = bounded_int(top_n, 25, min_value=1, max_value=200)
    services.logger.info(
        "MCP Tool executed: %s with include_detailed_types=%s, include_levels=%s, top_n=%s",
        ANALYZE_MODEL_STATISTICS_TOOL_NAME,
        include_detailed_types,
        include_levels,
        safe_top_n,
    )

    result = services.revit_client.call_listener(
        command_path="/model/statistics",
        method="POST",
        payload_data={
            "include_detailed_types": bool(include_detailed_types),
            "include_levels": bool(include_levels),
            "top_n": safe_top_n,
        },
    )

    return services.result_store.compact_result_payload(
        result,
        preserve_keys=[
            "status",
            "message",
            "project_name",
            "summary",
            "category_count",
            "categories_total",
            "categories_truncated",
            "levels",
            "options",
        ],
    )


def build_model_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=ANALYZE_MODEL_STATISTICS_TOOL_NAME,
            description=(
                "Analyzes the current Revit model composition. Returns element/type/family/view/sheet/level/room "
                "totals, top categories by element count, optional family/type breakdowns, and level distribution."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "include_detailed_types": {
                        "type": "boolean",
                        "description": "Whether to include family/type breakdowns within each returned category. Default true.",
                    },
                    "include_levels": {
                        "type": "boolean",
                        "description": "Whether to include level-by-level element counts. Default true.",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Maximum number of categories and per-category types to return. Default 25, max 200.",
                    },
                },
            },
            handler=analyze_model_statistics_handler,
        )
    ]
