"""Behavior checks for the web workspace; no live Revit or provider calls."""
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from RevitMCP_ExternalServer.providers.types import ProviderResult
from RevitMCP_ExternalServer.web.chat_service import run_chat_request
from RevitMCP_ExternalServer.web.routes import register_routes


class ContextRouteTests(unittest.TestCase):
    def client_for(self, result):
        app = Flask(__name__)
        services = SimpleNamespace(revit_client=SimpleNamespace(call_listener=Mock(return_value=result)))
        register_routes(app, services, Mock())
        return app.test_client(), services.revit_client.call_listener

    def test_context_excludes_file_paths_and_requests_no_write_check(self):
        client, listener = self.client_for({
            "status": "success",
            "document_state": {"title": "Office", "path": "private-path.rvt"},
            "active_view": {"name": "Level 2"},
            "selection": {"selected_count": 4, "element_ids": [1, 2, 3, 4]},
        })
        response = client.get("/revit_context")
        self.assertEqual(response.json, {
            "status": "connected", "document_name": "Office", "view_name": "Level 2", "selection_count": 4,
        })
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(listener.call_args.kwargs["payload_data"], {"check_write_context": False, "selection_limit": 0})

    def test_missing_document_is_distinct_from_disconnected_revit(self):
        client, _ = self.client_for({"status": "success", "document_state": {}, "selection": None})
        self.assertEqual(client.get("/revit_context").json["status"], "connected")
        client, _ = self.client_for({"status": "error", "message": "Internal traceback"})
        payload = client.get("/revit_context").json
        self.assertEqual(payload["status"], "disconnected")
        self.assertNotIn("traceback", payload["message"])


class ChatActivityTests(unittest.TestCase):
    def run_chat(self, tool_result, provider_result):
        services = SimpleNamespace(
            logger=logging.getLogger("web-tests"), memory_store=None,
            config=SimpleNamespace(max_tool_iterations=5),
        )
        registry = Mock()
        registry.dispatch.return_value = tool_result
        registry.list_definitions.return_value = []
        registry.to_openai_tools.return_value = []

        def provider(**kwargs):
            kwargs["execute_tool_call"]("get_active_selection", {"private": "never-in-activity"})
            return provider_result

        with patch("RevitMCP_ExternalServer.web.chat_service.run_openai_chat", side_effect=provider):
            return run_chat_request(services, registry, {
                "conversation": [{"role": "user", "content": "Inspect selection"}],
                "provider": "openai", "model": "test", "apiKey": "not-a-real-key",
            })

    def test_activity_is_returned_without_tool_arguments(self):
        payload, code = self.run_chat({"status": "success", "message": "4 elements"}, ProviderResult(reply="Done"))
        self.assertEqual(code, 200)
        self.assertEqual(payload["tool_calls"], [{"name": "get_active_selection", "status": "success", "message": "4 elements"}])
        self.assertNotIn("never-in-activity", str(payload))

    def test_activity_survives_provider_failure_after_a_tool_ran(self):
        payload, code = self.run_chat({"final_status": "partial", "summary": "One step failed"}, ProviderResult(reply="", error_detail="Provider disconnected"))
        self.assertEqual(code, 500)
        self.assertEqual(payload["tool_calls"][0]["status"], "partial")
        self.assertEqual(payload["error"], "Provider disconnected")

    def test_view_image_is_attached_without_a_local_path(self):
        with patch("RevitMCP_ExternalServer.web.chat_service.load_image_artifact", return_value={"mime_type": "image/png", "base64_data": "dGVzdA==", "path": "private"}):
            payload, code = self.run_chat({"status": "success"}, ProviderResult(reply="View"))
        self.assertEqual(code, 200)
        self.assertEqual(payload["images"], [{"mime_type": "image/png", "base64_data": "dGVzdA=="}])


if __name__ == "__main__":
    unittest.main()
