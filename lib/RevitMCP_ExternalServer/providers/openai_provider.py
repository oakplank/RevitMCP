import json

import openai

from .types import ProviderResult


def run_openai_chat(
    conversation_history,
    system_prompt: str,
    model_id: str,
    api_key: str,
    tool_specs,
    execute_tool_call,
    logger,
    max_tool_iterations: int = 5,
    client_factory=None,
    base_url=None,
    provider_name="OpenAI",
    extra_body=None,
) -> ProviderResult:
    model_reply_text = ""

    try:
        client_options = {"api_key": api_key}
        if base_url:
            client_options["base_url"] = base_url
        client = (client_factory or openai.OpenAI)(**client_options)
        request_options = {"extra_body": extra_body} if extra_body else {}
        messages_for_llm = [{"role": "system", "content": system_prompt}] + [
            {"role": "assistant" if message["role"] == "bot" else message["role"], "content": message["content"]}
            for message in conversation_history
        ]

        iteration = 0
        while iteration < max_tool_iterations:
            iteration += 1
            logger.debug("%s (iteration %s): Sending messages: %s", provider_name, iteration, messages_for_llm)
            completion = client.chat.completions.create(
                model=model_id,
                messages=messages_for_llm,
                tools=tool_specs,
                tool_choice="auto",
                **request_options,
            )
            response_message = completion.choices[0].message
            # Keep provider extensions such as reasoning_details and thought signatures
            # intact when sending tool results back to a reasoning model.
            messages_for_llm.append(response_message)
            tool_calls = response_message.tool_calls or []

            if tool_calls:
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        raw_arguments = tool_call.function.arguments or "{}"
                        function_args = json.loads(raw_arguments)
                    except json.JSONDecodeError as error:
                        logger.error(
                            "%s: Failed to parse function arguments for %s: %s. Error: %s",
                            provider_name,
                            function_name,
                            tool_call.function.arguments,
                            error,
                        )
                        tool_result_data = {
                            "status": "error",
                            "message": "Invalid arguments from LLM for tool {}.".format(function_name),
                        }
                    else:
                        tool_result_data = execute_tool_call(function_name, function_args)

                    messages_for_llm.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps(tool_result_data),
                        }
                    )
                continue

            model_reply_text = response_message.content or ""
            return ProviderResult(reply=model_reply_text)

        logger.warning("%s: Reached tool iteration limit without final response.", provider_name)
        return ProviderResult(reply="Reached tool execution limit without a final response.")
    except openai.APIConnectionError as error:
        return ProviderResult(reply=model_reply_text, error_detail=f"{provider_name} Connection Error: {error}. Please check network or API key.")
    except openai.AuthenticationError as error:
        return ProviderResult(reply=model_reply_text, error_detail=f"{provider_name} Authentication Error: {error}. Invalid API Key?")
    except openai.RateLimitError as error:
        return ProviderResult(reply=model_reply_text, error_detail=f"{provider_name} Rate Limit Error: {error}. Please try again later.")
    except openai.APIError as error:
        status = error.status_code if hasattr(error, "status_code") else "N/A"
        return ProviderResult(reply=model_reply_text, error_detail=f"{provider_name} API Error: {error} (Status: {status}).")

