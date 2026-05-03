# RevitMCP: Element operation HTTP routes
# -*- coding: UTF-8 -*-

import System
from pyrevit import routes, script, DB
from System.Collections.Generic import List

from routes.json_safety import sanitize_for_json


try:
    STRING_TYPES = (basestring,)
except NameError:
    STRING_TYPES = (str,)


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


def _bounded_int(value, default, min_value=None, max_value=None):
    try:
        number = int(value)
    except Exception:
        number = default
    if min_value is not None:
        number = max(min_value, number)
    if max_value is not None:
        number = min(max_value, number)
    return number


def _normalize_element_ids(raw_ids):
    if raw_ids is None:
        return [], []
    if isinstance(raw_ids, STRING_TYPES):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, (list, tuple)):
        return [], [str(raw_ids)]

    valid_values = []
    invalid_values = []
    seen = set()
    for raw_id in raw_ids:
        try:
            element_id_value = int(str(raw_id).strip())
        except Exception:
            invalid_values.append(str(raw_id))
            continue
        if element_id_value in seen:
            continue
        seen.add(element_id_value)
        valid_values.append(element_id_value)
    return valid_values, invalid_values


def _resolve_existing_element_ids(doc, raw_ids):
    element_id_values, invalid_ids = _normalize_element_ids(raw_ids)
    existing_ids = List[DB.ElementId]()
    existing_values = []
    missing_ids = []

    for element_id_value in element_id_values:
        element_id = DB.ElementId(element_id_value)
        try:
            element = doc.GetElement(element_id)
        except Exception:
            element = None
        if element:
            existing_ids.Add(element_id)
            existing_values.append(str(element_id_value))
        else:
            missing_ids.append(str(element_id_value))

    return existing_ids, existing_values, missing_ids, invalid_ids


def _safe_element_name(element):
    try:
        name = getattr(element, "Name", None)
        if name:
            return str(name)
    except Exception:
        pass

    try:
        return str(element.Id.IntegerValue)
    except Exception:
        return ""


def _build_delete_candidate_summary(doc, element_id):
    element = doc.GetElement(element_id)
    if not element:
        return None

    category_name = None
    try:
        if element.Category and element.Category.Name:
            category_name = element.Category.Name
    except Exception:
        category_name = None

    pinned = False
    can_unpin = False
    try:
        pinned = bool(element.Pinned)
        can_unpin = True
    except Exception:
        pinned = False
        can_unpin = False

    group_id = None
    try:
        if element.GroupId and element.GroupId != DB.ElementId.InvalidElementId:
            group_id = str(element.GroupId.IntegerValue)
    except Exception:
        group_id = None

    design_option_id = None
    try:
        if element.DesignOption and element.DesignOption.Id:
            design_option_id = str(element.DesignOption.Id.IntegerValue)
    except Exception:
        design_option_id = None

    type_id = None
    try:
        element_type_id = element.GetTypeId()
        if element_type_id and element_type_id != DB.ElementId.InvalidElementId:
            type_id = str(element_type_id.IntegerValue)
    except Exception:
        type_id = None

    warnings = []
    if pinned:
        warnings.append("Element is pinned; deletion may require unpin_before_delete=true.")
    if group_id:
        warnings.append("Element is in a group; Revit may block direct deletion.")
    if design_option_id:
        warnings.append("Element is in a design option; active option/editability may affect deletion.")

    return {
        "element_id": str(element_id.IntegerValue),
        "name": _safe_element_name(element),
        "category": category_name,
        "type_id": type_id,
        "pinned": pinned,
        "can_unpin": can_unpin,
        "group_id": group_id,
        "design_option_id": design_option_id,
        "warnings": warnings,
    }


def _parse_color(value):
    if value is None:
        return None, None

    if isinstance(value, dict):
        raw_components = [value.get("r"), value.get("g"), value.get("b")]
    elif isinstance(value, (list, tuple)) and len(value) >= 3:
        raw_components = [value[0], value[1], value[2]]
    else:
        return None, "color must be an object with r/g/b or an RGB array."

    components = []
    for raw_component in raw_components:
        try:
            component = int(raw_component)
        except Exception:
            return None, "color values must be integers from 0 to 255."
        if component < 0 or component > 255:
            return None, "color values must be integers from 0 to 255."
        components.append(component)

    return components, None


def _get_solid_fill_pattern_id(doc):
    try:
        for pattern_element in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement).ToElements():
            pattern = pattern_element.GetFillPattern()
            if pattern and pattern.IsSolidFill:
                return pattern_element.Id
    except Exception:
        pass
    return DB.ElementId.InvalidElementId


def _apply_color_override_settings(override_settings, color_components, solid_fill_pattern_id):
    if not color_components:
        return

    color = DB.Color(
        System.Byte(color_components[0]),
        System.Byte(color_components[1]),
        System.Byte(color_components[2]),
    )

    setter_names = [
        "SetProjectionLineColor",
        "SetCutLineColor",
        "SetSurfaceForegroundPatternColor",
        "SetSurfaceBackgroundPatternColor",
        "SetCutForegroundPatternColor",
    ]
    for setter_name in setter_names:
        try:
            getattr(override_settings, setter_name)(color)
        except Exception:
            pass

    if solid_fill_pattern_id and solid_fill_pattern_id != DB.ElementId.InvalidElementId:
        pattern_setters = [
            "SetSurfaceForegroundPatternId",
            "SetCutForegroundPatternId",
        ]
        for setter_name in pattern_setters:
            try:
                getattr(override_settings, setter_name)(solid_fill_pattern_id)
            except Exception:
                pass
        try:
            override_settings.SetSurfaceForegroundPatternVisible(True)
        except Exception:
            pass


def _build_override_settings(doc, payload):
    reset = _coerce_bool(payload.get("reset"), default=False)
    if reset:
        return DB.OverrideGraphicSettings(), None

    color_components, color_error = _parse_color(payload.get("color"))
    if color_error:
        return None, color_error

    has_transparency = payload.get("transparency") is not None
    has_halftone = payload.get("halftone") is not None
    if not color_components and not has_transparency and not has_halftone:
        return None, "Provide color, transparency, halftone, or reset=true."

    override_settings = DB.OverrideGraphicSettings()
    _apply_color_override_settings(override_settings, color_components, _get_solid_fill_pattern_id(doc))

    if has_transparency:
        transparency = _bounded_int(payload.get("transparency"), 0, min_value=0, max_value=100)
        try:
            override_settings.SetSurfaceTransparency(transparency)
        except Exception as transparency_error:
            return None, "Failed to configure transparency: {}".format(transparency_error)

    if has_halftone:
        try:
            override_settings.SetHalftone(_coerce_bool(payload.get("halftone"), default=False))
        except Exception as halftone_error:
            return None, "Failed to configure halftone: {}".format(halftone_error)

    return override_settings, None


def register_routes(api):
    @api.route('/elements/override_graphics', methods=['POST'])
    def handle_override_element_graphics(uidoc, doc, request):
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else {}
            if payload is None or not isinstance(payload, dict):
                return routes.Response(status=400, data={"status": "error", "error": "Invalid JSON payload"})

            active_view = uidoc.ActiveView if uidoc else None
            if not active_view:
                return routes.Response(status=503, data={"status": "error", "error": "No active Revit view"})

            if getattr(active_view, "IsTemplate", False):
                return routes.Response(
                    status=400,
                    data={
                        "status": "error",
                        "error": "Active view is a template. Element overrides must be applied in a model view.",
                    },
                )

            existing_ids, existing_values, missing_ids, invalid_ids = _resolve_existing_element_ids(
                doc,
                payload.get("element_ids"),
            )

            if existing_ids.Count == 0:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "No valid existing elements were provided.",
                        "missing_ids": missing_ids,
                        "invalid_ids": invalid_ids,
                    }),
                )

            override_settings, override_error = _build_override_settings(doc, payload)
            if override_error:
                return routes.Response(status=400, data={"status": "error", "error": override_error})

            refresh_view = _coerce_bool(payload.get("refresh_view"), default=True)
            focus = _coerce_bool(payload.get("focus"), default=False)
            reset = _coerce_bool(payload.get("reset"), default=False)

            applied_ids = []
            failed = []

            transaction_name = "Reset Element Graphic Overrides" if reset else "Override Element Graphics"
            transaction = DB.Transaction(doc, transaction_name)
            transaction.Start()
            try:
                for element_id in existing_ids:
                    try:
                        active_view.SetElementOverrides(element_id, override_settings)
                        applied_ids.append(str(element_id.IntegerValue))
                    except Exception as element_error:
                        failed.append({
                            "element_id": str(element_id.IntegerValue),
                            "error": str(element_error),
                        })
                transaction.Commit()
            except Exception:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                raise

            focus_result = None
            if focus and applied_ids:
                try:
                    uidoc.ShowElements(existing_ids)
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
                "status": "success" if not failed else "partial_success",
                "message": "{} graphic overrides for {} elements in active view '{}'.".format(
                    "Reset" if reset else "Applied",
                    len(applied_ids),
                    active_view.Name,
                ),
                "view": {
                    "id": str(active_view.Id.IntegerValue),
                    "name": active_view.Name,
                    "type": str(active_view.ViewType),
                },
                "requested_count": len(existing_values) + len(missing_ids) + len(invalid_ids),
                "applied_count": len(applied_ids),
                "applied_ids": applied_ids,
                "missing_ids": missing_ids,
                "invalid_ids": invalid_ids,
                "failed": failed,
                "reset": reset,
                "focus_result": focus_result,
                "refresh_result": refresh_result,
            })

        except Exception as e:
            route_logger.error("Error in /elements/override_graphics: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while overriding element graphics.",
                    "details": str(e),
                }),
            )

    @api.route('/elements/delete', methods=['POST'])
    def handle_delete_elements(doc, request):
        route_logger = script.get_logger()

        try:
            payload = request.data if hasattr(request, 'data') else {}
            if payload is None or not isinstance(payload, dict):
                return routes.Response(status=400, data={"status": "error", "error": "Invalid JSON payload"})

            existing_ids, existing_values, missing_ids, invalid_ids = _resolve_existing_element_ids(
                doc,
                payload.get("element_ids"),
            )

            dry_run = _coerce_bool(payload.get("dry_run"), default=True)
            confirm_delete = _coerce_bool(payload.get("confirm_delete"), default=False)
            max_count = _bounded_int(payload.get("max_count"), 25, min_value=1, max_value=500)
            unpin_before_delete = _coerce_bool(payload.get("unpin_before_delete"), default=False)
            deletion_mode = str(payload.get("deletion_mode") or "individual").strip().lower()
            if deletion_mode not in ("individual", "batch"):
                deletion_mode = "individual"

            if existing_ids.Count == 0:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "No valid existing elements were provided.",
                        "missing_ids": missing_ids,
                        "invalid_ids": invalid_ids,
                    }),
                )

            if existing_ids.Count > max_count:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "Refusing to delete {} elements because max_count is {}.".format(existing_ids.Count, max_count),
                        "candidate_count": existing_ids.Count,
                        "max_count": max_count,
                        "dry_run": dry_run,
                        "unpin_before_delete": unpin_before_delete,
                        "deletion_mode": deletion_mode,
                    }),
                )

            candidates = []
            for element_id in existing_ids:
                candidate = _build_delete_candidate_summary(doc, element_id)
                if candidate:
                    candidates.append(candidate)

            candidate_summary = {
                "status": "dry_run" if dry_run else "pending_delete",
                "message": "{} valid elements are candidates for deletion.".format(existing_ids.Count),
                "candidate_count": existing_ids.Count,
                "candidate_ids": existing_values,
                "candidates": candidates,
                "missing_ids": missing_ids,
                "invalid_ids": invalid_ids,
                "max_count": max_count,
                "dry_run": dry_run,
                "confirm_delete": confirm_delete,
                "unpin_before_delete": unpin_before_delete,
                "deletion_mode": deletion_mode,
            }

            if dry_run:
                candidate_summary["next_step"] = (
                    "Call again with dry_run=false and confirm_delete=true to delete these elements. "
                    "Use unpin_before_delete=true if the candidates are pinned and direct deletion is intended."
                )
                return sanitize_for_json(candidate_summary)

            if not confirm_delete:
                return routes.Response(
                    status=400,
                    data=sanitize_for_json({
                        "status": "error",
                        "error": "Deletion requires confirm_delete=true. Run with dry_run=true first to inspect candidates.",
                        "candidate_count": existing_ids.Count,
                        "candidate_ids": existing_values,
                        "unpin_before_delete": unpin_before_delete,
                        "deletion_mode": deletion_mode,
                    }),
                )

            deleted_values = []
            deleted_input_ids = []
            failed = []
            skipped = []
            unpinned_ids = []

            if deletion_mode == "batch":
                transaction = DB.Transaction(doc, "Delete Elements")
                transaction.Start()
                try:
                    if unpin_before_delete:
                        for element_id in existing_ids:
                            element = doc.GetElement(element_id)
                            if element:
                                try:
                                    if bool(element.Pinned):
                                        element.Pinned = False
                                        unpinned_ids.append(str(element_id.IntegerValue))
                                except Exception:
                                    pass
                    deleted_ids = doc.Delete(existing_ids)
                    transaction.Commit()
                    deleted_input_ids = list(existing_values)
                    try:
                        for deleted_id in deleted_ids:
                            deleted_values.append(str(deleted_id.IntegerValue))
                    except Exception:
                        deleted_values = []
                except Exception as batch_error:
                    try:
                        transaction.RollBack()
                    except Exception:
                        pass
                    return routes.Response(
                        status=400,
                        data=sanitize_for_json({
                            "status": "error",
                            "error": "Batch deletion failed. Retry with deletion_mode='individual' to isolate failures.",
                            "details": str(batch_error),
                            "candidate_count": existing_ids.Count,
                            "candidate_ids": existing_values,
                            "candidates": candidates,
                            "missing_ids": missing_ids,
                            "invalid_ids": invalid_ids,
                            "dry_run": False,
                            "confirm_delete": True,
                            "unpin_before_delete": unpin_before_delete,
                            "deletion_mode": deletion_mode,
                        }),
                    )
            else:
                for element_id in existing_ids:
                    element_id_text = str(element_id.IntegerValue)
                    if not doc.GetElement(element_id):
                        skipped.append({
                            "element_id": element_id_text,
                            "reason": "Element no longer exists; it may have been deleted as a dependent of another input.",
                        })
                        continue

                    transaction = DB.Transaction(doc, "Delete Element {}".format(element_id_text))
                    transaction.Start()
                    try:
                        element = doc.GetElement(element_id)
                        if not element:
                            transaction.RollBack()
                            skipped.append({
                                "element_id": element_id_text,
                                "reason": "Element no longer exists.",
                            })
                            continue

                        if unpin_before_delete:
                            try:
                                if bool(element.Pinned):
                                    element.Pinned = False
                                    unpinned_ids.append(element_id_text)
                            except Exception as unpin_error:
                                route_logger.warning("Could not unpin element {} before delete: {}".format(element_id_text, unpin_error))

                        single_id_list = List[DB.ElementId]()
                        single_id_list.Add(element_id)
                        deleted_ids = doc.Delete(single_id_list)
                        transaction.Commit()
                        deleted_input_ids.append(element_id_text)
                        try:
                            for deleted_id in deleted_ids:
                                deleted_values.append(str(deleted_id.IntegerValue))
                        except Exception:
                            pass
                    except Exception as element_error:
                        try:
                            transaction.RollBack()
                        except Exception:
                            pass
                        failed.append({
                            "element_id": element_id_text,
                            "error": str(element_error),
                        })

            status = "success"
            if failed and deleted_input_ids:
                status = "partial_success"
            elif failed and not deleted_input_ids:
                status = "error"

            return sanitize_for_json({
                "status": status,
                "message": "Deleted {} of {} input elements; Revit reported {} total deleted elements including dependents.".format(
                    len(deleted_input_ids),
                    existing_ids.Count,
                    len(deleted_values),
                ),
                "requested_count": len(existing_values) + len(missing_ids) + len(invalid_ids),
                "candidate_count": existing_ids.Count,
                "deleted_input_count": len(deleted_input_ids),
                "deleted_total_count": len(deleted_values),
                "deleted_ids": deleted_values,
                "deleted_input_ids": deleted_input_ids,
                "input_element_ids": existing_values,
                "missing_ids": missing_ids,
                "invalid_ids": invalid_ids,
                "failed": failed,
                "skipped": skipped,
                "unpinned_ids": unpinned_ids,
                "candidates": candidates,
                "dry_run": False,
                "confirm_delete": True,
                "unpin_before_delete": unpin_before_delete,
                "deletion_mode": deletion_mode,
            })

        except Exception as e:
            route_logger.error("Error in /elements/delete: {}".format(e), exc_info=True)
            return routes.Response(
                status=500,
                data=sanitize_for_json({
                    "status": "error",
                    "error": "Internal server error while deleting elements.",
                    "details": str(e),
                }),
            )
