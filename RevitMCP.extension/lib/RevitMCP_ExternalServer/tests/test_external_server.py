import importlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

LIB_ROOT = Path(__file__).resolve().parents[2]
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))


from RevitMCP_ExternalServer.bootstrap import create_application
from RevitMCP_ExternalServer.core.runtime_config import ANTHROPIC_MODEL_ID_MAP, resolve_runtime_surface
from RevitMCP_ExternalServer.providers.anthropic_provider import run_anthropic_chat
from RevitMCP_ExternalServer.providers.google_provider import run_google_chat
from RevitMCP_ExternalServer.providers.openai_provider import run_openai_chat
from RevitMCP_ExternalServer.tools.registry import build_tool_registry


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
        filter_operator_enum = filter_parameters["operator"]["enum"]
        stored_operator_enum = definition_map["filter_stored_elements_by_parameter"].json_schema["properties"]["operator"]["enum"]

        self.assertIn("greater_than", filter_operator_enum)
        self.assertIn("greater_than_or_equal", filter_operator_enum)
        self.assertIn("less_than_or_equal", filter_operator_enum)
        self.assertEqual(filter_operator_enum, stored_operator_enum)

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


class CompatibilityTests(unittest.TestCase):
    def test_resolve_runtime_surface_precedence(self):
        with patch.dict(os.environ, {"REVITMCP_SURFACE": "mcp"}):
            self.assertEqual(resolve_runtime_surface(["--surface", "web"]), "web")
            self.assertEqual(resolve_runtime_surface([]), "mcp")

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_runtime_surface([]), "web")

    def test_legacy_anthropic_model_aliases(self):
        self.assertEqual(ANTHROPIC_MODEL_ID_MAP["claude-4-sonnet"], "claude-sonnet-4-6")
        self.assertEqual(ANTHROPIC_MODEL_ID_MAP["claude-4-opus"], "claude-opus-4-6")


if __name__ == "__main__":
    unittest.main()
