# RevitMCP Architecture Refactoring Summary

A record of the move from a monolithic `startup.py` to a modular route layer that follows pyRevit's framework conventions.

## What Changed

The original `startup.py` was a ~1500-line script that mixed extension lifecycle, route registration, and Revit API logic into one file. It has been split into:

- A small `startup.py` coordinator that sets up sys.path and loads route modules.
- A `lib/routes/` package with one module per route domain (project, sheet, element, schema), each registering its routes via `api.route(...)`.
- A `lib/RevitMCP_Tools/` package for reusable Revit-side helpers (sheet placement, etc.) consumed by the route modules.

## Current Layout

```
RevitMCP/                         # repo root acts as the pyRevit extension root
├── extension.json
├── startup.py                    # coordinator: sys.path + register route modules
├── pyproject.toml                # pytest discovery for the external server tests
├── RevitMCP.tab/                 # ribbon UI (panel + pushbuttons)
├── lib/
│   ├── routes/                   # HTTP route layer (pyRevit Routes API)
│   │   ├── __init__.py
│   │   ├── project_routes.py     # /project_info
│   │   ├── sheet_routes.py       # /sheets/place_view, /sheets/list_views
│   │   ├── element_routes.py     # all element/view/selection routes
│   │   ├── schema_routes.py      # /schema/context
│   │   └── json_safety.py        # ASCII/JSON sanitization helpers
│   ├── RevitMCP_Tools/           # Revit-side helpers
│   │   └── sheet_placement_tool.py
│   ├── RevitMCP_ExternalServer/  # MCP server + chat / provider integrations
│   └── RevitMCP_UI/              # ribbon UI manager
└── docs/
```

## Route Migration Status

All routes from the original monolith have been migrated or intentionally retired.

### Live routes (in `lib/routes/`)

**Project** — `lib/routes/project_routes.py`
- `GET  /project_info`

**Sheet** — `lib/routes/sheet_routes.py`
- `POST /sheets/place_view`
- `GET  /sheets/list_views`

**Schema** — `lib/routes/schema_routes.py`
- `GET  /schema/context`

**Element / View / Selection** — `lib/routes/element_routes.py`
- `GET  /views/active/info`
- `POST /views/active/elements`
- `POST /selection/active`
- `POST /families/types`
- `POST /get_elements_by_category`
- `POST /select_elements_by_id`
- `POST /select_elements_focused`
- `POST /elements/filter`
- `POST /elements/get_properties`
- `POST /elements/update_parameters`

### Retired routes

The following endpoints from the original `startup.py` were removed during the refactor and are not migrated. They were debug/test scaffolding superseded by the cleaner core API:

- `/select_elements_with_3d_view`, `/select_elements_simple` — debug variants of selection
- `/test_select_manual_windows`, `/test_storage_system` — manual test endpoints
- `/get_and_select_elements_by_category` — covered by composing `/select_elements_by_id` with `/elements/filter`

## Handler Convention (important)

Route handlers should declare `doc`, `uidoc`, or `uiapp` as parameter names. pyRevit's Routes framework inspects the handler signature, recognizes those names, and injects the correct Revit objects on Revit's UI thread before invoking the handler. See [pyRevit Routes handler reference](https://docs.pyrevitlabs.io/reference/pyrevit/routes/server/handler/).

```python
@api.route('/elements/update_parameters', methods=['POST'])
def handle_update_element_parameters(doc, request):
    payload = request.data
    with DB.Transaction(doc, "Update Element Parameters") as t:
        t.Start()
        # ... model mutations ...
        t.Commit()
    return result
```

Do **not** reach for `__revit__.ActiveUIDocument` from inside a handler. The pyRevit Routes server invokes route handlers from a worker thread; access to `__revit__` from there yields stale UI state and Revit refuses transactions with *"modifications are temporarily disabled"*. Declaring `doc`/`uidoc`/`uiapp` is what bridges the worker thread to Revit's UI thread — pyRevit's framework dispatches injected handlers via `IExternalEventHandler.Execute(uiapp)` so transactions, selection mutations, and active-view reads all work as written.

## Adding a New Route

1. Add a tool function (if needed) in `lib/RevitMCP_Tools/` that takes `doc` and the route's parameters.
2. Add a handler in the appropriate `lib/routes/*.py` module (or create a new module). Declare `doc`/`uidoc`/`uiapp` in the signature.
3. If you create a new module, register it in `startup.py` alongside the existing modules.

## Benefits

- **Modular** — each route domain lives in its own file; handlers are easy to locate and change.
- **Aligned with the framework** — relies on pyRevit's parameter injection rather than custom thread-marshaling.
- **Testable** — the external server side has a `pytest` suite (run from repo root via the included `pyproject.toml`).
- **Smaller surface area** — dead/duplicate modules removed; one canonical implementation per concept.
