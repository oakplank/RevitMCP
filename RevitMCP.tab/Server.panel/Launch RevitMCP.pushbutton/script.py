# RevitMCP: This script runs in pyRevit (IronPython). Use Python 2.7 syntax (no f-strings, use 'except Exception, e:').
#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""Starts the RevitMCP External CPython Server."""

# pyRevit automatically adds the extension's 'lib' folder to sys.path.
# Modules (RevitMCP_RevitListener, RevitMCP_UI) placed in 'lib' are directly importable.

print("pyRevit Button: Launch RevitMCP - Attempting to load UI manager...")

import sys
import traceback # Import traceback module

try:
    from RevitMCP_UI import ui_manager 
    print("[LaunchRevitMCPBtn] Successfully imported ui_manager. Calling start_external_server...")
    ui_manager.start_external_server()
    print("[LaunchRevitMCPBtn] ui_manager.start_external_server() called.")
    # from pyrevit import forms
    # forms.alert("External Server start initiated. Check console for details.", title="RevitMCP")
except ImportError as ie:
    print("ERROR [LaunchRevitMCPBtn] ImportError occurred:")
    print(str(ie))
    # For ImportError, traceback might point to the problematic import line
    formatted_traceback = traceback.format_exc()
    print(formatted_traceback)
    try:
        from pyrevit import forms
        forms.alert(
            message="Failed to import RevitMCP UI module.\n\nImportError: {}\n\nTraceback:\n{}\n\nCheck pyRevit logs for full details.".format(str(ie), formatted_traceback),
            title="RevitMCP Import Error"
        )
    except:
        pass # Ignore if forms alert fails

except SyntaxError as se:
    print("ERROR [LaunchRevitMCPBtn] SyntaxError occurred:")
    # SyntaxError objects have filename, lineno, offset, text attributes
    error_details = "File: {}\nLine: {}\nOffset: {}\nLine Content: {}\nError: {}".format(
        se.filename,
        se.lineno,
        se.offset,
        se.text,
        str(se)
    )
    print(error_details)
    formatted_traceback = traceback.format_exc()
    print(formatted_traceback)
    try:
        from pyrevit import forms
        forms.alert(
            message="A SyntaxError occurred in the RevitMCP scripts.\n\n{}".format(error_details),
            title="RevitMCP Syntax Error"
        )
    except:
        pass # Ignore if forms alert fails

except Exception as e:
    print("ERROR [LaunchRevitMCPBtn] An unexpected error occurred:")
    error_type = type(e).__name__
    error_message = str(e)
    formatted_traceback = traceback.format_exc()
    print("Error Type: {}".format(error_type))
    print("Error Message: {}".format(error_message))
    print("Traceback:")
    print(formatted_traceback)
    try:
        from pyrevit import forms
        forms.alert(
            message="An unexpected error occurred.\n\nType: {}\nMessage: {}\n\nTraceback:\n{}\n\nCheck pyRevit logs for full details.".format(error_type, error_message, formatted_traceback),
            title="RevitMCP Error"
        )
    except:
        pass # Ignore if forms alert fails
    # from pyrevit import forms
    # forms.alert("An unexpected error occurred in RevitMCP.\nError: {}".format(e), title="RevitMCP Error")
