import os
import threading

from flask import Flask
from flask_cors import CORS
from mcp.server.fastmcp import FastMCP

from RevitMCP_ExternalServer.core.runtime_config import (
    configure_flask_logger,
    create_startup_logger,
    load_runtime_config,
    resolve_runtime_surface,
)
from RevitMCP_ExternalServer.core.services import create_services
from RevitMCP_ExternalServer.tools.context_tools import GET_SCHEMA_CONTEXT_TOOL_NAME
from RevitMCP_ExternalServer.tools.registry import build_tool_registry
from RevitMCP_ExternalServer.web.routes import register_routes


def create_flask_app(config):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, "templates"),
        static_folder=os.path.join(base_dir, "static"),
    )
    CORS(app, resources={r"/*": {"origins": config.cors_origins}})
    configure_flask_logger(app, config.debug_mode)
    app.logger.info(
        "Flask app initialized. Debug mode: %s. Host: %s. Port: %s. CORS origins: %s.",
        config.debug_mode,
        config.host,
        config.port,
        config.cors_origins,
    )
    return app


def _launch_schema_warmup_thread(services, tool_registry):
    def run_schema_warmup():
        try:
            schema_warmup = tool_registry.dispatch(services, GET_SCHEMA_CONTEXT_TOOL_NAME, {"force_refresh": True})
            if schema_warmup.get("status") == "success":
                services.logger.info("Schema context cache warmup succeeded.")
            else:
                services.logger.warning("Schema context cache warmup skipped: %s", schema_warmup.get("message"))
        except Exception as schema_warmup_error:
            services.logger.warning("Schema context cache warmup failed: %s", schema_warmup_error)

    threading.Thread(target=run_schema_warmup, name="revitmcp-schema-warmup", daemon=True).start()
    services.logger.info("Schema context warmup launched in background thread.")


def create_application(
    startup_logger=None,
    launch_background_tasks: bool = True,
    detect_revit_on_startup: bool = True,
):
    startup_logger = startup_logger or create_startup_logger()
    startup_logger.info("--- RevitMCP External Server script starting (inside bootstrap) ---")

    config = load_runtime_config()
    app = create_flask_app(config)
    mcp_server = FastMCP("RevitMCPServer")
    app.logger.info("FastMCP server instance created: %s", mcp_server.name)

    services = create_services(config=config, startup_logger=startup_logger, app=app)
    tool_registry = build_tool_registry()
    services.tool_registry = tool_registry

    if detect_revit_on_startup:
        services.revit_client.detect_port()

    tool_registry.register_mcp_tools(mcp_server, services)
    app.logger.info("MCP tools defined and registered from central registry.")

    register_routes(app, services, tool_registry)

    if launch_background_tasks and config.warm_schema_on_startup:
        _launch_schema_warmup_thread(services, tool_registry)
    elif launch_background_tasks:
        app.logger.info("Schema context warmup disabled via REVITMCP_WARM_SCHEMA_ON_STARTUP.")

    return app, mcp_server, services, tool_registry


def main(argv=None, startup_logger=None) -> int:
    argv = argv or []
    startup_logger = startup_logger or create_startup_logger()

    runtime_surface = resolve_runtime_surface(argv, startup_logger)
    startup_logger.info("--- Runtime surface selected: %s ---", runtime_surface)

    app, mcp_server, services, _tool_registry = create_application(
        startup_logger=startup_logger,
        launch_background_tasks=True,
        detect_revit_on_startup=True,
    )

    try:
        if runtime_surface == "mcp":
            startup_logger.info("--- Starting FastMCP server over stdio transport ---")
            mcp_server.run(transport="stdio")
            startup_logger.info("FastMCP server exited normally.")
        else:
            startup_logger.info(
                "--- Starting Flask development server on host %s, port %s ---",
                services.config.host,
                services.config.port,
            )
            app.run(debug=services.config.debug_mode, port=services.config.port, host=services.config.host)
            startup_logger.info("Flask app.run() exited normally.")
        return 0
    except OSError as os_error:
        startup_logger.error("OS Error during server startup: %s", os_error, exc_info=True)
        raise
    except Exception as main_error:
        startup_logger.error("Unexpected error during server startup: %s", main_error, exc_info=True)
        raise
