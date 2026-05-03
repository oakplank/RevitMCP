# RevitMCP: Sheet and view-related HTTP routes
# -*- coding: UTF-8 -*-
#
# Handlers declare `doc`, `uidoc`, or `uiapp` as parameter names so pyRevit's
# Routes framework injects them on the UI thread (see
# https://docs.pyrevitlabs.io/reference/pyrevit/routes/server/handler/).

from pyrevit import routes, script, DB
import sys
import os
import re
import tempfile
import time
import uuid
import glob
from System.Collections.Generic import List

from routes.json_safety import sanitize_for_json, to_safe_ascii_text


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


def _get_view_duplicate_option(option_name):
    normalized = str(option_name or "duplicate").strip().lower()
    if normalized in ("duplicate", "plain", "without_detailing"):
        return DB.ViewDuplicateOption.Duplicate, "duplicate"
    if normalized in ("with_detailing", "with detailing", "detailing"):
        return DB.ViewDuplicateOption.WithDetailing, "with_detailing"
    if normalized in ("as_dependent", "dependent", "as dependent"):
        return DB.ViewDuplicateOption.AsDependent, "as_dependent"
    return None, normalized


def _find_view_by_id(doc, view_id):
    if not view_id:
        return None
    try:
        element_id = DB.ElementId(int(str(view_id).strip()))
        view = doc.GetElement(element_id)
        if isinstance(view, DB.View):
            return view
    except Exception:
        return None
    return None


def _find_views_by_name(doc, view_name, exact_match=False):
    if not view_name:
        return []
    query = str(view_name).strip().lower()
    matches = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements():
        try:
            if not hasattr(view, "Name") or not view.Name:
                continue
            candidate = str(view.Name).strip().lower()
            if exact_match and candidate == query:
                matches.append(view)
            elif not exact_match and query in candidate:
                matches.append(view)
        except Exception:
            continue
    return matches


def _view_name_exists(doc, view_name):
    if not view_name:
        return False
    query = str(view_name).strip().lower()
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements():
        try:
            if str(view.Name).strip().lower() == query:
                return True
        except Exception:
            continue
    return False


def _unique_view_name(doc, base_name):
    if not _view_name_exists(doc, base_name):
        return base_name
    index = 1
    while index <= 999:
        candidate = "{} {}".format(base_name, index)
        if not _view_name_exists(doc, candidate):
            return candidate
        index += 1
    return base_name


def _build_view_summary(view):
    return {
        "id": str(view.Id.IntegerValue),
        "name": to_safe_ascii_text(view.Name),
        "type": str(view.ViewType),
        "is_template": bool(getattr(view, "IsTemplate", False)),
    }


def _default_capture_dir():
    extension_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    return os.path.join(extension_root, ".revitmcp_runtime", "captures")


def _ensure_capture_dir(capture_dir):
    target_dir = capture_dir or _default_capture_dir()
    try:
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        return target_dir
    except Exception:
        fallback_dir = os.path.join(tempfile.gettempdir(), "RevitMCP", "captures")
        if not os.path.exists(fallback_dir):
            os.makedirs(fallback_dir)
        return fallback_dir


def _safe_filename_component(value, fallback="view"):
    text = to_safe_ascii_text(value or fallback).lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] or fallback


def _snapshot_capture_files(capture_dir):
    try:
        return set(os.path.abspath(os.path.join(capture_dir, name)) for name in os.listdir(capture_dir))
    except Exception:
        return set()


def _find_exported_image(capture_dir, before_files, prefix, started_at):
    image_patterns = ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff"]
    candidates = []
    for pattern in image_patterns:
        candidates.extend(glob.glob(os.path.join(capture_dir, pattern)))

    filtered = []
    prefix_lower = prefix.lower()
    before_files = before_files or set()
    for path in candidates:
        try:
            absolute_path = os.path.abspath(path)
            name_lower = os.path.basename(path).lower()
            modified_at = os.path.getmtime(path)
            if absolute_path not in before_files or name_lower.startswith(prefix_lower) or modified_at >= started_at - 2:
                filtered.append(path)
        except Exception:
            continue

    if not filtered:
        return None

    filtered.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return filtered[0]


def _get_image_file_type(format_name):
    normalized = str(format_name or "png").strip().lower()
    if normalized in ("jpg", "jpeg"):
        return DB.ImageFileType.JPEGLossless, "jpg", "image/jpeg"
    if normalized == "bmp":
        return DB.ImageFileType.BMP, "bmp", "image/bmp"
    if normalized in ("tif", "tiff"):
        return DB.ImageFileType.TIFF, "tif", "image/tiff"
    return DB.ImageFileType.PNG, "png", "image/png"


def _bounded_int(value, default, min_value, max_value):
    try:
        number = int(value)
    except Exception:
        number = default
    return max(min_value, min(max_value, number))


def register_routes(api):
    """Register all sheet-related routes with the API"""

    def _require_doc(doc):
        if doc is None:
            return routes.Response(
                status=503,
                data={"error": "No active Revit document. Open a project and retry."},
            )
        return None

    @api.route('/sheets/place_view', methods=['POST'])
    def handle_place_view_on_sheet(doc, request):
        """
        Place a view on a new sheet by view name.

        Expected payload: {
            "view_name": "Detail 1",
            "exact_match": false (optional, defaults to false for fuzzy matching)
        }
        """
        route_logger = script.get_logger()

        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc

        try:
            lib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'RevitMCP_Tools')
            if lib_dir not in sys.path:
                sys.path.append(lib_dir)

            from sheet_placement_tool import place_view_on_new_sheet

            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"error": "Invalid JSON payload"})

            view_name = payload.get('view_name')
            view_id = payload.get('view_id')
            target_sheet_id = payload.get('target_sheet_id')
            target_sheet_name = payload.get('target_sheet_name')
            titleblock_id = payload.get('titleblock_id')
            titleblock_name = payload.get('titleblock_name')
            if not view_name and not view_id:
                return routes.Response(
                    status=400,
                    data={"error": "Provide either 'view_name' or 'view_id' in request"},
                )

            exact_match = payload.get('exact_match', False)

            route_logger.info(
                "Placing view (name='{}', id='{}') on sheet (target_sheet_id='{}', target_sheet_name='{}', titleblock_id='{}', titleblock_name='{}', exact_match={})".format(
                    to_safe_ascii_text(view_name) if view_name else None,
                    view_id,
                    target_sheet_id,
                    to_safe_ascii_text(target_sheet_name) if target_sheet_name else None,
                    titleblock_id,
                    to_safe_ascii_text(titleblock_name) if titleblock_name else None,
                    exact_match,
                )
            )

            result = place_view_on_new_sheet(
                doc, view_name, route_logger, exact_match,
                view_id=view_id,
                target_sheet_id=target_sheet_id,
                target_sheet_name=target_sheet_name,
                titleblock_id=titleblock_id,
                titleblock_name=titleblock_name,
            )

            placement_status = result.get("status")
            if placement_status == "success":
                route_logger.info("Successfully placed view '{}' on sheet '{}'".format(
                    to_safe_ascii_text(result.get("view_name")), result.get("sheet_number")))
                return sanitize_for_json(result)
            if placement_status == "multiple_matches":
                route_logger.info("Multiple views found for '{}': {}".format(
                    to_safe_ascii_text(view_name),
                    [to_safe_ascii_text(v["name"]) for v in result.get("matching_views", [])],
                ))
                return routes.Response(status=300, data=sanitize_for_json(result))

            route_logger.warning(
                "Failed to place view '{}': {}".format(
                    to_safe_ascii_text(view_name),
                    to_safe_ascii_text(result.get("message")),
                )
            )
            return routes.Response(status=400, data=sanitize_for_json(result))

        except ImportError as ie:
            route_logger.error("Error importing sheet_placement_tool: {}".format(ie), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Failed to import sheet placement tool",
                "details": str(ie)
            })
        except Exception as e:
            route_logger.error("Error in place_view_on_sheet: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Internal server error",
                "details": str(e)
            })

    @api.route('/views/activate', methods=['POST'])
    def handle_activate_view(uidoc, doc, request):
        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc

        route_logger = script.get_logger()

        try:
            if uidoc is None:
                return routes.Response(
                    status=503,
                    data={"status": "error", "error": "No active Revit UI document. Open a project and retry."},
                )

            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"status": "error", "error": "Invalid JSON payload"})

            view_id = payload.get('view_id')
            view_name = payload.get('view_name')
            exact_match = _coerce_bool(payload.get('exact_match'), default=False)

            if not view_id and not view_name:
                return routes.Response(
                    status=400,
                    data={"status": "error", "error": "Provide either 'view_id' or 'view_name' in request."},
                )

            target_view = _find_view_by_id(doc, view_id)
            if not target_view and view_name:
                matches = _find_views_by_name(doc, view_name, exact_match=exact_match)
                matches = [view for view in matches if not getattr(view, "IsTemplate", False)]
                if len(matches) > 1:
                    return routes.Response(
                        status=300,
                        data=sanitize_for_json({
                            "status": "multiple_matches",
                            "message": "Multiple views match '{}'. Retry with view_id.".format(to_safe_ascii_text(view_name)),
                            "matching_views": [_build_view_summary(view) for view in matches[:25]],
                        }),
                    )
                if len(matches) == 1:
                    target_view = matches[0]

            if not target_view:
                return routes.Response(
                    status=404,
                    data={"status": "error", "error": "View not found. Provide view_id or view_name."},
                )

            if getattr(target_view, "IsTemplate", False):
                return routes.Response(
                    status=400,
                    data={"status": "error", "error": "View templates cannot be activated."},
                )

            previous_view = None
            try:
                previous_view = uidoc.ActiveView
            except Exception:
                previous_view = None

            try:
                uidoc.ActiveView = target_view
            except Exception as activate_error:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "Could not activate view '{}'. The view may not be openable in the current UI context.".format(
                            to_safe_ascii_text(target_view.Name)
                        ),
                        "details": str(activate_error),
                        "target_view": _build_view_summary(target_view),
                    }),
                )

            try:
                uidoc.RefreshActiveView()
            except Exception as refresh_error:
                route_logger.warning("Could not refresh activated view: {}".format(refresh_error))

            return sanitize_for_json({
                "status": "success",
                "message": "Activated view '{}'.".format(to_safe_ascii_text(target_view.Name)),
                "previous_view": _build_view_summary(previous_view) if previous_view else None,
                "active_view": _build_view_summary(target_view),
            })

        except Exception as e:
            route_logger.error("Error in activate_view: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while activating view.",
                    "details": str(e),
                }),
            )

    @api.route('/views/active/export_image', methods=['POST'])
    def handle_export_active_view_image(uidoc, doc, request):
        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc

        route_logger = script.get_logger()

        try:
            active_view = uidoc.ActiveView if uidoc else None
            if not active_view:
                return routes.Response(status=503, data={"status": "error", "error": "No active Revit view."})

            if getattr(active_view, "IsTemplate", False):
                return routes.Response(
                    status=400,
                    data={"status": "error", "error": "Active view is a template and cannot be exported as an image."},
                )

            payload = request.data if hasattr(request, 'data') else {}
            if payload is None or not isinstance(payload, dict):
                return routes.Response(status=400, data={"status": "error", "error": "Invalid JSON payload"})

            capture_dir = _ensure_capture_dir(payload.get("capture_dir"))
            image_file_type, extension, mime_type = _get_image_file_type(payload.get("format"))
            pixel_size = _bounded_int(payload.get("pixel_size"), 1600, min_value=256, max_value=4096)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            view_name_part = _safe_filename_component(active_view.Name)
            prefix = "active_view_{}_{}_{}".format(timestamp, active_view.Id.IntegerValue, view_name_part)
            file_prefix_path = os.path.join(capture_dir, prefix)

            before_files = _snapshot_capture_files(capture_dir)
            started_at = time.time()

            options = DB.ImageExportOptions()
            options.ExportRange = DB.ExportRange.SetOfViews
            options.FilePath = file_prefix_path
            options.HLRandWFViewsFileType = image_file_type
            options.ShadowViewsFileType = image_file_type

            view_ids = List[DB.ElementId]()
            view_ids.Add(active_view.Id)
            options.SetViewsAndSheets(view_ids)

            try:
                options.ZoomType = DB.ZoomFitType.FitToPage
            except Exception:
                pass
            try:
                options.PixelSize = pixel_size
            except Exception:
                pass
            try:
                options.FitDirection = DB.FitDirectionType.Horizontal
            except Exception:
                pass
            try:
                options.ImageResolution = DB.ImageResolution.DPI_150
            except Exception:
                pass

            doc.ExportImage(options)

            exported_path = _find_exported_image(capture_dir, before_files, prefix, started_at)
            if not exported_path:
                return routes.Response(
                    status=500,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "Revit completed image export but no exported image was found in the capture directory.",
                        "capture_dir": capture_dir,
                        "file_prefix": file_prefix_path,
                    }),
                )

            file_size = None
            try:
                file_size = os.path.getsize(exported_path)
            except Exception:
                file_size = None

            return sanitize_for_json({
                "status": "success",
                "message": "Exported active view '{}'.".format(to_safe_ascii_text(active_view.Name)),
                "artifact_type": "image",
                "image_path": os.path.abspath(exported_path),
                "mime_type": mime_type,
                "format": extension,
                "file_size_bytes": file_size,
                "capture_dir": capture_dir,
                "requested_pixel_size": pixel_size,
                "view": _build_view_summary(active_view),
            })

        except Exception as e:
            route_logger.error("Error in export_active_view_image: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while exporting active view image.",
                    "details": str(e),
                }),
            )

    @api.route('/views/duplicate', methods=['POST'])
    def handle_duplicate_view(uidoc, doc, request):
        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc

        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else None
            if not payload or not isinstance(payload, dict):
                return routes.Response(status=400, data={"status": "error", "error": "Invalid JSON payload"})

            view_id = payload.get('view_id') or payload.get('source_view_id')
            view_name = payload.get('view_name') or payload.get('source_view_name')
            exact_match = _coerce_bool(payload.get('exact_match'), default=False)
            duplicate_option, option_key = _get_view_duplicate_option(payload.get('duplicate_option'))
            new_name = payload.get('new_name')
            uniquify_name = _coerce_bool(payload.get('uniquify_name'), default=True)
            apply_template_id = payload.get('apply_template_id') or payload.get('view_template_id')
            activate = _coerce_bool(payload.get('activate'), default=False)

            if duplicate_option is None:
                return routes.Response(
                    status=400,
                    data={
                        "status": "error",
                        "error": "Unsupported duplicate_option '{}'. Use duplicate, with_detailing, or as_dependent.".format(option_key),
                    },
                )

            source_view = _find_view_by_id(doc, view_id)
            if not source_view and view_name:
                matches = _find_views_by_name(doc, view_name, exact_match=exact_match)
                if len(matches) > 1:
                    return routes.Response(
                        status=300,
                        data=sanitize_for_json({
                            "status": "multiple_matches",
                            "message": "Multiple views match '{}'. Retry with view_id.".format(view_name),
                            "matching_views": [
                                {
                                    "id": str(view.Id.IntegerValue),
                                    "name": to_safe_ascii_text(view.Name),
                                    "type": str(view.ViewType),
                                    "is_template": bool(getattr(view, "IsTemplate", False)),
                                }
                                for view in matches[:25]
                            ],
                        }),
                    )
                if len(matches) == 1:
                    source_view = matches[0]

            if not source_view and not view_id and not view_name and uidoc and uidoc.ActiveView:
                source_view = uidoc.ActiveView

            if not source_view:
                return routes.Response(
                    status=404,
                    data={"status": "error", "error": "Source view not found. Provide view_id or view_name."},
                )

            if getattr(source_view, "IsTemplate", False):
                return routes.Response(
                    status=400,
                    data={"status": "error", "error": "Source view is a template and cannot be duplicated as a model view."},
                )

            try:
                if not source_view.CanViewBeDuplicated(duplicate_option):
                    return routes.Response(
                        status=400,
                        data={
                            "status": "error",
                            "error": "View '{}' cannot be duplicated using option '{}'.".format(source_view.Name, option_key),
                        },
                    )
            except Exception as can_duplicate_error:
                return routes.Response(
                    status=400,
                    data={
                        "status": "error",
                        "error": "Could not verify whether the view can be duplicated.",
                        "details": str(can_duplicate_error),
                    },
                )

            target_template_id = None
            if apply_template_id:
                target_template = _find_view_by_id(doc, apply_template_id)
                if not target_template or not getattr(target_template, "IsTemplate", False):
                    return routes.Response(
                        status=400,
                        data={"status": "error", "error": "apply_template_id does not refer to a view template."},
                    )
                target_template_id = target_template.Id

            final_name = None
            if new_name:
                final_name = str(new_name).strip()
                if uniquify_name:
                    final_name = _unique_view_name(doc, final_name)
                elif _view_name_exists(doc, final_name):
                    return routes.Response(
                        status=400,
                        data={"status": "error", "error": "A view named '{}' already exists.".format(final_name)},
                    )

            transaction = DB.Transaction(doc, "Duplicate View")
            transaction.Start()
            try:
                new_view_id = source_view.Duplicate(duplicate_option)
                new_view = doc.GetElement(new_view_id)
                if final_name:
                    new_view.Name = final_name
                if target_template_id:
                    new_view.ViewTemplateId = target_template_id
                transaction.Commit()
            except Exception:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                raise

            if activate:
                try:
                    uidoc.ActiveView = new_view
                except Exception as activate_error:
                    route_logger.warning("Could not activate duplicated view: {}".format(activate_error))

            return sanitize_for_json({
                "status": "success",
                "message": "Duplicated view '{}' as '{}'.".format(source_view.Name, new_view.Name),
                "source_view": {
                    "id": str(source_view.Id.IntegerValue),
                    "name": to_safe_ascii_text(source_view.Name),
                    "type": str(source_view.ViewType),
                },
                "new_view": {
                    "id": str(new_view.Id.IntegerValue),
                    "name": to_safe_ascii_text(new_view.Name),
                    "type": str(new_view.ViewType),
                    "is_template": bool(getattr(new_view, "IsTemplate", False)),
                    "view_template_id": (
                        str(new_view.ViewTemplateId.IntegerValue)
                        if getattr(new_view, "ViewTemplateId", None) and new_view.ViewTemplateId != DB.ElementId.InvalidElementId
                        else None
                    ),
                },
                "duplicate_option": option_key,
                "activated": activate,
            })

        except Exception as e:
            route_logger.error("Error in duplicate_view: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while duplicating view.",
                    "details": str(e),
                }),
            )

    @api.route('/sheets/list_views', methods=['GET'])
    def handle_list_views(doc, request):
        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc
        """
        List all views in the current document that can be placed on sheets.

        Returns a list of views with their names, types, and IDs for reference.
        """
        route_logger = script.get_logger()

        try:
            lib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'RevitMCP_Tools')
            if lib_dir not in sys.path:
                sys.path.append(lib_dir)

            from sheet_placement_tool import get_view_type_name

            views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()

            view_list = []
            for view in views:
                try:
                    if not hasattr(view, 'Name') or not view.Name:
                        continue

                    if hasattr(view, 'IsTemplate') and view.IsTemplate:
                        continue

                    if hasattr(view, 'ViewType') and view.ViewType == DB.ViewType.DrawingSheet:
                        continue

                    can_be_placed = getattr(view, 'CanBePrinted', True)

                    is_on_sheet = False
                    sheet_name = None
                    if hasattr(view, 'Sheet') and view.Sheet and view.Sheet.Id != DB.ElementId.InvalidElementId:
                        is_on_sheet = True
                        sheet_name = getattr(view.Sheet, 'Name', 'Unknown Sheet')

                    view_info = {
                        "name": to_safe_ascii_text(view.Name),
                        "type": get_view_type_name(view, route_logger),
                        "id": str(view.Id.IntegerValue),
                        "can_be_placed": can_be_placed,
                        "is_on_sheet": is_on_sheet,
                        "sheet_name": to_safe_ascii_text(sheet_name) if sheet_name else None
                    }

                    view_list.append(view_info)

                except Exception as view_error:
                    route_logger.warning("Error processing view: {}".format(view_error))
                    continue

            view_list.sort(key=lambda x: (x["type"], x["name"]))

            route_logger.info("Found {} views in document".format(len(view_list)))

            return sanitize_for_json({
                "status": "success",
                "message": "Found {} views".format(len(view_list)),
                "count": len(view_list),
                "views": view_list
            })

        except Exception as e:
            route_logger.error("Error in list_views: {}".format(e), exc_info=True)
            return routes.Response(status=500, data={
                "error": "Internal server error",
                "details": str(e)
            })
