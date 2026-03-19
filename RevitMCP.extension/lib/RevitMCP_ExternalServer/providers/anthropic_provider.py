import json

import anthropic

from .types import ProviderResult


def run_anthropic_chat(
    conversation_history,
    system_prompt: str,
    model_id: str,
    api_key: str,
    tool_specs,
    execute_tool_call,
    logger,
    max_tool_iterations: int = 5,
    client_factory=None,
) -> ProviderResult:
    model_reply_text = ""

    try:
        client = client_factory(api_key=api_key) if client_factory else anthropic.Anthropic(api_key=api_key)
        messages_for_llm = [
            {"role": "assistant" if message["role"] == "bot" else message["role"], "content": message["content"]}
            for message in conversation_history
        ]

        iteration = 0
        while iteration < max_tool_iterations:
            iteration += 1
            logger.debug("Anthropic (iteration %s): Sending messages: %s", iteration, messages_for_llm)
            response = client.messages.create(
                model=model_id,
                max_tokens=3000,
                system=system_prompt,
                messages=messages_for_llm,
                tools=tool_specs,
                tool_choice={"type": "auto"},
            )
            messages_for_llm.append({"role": "assistant", "content": response.content})

            tool_results_for_turn = []
            for response_block in response.content:
                if getattr(response_block, "type", None) == "tool_use":
                    tool_name = response_block.name
                    function_args = response_block.input if isinstance(response_block.input, dict) else {}
                    logger.info("Anthropic: Tool use requested: %s, Input: %s", tool_name, function_args)
                    tool_result_data = execute_tool_call(tool_name, function_args)
                    tool_results_for_turn.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": response_block.id,
                            "content": json.dumps(tool_result_data),
                        }
                    )

            if tool_results_for_turn:
                messages_for_llm.append({"role": "user", "content": tool_results_for_turn})
                continue

            text_parts = [
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text" and getattr(block, "text", None)
            ]
            if text_parts:
                model_reply_text = "".join(text_parts)
            else:
                model_reply_text = "Anthropic model responded without text content after tool execution."
            return ProviderResult(reply=model_reply_text)

        logger.warning("Anthropic: Reached tool iteration limit without final response.")
        return ProviderResult(reply="Reached tool execution limit without a final response.")
    except anthropic.APIConnectionError as error:
        return ProviderResult(reply=model_reply_text, error_detail=f"Anthropic Connection Error: {error}. Please check network or API key.")
    except anthropic.AuthenticationError as error:
        return ProviderResult(reply=model_reply_text, error_detail=f"Anthropic Authentication Error: {error}. Invalid API Key?")
    except anthropic.RateLimitError as error:
        return ProviderResult(reply=model_reply_text, error_detail=f"Anthropic Rate Limit Error: {error}. Please try again later.")
    except anthropic.APIError as error:
        status = error.status_code if hasattr(error, "status_code") else "N/A"
        return ProviderResult(reply=model_reply_text, error_detail=f"Anthropic API Error: {error} (Status: {status}).")

