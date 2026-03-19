# RevitMCP: This script runs in a standard CPython 3.7+ environment. Modern Python syntax is expected.
"""
External Flask server bootstrap for RevitMCP.
This file remains the stable launch target for both the web UI and MCP surface.
"""

import os
import sys
import traceback


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


from RevitMCP_ExternalServer.bootstrap import create_application, main  # noqa: E402
from RevitMCP_ExternalServer.core.runtime_config import STARTUP_LOG_FILE, create_startup_logger  # noqa: E402


__all__ = ["create_application", "main"]


def _run_main() -> int:
    startup_logger = create_startup_logger()
    try:
        return main(sys.argv[1:], startup_logger=startup_logger)
    except Exception as global_error:
        startup_logger.error("!!!!!!!!!! GLOBAL SCRIPT EXECUTION ERROR !!!!!!!!!!", exc_info=True)
        sys.stderr.write(f"GLOBAL SCRIPT ERROR: {global_error}\n{traceback.format_exc()}\n")
        sys.stderr.write(f"Check '{STARTUP_LOG_FILE}' for details.\n")
        return 1
    finally:
        startup_logger.info("--- Server script execution finished or encountered a global error ---")


if __name__ == "__main__":
    raise SystemExit(_run_main())
