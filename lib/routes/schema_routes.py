# RevitMCP: Schema/context HTTP routes
# -*- coding: UTF-8 -*-

from pyrevit import routes, script, DB


def _to_safe_ascii_text(value):
    """Best-effort conversion of text-like values to ASCII-safe strings."""
    if value is None:
        return ""

    try:
        text = str(value)
    except Exception:
        try:
            text = repr(value)
        except Exception:
            return ""

    try:
        # Replace non-ASCII characters with escaped sequences to keep payload JSON-safe
        return text.encode('ascii', 'backslashreplace').decode('ascii')
    except Exception:
        return text


def _sanitize_for_json(value):
    """Recursively sanitize payload content for pyRevit JSON serialization."""
    if value is None:
        return None

    if isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[_to_safe_ascii_text(k)] = _sanitize_for_json(v)
        return out

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in value]

    return _to_safe_ascii_text(value)


def register_routes(api):
    """Register schema/context discovery routes with the API."""

    @api.route('/schema/context', methods=['GET'])
    def handle_get_schema_context(request):
        """
        Returns canonical Revit schema context for resolver use:
        - BuiltInCategory names
        - Document level names
        - Family and type names
        - Common parameter names sampled from model elements
        """
        route_logger = script.get_logger()

        try:
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                return routes.Response(status=503, data={"error": "No active Revit UI document found."})

            uidoc = current_uiapp.ActiveUIDocument
            doc = uidoc.Document

            # BuiltInCategory names (canonical values like OST_Walls)
            bic_names = []
            try:
                import System
                bic_names = list(System.Enum.GetNames(DB.BuiltInCategory))
            except Exception as bic_err:
                route_logger.warning("Failed to enumerate BuiltInCategory names: {}".format(bic_err))

            # Category names visible in the current document
            category_names = []
            try:
                for cat in doc.Settings.Categories:
                    if hasattr(cat, 'Name') and cat.Name:
                        category_names.append(cat.Name)
            except Exception as cat_err:
                route_logger.warning("Failed to enumerate doc categories: {}".format(cat_err))

            # Exact level names currently in document
            level_names = []
            try:
                levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
                for level in levels:
                    if hasattr(level, 'Name') and level.Name:
                        level_names.append(level.Name)
                level_names = sorted(set(level_names))
            except Exception as level_err:
                route_logger.warning("Failed to enumerate levels: {}".format(level_err))

            # Family/type names from loaded symbols
            family_names = set()
            type_names = set()
            try:
                symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).ToElements()
                for sym in symbols:
                    try:
                        fam = getattr(sym, 'Family', None)
                        fam_name = fam.Name if fam and hasattr(fam, 'Name') else None
                        typ_name = sym.Name if hasattr(sym, 'Name') else None
                        if fam_name:
                            family_names.add(fam_name)
                        if typ_name:
                            type_names.add(typ_name)
                    except Exception:
                        continue
            except Exception as type_err:
                route_logger.warning("Failed to enumerate family symbols: {}".format(type_err))

            # Common parameter names sampled from model elements (bounded for performance)
            parameter_names = set()
            sample_limit = 400
            try:
                sampled = 0
                sample_collector = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
                for elem in sample_collector:
                    if sampled >= sample_limit:
                        break
                    sampled += 1
                    try:
                        params = elem.Parameters
                        if params:
                            for p in params:
                                try:
                                    pname = p.Definition.Name if p and p.Definition else None
                                    if pname:
                                        parameter_names.add(pname)
                                except Exception:
                                    continue
                    except Exception:
                        continue
            except Exception as param_err:
                route_logger.warning("Failed to sample parameter names: {}".format(param_err))

            context = {
                "status": "success",
                "doc": {
                    "title": doc.Title,
                    "path": doc.PathName
                },
                "schema": {
                    "built_in_categories": sorted(set(bic_names)),
                    "document_categories": sorted(set(category_names)),
                    "levels": level_names,
                    "family_names": sorted(family_names),
                    "type_names": sorted(type_names),
                    "parameter_names": sorted(parameter_names)
                }
            }

            route_logger.info(
                "Schema context generated. Categories: {} doc categories, {} BIC names; Levels: {}; Families: {}; Types: {}; Params: {}".format(
                    len(context["schema"]["document_categories"]),
                    len(context["schema"]["built_in_categories"]),
                    len(context["schema"]["levels"]),
                    len(context["schema"]["family_names"]),
                    len(context["schema"]["type_names"]),
                    len(context["schema"]["parameter_names"])
                )
            )
            return _sanitize_for_json(context)

        except Exception as e:
            route_logger.critical("Error generating /schema/context: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={"error": "Internal server error generating schema context.", "details": str(e)})
