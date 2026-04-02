# RevitMCP: This script runs in pyRevit (IronPython).
# -*- coding: UTF-8 -*-
"""
Tool for exporting Revit views as images.
"""
import sys
import os
import base64
import tempfile

try:
    import Autodesk
    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        ViewFamilyType,
        ViewType,
        ImageExportOptions,
        ImageFileType,
        ExportRange
    )
    # script and logger from pyrevit are not directly used in this specific tool function,
    # but if this file were to have other utilities or its own logger, it might be here.
    # The logger is passed into the main function from the route handler.
except ImportError:
    print("ERROR (view_export_tool): Revit API modules not found. This script must run in Revit.")
    # Define placeholders for critical DB items if needed for linting/standalone analysis,
    # though the tool is useless outside Revit.
    class Autodesk:
        class Revit:
            class DB:
                FilteredElementCollector = None
                ViewFamilyType = None
                ViewType = None
                ImageExportOptions = None
                ImageFileType = None
                ExportRange = None

def export_named_view(doc, view_name_to_export, logger):
    """
    Exports a specific Revit view by name to a temporary image file,
    reads it as base64, and then cleans up the file.

    Args:
        doc: The current Revit document.
        view_name_to_export (str): The name of the view to export.
        logger: A logger instance for logging messages.

    Returns:
        tuple: (response_dict, status_code)
               response_dict contains {"status": "success", "message": "View exported.", "image_data": "base64_string"}
               or {"status": "error", "message": "Error details..."}
    """
    if not doc:
        logger.error("ViewExportTool: Document is not available.")
        return {"status": "error", "message": "Revit document not accessible."}, 500

    if not view_name_to_export:
        logger.warning("ViewExportTool: No view name provided for export.")
        return {"status": "error", "message": "View name not provided for export."}, 400

    logger.info("ViewExportTool: Attempting to export view: '{}'".format(view_name_to_export))

    # Find the view
    view_to_export = None
    try:
        collector = FilteredElementCollector(doc).OfClass(Autodesk.Revit.DB.View)
        for v_element in collector:
            # Some elements might not have a Name property (e.g. certain view templates or subtypes)
            # Or we only care about views that can be exported (ViewPlan, ViewSection, View3D, etc.)
            if hasattr(v_element, 'Name') and v_element.Name == view_name_to_export and v_element.CanBePrinted:
                view_to_export = v_element
                break
    except Exception as e_collect:
        logger.error("ViewExportTool: Error while collecting views: {}".format(e_collect), exc_info=True)
        return {"status": "error", "message": "Error collecting views: {}".format(e_collect)}, 500

    if not view_to_export:
        logger.warning("ViewExportTool: View '{}' not found or cannot be printed.".format(view_name_to_export))
        return {"status": "error", "message": "View '{}' not found or cannot be printed.".format(view_name_to_export)}, 404

    logger.info("ViewExportTool: Found view '{}' (ID: {}). Proceeding with export.".format(view_name_to_export, view_to_export.Id))

    # Setup export options
    export_options = ImageExportOptions()
    export_options.ZoomType = ExportRange.ZoomToFit
    export_options.PixelSize = 1024  # Define a reasonable pixel size
    export_options.ImageResolution = 72 # DPI, 72 is common for screen
    export_options.ShadowViews = False # No shadows for faster export, can be parameterized if needed
    export_options.HLRandWFViews = True # Hidden Line Removal and Wireframe Views
    export_options.ExportFormat = ImageFileType.PNG # PNG is good for web
    
    # Create a temporary file path
    temp_dir = tempfile.gettempdir()
    # Ensure a unique name to avoid collisions if multiple users/sessions run this
    temp_file_name = "revit_view_export_{}_{}.png".format(view_to_export.Id.ToString().replace("-","_"), os.getpid())
    export_options.FilePath = os.path.join(temp_dir, temp_file_name)

    # Check if the view can be exported with these options
    if not ImageExportOptions.IsValidForView(export_options, view_to_export):
        logger.error("ViewExportTool: Export options are not valid for the selected view '{}'.".format(view_name_to_export))
        return {"status": "error", "message": "Export options are not valid for view '{}'.".format(view_name_to_export)}, 400

    base64_image_data = None
    try:
        logger.info("ViewExportTool: Exporting view to temporary file: {}".format(export_options.FilePath))
        doc.ExportImage(export_options)
        logger.info("ViewExportTool: View exported successfully to temporary file.")

        # Read the image file and encode as base64
        with open(export_options.FilePath, "rb") as image_file:
            base64_image_data = base64.b64encode(image_file.read()).decode('utf-8')
        logger.info("ViewExportTool: Image file read and encoded to base64.")

    except Exception as e_export:
        logger.error("ViewExportTool: Error during image export or encoding for view '{}': {}".format(view_name_to_export, e_export), exc_info=True)
        return {"status": "error", "message": "Error exporting or encoding view '{}': {}".format(view_name_to_export, e_export)}, 500
    finally:
        # Clean up the temporary file
        if os.path.exists(export_options.FilePath):
            try:
                os.remove(export_options.FilePath)
                logger.info("ViewExportTool: Temporary export file '{}' deleted.".format(export_options.FilePath))
            except Exception as e_cleanup:
                logger.warning("ViewExportTool: Failed to delete temporary export file '{}': {}".format(export_options.FilePath, e_cleanup))
    
    if base64_image_data:
        return {
            "status": "success", 
            "message": "View '{}' exported successfully.".format(view_name_to_export),
            "image_data": base64_image_data,
            "view_id": view_to_export.Id.ToString(), # Include view ID for reference
            "view_name": view_name_to_export
        }, 200
    else:
        # This case should ideally be caught by earlier specific errors
        logger.error("ViewExportTool: Image data was not generated for view '{}', but no specific exception was caught.".format(view_name_to_export))
        return {"status": "error", "message": "Failed to generate image data for view '{}'.".format(view_name_to_export)}, 500 