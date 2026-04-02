from RevitMCP_ExternalServer.providers.anthropic_provider import run_anthropic_chat
from RevitMCP_ExternalServer.providers.google_provider import run_google_chat
from RevitMCP_ExternalServer.providers.openai_provider import run_openai_chat
from RevitMCP_ExternalServer.providers.types import ProviderResult
from RevitMCP_ExternalServer.tools.planning_tools import build_planning_system_prompt


def _infer_provider_from_model_name(model_name: str) -> str:
    if model_name == "echo_model":
        return "echo"
    if model_name.startswith("gpt-") or model_name.startswith("o"):
        return "openai"
    if model_name.startswith("claude-"):
        return "anthropic"
    if model_name.startswith("gemini-"):
        return "google"
    return ""


def run_chat_request(
    services,
    tool_registry,
    request_data: dict,
    openai_client_factory=None,
    anthropic_client_factory=None,
    genai_module=None,
    types_module=None,
):
    data = request_data or {}
    conversation_history = data.get("conversation") or []
    last_user_message = conversation_history[-1]["content"] if conversation_history else ""
    api_key = data.get("apiKey")
    selected_model_ui_name = data.get("model") or ""
    selected_provider = data.get("provider") or _infer_provider_from_model_name(selected_model_ui_name)
    project_context = services.memory_store.get_current_project_context(services) if getattr(services, "memory_store", None) else {}
    memory_context = (
        services.memory_store.build_prompt_context(
            query_text=last_user_message,
            scope="auto",
            project_context=project_context,
            max_notes=6,
        )
        if getattr(services, "memory_store", None)
        else ""
    )
    planning_system_prompt = build_planning_system_prompt(tool_registry, memory_context=memory_context)

    execute_tool_call = lambda tool_name, function_args: tool_registry.dispatch(services, tool_name, function_args)

    if selected_provider == "echo" or selected_model_ui_name == "echo_model":
        provider_result = ProviderResult(reply=f"Echo: {last_user_message}")
    elif selected_provider == "openai":
        provider_result = run_openai_chat(
            conversation_history=conversation_history,
            system_prompt=planning_system_prompt,
            model_id=selected_model_ui_name,
            api_key=api_key,
            tool_specs=tool_registry.to_openai_tools(),
            execute_tool_call=execute_tool_call,
            logger=services.logger,
            max_tool_iterations=services.config.max_tool_iterations,
            client_factory=openai_client_factory,
        )
    elif selected_provider == "anthropic":
        actual_model_id = services.config.anthropic_model_id_map.get(selected_model_ui_name, selected_model_ui_name)
        provider_result = run_anthropic_chat(
            conversation_history=conversation_history,
            system_prompt=planning_system_prompt,
            model_id=actual_model_id,
            api_key=api_key,
            tool_specs=tool_registry.to_anthropic_tools(),
            execute_tool_call=execute_tool_call,
            logger=services.logger,
            max_tool_iterations=services.config.max_tool_iterations,
            client_factory=anthropic_client_factory,
        )
    elif selected_provider == "google":
        provider_result = run_google_chat(
            conversation_history=conversation_history,
            system_prompt=planning_system_prompt,
            model_id=selected_model_ui_name,
            api_key=api_key,
            tool_specs=tool_registry.to_google_tools(),
            execute_tool_call=execute_tool_call,
            logger=services.logger,
            max_tool_iterations=services.config.max_tool_iterations,
            genai_module=genai_module,
            types_module=types_module,
        )
    else:
        provider_result = ProviderResult(
            reply="",
            error_detail="Model '{}' with provider '{}' is not recognized or supported.".format(selected_model_ui_name, selected_provider or "unknown"),
        )

    response_payload = {"reply": provider_result.reply}
    if provider_result.error_detail and not provider_result.reply:
        return {"error": provider_result.error_detail}, 500
    if provider_result.error_detail:
        response_payload["error_detail"] = provider_result.error_detail
    return response_payload, 200
