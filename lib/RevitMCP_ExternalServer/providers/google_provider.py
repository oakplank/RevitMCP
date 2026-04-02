import google.generativeai as genai
from google.generativeai import types as google_types

from .types import ProviderResult


def run_google_chat(
    conversation_history,
    system_prompt: str,
    model_id: str,
    api_key: str,
    tool_specs,
    execute_tool_call,
    logger,
    max_tool_iterations: int = 5,
    genai_module=None,
    types_module=None,
) -> ProviderResult:
    model_reply_text = ""
    genai_module = genai_module or genai
    types_module = types_module or google_types

    try:
        genai_module.configure(api_key=api_key)
        gemini_tool_config = types_module.ToolConfig(
            function_calling_config=types_module.FunctionCallingConfig(
                mode=types_module.FunctionCallingConfig.Mode.AUTO
            )
        )
        model = genai_module.GenerativeModel(
            model_id,
            tools=tool_specs,
            tool_config=gemini_tool_config,
            system_instruction=system_prompt,
        )

        gemini_history_for_chat = []
        for message in conversation_history:
            role = "user" if message["role"] == "user" else "model"
            gemini_history_for_chat.append({"role": role, "parts": [types_module.Part(text=message["content"])]})

        if gemini_history_for_chat:
            current_user_prompt_parts = gemini_history_for_chat.pop()["parts"]
        else:
            current_user_prompt_parts = [types_module.Part(text=conversation_history[-1]["content"])]

        chat_session = model.start_chat(history=gemini_history_for_chat)
        logger.debug(
            "Google: Sending prompt parts: %s with history count: %s",
            current_user_prompt_parts,
            len(chat_session.history),
        )

        gemini_response = chat_session.send_message(current_user_prompt_parts)
        for iteration in range(1, max_tool_iterations + 1):
            candidate = gemini_response.candidates[0]
            function_part = next(
                (part for part in candidate.content.parts if getattr(part, "function_call", None)),
                None,
            )

            if function_part:
                function_name = function_part.function_call.name
                function_args = dict(function_part.function_call.args)
                logger.info("Google: Function call requested: %s with args %s", function_name, function_args)
                tool_result_data = execute_tool_call(function_name, function_args)
                function_response_part = types_module.Part(
                    function_response=types_module.FunctionResponse(
                        name=function_name,
                        response=tool_result_data,
                    )
                )
                logger.debug("Google: Resending with tool response for iteration %s.", iteration)
                gemini_response = chat_session.send_message([function_response_part])
                continue

            text_output = "".join(part.text for part in candidate.content.parts if getattr(part, "text", None))
            model_reply_text = text_output or getattr(gemini_response, "text", "")
            return ProviderResult(reply=model_reply_text)

        logger.warning("Google: Reached tool iteration limit without final response.")
        return ProviderResult(reply="Reached tool execution limit without a final response.")
    except Exception as error:
        return ProviderResult(reply=model_reply_text, error_detail=f"Google API Error: {error}")
