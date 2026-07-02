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
from routes.revit_compat import get_element_id_text, make_element_id


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
        element_id = make_element_id(DB, view_id)
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
        "id": get_element_id_text(view.Id),
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


def _bounding_box_corners(bbox):
    transform = getattr(bbox, "Transform", None) or DB.Transform.Identity
    min_pt = bbox.Min
    max_pt = bbox.Max
    corners = []
    for x in (min_pt.X, max_pt.X):
        for y in (min_pt.Y, max_pt.Y):
            for z in (min_pt.Z, max_pt.Z):
                corners.append(transform.OfPoint(DB.XYZ(x, y, z)))
    return corners


def _copy_section_box(section_box):
    copied = DB.BoundingBoxXYZ()
    copied.Transform = section_box.Transform
    copied.Min = section_box.Min
    copied.Max = section_box.Max
    copied.Enabled = section_box.Enabled
    return copied


def _build_section_box_for_elements(doc, view3d, element_ids, margin_feet):
    existing_box = view3d.GetSectionBox()
    section_transform = getattr(existing_box, "Transform", None) or DB.Transform.Identity
    inverse_transform = section_transform.Inverse
    local_points = []
    missing_bbox_ids = []

    for element_id in element_ids:
        element = doc.GetElement(element_id)
        if not element:
            continue

        bbox = None
        try:
            bbox = element.get_BoundingBox(view3d)
        except Exception:
            bbox = None
        if bbox is None:
            try:
                bbox = element.get_BoundingBox(None)
            except Exception:
                bbox = None
        if bbox is None:
            missing_bbox_ids.append(get_element_id_text(element_id))
            continue

        for point in _bounding_box_corners(bbox):
            local_points.append(inverse_transform.OfPoint(point))

    if not local_points:
        return None, missing_bbox_ids

    min_x = min(point.X for point in local_points) - margin_feet
    min_y = min(point.Y for point in local_points) - margin_feet
    min_z = min(point.Z for point in local_points) - margin_feet
    max_x = max(point.X for point in local_points) + margin_feet
    max_y = max(point.Y for point in local_points) + margin_feet
    max_z = max(point.Z for point in local_points) + margin_feet

    new_box = DB.BoundingBoxXYZ()
    new_box.Transform = section_transform
    new_box.Min = DB.XYZ(min_x, min_y, min_z)
    new_box.Max = DB.XYZ(max_x, max_y, max_z)
    return new_box, missing_bbox_ids


_SNAPSHOT_HIDE_CATEGORY_NAMES = (
    "OST_Levels",
    "OST_Grids",
    "OST_ReferencePlanes",
    "OST_SectionBox",
    "OST_VolumeOfInterest",
    "OST_Cameras",
    "OST_Elev",
    "OST_Sections",
)


def _apply_snapshot_view_cleanup(doc, view):
    state = {
        "annotation_categories_hidden": None,
        "category_hidden_states": [],
        "changed_count": 0,
    }

    try:
        state["annotation_categories_hidden"] = bool(view.AreAnnotationCategoriesHidden)
        if not state["annotation_categories_hidden"]:
            view.AreAnnotationCategoriesHidden = True
            state["changed_count"] += 1
    except Exception:
        state["annotation_categories_hidden"] = None

    for category_name in _SNAPSHOT_HIDE_CATEGORY_NAMES:
        try:
            built_in_category = getattr(DB.BuiltInCategory, category_name)
        except Exception:
            continue
        try:
            category = DB.Category.GetCategory(doc, built_in_category)
        except Exception:
            category = None
        if category is None:
            continue

        category_id = category.Id
        try:
            if hasattr(view, "CanCategoryBeHidden") and not view.CanCategoryBeHidden(category_id):
                continue
        except Exception:
            pass

        try:
            was_hidden = bool(view.GetCategoryHidden(category_id))
            state["category_hidden_states"].append((category_id, was_hidden))
            if not was_hidden:
                view.SetCategoryHidden(category_id, True)
                state["changed_count"] += 1
        except Exception:
            continue

    return state


def _restore_snapshot_view_cleanup(view, state):
    if not state:
        return

    for category_id, was_hidden in state.get("category_hidden_states", []):
        try:
            view.SetCategoryHidden(category_id, was_hidden)
        except Exception:
            pass

    annotation_categories_hidden = state.get("annotation_categories_hidden")
    if annotation_categories_hidden is not None:
        try:
            view.AreAnnotationCategoriesHidden = annotation_categories_hidden
        except Exception:
            pass


def _resolve_payload_element_ids(uidoc, doc, payload, use_active_selection_default=False):
    raw_ids = payload.get("element_ids")
    if raw_ids is None and payload.get("element_id") is not None:
        raw_ids = [payload.get("element_id")]

    use_active_selection = _coerce_bool(
        payload.get("use_active_selection"),
        default=(raw_ids is None and bool(use_active_selection_default)),
    )
    if raw_ids is None and use_active_selection:
        try:
            raw_ids = [get_element_id_text(element_id) for element_id in uidoc.Selection.GetElementIds()]
        except Exception:
            raw_ids = []

    if isinstance(raw_ids, (str, int)):
        raw_ids = [raw_ids]

    element_ids = List[DB.ElementId]()
    invalid_ids = []
    missing_ids = []

    if not isinstance(raw_ids, list) or not raw_ids:
        return (
            element_ids,
            invalid_ids,
            missing_ids,
            "Provide element_id/element_ids, or select elements in Revit and set use_active_selection=true.",
            use_active_selection,
        )

    for raw_id in raw_ids:
        try:
            element_id = make_element_id(DB, raw_id)
        except Exception:
            invalid_ids.append(str(raw_id))
            continue
        if doc.GetElement(element_id):
            element_ids.Add(element_id)
        else:
            missing_ids.append(str(raw_id))

    if element_ids.Count == 0:
        return element_ids, invalid_ids, missing_ids, "No valid existing elements were provided.", use_active_selection

    return element_ids, invalid_ids, missing_ids, None, use_active_selection


def _activate_view_from_payload(uidoc, doc, payload):
    view_id = payload.get("view_id")
    view_name = payload.get("view_name")
    target_view = None

    if view_id:
        target_view = _find_view_by_id(doc, view_id)
    if not target_view and view_name:
        exact_match = _coerce_bool(payload.get("exact_match"), default=False)
        matches = [
            view
            for view in _find_views_by_name(doc, view_name, exact_match=exact_match)
            if not getattr(view, "IsTemplate", False)
        ]
        if len(matches) > 1:
            return None, routes.Response(
                status=300,
                data=sanitize_for_json({
                    "status": "multiple_matches",
                    "message": "Multiple views match '{}'. Retry with view_id.".format(to_safe_ascii_text(view_name)),
                    "matching_views": [_build_view_summary(view) for view in matches[:25]],
                }),
            )
        if len(matches) == 1:
            target_view = matches[0]

    if target_view:
        try:
            uidoc.ActiveView = target_view
        except Exception as activate_error:
            return None, routes.Response(
                status=400,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Could not activate target view.",
                    "details": str(activate_error),
                    "target_view": _build_view_summary(target_view),
                }),
            )

    return target_view, None


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
            prefix = "active_view_{}_{}_{}".format(timestamp, get_element_id_text(active_view.Id), view_name_part)
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

    @api.route('/views/active/isolate_elements', methods=['POST'])
    def handle_isolate_elements_in_view(uidoc, doc, request):
        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc

        route_logger = script.get_logger()

        try:
            if uidoc is None:
                return routes.Response(status=503, data={"status": "error", "error": "No active Revit UI document."})

            payload = request.data if hasattr(request, 'data') else {}
            if payload is None or not isinstance(payload, dict):
                return routes.Response(status=400, data={"status": "error", "error": "Invalid JSON payload"})

            _target_view, activation_error = _activate_view_from_payload(uidoc, doc, payload)
            if activation_error is not None:
                return activation_error

            active_view = uidoc.ActiveView if uidoc else None
            if not active_view:
                return routes.Response(status=503, data={"status": "error", "error": "No active Revit view."})
            if getattr(active_view, "IsTemplate", False):
                return routes.Response(
                    status=400,
                    data={"status": "error", "error": "View templates cannot isolate elements."},
                )

            element_ids, invalid_ids, missing_ids, element_error, used_active_selection = _resolve_payload_element_ids(
                uidoc,
                doc,
                payload,
                use_active_selection_default=True,
            )
            if element_error:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": element_error,
                        "invalid_ids": invalid_ids,
                        "missing_ids": missing_ids,
                        "used_active_selection": used_active_selection,
                    }),
                )

            clear_existing = _coerce_bool(payload.get("clear_existing"), default=True)
            focus = _coerce_bool(payload.get("focus"), default=True)
            refresh_view = _coerce_bool(payload.get("refresh_view"), default=True)

            transaction = DB.Transaction(doc, "Temporary Isolate Elements")
            transaction.Start()
            try:
                if clear_existing:
                    try:
                        active_view.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate)
                    except Exception:
                        pass
                active_view.IsolateElementsTemporary(element_ids)
                transaction.Commit()
            except Exception:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                raise

            focus_result = None
            if focus:
                try:
                    uidoc.Selection.SetElementIds(element_ids)
                    uidoc.ShowElements(element_ids)
                    focus_result = "show_elements_applied"
                except Exception as focus_error:
                    focus_result = "show_elements_failed: {}".format(focus_error)

            refresh_result = None
            if refresh_view:
                try:
                    uidoc.RefreshActiveView()
                    refresh_result = "active_view_refreshed"
                except Exception as refresh_error:
                    refresh_result = "refresh_failed: {}".format(refresh_error)

            return sanitize_for_json({
                "status": "success",
                "message": "Temporarily isolated {} element(s) in view '{}'.".format(
                    element_ids.Count,
                    to_safe_ascii_text(active_view.Name),
                ),
                "view": _build_view_summary(active_view),
                "element_ids": [get_element_id_text(element_id) for element_id in element_ids],
                "isolated_count": element_ids.Count,
                "invalid_ids": invalid_ids,
                "missing_ids": missing_ids,
                "used_active_selection": used_active_selection,
                "clear_existing": clear_existing,
                "focus_result": focus_result,
                "refresh_result": refresh_result,
            })

        except Exception as e:
            route_logger.error("Error in isolate_elements_in_view: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while isolating elements in view.",
                    "details": str(e),
                }),
            )

    @api.route('/views/active/clear_temporary_isolate', methods=['POST'])
    def handle_clear_temporary_isolate(uidoc, doc, request):
        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc

        route_logger = script.get_logger()

        try:
            if uidoc is None:
                return routes.Response(status=503, data={"status": "error", "error": "No active Revit UI document."})

            payload = request.data if hasattr(request, 'data') else {}
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                return routes.Response(status=400, data={"status": "error", "error": "Invalid JSON payload"})

            _target_view, activation_error = _activate_view_from_payload(uidoc, doc, payload)
            if activation_error is not None:
                return activation_error

            active_view = uidoc.ActiveView if uidoc else None
            if not active_view:
                return routes.Response(status=503, data={"status": "error", "error": "No active Revit view."})

            temporary_isolate_was_active = None
            try:
                is_active = getattr(active_view, "IsTemporaryHideIsolateActive", None)
                if is_active is not None:
                    temporary_isolate_was_active = bool(is_active() if callable(is_active) else is_active)
            except Exception:
                temporary_isolate_was_active = None

            clear_applied = False
            transaction = DB.Transaction(doc, "Clear Temporary Isolate")
            transaction.Start()
            try:
                if temporary_isolate_was_active is not False:
                    active_view.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate)
                    clear_applied = True
                transaction.Commit()
            except Exception:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                raise

            refresh_result = None
            if _coerce_bool(payload.get("refresh_view"), default=True):
                try:
                    uidoc.RefreshActiveView()
                    refresh_result = "active_view_refreshed"
                except Exception as refresh_error:
                    refresh_result = "refresh_failed: {}".format(refresh_error)

            return sanitize_for_json({
                "status": "success",
                "message": "Cleared temporary hide/isolate in view '{}'.".format(to_safe_ascii_text(active_view.Name)),
                "view": _build_view_summary(active_view),
                "temporary_isolate_was_active": temporary_isolate_was_active,
                "clear_applied": clear_applied,
                "refresh_result": refresh_result,
            })

        except Exception as e:
            route_logger.error("Error in clear_temporary_isolate: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while clearing temporary hide/isolate.",
                    "details": str(e),
                }),
            )

    @api.route('/views/element_snapshot', methods=['POST'])
    def handle_export_element_snapshot(uidoc, doc, request):
        no_doc = _require_doc(doc)
        if no_doc is not None:
            return no_doc

        route_logger = script.get_logger()

        try:
            if uidoc is None:
                return routes.Response(status=503, data={"status": "error", "error": "No active Revit UI document."})

            payload = request.data if hasattr(request, 'data') else {}
            if payload is None or not isinstance(payload, dict):
                return routes.Response(status=400, data={"status": "error", "error": "Invalid JSON payload"})

            raw_ids = payload.get("element_ids")
            if raw_ids is None and payload.get("element_id") is not None:
                raw_ids = [payload.get("element_id")]
            use_active_selection = _coerce_bool(payload.get("use_active_selection"), default=raw_ids is None)
            if raw_ids is None and use_active_selection:
                try:
                    raw_ids = [get_element_id_text(element_id) for element_id in uidoc.Selection.GetElementIds()]
                except Exception:
                    raw_ids = []
            if isinstance(raw_ids, (str, int)):
                raw_ids = [raw_ids]
            if not isinstance(raw_ids, list) or not raw_ids:
                return routes.Response(
                    status=400,
                    data={
                        "status": "error",
                        "error": "Provide element_id/element_ids, or select elements in Revit and set use_active_selection=true.",
                    },
                )

            element_ids = List[DB.ElementId]()
            invalid_ids = []
            missing_ids = []
            for raw_id in raw_ids:
                try:
                    element_id = make_element_id(DB, raw_id)
                except Exception:
                    invalid_ids.append(str(raw_id))
                    continue
                if doc.GetElement(element_id):
                    element_ids.Add(element_id)
                else:
                    missing_ids.append(str(raw_id))

            if element_ids.Count == 0:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "No valid existing elements were provided.",
                        "invalid_ids": invalid_ids,
                        "missing_ids": missing_ids,
                    }),
                )

            target_view = None
            view_id = payload.get("view_id")
            view_name = payload.get("view_name")
            if view_id:
                target_view = _find_view_by_id(doc, view_id)
            if not target_view and view_name:
                exact_match = _coerce_bool(payload.get("exact_match"), default=False)
                matches = [view for view in _find_views_by_name(doc, view_name, exact_match=exact_match) if not getattr(view, "IsTemplate", False)]
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

            previous_view = None
            try:
                previous_view = uidoc.ActiveView
            except Exception:
                previous_view = None

            if target_view:
                try:
                    uidoc.ActiveView = target_view
                except Exception as activate_error:
                    return routes.Response(
                        status=400,
                        data=sanitize_for_json({
                            "status": "error",
                            "error": "Could not activate target view.",
                            "details": str(activate_error),
                            "target_view": _build_view_summary(target_view),
                        }),
                    )

            active_view = uidoc.ActiveView if uidoc else None
            if not active_view:
                return routes.Response(status=503, data={"status": "error", "error": "No active Revit view."})

            capture_dir = _ensure_capture_dir(payload.get("capture_dir"))
            image_file_type, extension, mime_type = _get_image_file_type(payload.get("format"))
            pixel_size = _bounded_int(payload.get("pixel_size"), 1600, min_value=256, max_value=4096)
            margin_mm = _bounded_int(payload.get("section_box_margin_mm"), 300, min_value=0, max_value=10000)
            margin_feet = float(margin_mm) / 304.8
            isolate = _coerce_bool(payload.get("isolate"), default=True)
            requested_section_box = _coerce_bool(payload.get("use_section_box"), default=True)
            active_view_is_3d = isinstance(active_view, DB.View3D)
            use_section_box = requested_section_box and active_view_is_3d
            section_box_skipped_reason = None
            if requested_section_box and not active_view_is_3d:
                section_box_skipped_reason = "Section boxes are only available in 3D views."
            hide_annotations = _coerce_bool(payload.get("hide_annotations"), default=True)

            original_section_box = None
            original_section_box_active = None
            snapshot_view_cleanup_state = None
            section_box_applied = False
            isolate_applied = False
            selection_cleared_before_export = False
            missing_bbox_ids = []

            try:
                try:
                    original_section_box_active = bool(active_view.IsSectionBoxActive)
                    original_section_box = _copy_section_box(active_view.GetSectionBox())
                except Exception:
                    original_section_box = None
                    original_section_box_active = None

                transaction = DB.Transaction(doc, "Prepare Element Snapshot")
                transaction.Start()
                try:
                    if hide_annotations:
                        snapshot_view_cleanup_state = _apply_snapshot_view_cleanup(doc, active_view)
                    if use_section_box:
                        section_box, missing_bbox_ids = _build_section_box_for_elements(doc, active_view, element_ids, margin_feet)
                        if section_box is not None:
                            active_view.SetSectionBox(section_box)
                            active_view.IsSectionBoxActive = True
                            section_box_applied = True
                    if isolate:
                        try:
                            active_view.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate)
                        except Exception:
                            pass
                        active_view.IsolateElementsTemporary(element_ids)
                        isolate_applied = True
                    transaction.Commit()
                except Exception:
                    try:
                        transaction.RollBack()
                    except Exception:
                        pass
                    raise

                try:
                    uidoc.Selection.SetElementIds(element_ids)
                    uidoc.ShowElements(element_ids)
                    uidoc.Selection.SetElementIds(List[DB.ElementId]())
                    selection_cleared_before_export = True
                    uidoc.RefreshActiveView()
                except Exception as focus_error:
                    route_logger.warning("Could not focus snapshot elements: {}".format(focus_error))

                timestamp = time.strftime("%Y%m%d_%H%M%S")
                first_id = get_element_id_text(element_ids[0])
                view_name_part = _safe_filename_component(active_view.Name)
                prefix = "element_snapshot_{}_{}_{}_{}".format(timestamp, first_id, get_element_id_text(active_view.Id), view_name_part)
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
                    "message": "Exported isolated element snapshot from view '{}'.".format(to_safe_ascii_text(active_view.Name)),
                    "artifact_type": "image",
                    "image_path": os.path.abspath(exported_path),
                    "mime_type": mime_type,
                    "format": extension,
                    "file_size_bytes": file_size,
                    "capture_dir": capture_dir,
                    "requested_pixel_size": pixel_size,
                    "element_ids": [get_element_id_text(element_id) for element_id in element_ids],
                    "invalid_ids": invalid_ids,
                    "missing_ids": missing_ids,
                    "missing_bbox_ids": missing_bbox_ids,
                    "isolate_applied": isolate_applied,
                    "section_box_requested": requested_section_box,
                    "section_box_applied": section_box_applied,
                    "section_box_skipped_reason": section_box_skipped_reason,
                    "section_box_margin_mm": margin_mm,
                    "hide_annotations": hide_annotations,
                    "selection_cleared_before_export": selection_cleared_before_export,
                    "annotation_cleanup_changed_count": (
                        snapshot_view_cleanup_state.get("changed_count", 0)
                        if snapshot_view_cleanup_state else 0
                    ),
                    "view": _build_view_summary(active_view),
                })
            finally:
                try:
                    cleanup = DB.Transaction(doc, "Restore Element Snapshot View")
                    cleanup.Start()
                    try:
                        if isolate_applied:
                            active_view.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate)
                        if original_section_box is not None:
                            active_view.SetSectionBox(original_section_box)
                        if original_section_box_active is not None:
                            active_view.IsSectionBoxActive = original_section_box_active
                        _restore_snapshot_view_cleanup(active_view, snapshot_view_cleanup_state)
                        cleanup.Commit()
                    except Exception:
                        try:
                            cleanup.RollBack()
                        except Exception:
                            pass
                        raise
                except Exception as cleanup_error:
                    route_logger.warning("Could not restore element snapshot view state: {}".format(cleanup_error))
                if previous_view and target_view:
                    try:
                        uidoc.ActiveView = previous_view
                    except Exception:
                        pass

        except Exception as e:
            route_logger.error("Error in element_snapshot: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while exporting element snapshot.",
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
                                    "id": get_element_id_text(view.Id),
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
                    "id": get_element_id_text(source_view.Id),
                    "name": to_safe_ascii_text(source_view.Name),
                    "type": str(source_view.ViewType),
                },
                "new_view": {
                    "id": get_element_id_text(new_view.Id),
                    "name": to_safe_ascii_text(new_view.Name),
                    "type": str(new_view.ViewType),
                    "is_template": bool(getattr(new_view, "IsTemplate", False)),
                    "view_template_id": (
                        get_element_id_text(new_view.ViewTemplateId)
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
                        "id": get_element_id_text(view.Id),
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
