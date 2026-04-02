import inspect
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from google.generativeai import types as google_types


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    json_schema: dict[str, Any]
    handler: Callable[..., dict]


def _annotation_from_schema(schema: dict) -> object:
    json_type = schema.get("type")
    if isinstance(json_type, list):
        non_null_types = [item for item in json_type if item != "null"]
        json_type = non_null_types[0] if non_null_types else None

    if json_type == "string":
        return str
    if json_type == "integer":
        return int
    if json_type == "number":
        return float
    if json_type == "boolean":
        return bool
    if json_type == "array":
        item_annotation = _annotation_from_schema(schema.get("items", {}))
        try:
            return list[item_annotation]
        except Exception:
            return list
    if json_type == "object":
        return dict
    return object


class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition]):
        ordered = OrderedDict()
        for definition in definitions:
            if definition.name in ordered:
                raise ValueError("Duplicate tool name detected: {}".format(definition.name))
            ordered[definition.name] = definition
        self._definitions = ordered

    def list_definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def get(self, tool_name: str) -> ToolDefinition | None:
        return self._definitions.get(tool_name)

    def dispatch(self, services, tool_name: str, function_args: dict | None = None) -> dict:
        normalized_args = function_args or {}
        definition = self.get(tool_name)
        if not definition:
            services.logger.warning("Unknown tool '%s' requested by LLM.", tool_name)
            return {"status": "error", "message": "Unknown tool '{}' requested by LLM.".format(tool_name)}

        try:
            return definition.handler(services, **normalized_args)
        except TypeError as exc:
            services.logger.error("Invalid arguments for tool '%s': %s", tool_name, exc, exc_info=True)
            return {"status": "error", "message": "Invalid arguments for tool '{}': {}".format(tool_name, exc)}
        except Exception as exc:
            services.logger.error("Exception while executing tool '%s': %s", tool_name, exc, exc_info=True)
            return {"status": "error", "message": "Exception while executing tool '{}': {}".format(tool_name, exc)}

    def register_mcp_tools(self, mcp_server, services) -> None:
        for definition in self.list_definitions():
            mcp_server.add_tool(
                self._build_mcp_callable(definition, services),
                name=definition.name,
                description=definition.description,
            )

    def to_openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": definition.json_schema,
                },
            }
            for definition in self.list_definitions()
        ]

    def to_anthropic_tools(self) -> list[dict]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "input_schema": definition.json_schema,
            }
            for definition in self.list_definitions()
        ]

    def to_google_tools(self) -> list[google_types.Tool]:
        function_declarations = [
            google_types.FunctionDeclaration(
                name=definition.name,
                description=definition.description,
                parameters=definition.json_schema,
            )
            for definition in self.list_definitions()
        ]
        return [google_types.Tool(function_declarations=function_declarations)]

    @staticmethod
    def _build_mcp_callable(definition: ToolDefinition, services):
        properties = definition.json_schema.get("properties", {}) or {}
        required = set(definition.json_schema.get("required", []) or [])

        def wrapper(**kwargs):
            return definition.handler(services, **kwargs)

        wrapper.__name__ = definition.name
        wrapper.__doc__ = definition.description

        parameters = []
        annotations = {"return": dict}
        for property_name, property_schema in properties.items():
            annotation = _annotation_from_schema(property_schema)
            annotations[property_name] = annotation
            default = inspect.Parameter.empty if property_name in required else None
            parameters.append(
                inspect.Parameter(
                    property_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=annotation,
                )
            )

        wrapper.__annotations__ = annotations
        wrapper.__signature__ = inspect.Signature(parameters, return_annotation=dict)
        return wrapper


def build_tool_registry() -> ToolRegistry:
    from .context_tools import build_context_tools
    from .element_tools import build_element_tools
    from .memory_tools import build_memory_tools
    from .view_tools import build_view_tools
    from .planning_tools import build_planning_tools

    definitions = []
    definitions.extend(build_context_tools())
    definitions.extend(build_memory_tools())
    definitions.extend(build_view_tools())
    definitions.extend(build_element_tools())
    definitions.extend(build_planning_tools())
    return ToolRegistry(definitions)
