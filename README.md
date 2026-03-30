# RevitMCP: Revit Model Content Protocol Extension

## Introduction

RevitMCP (Revit Model Content Protocol) is a pyRevit extension that allows external applications, such as AI assistants or other services, to interact with a running instance of Autodesk Revit. It achieves this by exposing an HTTP API from within Revit using pyRevit's "Routes" functionality. An external server component (typically `server.py` in this project) acts as an intermediary, which the external application communicates with. This intermediary server then makes calls to the API hosted by pyRevit within Revit.

## Key Features

- **Schema-aware automation:** Load canonical Revit context for levels, categories, families, types, and parameters before acting
- **Element search and selection:** Retrieve, filter, store, and re-select result sets without pushing large ID lists through the model
- **Parameter read/write workflows:** Inspect populated properties and update instance or type parameters with validation
- **Sheet and view tooling:** List placeable views, auto-create sheets, and place views with smart numbering
- **AI-native operation:** Available through both the local web UI and the MCP stdio surface for desktop AI assistants

## Supported Tools

RevitMCP currently exposes these 20 MCP tools:

| Tool | Description |
| --- | --- |
| `get_revit_project_info` | Get active project metadata, document path, and Revit version details |
| `get_active_view_info` | Read the current view's name, type, scale, and related metadata |
| `get_active_view_elements` | Capture a bounded snapshot of elements visible in the active view |
| `get_active_selection` | Read the current Revit selection as a reusable result set |
| `list_family_types` | List loaded family types with category, family, type, and symbol IDs |
| `get_revit_schema_context` | Load canonical Revit schema context including levels, categories, families, types, and common parameters |
| `resolve_revit_targets` | Resolve user terms to exact Revit category, level, family, type, and parameter names |
| `get_elements_by_category` | Retrieve all elements for a category and store the result for follow-on actions |
| `select_elements_by_id` | Select elements by explicit IDs or a stored result handle; retained for compatibility |
| `select_stored_elements` | Select a previously stored search or filter result inside Revit |
| `list_stored_elements` | List stored element result sets and their counts currently available on the server |
| `filter_elements` | Find elements by category, level, and parameter-based conditions |
| `filter_stored_elements_by_parameter` | Refine a stored result set with batched server-side parameter filtering |
| `get_element_properties` | Read parameter values for specific elements or an existing result handle |
| `update_element_parameters` | Update one or many element parameters with typed value handling |
| `place_view_on_sheet` | Create a new sheet, auto-number it, and place a matched view on it |
| `list_views` | List views that can be placed on sheets, including type and placement status |
| `analyze_view_naming_patterns` | Cluster view names by type and flag likely naming outliers |
| `suggest_view_name_corrections` | Generate rename suggestions from a prior view naming analysis |
| `plan_and_execute_workflow` | Execute a multi-step Revit workflow from a structured tool plan |

This README provides instructions on how to set up and use the `RevitMCP.extension`.

## Prerequisites

1.  **Autodesk Revit:** A compatible version of Autodesk Revit must be installed.
2.  **pyRevit:** pyRevit must be installed for your Revit version. If you don't have it, download and install it from [pyrevitlabs.io](https://pyrevitlabs.io/).

## Installation

1.  **Install pyRevit:**
    *   Follow the official installation guide on the [pyRevit website](https://pyrevitlabs.io/docs/pyrevit/installer).

2.  **Install the `RevitMCP.extension`:**
    *   Locate your pyRevit extensions folder. You can typically find this by:
        *   Opening pyRevit Settings in Revit (pyRevit Tab -> Settings).
        *   Going to the "Extensions" section. It might show registered extension paths.
        *   Common default locations include:
            *   `%APPDATA%/pyRevit/Extensions`
            *   `%PROGRAMDATA%/pyRevit/Extensions`
    *   Copy the entire `RevitMCP.extension` folder (which contains `startup.py`, `lib/`, etc.) into one of your pyRevit extensions directories.

3.  **Reload pyRevit / Restart Revit:**
    *   After copying the extension, either "Reload" pyRevit (from the pyRevit tab in Revit) or restart Revit to ensure the extension is recognized and its `startup.py` script is executed.

## Configuration

1.  **Enable pyRevit Routes Server:**
    *   Open Revit.
    *   Go to the **pyRevit Tab -> Settings**.
    *   Find the section related to **"Routes"** or **"Web Server"** or **"API"**.
    *   **Enable the Routes server.**
    *   Note the **default port number**, which is typically `48884` for the first Revit instance. Subsequent Revit instances will use incrementing port numbers (e.g., `48885`, `48886`). Your external server (`server.py`) must be configured to point to the correct port.
    *   **Restart Revit** after enabling the Routes server if prompted or to ensure the settings take effect. The `startup.py` script in `RevitMCP.extension` defines the API endpoints when pyRevit loads.

2.  **Firewall/Network Access:**
    *   When the pyRevit Routes server starts for the first time, your operating system's firewall might ask for permission to allow Revit (or the Python process within Revit) to open a network port and listen for incoming connections. You must **allow this access** for the system to work.
    *   Ensure that no other firewall or security software is blocking connections to the port used by the pyRevit Routes server (e.g., `48884`).

## Running the System

The system consists of two main parts that need to be running:

1.  **The Revit-Side API (Managed by `RevitMCP.extension` and pyRevit):**
    *   When Revit starts and pyRevit loads the `RevitMCP.extension`, the `startup.py` script within the extension automatically runs.
    *   This script defines the necessary API endpoints (e.g., `/revit-mcp-v1/project_info`) and registers them with the pyRevit Routes server running inside Revit.
    *   You can verify this by checking pyRevit logs for messages from `startup.py` (see Troubleshooting below).

2.  **The External Intermediary Server (e.g., `server.py`):**
    *   This is a separate Python application (likely a Flask or FastAPI server) that the end-user application (e.g., AI Assistant) communicates with.
    *   This server is responsible for:
        *   Receiving requests from the end-user application.
        *   Making HTTP calls to the pyRevit Routes API running inside Revit (e.g., to `http://localhost:48884/revit-mcp-v1/...`).
        *   Processing the response from Revit and sending it back to the end-user application.
    *   **Launching this server:** The `RevitMCP.extension` includes a UI panel in Revit (e.g., "Server.panel") with a button like "Launch RevitMCP". This button is typically configured to start this external `server.py` script.
        *   Click this button in the Revit UI to start the intermediary server.
        *   Check the console output of this server to ensure it starts correctly and is listening on its configured port (e.g., your logs showed it running on port `8000`).

    **User Interface for the External Server:**
    *   Once the external server (`server.py`) is running, you typically interact with it through a web-based chat interface (often served at `http://localhost:PORT` where `PORT` is the one for `server.py`, e.g., `8000`).
    *   This interface usually provides:
        *   A **dropdown menu** to select the desired AI model (e.g., Anthropic, OpenAI, Google Generative AI).
        *   A **settings area or popup** where you can input your API keys for the selected AI model provider. These keys are necessary for the server to make requests to the AI services.

**Workflow Summary:**
   `AI Assistant/Client App`  ->  `External Server (server.py on e.g., port 8000)`  ->  `pyRevit Routes API (in Revit on e.g., port 48884)`

## Runtime Surfaces

`server.py` supports two runtime surfaces so users can choose where they interact:

1.  **`web` surface (default):**
    *   Runs the Flask chat UI on localhost.
    *   Best for browser-based interaction at `http://127.0.0.1:8000`.

2.  **`mcp` surface:**
    *   Runs MCP over stdio for Claude Desktop local MCP servers.
    *   Best for direct Claude tool use without the web UI.

### How Surface Is Selected

Surface selection priority is:

1.  CLI argument: `--surface web` or `--surface mcp`
2.  Environment variable: `REVITMCP_SURFACE`
3.  Default: `web`

Examples:

```powershell
# Web UI mode
python server.py --surface web

# Claude Desktop MCP mode
python server.py --surface mcp
```

For pyRevit launcher users, the surface is read from:
`%USERPROFILE%\Documents\RevitMCP\user_data\revitmcp_settings.json`

```json
{
  "preferences": {
    "server_surface": "web"
  }
}
```

Use `"mcp"` to launch in Claude Desktop mode.

## Claude Desktop (Local MCP) Setup

Download Claude Desktop:  
`https://claude.ai/download`

Add this to Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "revitmcp": {
      "command": "python",
      "args": [
        "C:\\Program Files\\pyRevit-Master\\extensions\\RevitMCP.extension\\lib\\RevitMCP_ExternalServer\\server.py",
        "--surface",
        "mcp"
      ]
    }
  }
}
```

Note: The path to `server.py` may vary depending on your install location. Use the actual location of your installed `RevitMCP.extension`.

Then fully restart Claude Desktop.

### Quick Setup (Recommended)

1.  Install Claude Desktop and sign in.
2.  Open Claude Desktop settings and go to:
    *   **Developer -> Local MCP Servers** (or **Extensions** in newer UI builds).
3.  Click **Edit Config** and add the `revitmcp` server JSON shown above.
4.  Save config and fully restart Claude Desktop.
5.  Re-open **Developer -> Local MCP Servers** and confirm `revitmcp` shows **running**.

Expected Claude Desktop screen after Local MCP is enabled and `revitmcp` is configured:

![Claude Desktop Local MCP settings showing Developer selected and the revitmcp server running](docs/images/claude-local-mcp-settings.png)

6.  In a new chat, test with: `Get Revit project info`.

## Claude Desktop Usage Guide

After setup:

1.  Open Revit with a project loaded and ensure pyRevit Routes is enabled.
2.  Open Claude Desktop.
3.  Start a new chat and ask tool-driven prompts such as:
    *   `Get Revit project info`
    *   `List views that can be placed on sheets`
    *   `Get elements by category Walls`
4.  If needed, open Claude Desktop -> Settings -> Developer -> Local MCP Servers -> `revitmcp` -> `View Logs`.

Notes:
*   Claude Desktop local MCP mode does not use the web UI model dropdown.
*   In MCP mode, model selection is whatever Claude model you choose in Claude Desktop itself.

## Web UI Model Catalog (Updated for Feb 2026)

The web surface (`--surface web`) model dropdown currently includes:

*   OpenAI:
    *   `gpt-5.2`
    *   `gpt-5-mini`
*   Anthropic:
    *   `claude-sonnet-4-6`
    *   `claude-opus-4-6`
    *   `claude-haiku-4-5`
*   Google Gemini:
    *   `gemini-3-pro-preview-02-05`
    *   `gemini-3-flash-preview-02-05`

## Troubleshooting

*   **Route Not Found Errors (`RouteHandlerNotDefinedException`):**
    *   Ensure `RevitMCP.extension/startup.py` exists and contains the route definitions.
    *   Reload pyRevit or Restart Revit after any changes to `startup.py`.
    *   Check pyRevit logs for messages from `startup.py` indicating it ran and defined the routes.
    *   Ensure the pyRevit Routes server is enabled in pyRevit Settings and Revit was restarted.
    *   Use the diagnostic script (provided during development) in a pyRevit-aware Python console within Revit to check `routes.get_routes("revit-mcp-v1")` and `routes.get_active_server()`.

*   **Connection Refused / Cannot Connect to pyRevit Routes API:**
    *   Verify the pyRevit Routes server is enabled in pyRevit Settings.
    *   Confirm the port number used by the external server to call the pyRevit API matches the port the pyRevit Routes server is actually listening on (default `48884`).
    *   Check firewall settings.

*   **Check Logs:**
    *   **pyRevit Logs:** (pyRevit Tab -> Settings -> Logging) for errors related to `RevitMCP.extension` loading, `startup.py` execution, or the Routes server.
    *   **External Server (`server.py`) Logs:** Check the console output of your `server.py` for errors when it tries to communicate with the pyRevit Routes API or when it's handling requests from the client application.

---
This README should help users set up and understand the RevitMCP system. 
