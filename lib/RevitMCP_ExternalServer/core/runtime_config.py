import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field


USER_DOCUMENTS = os.path.expanduser("~/Documents")
LOG_BASE_DIR = os.path.join(USER_DOCUMENTS, "RevitMCP", "server_logs")
STARTUP_LOG_FILE = os.path.join(LOG_BASE_DIR, "server_startup_error.log")
APP_LOG_FILE = os.path.join(LOG_BASE_DIR, "server_app.log")

DEFAULT_CORS_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]
DEFAULT_REVIT_PORTS = [48885, 48884, 48886]
DEFAULT_DIRECT_REVIT_LISTENER_URL = "http://localhost:8001"
FALLBACK_LOG_BASE_DIR = os.path.join(tempfile.gettempdir(), "RevitMCP", "server_logs")

ANTHROPIC_MODEL_ID_MAP = {
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-haiku-4-5": "claude-haiku-4-5",
}


def _ensure_log_dir() -> None:
    global LOG_BASE_DIR, STARTUP_LOG_FILE, APP_LOG_FILE

    try:
        if not os.path.exists(LOG_BASE_DIR):
            os.makedirs(LOG_BASE_DIR)
    except PermissionError:
        LOG_BASE_DIR = FALLBACK_LOG_BASE_DIR
        if not os.path.exists(LOG_BASE_DIR):
            os.makedirs(LOG_BASE_DIR)
        STARTUP_LOG_FILE = os.path.join(LOG_BASE_DIR, os.path.basename(STARTUP_LOG_FILE))
        APP_LOG_FILE = os.path.join(LOG_BASE_DIR, os.path.basename(APP_LOG_FILE))


def _create_file_handler(log_path: str, mode: str = "a") -> tuple[logging.FileHandler, str]:
    global LOG_BASE_DIR, STARTUP_LOG_FILE, APP_LOG_FILE

    try:
        return logging.FileHandler(log_path, mode=mode, encoding="utf-8"), log_path
    except PermissionError:
        LOG_BASE_DIR = FALLBACK_LOG_BASE_DIR
        if not os.path.exists(LOG_BASE_DIR):
            os.makedirs(LOG_BASE_DIR)

        fallback_path = os.path.join(LOG_BASE_DIR, os.path.basename(log_path))
        if os.path.basename(log_path) == os.path.basename(STARTUP_LOG_FILE):
            STARTUP_LOG_FILE = fallback_path
        if os.path.basename(log_path) == os.path.basename(APP_LOG_FILE):
            APP_LOG_FILE = fallback_path
        return logging.FileHandler(fallback_path, mode=mode, encoding="utf-8"), fallback_path


def create_startup_logger() -> logging.Logger:
    global STARTUP_LOG_FILE
    _ensure_log_dir()

    logger = logging.getLogger("RevitMCPServerStartup")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    if os.path.exists(STARTUP_LOG_FILE):
        try:
            os.remove(STARTUP_LOG_FILE)
        except Exception:
            pass

    file_handler, resolved_path = _create_file_handler(STARTUP_LOG_FILE, mode="a")
    if resolved_path != STARTUP_LOG_FILE:
        STARTUP_LOG_FILE = resolved_path
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(file_handler)
    logger.info("--- Server script attempting to start ---")
    return logger


def configure_flask_logger(app_instance, debug_mode: bool) -> None:
    global APP_LOG_FILE
    _ensure_log_dir()

    file_handler, resolved_path = _create_file_handler(APP_LOG_FILE, mode="a")
    if resolved_path != APP_LOG_FILE:
        APP_LOG_FILE = resolved_path
    file_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)

    for handler in list(app_instance.logger.handlers):
        app_instance.logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    app_instance.logger.addHandler(file_handler)
    app_instance.logger.propagate = False

    if debug_mode:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        app_instance.logger.addHandler(console_handler)
        app_instance.logger.setLevel(logging.DEBUG)
        app_instance.logger.info("Flask app logger: Configured for DEBUG mode (file and console).")
    else:
        app_instance.logger.setLevel(logging.INFO)
        app_instance.logger.info("Flask app logger: Configured for INFO mode (file only).")


def resolve_runtime_surface(argv_values, startup_logger=None) -> str:
    valid_surfaces = ("web", "mcp")
    cli_surface = None

    for index, arg in enumerate(argv_values):
        if arg.startswith("--surface="):
            cli_surface = arg.split("=", 1)[1].strip().lower()
            break
        if arg == "--surface" and index + 1 < len(argv_values):
            cli_surface = argv_values[index + 1].strip().lower()
            break

    env_surface = os.environ.get("REVITMCP_SURFACE", "").strip().lower()
    requested_surface = cli_surface or env_surface or "web"

    if requested_surface not in valid_surfaces:
        if startup_logger:
            startup_logger.warning(
                "Invalid runtime surface '%s'. Falling back to 'web'. Valid values: %s",
                requested_surface,
                ", ".join(valid_surfaces),
            )
        return "web"

    return requested_surface


def bounded_int(value, default_value: int, min_value: int = 1, max_value: int = 2000) -> int:
    try:
        normalized = int(value if value is not None else default_value)
    except Exception:
        normalized = int(default_value)
    return max(min_value, min(max_value, normalized))


@dataclass(frozen=True)
class RuntimeConfig:
    debug_mode: bool
    port: int
    host: str
    cors_origins: list[str]
    max_elements_for_selection: int
    max_elements_for_property_read: int
    default_server_filter_batch_size: int
    max_elements_in_response: int
    max_records_in_response: int
    max_family_types_in_response: int
    max_views_in_response: int
    max_outliers_in_response: int
    max_suggestions_in_response: int
    min_confidence_for_parameter_remap: float
    warm_schema_on_startup: bool
    max_tool_iterations: int
    revit_possible_ports: list[int] = field(default_factory=lambda: list(DEFAULT_REVIT_PORTS))
    direct_revit_listener_url: str = DEFAULT_DIRECT_REVIT_LISTENER_URL
    anthropic_model_id_map: dict[str, str] = field(default_factory=lambda: dict(ANTHROPIC_MODEL_ID_MAP))


def load_runtime_config() -> RuntimeConfig:
    cors_origins_raw = os.environ.get("FLASK_CORS_ORIGINS", "")
    if cors_origins_raw.strip():
        cors_origins = [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]
    else:
        cors_origins = list(DEFAULT_CORS_ORIGINS)

    return RuntimeConfig(
        debug_mode=os.environ.get("FLASK_DEBUG_MODE", "False").lower() == "true",
        port=int(os.environ.get("FLASK_PORT", 8000)),
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        cors_origins=cors_origins,
        max_elements_for_selection=250,
        max_elements_for_property_read=int(os.environ.get("REVITMCP_MAX_ELEMENTS_FOR_PROPERTY_READ", "300")),
        default_server_filter_batch_size=int(os.environ.get("REVITMCP_SERVER_FILTER_BATCH_SIZE", "600")),
        max_elements_in_response=int(os.environ.get("REVITMCP_MAX_ELEMENTS_IN_RESPONSE", "40")),
        max_records_in_response=int(os.environ.get("REVITMCP_MAX_RECORDS_IN_RESPONSE", "20")),
        max_family_types_in_response=int(os.environ.get("REVITMCP_MAX_FAMILY_TYPES_IN_RESPONSE", "40")),
        max_views_in_response=int(os.environ.get("REVITMCP_MAX_VIEWS_IN_RESPONSE", "60")),
        max_outliers_in_response=int(os.environ.get("REVITMCP_MAX_OUTLIERS_IN_RESPONSE", "40")),
        max_suggestions_in_response=int(os.environ.get("REVITMCP_MAX_SUGGESTIONS_IN_RESPONSE", "30")),
        min_confidence_for_parameter_remap=float(
            os.environ.get("REVITMCP_MIN_CONFIDENCE_FOR_PARAMETER_REMAP", "0.82")
        ),
        warm_schema_on_startup=os.environ.get("REVITMCP_WARM_SCHEMA_ON_STARTUP", "true").strip().lower()
        in ("1", "true", "yes", "on"),
        max_tool_iterations=int(os.environ.get("REVITMCP_MAX_TOOL_ITERATIONS", "5")),
        revit_possible_ports=list(DEFAULT_REVIT_PORTS),
        direct_revit_listener_url=os.environ.get(
            "REVITMCP_DIRECT_LISTENER_URL",
            DEFAULT_DIRECT_REVIT_LISTENER_URL,
        ),
    )
