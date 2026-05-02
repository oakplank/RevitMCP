# startup.py - Lightweight coordinator

from pyrevit import routes, script
import sys
import os

logger = script.get_logger()
logger.info("RevitMCP startup script executing...")
STARTUP_DIAGNOSTIC_VERSION = "2026-05-02-startup-diagnostics"


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default


def _safe_name(value):
    try:
        return str(value)
    except Exception:
        return "<unavailable>"

try:
    # Initialize API namespace
    api = routes.API("revit-mcp-v1")
    logger.info("pyRevit routes API 'revit-mcp-v1' initialized.")

    # Add extension directory to Python path
    extension_dir = os.path.dirname(__file__)
    lib_dir = os.path.join(extension_dir, 'lib')
    routes_dir = os.path.join(lib_dir, 'routes')
    
    logger.info("Extension directory: {}".format(extension_dir))
    logger.info("Lib directory: {}".format(lib_dir))
    logger.info("Routes directory: {}".format(routes_dir))
    logger.info("Routes directory exists: {}".format(os.path.exists(routes_dir)))
    
    if lib_dir not in sys.path:
        sys.path.append(lib_dir)
        logger.info("Added lib directory to Python path: {}".format(lib_dir))

    @api.route('/diagnostics/revit_state', methods=['GET', 'POST'])
    def handle_get_revit_diagnostics(uiapp, uidoc, doc, request):
        """Always-on startup diagnostic route. Delegates to element_routes when available."""
        try:
            from routes import element_routes
            if hasattr(element_routes, "handle_revit_diagnostics"):
                return element_routes.handle_revit_diagnostics(uiapp, uidoc, doc, request)
            delegation_error = "routes.element_routes.handle_revit_diagnostics is missing"
        except Exception as diag_import_error:
            delegation_error = str(diag_import_error)

        payload = request.data if hasattr(request, 'data') else {}
        if payload is None or not isinstance(payload, dict):
            payload = {}

        active_view = None
        try:
            if uidoc and uidoc.ActiveView:
                active_view = {
                    "id": str(uidoc.ActiveView.Id.IntegerValue),
                    "name": _safe_name(uidoc.ActiveView.Name),
                    "view_type": _safe_name(uidoc.ActiveView.ViewType),
                }
        except Exception as active_view_error:
            active_view = {"error": str(active_view_error)}

        document_state = {
            "has_doc": doc is not None,
            "title": None,
            "path": None,
            "is_read_only": None,
            "is_modifiable": None,
            "active_view_type": active_view.get("view_type") if isinstance(active_view, dict) else None,
        }
        try:
            if doc:
                document_state["title"] = _safe_name(doc.Title)
                document_state["path"] = _safe_name(doc.PathName)
                document_state["is_read_only"] = bool(doc.IsReadOnly)
                document_state["is_modifiable"] = bool(doc.IsModifiable)
        except Exception as doc_state_error:
            document_state["error"] = str(doc_state_error)

        selection = {"selected_count": None, "element_ids": []}
        try:
            if uidoc:
                selected_ids = uidoc.Selection.GetElementIds()
                selection["selected_count"] = selected_ids.Count
                for element_id in selected_ids:
                    if len(selection["element_ids"]) >= 10:
                        break
                    selection["element_ids"].append(str(element_id.IntegerValue))
        except Exception as selection_error:
            selection["error"] = str(selection_error)

        open_documents = []
        try:
            if uiapp and uiapp.Application:
                for open_doc in uiapp.Application.Documents:
                    open_documents.append({
                        "title": _safe_name(open_doc.Title),
                        "path": _safe_name(open_doc.PathName),
                        "is_active": bool(doc and open_doc.Equals(doc)),
                        "is_read_only": bool(open_doc.IsReadOnly),
                    })
        except Exception as open_docs_error:
            open_documents = [{"error": str(open_docs_error)}]

        check_write_context = _coerce_bool(payload.get('check_write_context'), default=False)
        write_context_check = {
            "attempted": check_write_context,
            "can_start_transaction": None,
            "rollback_ok": None,
            "error": None,
        }
        if check_write_context:
            try:
                from Autodesk.Revit import DB
                transaction = DB.Transaction(doc, "RevitMCP Startup Diagnostics Write Context")
                transaction.Start()
                write_context_check["can_start_transaction"] = True
                try:
                    transaction.RollBack()
                    write_context_check["rollback_ok"] = True
                except Exception as rollback_error:
                    write_context_check["rollback_ok"] = False
                    write_context_check["rollback_error"] = str(rollback_error)
            except Exception as transaction_error:
                write_context_check["can_start_transaction"] = False
                write_context_check["error"] = str(transaction_error)

        return {
            "status": "success",
            "message": "Startup diagnostic fallback route is active; rich element diagnostics did not load.",
            "route_version": STARTUP_DIAGNOSTIC_VERSION,
            "diagnostic_mode": "startup_fallback",
            "delegation_error": delegation_error,
            "document_state": document_state,
            "active_view": active_view,
            "selection": selection,
            "open_documents": open_documents,
            "write_context_check": write_context_check,
        }

    logger.info("Startup diagnostic route registered: /diagnostics/revit_state")

    # Import and register route modules
    try:
        logger.info("Attempting to import route modules...")
        from routes import (
            project_routes,
            sheet_routes,
            element_routes,
            schema_routes
        )
        logger.info("Route modules imported successfully")
        
        # Register each module's routes
        project_routes.register_routes(api)
        logger.info("Project routes registered successfully")
        
        sheet_routes.register_routes(api)
        logger.info("Sheet routes registered successfully")
        
        element_routes.register_routes(api)
        logger.info("Element routes registered successfully")

        schema_routes.register_routes(api)
        logger.info("Schema routes registered successfully")
        
    except ImportError as ie:
        import_error_message = str(ie)
        logger.error("Error importing route modules: {}".format(import_error_message), exc_info=True)
        logger.info("Falling back to diagnostic route...")

        @api.route('/project_info', methods=['GET'])
        def handle_get_project_info_fallback(request):
            return routes.Response(status=503, data={
                "status": "error",
                "error": "RevitMCP routes failed to load.",
                "details": import_error_message,
                "fallback_mode": True
            })

        logger.info("Diagnostic fallback route registered")
        
    logger.info("Route setup completed")

except Exception as e:
    logger.error("Error during RevitMCP startup.py execution: {}".format(e), exc_info=True)

logger.info("RevitMCP startup script finished.") 
