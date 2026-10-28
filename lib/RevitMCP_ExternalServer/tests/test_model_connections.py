"""Exercise API routing and tool continuation through the real SDK, without network."""
import json
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import openai

from RevitMCP_ExternalServer.web.chat_service import run_chat_request


class ModelConnectionTests(unittest.TestCase):
    def run_request(self, handler, provider="openrouter", model="google/gemini-4-argon", api_key="test-private-key"):
        services = SimpleNamespace(logger=logging.getLogger("connection-tests"), memory_store=None,
                                   config=SimpleNamespace(max_tool_iterations=5))
        registry = Mock()
        registry.list_definitions.return_value = []
        registry.to_openai_tools.return_value = [{
            "type": "function", "function": {"name": "get_selection", "description": "Read selection",
                                               "parameters": {"type": "object", "properties": {}}},
        }]
        registry.dispatch.return_value = {"status": "success", "message": "Two elements selected"}
        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            def factory(**kwargs):
                return openai.OpenAI(http_client=http_client, max_retries=0, **kwargs)

            result = run_chat_request(services, registry, {
                "conversation": [{"role": "user", "content": "Inspect selection"}],
                "provider": provider, "model": model, "apiKey": api_key,
            }, openai_client_factory=factory)
        return result, registry

    @staticmethod
    def completion(message, finish_reason="stop"):
        return httpx.Response(200, json={
            "id": "test-completion", "object": "chat.completion", "created": 0,
            "model": "test-model", "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        })

    def test_openrouter_preserves_reasoning_and_tool_signatures(self):
        requests = []
        reasoning = [{"type": "reasoning.encrypted", "data": "opaque-state", "format": "google-gemini-v1"}]
        signature = {"google": {"thought_signature": "opaque-signature"}}

        def handler(request):
            requests.append((request, json.loads(request.content)))
            if len(requests) == 1:
                return self.completion({
                    "role": "assistant", "content": None, "reasoning_details": reasoning,
                    "tool_calls": [{"id": "call-1", "type": "function", "extra_content": signature,
                                    "function": {"name": "get_selection", "arguments": "{}"}}],
                }, "tool_calls")
            return self.completion({"role": "assistant", "content": "Two elements are selected."})

        (payload, status), registry = self.run_request(handler)
        self.assertEqual(status, 200)
        self.assertEqual(len(requests), 2)
        for request, body in requests:
            self.assertEqual(str(request.url), "https://openrouter.ai/api/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer test-private-key")
            self.assertEqual(body["model"], "google/gemini-4-argon")
            self.assertEqual(body["provider"], {"require_parameters": True})
        messages = requests[1][1]["messages"]
        self.assertEqual(messages[2]["reasoning_details"], reasoning)
        self.assertEqual(messages[2]["tool_calls"][0]["extra_content"], signature)
        self.assertEqual(messages[3]["tool_call_id"], "call-1")
        registry.dispatch.assert_called_once()
        self.assertNotIn("test-private-key", json.dumps(payload))
        self.assertEqual(payload["tool_calls"][0]["name"], "get_selection")

    def test_direct_xai_uses_only_its_endpoint_and_model_id(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://api.x.ai/v1/chat/completions")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "grok-4.7")
            self.assertNotIn("provider", body)
            return self.completion({"role": "assistant", "content": "Ready"})

        (payload, status), _ = self.run_request(handler, provider="xai", model="grok-4.7")
        self.assertEqual((status, payload["reply"]), (200, "Ready"))

    def test_direct_google_uses_compatibility_endpoint(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "gemini-4-argon")
            self.assertNotIn("provider", body)
            return self.completion({"role": "assistant", "content": "Ready"})

        (payload, status), _ = self.run_request(handler, provider="google", model="gemini-4-argon")
        self.assertEqual((status, payload["reply"]), (200, "Ready"))

    def test_direct_gpt6_uses_responses_with_stateless_tool_continuation(self):
        for model in ("gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-astra"):
            with self.subTest(model=model):
                bodies = []

                def handler(request):
                    self.assertEqual(request.url.path, "/v1/responses")
                    bodies.append(json.loads(request.content))
                    if len(bodies) == 1:
                        output = [
                            {"id": "reasoning-1", "type": "reasoning", "summary": [], "encrypted_content": "opaque-reasoning"},
                            {"id": "function-1", "type": "function_call", "call_id": "call-1", "name": "get_selection", "arguments": "{}"},
                        ]
                    else:
                        output = [{"id": "message-1", "type": "message", "role": "assistant", "status": "completed",
                                   "content": [{"type": "output_text", "text": "Two elements are selected.", "annotations": []}]}]
                    return httpx.Response(200, json={"id": "response-1", "object": "response", "created_at": 0,
                                                    "model": model, "status": "completed", "output": output})

                (payload, status), registry = self.run_request(handler, provider="openai", model=model)
                self.assertEqual(status, 200)
                self.assertEqual(payload["reply"], "Two elements are selected.")
                self.assertEqual(len(bodies), 2)
                self.assertFalse(bodies[0]["store"])
                self.assertEqual(bodies[0]["model"], model)
                self.assertEqual(bodies[0]["tools"][0]["name"], "get_selection")
                self.assertFalse(bodies[0]["tools"][0]["strict"])
                self.assertEqual(bodies[1]["input"][1]["encrypted_content"], "opaque-reasoning")
                self.assertEqual(bodies[1]["input"][-1]["type"], "function_call_output")
                self.assertEqual(bodies[1]["input"][-1]["call_id"], "call-1")
                registry.dispatch.assert_called_once()

    def test_authentication_error_names_openrouter_and_redacts_key(self):
        def handler(_request):
            return httpx.Response(401, json={"error": {
                "message": "Invalid key: test-private-key", "type": "authentication_error", "code": 401,
            }})

        (payload, status), registry = self.run_request(handler)
        self.assertEqual(status, 500)
        self.assertIn("OpenRouter Authentication Error", payload["error"])
        self.assertNotIn("test-private-key", json.dumps(payload))
        registry.dispatch.assert_not_called()

    def test_missing_key_does_not_fall_back_to_environment_credentials(self):
        for provider in ("openrouter", "xai", "google"):
            with self.subTest(provider=provider):
                handler = Mock(side_effect=AssertionError("No API call should be made"))
                (payload, status), registry = self.run_request(handler, provider=provider, api_key=None)
                self.assertEqual(status, 400)
                self.assertIn("Settings", payload["error"])
                handler.assert_not_called()
                registry.dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
