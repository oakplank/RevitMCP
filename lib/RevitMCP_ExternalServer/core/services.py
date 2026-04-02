from dataclasses import dataclass

from .memory_store import MemoryStore
from .result_store import ResultStore
from .revit_client import RevitClient
from .runtime_config import RuntimeConfig


@dataclass
class ServerServices:
    config: RuntimeConfig
    startup_logger: object
    logger: object
    result_store: ResultStore
    revit_client: RevitClient
    memory_store: MemoryStore = None
    app: object = None
    tool_registry: object = None


def create_services(config: RuntimeConfig, startup_logger, app) -> ServerServices:
    result_store = ResultStore(config=config, logger=app.logger)
    memory_store = MemoryStore(logger=app.logger)
    revit_client = RevitClient(
        config=config,
        logger=app.logger,
        startup_logger=startup_logger,
        result_store=result_store,
    )
    return ServerServices(
        config=config,
        startup_logger=startup_logger,
        logger=app.logger,
        result_store=result_store,
        revit_client=revit_client,
        memory_store=memory_store,
        app=app,
    )
