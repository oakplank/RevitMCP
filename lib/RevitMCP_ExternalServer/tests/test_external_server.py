import importlib
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

LIB_ROOT = Path(__file__).resolve().parents[2]
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))


def make_workspace_temp_file_path(prefix: str) -> str:
    base_dir = LIB_ROOT / "_tmp_testdata"
    base_dir.mkdir(exist_ok=True)
    return str(base_dir / "{}_{}.json".format(prefix, uuid.uuid4().hex))


def make_workspace_temp_png_path(prefix: str) -> str:
    base_dir = LIB_ROOT / "_tmp_testdata"
    base_dir.mkdir(exist_ok=True)
    return str(base_dir / "{}_{}.png".format(prefix, uuid.uuid4().hex))


def write_tiny_png(path: str) -> None:
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
        b"\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with open(path, "wb") as handle:
        handle.write(png_bytes)


from RevitMCP_ExternalServer.bootstrap import create_application
from RevitMCP_ExternalServer.core.memory_store import MemoryStore
from RevitMCP_ExternalServer.core.runtime_config import resolve_runtime_surface
from RevitMCP_ExternalServer.providers.anthropic_provider import run_anthropic_chat
from RevitMCP_ExternalServer.providers.google_provider import run_google_chat
from RevitMCP_ExternalServer.providers.openai_provider import run_openai_chat
from RevitMCP_ExternalServer.tools.context_tools import resolve_revit_targets_internal
from RevitMCP_ExternalServer.tools.element_tools import (
    filter_stored_elements_by_parameter_handler,
    get_element_properties_handler,
    get_revit_diagnostics_handler,
    select_elements_by_id_handler,
)
from RevitMCP_ExternalServer.tools.element_operation_tools import (
    delete_elements_handler,
    override_element_graphics_handler,
)
from RevitMCP_ExternalServer.tools.model_tools import analyze_model_statistics_handler
from RevitMCP_ExternalServer.tools.registry import ToolDefinition, ToolRegistry, build_tool_registry
from RevitMCP_ExternalServer.tools.view_tools import (
    activate_view_handler,
    duplicate_view_handler,
    export_active_view_image_handler,
)
from RevitMCP_ExternalServer.web.chat_service import run_chat_request
from routes.json_safety import sanitize_for_json


class BootstrapTests(unittest.TestCase):
    def test_server_import_smoke(self):
        module = importlib.import_module("RevitMCP_ExternalServer.server")
        self.assertTrue(callable(module.create_application))
        self.assertTrue(callable(module.main))

    def test_create_application_without_startup_network(self):
        with patch("RevitMCP_ExternalServer.core.revit_client.RevitClient.detect_port") as detect_port:
            app, mcp_server, services, registry = create_application(
                launch_background_tasks=False,
                detect_revit_on_startup=False,
            )
        detect_port.assert_not_called()
        self.assertEqual(mcp_server.name, "RevitMCPServer")
        self.assertIs(services.app, app)
        self.assertIs(services.tool_registry, registry)


class RegistryTests(unittest.TestCase):
    def test_registry_completeness_and_provider_specs(self):
        registry = build_tool_registry()
        definitions = registry.list_definitions()
        self.assertGreater(len(definitions), 0)

        for definition in definitions:
            self.assertTrue(definition.name)
            self.assertTrue(definition.description)
            self.assertIsInstance(definition.json_schema, dict)
            self.assertTrue(callable(definition.handler))

        openai_specs = registry.to_openai_tools()
        anthropic_specs = registry.to_anthropic_tools()
        google_specs = registry.to_google_tools()

        self.assertEqual(len(openai_specs), len(definitions))
        self.assertEqual(len(anthropic_specs), len(definitions))
        self.assertEqual(len(google_specs), 1)
        self.assertEqual(len(google_specs[0].function_declarations), len(definitions))

        definition_map = {definition.name: definition for definition in definitions}
        filter_parameters = definition_map["filter_elements"].json_schema["properties"]["parameters"]["items"]["properties"]
        stored_filter_schema = definition_map["filter_stored_elements_by_parameter"].json_schema
        filter_operator_enum = filter_parameters["operator"]["enum"]
        stored_operator_enum = stored_filter_schema["properties"]["operator"]["enum"]

        self.assertIn("greater_than", filter_operator_enum)
        self.assertIn("greater_than_or_equal", filter_operator_enum)
        self.assertIn("less_than_or_equal", filter_operator_enum)
        self.assertEqual(filter_operator_enum, stored_operator_enum)
        self.assertIn("values", stored_filter_schema["properties"])
        self.assertIn("match_mode", stored_filter_schema["properties"])
        self.assertEqual(stored_filter_schema["required"], ["parameter_name"])
        self.assertIn("offset", definition_map["get_element_properties"].json_schema["properties"])
        self.assertIn("limit", definition_map["get_element_properties"].json_schema["properties"])
        self.assertIn("get_revit_memory_context", definition_map)
        self.assertIn("save_revit_memory_note", definition_map)
        self.assertIn("get_revit_diagnostics", definition_map)
        self.assertIn("analyze_model_statistics", definition_map)
        self.assertIn("override_element_graphics", definition_map)
        self.assertIn("delete_elements", definition_map)
        self.assertIn("activate_view", definition_map)
        self.assertIn("export_active_view_image", definition_map)
        self.assertIn("duplicate_view", definition_map)

    def test_dispatch_known_and_unknown_tool(self):
        app, _mcp_server, services, registry = create_application(
            launch_background_tasks=False,
            detect_revit_on_startup=False,
        )
        known_result = registry.dispatch(services, "list_stored_elements", {})
        unknown_result = registry.dispatch(services, "not_a_tool", {})

        self.assertEqual(known_result["status"], "success")
        self.assertEqual(known_result["total_categories"], 0)
        self.assertEqual(unknown_result["status"], "error")
        self.assertIn("Unknown tool", unknown_result["message"])
        self.assertIsNotNone(app)

    def test_mcp_callable_returns_image_content_for_image_artifact(self):
        image_path = make_workspace_temp_png_path("mcp_artifact")
        write_tiny_png(image_path)

        def handler(_services, **_kwargs):
            return {
                "status": "success",
                "artifact_type": "image",
                "image_path": image_path,
                "mime_type": "image/png",
            }

        services = SimpleNamespace(
            logger=SimpleNamespace(warning=lambda *a, **k: None),
        )
        definition = ToolDefinition(
            name="image_tool",
            description="returns image",
            json_schema={"type": "object", "properties": {}},
            handler=handler,
        )

        try:
            wrapper = ToolRegistry._build_mcp_callable(definition, services)
            result = wrapper()
        finally:
            if os.path.exists(image_path):
                os.remove(image_path)

        self.assertEqual(len(result.content), 2)
        self.assertEqual(result.content[0].type, "text")
        self.assertEqual(result.content[1].type, "image")
        self.assertEqual(result.content[1].mimeType, "image/png")
        self.assertEqual(result.structuredContent["artifact_type"], "image")


class RouteJsonSafetyTests(unittest.TestCase):
    def test_sanitize_for_json_escapes_non_ascii_text_and_bytes(self):
        payload = {
            "views": [
                {"name": "Café Section", "sheet_name": b"Etage \xe9"},
            ]
        }

        sanitized = sanitize_for_json(payload)

        self.assertEqual(sanitized["views"][0]["name"], "Caf\\xe9 Section")
        self.assertEqual(sanitized["views"][0]["sheet_name"], "Etage \\xe9")


class ProviderTests(unittest.TestCase):
    def test_openai_provider_tool_loop(self):
        executed = []

        def execute_tool_call(name, args):
            executed.append((name, args))
            return {"status": "success", "message": "tool ok"}

        class FakeOpenAIClient:
            def __init__(self, **_kwargs):
                self.calls = 0
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def create(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    tool_call = SimpleNamespace(
                        id="tool-1",
                        function=SimpleNamespace(name="list_stored_elements", arguments="{}"),
                    )
                    message = SimpleNamespace(content=None, tool_calls=[tool_call])
                else:
                    message = SimpleNamespace(content="openai ok", tool_calls=[])
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        result = run_openai_chat(
            conversation_history=[{"role": "user", "content": "test"}],
            system_prompt="prompt",
            model_id="gpt-test",
            api_key="key",
            tool_specs=[],
            execute_tool_call=execute_tool_call,
            logger=SimpleNamespace(debug=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None),
            client_factory=FakeOpenAIClient,
        )

        self.assertEqual(result.reply, "openai ok")
        self.assertEqual(executed, [("list_stored_elements", {})])

    def test_anthropic_provider_tool_loop(self):
        executed = []

        def execute_tool_call(name, args):
            executed.append((name, args))
            return {"status": "success", "message": "tool ok"}

        class FakeAnthropicClient:
            def __init__(self, **_kwargs):
                self.calls = 0
                self.messages = SimpleNamespace(create=self.create)

            def create(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    content = [SimpleNamespace(type="tool_use", name="list_stored_elements", input={}, id="tool-1")]
                else:
                    content = [SimpleNamespace(type="text", text="anthropic ok")]
                return SimpleNamespace(content=content)

        result = run_anthropic_chat(
            conversation_history=[{"role": "user", "content": "test"}],
            system_prompt="prompt",
            model_id="claude-test",
            api_key="key",
            tool_specs=[],
            execute_tool_call=execute_tool_call,
            logger=SimpleNamespace(debug=lambda *a, **k: None, info=lambda *a, **k: None, warning=lambda *a, **k: None),
            client_factory=FakeAnthropicClient,
        )

        self.assertEqual(result.reply, "anthropic ok")
        self.assertEqual(executed, [("list_stored_elements", {})])

    def test_google_provider_tool_loop(self):
        executed = []

        def execute_tool_call(name, args):
            executed.append((name, args))
            return {"status": "success", "message": "tool ok"}

        class FakeGoogleResponse:
            def __init__(self, parts, text=""):
                self.candidates = [SimpleNamespace(content=SimpleNamespace(parts=parts))]
                self.text = text

        class FakeChatSession:
            def __init__(self):
                self.history = []
                self.calls = 0

            def send_message(self, _parts):
                self.calls += 1
                if self.calls == 1:
                    function_call = SimpleNamespace(name="list_stored_elements", args={})
                    return FakeGoogleResponse([SimpleNamespace(function_call=function_call)])
                return FakeGoogleResponse([SimpleNamespace(text="google ok")], text="google ok")

        class FakeGenerativeModel:
            def __init__(self, *_args, **_kwargs):
                pass

            def start_chat(self, history):
                session = FakeChatSession()
                session.history = history
                return session

        fake_genai_module = SimpleNamespace(
            configure=lambda **_kwargs: None,
            GenerativeModel=FakeGenerativeModel,
        )
        fake_types_module = SimpleNamespace(
            ToolConfig=lambda **kwargs: SimpleNamespace(**kwargs),
            FunctionCallingConfig=type(
                "FunctionCallingConfig",
                (),
                {
                    "Mode": SimpleNamespace(AUTO="AUTO"),
                    "__init__": lambda self, **kwargs: self.__dict__.update(kwargs),
                },
            ),
            Part=lambda **kwargs: SimpleNamespace(**kwargs),
            FunctionResponse=lambda **kwargs: SimpleNamespace(**kwargs),
        )

        result = run_google_chat(
            conversation_history=[{"role": "user", "content": "test"}],
            system_prompt="prompt",
            model_id="gemini-test",
            api_key="key",
            tool_specs=[],
            execute_tool_call=execute_tool_call,
            logger=SimpleNamespace(debug=lambda *a, **k: None, info=lambda *a, **k: None, warning=lambda *a, **k: None),
            genai_module=fake_genai_module,
            types_module=fake_types_module,
        )

        self.assertEqual(result.reply, "google ok")
        self.assertEqual(executed, [("list_stored_elements", {})])


class WebRouteTests(unittest.TestCase):
    def test_required_routes_registered(self):
        app, _mcp_server, _services, _registry = create_application(
            launch_background_tasks=False,
            detect_revit_on_startup=False,
        )
        registered_routes = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertIn("/", registered_routes)
        self.assertIn("/test_log", registered_routes)
        self.assertIn("/chat_api", registered_routes)
        self.assertIn("/send_revit_command", registered_routes)


class ChatServiceTests(unittest.TestCase):
    def test_explicit_provider_routes_custom_openai_model(self):
        app, _mcp_server, services, registry = create_application(
            launch_background_tasks=False,
            detect_revit_on_startup=False,
        )

        class FakeOpenAIClient:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def create(self, **_kwargs):
                message = SimpleNamespace(content="openai explicit ok", tool_calls=[])
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        response_payload, status_code = run_chat_request(
            services,
            registry,
            {
                "conversation": [{"role": "user", "content": "test"}],
                "model": "custom-openai-model",
                "provider": "openai",
                "apiKey": "key",
            },
            openai_client_factory=FakeOpenAIClient,
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_payload["reply"], "openai explicit ok")

    def test_unknown_provider_returns_error(self):
        app, _mcp_server, services, registry = create_application(
            launch_background_tasks=False,
            detect_revit_on_startup=False,
        )

        response_payload, status_code = run_chat_request(
            services,
            registry,
            {
                "conversation": [{"role": "user", "content": "test"}],
                "model": "custom-model",
                "provider": "not-real",
                "apiKey": "key",
            },
        )

        self.assertIsNotNone(app)
        self.assertEqual(status_code, 500)
        self.assertIn("provider 'not-real'", response_payload["error"])


class ViewToolTests(unittest.TestCase):
    def test_export_active_view_image_posts_capture_payload(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {
                    "status": "success",
                    "artifact_type": "image",
                    "image_path": "C:\\captures\\active_view.png",
                    "mime_type": "image/png",
                }

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            config=SimpleNamespace(capture_base_dir="C:\\captures"),
            revit_client=FakeRevitClient(),
        )

        result = export_active_view_image_handler(
            services,
            pixel_size=99999,
            format="jpeg",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(calls[0][0], "/views/active/export_image")
        self.assertEqual(calls[0][1], "POST")
        self.assertEqual(calls[0][2]["capture_dir"], "C:\\captures")
        self.assertEqual(calls[0][2]["pixel_size"], 4096)
        self.assertEqual(calls[0][2]["format"], "jpeg")

    def test_activate_view_posts_activate_route_payload(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {"status": "success", "active_view": {"id": payload_data["view_id"], "name": "Level 1"}}

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            revit_client=FakeRevitClient(),
        )

        result = activate_view_handler(
            services,
            view_id="100",
            view_name="Level",
            exact_match=True,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(calls[0][0], "/views/activate")
        self.assertEqual(calls[0][1], "POST")
        self.assertEqual(calls[0][2]["view_id"], "100")
        self.assertEqual(calls[0][2]["view_name"], "Level")
        self.assertTrue(calls[0][2]["exact_match"])

    def test_activate_view_requires_view_identifier_before_route_call(self):
        class FakeRevitClient:
            def call_listener(self, *_args, **_kwargs):
                raise AssertionError("route should not be called")

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            revit_client=FakeRevitClient(),
        )

        result = activate_view_handler(services)

        self.assertEqual(result["status"], "error")
        self.assertIn("view_id or view_name", result["message"])

    def test_duplicate_view_posts_duplicate_route_payload(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {"status": "success", "new_view": {"id": "200", "name": payload_data["new_name"]}}

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            revit_client=FakeRevitClient(),
        )

        result = duplicate_view_handler(
            services,
            view_id="100",
            duplicate_option="with_detailing",
            new_name="L4 Demo Copy",
            apply_template_id="300",
            activate=True,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(calls[0][0], "/views/duplicate")
        self.assertEqual(calls[0][1], "POST")
        self.assertEqual(calls[0][2]["view_id"], "100")
        self.assertEqual(calls[0][2]["duplicate_option"], "with_detailing")
        self.assertEqual(calls[0][2]["new_name"], "L4 Demo Copy")
        self.assertEqual(calls[0][2]["apply_template_id"], "300")
        self.assertTrue(calls[0][2]["activate"])

    def test_duplicate_view_rejects_unknown_option_before_route_call(self):
        class FakeRevitClient:
            def call_listener(self, *_args, **_kwargs):
                raise AssertionError("route should not be called")

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            revit_client=FakeRevitClient(),
        )

        result = duplicate_view_handler(services, duplicate_option="bad")

        self.assertEqual(result["status"], "error")
        self.assertIn("duplicate_option", result["message"])


class ElementToolTests(unittest.TestCase):
    def test_analyze_model_statistics_calls_model_route_with_bounds(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {"status": "success", "summary": {"total_elements": 12}}

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            result_store=SimpleNamespace(compact_result_payload=lambda result, preserve_keys=None: result),
            revit_client=FakeRevitClient(),
        )

        result = analyze_model_statistics_handler(services, top_n=999)

        self.assertEqual(result["status"], "success")
        self.assertEqual(calls[0][0], "/model/statistics")
        self.assertEqual(calls[0][1], "POST")
        self.assertEqual(calls[0][2]["top_n"], 200)
        self.assertTrue(calls[0][2]["include_detailed_types"])

    def test_analyze_model_statistics_can_disable_detailed_types(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {"status": "success", "summary": {"total_elements": 12}}

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            result_store=SimpleNamespace(compact_result_payload=lambda result, preserve_keys=None: result),
            revit_client=FakeRevitClient(),
        )

        result = analyze_model_statistics_handler(services, include_detailed_types=False)

        self.assertEqual(result["status"], "success")
        self.assertFalse(calls[0][2]["include_detailed_types"])

    def test_override_element_graphics_resolves_result_handle(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {"status": "success", "applied_count": len(payload_data["element_ids"])}

        class FakeResultStore:
            def resolve_element_ids(self, element_ids=None, result_handle=None, category_name=None):
                self.request = (element_ids, result_handle, category_name)
                return ["101", "102"], {"result_handle": "res_source", "category": "Windows"}, None

            def compact_result_payload(self, result, preserve_keys=None):
                return result

        result_store = FakeResultStore()
        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            result_store=result_store,
            revit_client=FakeRevitClient(),
        )

        result = override_element_graphics_handler(
            services,
            result_handle="res_source",
            color={"r": 10, "g": 20, "b": 30},
            transparency=45,
            focus=True,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source_result_handle"], "res_source")
        self.assertEqual(calls[0][0], "/elements/override_graphics")
        self.assertEqual(calls[0][2]["element_ids"], ["101", "102"])
        self.assertEqual(calls[0][2]["color"], {"r": 10, "g": 20, "b": 30})
        self.assertEqual(calls[0][2]["transparency"], 45)
        self.assertTrue(calls[0][2]["focus"])

    def test_delete_elements_defaults_to_dry_run_and_requires_route_payload(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {
                    "status": "dry_run",
                    "candidate_count": len(payload_data["element_ids"]),
                    "dry_run": payload_data["dry_run"],
                    "confirm_delete": payload_data["confirm_delete"],
                    "unpin_before_delete": payload_data["unpin_before_delete"],
                    "deletion_mode": payload_data["deletion_mode"],
                }

        class FakeResultStore:
            def resolve_element_ids(self, element_ids=None, result_handle=None, category_name=None):
                return [str(value) for value in range(1, 30)], None, None

            def compact_result_payload(self, result, preserve_keys=None):
                return result

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            result_store=FakeResultStore(),
            revit_client=FakeRevitClient(),
        )

        result = delete_elements_handler(services, element_ids=["1"], max_count=999)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(calls[0][0], "/elements/delete")
        self.assertTrue(calls[0][2]["dry_run"])
        self.assertFalse(calls[0][2]["confirm_delete"])
        self.assertEqual(calls[0][2]["max_count"], 500)
        self.assertFalse(calls[0][2]["unpin_before_delete"])
        self.assertEqual(calls[0][2]["deletion_mode"], "individual")

    def test_delete_elements_can_request_unpin_and_batch_mode(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {
                    "status": "success",
                    "deleted_input_count": len(payload_data["element_ids"]),
                    "unpin_before_delete": payload_data["unpin_before_delete"],
                    "deletion_mode": payload_data["deletion_mode"],
                }

        class FakeResultStore:
            def resolve_element_ids(self, element_ids=None, result_handle=None, category_name=None):
                return ["501", "502"], {"result_handle": "res_panels", "category": "Curtain Panels"}, None

            def compact_result_payload(self, result, preserve_keys=None):
                return result

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            result_store=FakeResultStore(),
            revit_client=FakeRevitClient(),
        )

        result = delete_elements_handler(
            services,
            result_handle="res_panels",
            dry_run=False,
            confirm_delete=True,
            unpin_before_delete=True,
            deletion_mode="batch",
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(calls[0][2]["unpin_before_delete"])
        self.assertEqual(calls[0][2]["deletion_mode"], "batch")

    def test_get_revit_diagnostics_calls_diagnostic_route_with_write_check(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {
                    "status": "success",
                    "route_version": "test-version",
                    "document_state": {"title": "Model.rvt"},
                    "write_context_check": {"attempted": True, "can_start_transaction": False},
                }

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            result_store=SimpleNamespace(compact_result_payload=lambda result, preserve_keys=None: result),
            revit_client=FakeRevitClient(),
        )

        result = get_revit_diagnostics_handler(services, check_write_context=True, selection_limit=500)

        self.assertEqual(result["status"], "success")
        self.assertEqual(calls[0][0], "/diagnostics/revit_state")
        self.assertEqual(calls[0][1], "POST")
        self.assertTrue(calls[0][2]["check_write_context"])
        self.assertEqual(calls[0][2]["selection_limit"], 200)

    def test_select_elements_requests_focus_and_refresh_by_default(self):
        calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                calls.append((command_path, method, payload_data))
                return {"status": "success", "selected_count": len(payload_data["element_ids"])}

        class FakeResultStore:
            def resolve_element_ids(self, element_ids=None, result_handle=None):
                return element_ids, None, None

            def compact_result_payload(self, result, preserve_keys=None):
                return result

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            result_store=FakeResultStore(),
            revit_client=FakeRevitClient(),
        )

        result = select_elements_by_id_handler(services, element_ids=["101", 102])

        self.assertEqual(result["selected_count"], 2)
        self.assertEqual(calls[0][0], "/select_elements_by_id")
        self.assertEqual(calls[0][2]["element_ids"], ["101", "102"])
        self.assertTrue(calls[0][2]["focus"])
        self.assertTrue(calls[0][2]["refresh_view"])

    def test_filter_stored_elements_supports_multi_value_any_match(self):
        property_reads = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                property_reads.append((command_path, method, payload_data))
                return {
                    "status": "success",
                    "elements": [
                        {
                            "element_id": "101",
                            "properties": {"Mark": "A-01"},
                            "typed_properties": {"Mark": {"storage_type": "String", "is_numeric": False}},
                        },
                        {
                            "element_id": "102",
                            "properties": {"Mark": "B-02"},
                            "typed_properties": {"Mark": {"storage_type": "String", "is_numeric": False}},
                        },
                        {
                            "element_id": "103",
                            "properties": {"Mark": "C-03"},
                            "typed_properties": {"Mark": {"storage_type": "String", "is_numeric": False}},
                        },
                    ],
                }

            def is_route_not_defined(self, *_args, **_kwargs):
                return False

        class FakeResultStore:
            def resolve_element_ids(self, **_kwargs):
                return ["101", "102", "103"], {"storage_key": "curtain_panels"}, None

            def normalize_storage_key(self, value):
                return str(value or "").lower().replace(" ", "_")

            def store_elements(self, category_name, element_ids, count):
                self.stored = (category_name, element_ids, count)
                return category_name, "res_filtered"

            def compact_result_payload(self, result, preserve_keys=None):
                return result

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            config=SimpleNamespace(
                min_confidence_for_parameter_remap=0.82,
                default_server_filter_batch_size=600,
                max_records_in_response=20,
            ),
            result_store=FakeResultStore(),
            revit_client=FakeRevitClient(),
        )

        with patch(
            "RevitMCP_ExternalServer.tools.element_tools.resolve_revit_targets_internal",
            return_value={"status": "success", "resolved": {"parameter_names": {}}},
        ):
            result = filter_stored_elements_by_parameter_handler(
                services,
                parameter_name="Mark",
                values=["A-01", "C-03"],
                operator="equals",
                match_mode="any",
                result_handle="res_source",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["values"], ["A-01", "C-03"])
        self.assertEqual(result["match_mode"], "any")
        self.assertEqual(result["element_ids"], ["101", "103"])
        self.assertEqual(len(property_reads), 1)
        self.assertEqual(property_reads[0][0], "/elements/get_properties")

    def test_filter_stored_elements_interprets_bare_length_using_display_units(self):
        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                return {
                    "status": "success",
                    "elements": [
                        {
                            "element_id": "201",
                            "properties": {"Side 1": "1523 mm"},
                            "typed_properties": {
                                "Side 1": {
                                    "storage_type": "StorageType.Double",
                                    "is_numeric": True,
                                    "numeric_value": 1523 / 304.8,
                                    "display_value": "1523 mm",
                                }
                            },
                        },
                        {
                            "element_id": "202",
                            "properties": {"Side 1": "2000 mm"},
                            "typed_properties": {
                                "Side 1": {
                                    "storage_type": "StorageType.Double",
                                    "is_numeric": True,
                                    "numeric_value": 2000 / 304.8,
                                    "display_value": "2000 mm",
                                }
                            },
                        },
                    ],
                }

            def is_route_not_defined(self, *_args, **_kwargs):
                return False

        class FakeResultStore:
            def resolve_element_ids(self, **_kwargs):
                return ["201", "202"], {"storage_key": "windows"}, None

            def normalize_storage_key(self, value):
                return str(value or "").lower().replace(" ", "_")

            def store_elements(self, category_name, element_ids, count):
                self.stored = (category_name, element_ids, count)
                return category_name, "res_filtered"

            def compact_result_payload(self, result, preserve_keys=None):
                return result

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            config=SimpleNamespace(
                min_confidence_for_parameter_remap=0.82,
                default_server_filter_batch_size=600,
                max_records_in_response=20,
            ),
            result_store=FakeResultStore(),
            revit_client=FakeRevitClient(),
        )

        with patch(
            "RevitMCP_ExternalServer.tools.element_tools.resolve_revit_targets_internal",
            return_value={"status": "success", "resolved": {"parameter_names": {}}},
        ):
            result = filter_stored_elements_by_parameter_handler(
                services,
                parameter_name="Side 1",
                value="1800",
                operator="greater_than",
                result_handle="res_source",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["element_ids"], ["202"])

    def test_get_element_properties_pages_stored_result_handles(self):
        property_reads = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                property_reads.append((command_path, method, payload_data))
                return {
                    "status": "success",
                    "count": len(payload_data["element_ids"]),
                    "elements": [
                        {
                            "element_id": element_id,
                            "properties": {"Element_Name": "Residential Door"},
                            "typed_properties": {},
                        }
                        for element_id in payload_data["element_ids"]
                    ],
                }

            def is_route_not_defined(self, *_args, **_kwargs):
                return False

        class FakeResultStore:
            def resolve_element_ids(self, **_kwargs):
                return [str(value) for value in range(1, 46)], {"storage_key": "doors"}, None

            def compact_result_payload(self, result, preserve_keys=None):
                return result

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            config=SimpleNamespace(
                max_elements_for_property_read=300,
                max_records_in_response=20,
            ),
            result_store=FakeResultStore(),
            revit_client=FakeRevitClient(),
        )

        first_page = get_element_properties_handler(
            services,
            result_handle="res_doors",
            parameter_names=["Element_Name"],
        )
        second_page = get_element_properties_handler(
            services,
            result_handle="res_doors",
            parameter_names=["Element_Name"],
            offset=20,
            limit=20,
        )
        last_page = get_element_properties_handler(
            services,
            result_handle="res_doors",
            parameter_names=["Element_Name"],
            offset=40,
            limit=20,
        )

        self.assertEqual(first_page["returned_count"], 20)
        self.assertTrue(first_page["has_more"])
        self.assertEqual(first_page["next_offset"], 20)
        self.assertEqual(second_page["elements"][0]["element_id"], "21")
        self.assertEqual(second_page["elements"][-1]["element_id"], "40")
        self.assertEqual(second_page["next_offset"], 40)
        self.assertEqual(last_page["returned_count"], 5)
        self.assertFalse(last_page["has_more"])
        self.assertIsNone(last_page["next_offset"])
        self.assertEqual(property_reads[0][2]["element_ids"], [str(value) for value in range(1, 21)])
        self.assertEqual(property_reads[1][2]["element_ids"], [str(value) for value in range(21, 41)])
        self.assertEqual(property_reads[2][2]["element_ids"], [str(value) for value in range(41, 46)])

    def test_get_element_properties_explicit_limit_returns_full_page_for_exports(self):
        property_reads = []
        compact_calls = []

        class FakeRevitClient:
            def call_listener(self, command_path, method, payload_data=None):
                property_reads.append((command_path, method, payload_data))
                return {
                    "status": "success",
                    "count": len(payload_data["element_ids"]),
                    "elements": [
                        {
                            "element_id": element_id,
                            "properties": {"Mark": "D-{}".format(element_id)},
                            "typed_properties": {},
                        }
                        for element_id in payload_data["element_ids"]
                    ],
                }

            def is_route_not_defined(self, *_args, **_kwargs):
                return False

        class FakeResultStore:
            def resolve_element_ids(self, **_kwargs):
                return [str(value) for value in range(1, 46)], {"storage_key": "doors"}, None

            def compact_result_payload(self, result, preserve_keys=None):
                compact_calls.append(preserve_keys)
                compact = dict(result)
                if isinstance(compact.get("elements"), list) and len(compact["elements"]) > 20:
                    compact["elements_sample"] = compact["elements"][:20]
                    compact["elements_truncated"] = True
                    compact["elements_total"] = len(compact["elements"])
                    compact.pop("elements", None)
                for key in preserve_keys or []:
                    if key in result:
                        compact[key] = result[key]
                return compact

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            config=SimpleNamespace(
                max_elements_for_property_read=300,
                max_records_in_response=20,
            ),
            result_store=FakeResultStore(),
            revit_client=FakeRevitClient(),
        )

        result = get_element_properties_handler(
            services,
            result_handle="res_doors",
            parameter_names=["Mark"],
            limit=45,
        )

        self.assertEqual(result["returned_count"], 45)
        self.assertFalse(result["has_more"])
        self.assertIn("elements", result)
        self.assertEqual(len(result["elements"]), 45)
        self.assertEqual(property_reads[0][2]["element_ids"], [str(value) for value in range(1, 46)])
        self.assertEqual(compact_calls[0], ["elements"])


class ContextToolMemoryTests(unittest.TestCase):
    def test_resolve_revit_targets_auto_saves_non_exact_resolution_mappings(self):
        saved_notes = []

        services = SimpleNamespace(
            logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
            config=SimpleNamespace(min_confidence_for_parameter_remap=0.82),
            result_store=SimpleNamespace(compact_result_payload=lambda result: result),
            memory_store=SimpleNamespace(
                save_note=lambda **kwargs: saved_notes.append(kwargs),
                get_current_project_context=lambda _services: {"project_key": "proj-1", "project_name": "Tower A"},
            ),
        )

        with patch(
            "RevitMCP_ExternalServer.tools.context_tools.get_revit_schema_context_handler",
            return_value={
                "status": "success",
                "schema": {
                    "built_in_categories": [],
                    "document_categories": ["Curtain Panels"],
                    "levels": [],
                    "family_names": [],
                    "type_names": [],
                    "parameter_names": ["Reference Level"],
                },
                "doc": {},
            },
        ):
            result = resolve_revit_targets_internal(
                services,
                {"category_name": "Panels", "parameter_names": ["reference"]},
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["resolved"]["category_name"], "Curtain Panels")
        self.assertEqual(result["resolved"]["parameter_names"]["reference"]["resolved_name"], "Reference Level")
        self.assertEqual(len(saved_notes), 2)
        self.assertEqual(saved_notes[0]["note_type"], "category_mapping")
        self.assertEqual(saved_notes[1]["note_type"], "parameter_mapping")
        self.assertIn("Panels", saved_notes[0]["title"])
        self.assertIn("Reference Level", saved_notes[1]["content"])


class MemoryStoreTests(unittest.TestCase):
    def test_memory_store_prefers_project_notes_for_relevant_query(self):
        memory_path = make_workspace_temp_file_path("memory_store")
        try:
            store = MemoryStore(
                logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
                storage_path=memory_path,
            )
            project_context = {"project_key": "proj-1", "project_name": "Tower A", "project_number": "001"}

            store.save_note(
                title="Curtain panels carry frame sequences",
                content="Frame sequence values in this model are stored on Curtain Panels under Mark.",
                note_type="category_mapping",
                scope="project",
                keywords=["curtain panels", "mark", "frame sequence"],
                project_context=project_context,
            )
            store.save_note(
                title="Fallback category check",
                content="If panels do not match, inspect Generic Models next.",
                note_type="workflow_hint",
                scope="global",
                keywords=["generic models"],
                project_context={},
            )

            notes = store.list_notes(
                query_text="find frame sequence marks on curtain panels",
                scope="auto",
                project_context=project_context,
                max_notes=5,
            )
            prompt_context = store.build_prompt_context(
                query_text="find frame sequence marks on curtain panels",
                scope="auto",
                project_context=project_context,
                max_notes=5,
            )
        finally:
            if os.path.exists(memory_path):
                os.remove(memory_path)

        self.assertGreaterEqual(len(notes), 2)
        self.assertEqual(notes[0]["title"], "Curtain panels carry frame sequences")
        self.assertIn("Relevant persistent Revit memory", prompt_context)
        self.assertIn("Curtain panels carry frame sequences", prompt_context)
        self.assertIn("Tower A", prompt_context)


class ChatServiceMemoryTests(unittest.TestCase):
    def test_run_chat_request_includes_memory_context_in_system_prompt(self):
        _app, _mcp_server, services, registry = create_application(
            launch_background_tasks=False,
            detect_revit_on_startup=False,
        )

        memory_path = make_workspace_temp_file_path("chat_memory")
        try:
            services.memory_store.storage_path = memory_path
            services.memory_store.save_note(
                title="Curtain panel mark mapping",
                content="Sequence identifiers for this workflow are usually stored on Curtain Panels in the Mark parameter.",
                note_type="workflow_hint",
                scope="global",
                keywords=["curtain panels", "mark"],
                project_context={},
            )
            services.memory_store.get_current_project_context = lambda _services: {}

            captured = {}

            class FakeOpenAIClient:
                def __init__(self, **_kwargs):
                    self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

                def create(self, **kwargs):
                    captured["system_prompt"] = kwargs["messages"][0]["content"]
                    message = SimpleNamespace(content="memory ok", tool_calls=[])
                    return SimpleNamespace(choices=[SimpleNamespace(message=message)])

            response_payload, status_code = run_chat_request(
                services,
                registry,
                {
                    "conversation": [{"role": "user", "content": "find those frame sequence marks"}],
                    "model": "gpt-test",
                    "provider": "openai",
                    "apiKey": "key",
                },
                openai_client_factory=FakeOpenAIClient,
            )
        finally:
            if os.path.exists(memory_path):
                os.remove(memory_path)

        self.assertEqual(status_code, 200)
        self.assertEqual(response_payload["reply"], "memory ok")
        self.assertIn("Relevant persistent Revit memory", captured["system_prompt"])
        self.assertIn("Curtain panel mark mapping", captured["system_prompt"])


class CompatibilityTests(unittest.TestCase):
    def test_resolve_runtime_surface_precedence(self):
        with patch.dict(os.environ, {"REVITMCP_SURFACE": "mcp"}):
            self.assertEqual(resolve_runtime_surface(["--surface", "web"]), "web")
            self.assertEqual(resolve_runtime_surface([]), "mcp")

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_runtime_surface([]), "web")


if __name__ == "__main__":
    unittest.main()
