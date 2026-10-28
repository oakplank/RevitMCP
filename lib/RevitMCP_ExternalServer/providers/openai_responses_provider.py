"""Direct OpenAI tool calling for GPT-6 models, which require Responses."""
import json

import openai

from .types import ProviderResult


def run_openai_responses_chat(
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
    try:
        client = (client_factory or openai.OpenAI)(api_key=api_key)
        inputs = [
            {"role": "assistant" if message["role"] == "bot" else message["role"], "content": message["content"]}
            for message in conversation_history
        ]
        # Responses uses flat function definitions. Preserve the registry's optional arguments.
        tools = [{"type": "function", **tool["function"], "strict": False} for tool in tool_specs]
        for _iteration in range(max_tool_iterations):
            response = client.responses.create(
                model=model_id, instructions=system_prompt, input=inputs, tools=tools,
                store=False, include=["reasoning.encrypted_content"],
            )
            # Retain encrypted reasoning and call IDs for stateless tool continuation.
            inputs.extend(response.output)
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                return ProviderResult(reply=response.output_text or "")
            for call in calls:
                try:
                    arguments = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    result = {"status": "error", "message": "Invalid arguments from LLM for tool {}.".format(call.name)}
                else:
                    result = execute_tool_call(call.name, arguments)
                inputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)})
        logger.warning("OpenAI: Reached tool iteration limit without final response.")
        return ProviderResult(reply="Reached tool execution limit without a final response.")
    except openai.APIConnectionError as error:
        return ProviderResult(reply="", error_detail=f"OpenAI Connection Error: {error}. Please check your connection.")
    except openai.AuthenticationError as error:
        return ProviderResult(reply="", error_detail=f"OpenAI Authentication Error: {error}. Check your API key in Settings.")
    except openai.RateLimitError as error:
        return ProviderResult(reply="", error_detail=f"OpenAI Rate Limit Error: {error}. Please try again later.")
    except openai.APIError as error:
        return ProviderResult(reply="", error_detail=f"OpenAI API Error: {error}.")
