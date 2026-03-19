import re

from RevitMCP_ExternalServer.tools.context_tools import resolve_revit_targets_internal
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


PLANNER_TOOL_NAME = "plan_and_execute_workflow"


def _tool_params_summary(tool_schema: dict) -> str:
    properties = list((tool_schema.get("properties") or {}).keys())
    if not properties:
        return "no params"
    return "params: {}".format(", ".join(properties))


def build_planning_system_prompt(tool_registry) -> str:
    tool_lines = []
    for definition in tool_registry.list_definitions():
        if definition.name == PLANNER_TOOL_NAME:
            continue
        tool_lines.append("- {}: {}".format(definition.name, _tool_params_summary(definition.json_schema)))

    return """You are a Revit automation assistant with planning capabilities.

PLANNING APPROACH:
For complex requests, use the plan_and_execute_workflow tool which allows you to:
1. Analyze the user request
2. Plan a sequence of steps using available tools
3. Execute all steps in one operation
4. Return complete results

AVAILABLE TOOLS FOR PLANNING:
{tool_lines}

EXECUTION PLAN FORMAT:
[
  {{
    "tool": "filter_elements",
    "params": {{"category_name": "Windows", "level_name": "L5", "parameters": [{{"name": "Sill Height", "value": "2' 3\\"", "condition": "equals"}}]}},
    "description": "Find windows on L5 with sill height 2'3\\""
  }},
  {{
    "tool": "update_element_parameters",
    "params": {{"result_handle": "${{step_1_result_handle}}", "parameter_name": "Sill Height", "new_value": "2' 6\\""}},
    "description": "Update sill height to 2'6\\""
  }}
]

WORKFLOW EXAMPLES:
- Parameter updates: filter_elements -> update_element_parameters -> select_stored_elements
- Property inspection: get_elements_by_category -> filter_stored_elements_by_parameter -> get_element_properties
- Element discovery: get_elements_by_category -> filter_stored_elements_by_parameter -> select_stored_elements
- Naming audit: analyze_view_naming_patterns -> suggest_view_name_corrections

IMPORTANT:
- Always resolve terms with resolve_revit_targets before filter_elements or update_element_parameters.
- For large sets, prefer filter_stored_elements_by_parameter before get_element_properties.
- Do not use raw user category or level names directly.

Use plan_and_execute_workflow for multi-step operations to provide complete results in one response.""".format(
        tool_lines="\n".join(tool_lines)
    )


def _substitute_placeholders(obj, workflow_results: dict, logger):
    if isinstance(obj, str):
        pattern = r"\$\{step_(\d+)_([^}]+)\}"

        def replace_placeholder(match):
            step_number = int(match.group(1))
            key = match.group(2)
            placeholder_key = f"step_{step_number}_{key}"
            if placeholder_key in workflow_results:
                value = workflow_results[placeholder_key]
                if obj.strip() == match.group(0):
                    return value
                return str(value)
            logger.warning("Placeholder %s not found in workflow results", placeholder_key)
            return match.group(0)

        full_match = re.fullmatch(pattern, obj.strip())
        if full_match:
            step_number = int(full_match.group(1))
            key = full_match.group(2)
            placeholder_key = f"step_{step_number}_{key}"
            if placeholder_key in workflow_results:
                return workflow_results[placeholder_key]

        return re.sub(pattern, replace_placeholder, obj)

    if isinstance(obj, dict):
        return {key: _substitute_placeholders(value, workflow_results, logger) for key, value in obj.items()}

    if isinstance(obj, list):
        return [_substitute_placeholders(item, workflow_results, logger) for item in obj]

    return obj


def plan_and_execute_workflow_handler(services, user_request: str, execution_plan: list[dict], **_kwargs) -> dict:
    services.logger.info(
        "MCP Tool executed: %s - Executing %s planned steps",
        PLANNER_TOOL_NAME,
        len(execution_plan),
    )

    workflow_results = {
        "user_request": user_request,
        "planned_steps": len(execution_plan),
        "executed_steps": [],
        "step_results": [],
        "final_status": "success",
        "summary": "",
    }

    try:
        for index, step in enumerate(execution_plan, 1):
            step_info = {
                "step_number": index,
                "tool": step.get("tool"),
                "description": step.get("description", ""),
                "status": "pending",
            }

            tool_name = step.get("tool")
            tool_params = (step.get("params", {}) or {}).copy()
            tool_params = _substitute_placeholders(tool_params, workflow_results, services.logger)

            if tool_name in ["filter_elements", "update_element_parameters", "filter_stored_elements_by_parameter"]:
                resolver_input = {}
                if tool_name == "filter_elements":
                    resolver_input["category_name"] = tool_params.get("category_name")
                    resolver_input["level_name"] = tool_params.get("level_name")
                    resolver_input["parameter_names"] = [
                        parameter.get("name")
                        for parameter in (tool_params.get("parameters", []) or [])
                        if isinstance(parameter, dict) and parameter.get("name")
                    ]
                elif tool_name == "filter_stored_elements_by_parameter":
                    resolver_input["parameter_names"] = [tool_params.get("parameter_name")]
                elif tool_name == "update_element_parameters":
                    parameter_candidates = []
                    if tool_params.get("parameter_name"):
                        parameter_candidates.append(tool_params.get("parameter_name"))
                    if isinstance(tool_params.get("updates"), list):
                        for update in tool_params.get("updates"):
                            if isinstance(update, dict) and isinstance(update.get("parameters"), dict):
                                parameter_candidates.extend(list(update.get("parameters").keys()))
                    resolver_input["parameter_names"] = list(set(parameter_candidates))

                resolution = resolve_revit_targets_internal(services, resolver_input)
                step_info["resolution"] = resolution
                if resolution.get("status") == "error":
                    step_info["status"] = "error"
                    step_info["error"] = "Target resolution failed before executing '{}'".format(tool_name)
                    step_info["result"] = resolution
                    workflow_results["executed_steps"].append(step_info)
                    workflow_results["step_results"].append(step_info["result"])
                    continue

                resolved_payload = resolution.get("resolved", {})
                if tool_name == "filter_elements":
                    if resolved_payload.get("category_name"):
                        tool_params["category_name"] = resolved_payload["category_name"]
                    if resolved_payload.get("level_name"):
                        tool_params["level_name"] = resolved_payload["level_name"]
                    param_map = resolved_payload.get("parameter_names", {})
                    if param_map and isinstance(tool_params.get("parameters"), list):
                        for parameter in tool_params["parameters"]:
                            if isinstance(parameter, dict) and parameter.get("name") in param_map:
                                mapped = param_map[parameter["name"]]
                                confidence = float(mapped.get("confidence", 0.0))
                                if confidence >= services.config.min_confidence_for_parameter_remap:
                                    parameter["name"] = mapped.get("resolved_name", parameter["name"])
                elif tool_name == "filter_stored_elements_by_parameter":
                    param_map = resolved_payload.get("parameter_names", {})
                    current_param = tool_params.get("parameter_name")
                    if current_param in param_map:
                        mapped = param_map[current_param]
                        confidence = float(mapped.get("confidence", 0.0))
                        if confidence >= services.config.min_confidence_for_parameter_remap:
                            tool_params["parameter_name"] = mapped.get("resolved_name", current_param)
                elif tool_name == "update_element_parameters":
                    param_map = resolved_payload.get("parameter_names", {})
                    if tool_params.get("parameter_name") in param_map:
                        mapped = param_map[tool_params["parameter_name"]]
                        confidence = float(mapped.get("confidence", 0.0))
                        if confidence >= services.config.min_confidence_for_parameter_remap:
                            tool_params["parameter_name"] = mapped.get("resolved_name", tool_params["parameter_name"])
                    if isinstance(tool_params.get("updates"), list):
                        for update in tool_params["updates"]:
                            if isinstance(update, dict) and isinstance(update.get("parameters"), dict):
                                new_params = {}
                                for key, value in update["parameters"].items():
                                    if key in param_map:
                                        mapped = param_map[key]
                                        confidence = float(mapped.get("confidence", 0.0))
                                        if confidence >= services.config.min_confidence_for_parameter_remap:
                                            new_params[mapped.get("resolved_name", key)] = value
                                        else:
                                            new_params[key] = value
                                    else:
                                        new_params[key] = value
                                update["parameters"] = new_params

            services.logger.info("Executing step %s: %s - %s", index, tool_name, step.get("description", ""))
            services.logger.debug("Step %s parameters after substitution: %s", index, tool_params)

            if tool_name == PLANNER_TOOL_NAME:
                step_info["status"] = "error"
                step_info["error"] = "Recursive planner calls are not supported."
                step_info["result"] = {"error": "Tool '{}' not available".format(tool_name)}
            elif not services.tool_registry.get(tool_name):
                step_info["status"] = "error"
                step_info["error"] = "Unknown tool: {}".format(tool_name)
                step_info["result"] = {"error": "Tool '{}' not available".format(tool_name)}
            else:
                result = services.tool_registry.dispatch(services, tool_name, tool_params)
                step_info["result"] = result

                result_status = ""
                if isinstance(result, dict):
                    result_status = str(result.get("status", "")).lower()

                if result_status in ["error", "failed", "limit_exceeded"]:
                    step_info["status"] = "error"
                    if isinstance(result, dict) and "message" in result:
                        step_info["error"] = result.get("message")
                else:
                    step_info["status"] = "completed"

                if isinstance(result, dict) and "result_handle" in result:
                    workflow_results[f"step_{index}_result_handle"] = result["result_handle"]
                if isinstance(result, dict) and "element_ids" in result:
                    workflow_results[f"step_{index}_element_ids"] = result["element_ids"]
                if isinstance(result, dict) and "element_ids_sample" in result:
                    workflow_results[f"step_{index}_element_ids_sample"] = result["element_ids_sample"]
                if isinstance(result, dict) and "count" in result:
                    workflow_results[f"step_{index}_count"] = result["count"]
                if isinstance(result, dict) and "elements" in result:
                    workflow_results[f"step_{index}_elements"] = result["elements"]

            workflow_results["executed_steps"].append(step_info)
            workflow_results["step_results"].append(step_info["result"])

        successful_steps = len([step for step in workflow_results["executed_steps"] if step["status"] == "completed"])
        failed_steps = len([step for step in workflow_results["executed_steps"] if step["status"] == "error"])

        if failed_steps == 0:
            workflow_results["final_status"] = "success"
            workflow_results["summary"] = "Successfully completed all {} planned steps".format(successful_steps)
        elif successful_steps > 0:
            workflow_results["final_status"] = "partial"
            workflow_results["summary"] = "Completed {} steps, {} steps failed".format(successful_steps, failed_steps)
        else:
            workflow_results["final_status"] = "failed"
            workflow_results["summary"] = "All {} steps failed".format(failed_steps)

        services.logger.info("Workflow completed: %s", workflow_results["summary"])
        return workflow_results

    except Exception as error:
        workflow_results["final_status"] = "error"
        workflow_results["error"] = str(error)
        workflow_results["summary"] = "Workflow execution failed: {}".format(error)
        services.logger.error("Workflow execution error: %s", error, exc_info=True)
        return workflow_results


def build_planning_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=PLANNER_TOOL_NAME,
            description=(
                "Executes a sequence of tools based on a planned workflow. The LLM should first analyze the user "
                "request, then provide a step-by-step execution plan."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "user_request": {"type": "string", "description": "The original user request"},
                    "execution_plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string", "description": "The tool to execute"},
                                "params": {"type": "object", "description": "Parameters for the tool"},
                                "description": {"type": "string", "description": "What this step accomplishes"},
                            },
                            "required": ["tool", "params"],
                        },
                        "description": "List of planned steps",
                    },
                },
                "required": ["user_request", "execution_plan"],
            },
            handler=plan_and_execute_workflow_handler,
        )
    ]
