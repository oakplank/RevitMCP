from RevitMCP_ExternalServer.providers.anthropic_provider import run_anthropic_chat
from RevitMCP_ExternalServer.providers.openai_provider import run_openai_chat
from RevitMCP_ExternalServer.providers.openai_responses_provider import run_openai_responses_chat
from RevitMCP_ExternalServer.providers.types import ProviderResult
from RevitMCP_ExternalServer.tools.planning_tools import build_planning_system_prompt
from RevitMCP_ExternalServer.core.image_artifacts import load_image_artifact


def _infer_provider_from_model_name(model_name: str) -> str:
    if model_name == "echo_model":
        return "echo"
    if "/" in model_name:
        return "openrouter"
    if model_name.startswith("grok-"):
        return "xai"
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
):
    data = request_data or {}
    conversation_history = data.get("conversation") or []
    last_user_message = conversation_history[-1]["content"] if conversation_history else ""
    api_key = data.get("apiKey")
    selected_model_ui_name = data.get("model") or ""
    selected_provider = data.get("provider") or _infer_provider_from_model_name(selected_model_ui_name)
    if selected_provider in ("openrouter", "xai", "google") and (not isinstance(api_key, str) or not api_key.strip()):
        provider_label = {"openrouter": "OpenRouter", "xai": "xAI", "google": "Google"}[selected_provider]
        return {"error": "Add your {} API key in Settings.".format(provider_label)}, 400
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

    tool_calls = []
    images = []

    def collect_image(result):
        if len(images) >= 3:
            return
        artifact = load_image_artifact(result, logger=services.logger)
        if artifact:
            images.append({"mime_type": artifact["mime_type"], "base64_data": artifact["base64_data"]})

    def execute_tool_call(tool_name, function_args):
        result = tool_registry.dispatch(services, tool_name, function_args)
        if isinstance(result, dict):
            tool_calls.append({
                "name": tool_name,
                "status": result.get("status") or result.get("final_status") or "finished",
                "message": str(result.get("message") or result.get("summary") or "")[:400],
            })
            collect_image(result)
            # Workflow results can contain view exports from individual steps.
            for step in result.get("executed_steps", []) or []:
                if isinstance(step, dict):
                    collect_image(step.get("result"))
        return result

    if selected_provider == "echo" or selected_model_ui_name == "echo_model":
        provider_result = ProviderResult(reply=f"Echo: {last_user_message}")
    elif selected_provider in ("openai", "openrouter", "xai", "google"):
        connection_options = {}
        if selected_provider == "openrouter":
            connection_options = {
                "base_url": "https://openrouter.ai/api/v1",
                "provider_name": "OpenRouter",
                "extra_body": {"provider": {"require_parameters": True}},
            }
        elif selected_provider == "xai":
            connection_options = {"base_url": "https://api.x.ai/v1", "provider_name": "xAI"}
        elif selected_provider == "google":
            connection_options = {
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "provider_name": "Google",
            }
        runner = run_openai_responses_chat if selected_provider == "openai" and selected_model_ui_name.startswith("gpt-6") else run_openai_chat
        provider_result = runner(
            conversation_history=conversation_history,
            system_prompt=planning_system_prompt,
            model_id=selected_model_ui_name,
            api_key=api_key,
            tool_specs=tool_registry.to_openai_tools(),
            execute_tool_call=execute_tool_call,
            logger=services.logger,
            max_tool_iterations=services.config.max_tool_iterations,
            client_factory=openai_client_factory,
            **connection_options,
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
    else:
        provider_result = ProviderResult(
            reply="",
            error_detail="Model '{}' with provider '{}' is not recognized or supported.".format(selected_model_ui_name, selected_provider or "unknown"),
        )

    response_payload = {"reply": provider_result.reply}
    if tool_calls:
        response_payload["tool_calls"] = tool_calls
    if images:
        response_payload["images"] = images
    error_detail = provider_result.error_detail
    if error_detail and isinstance(api_key, str) and api_key:
        error_detail = error_detail.replace(api_key, "[redacted]")
    if error_detail and not provider_result.reply:
        response_payload["error"] = error_detail
        return response_payload, 500
    if error_detail:
        response_payload["error_detail"] = error_detail
    return response_payload, 200
