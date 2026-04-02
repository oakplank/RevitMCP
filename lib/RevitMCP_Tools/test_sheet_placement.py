# RevitMCP: This script runs in pyRevit (IronPython).
# -*- coding: UTF-8 -*-
"""
Test script for Sheet Placement Tool functionality.
This can be run from the pyRevit Python shell to test the functionality.
"""

try:
    from sheet_placement_tool import (
        find_views_by_name,
        get_titleblock_family_symbols,
        find_next_sheet_number,
        get_view_type_name,
        place_view_on_new_sheet
    )
    from pyrevit import script
    
    # Test with current Revit document
    logger = script.get_logger()
    
    def test_sheet_placement():
        """
        Test the sheet placement functionality with the current document.
        """
        try:
            # Get current document
            current_uiapp = __revit__
            if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
                print("ERROR: No active UI document")
                return
            
            doc = current_uiapp.ActiveUIDocument.Document
            print("Testing with document: {}".format(doc.PathName or "Unsaved Document"))
            
            # Test 1: Find views
            print("\n=== TEST 1: Finding Views ===")
            views = find_views_by_name(doc, "detail", logger, exact_match=False)
            print("Found {} views matching 'detail'".format(len(views)))
            for view in views[:3]:  # Show first 3
                print("  - {} ({})".format(view.Name, get_view_type_name(view, logger)))
            
            # Test 2: Get titleblocks
            print("\n=== TEST 2: Getting Titleblocks ===")
            titleblocks = get_titleblock_family_symbols(doc, logger)
            print("Found {} titleblock family symbols".format(len(titleblocks)))
            for tb in titleblocks:
                print("  - {} - {}".format(tb.Family.Name, tb.Name))
            
            # Test 3: Next sheet numbering
            print("\n=== TEST 3: Sheet Numbering ===")
            next_detail = find_next_sheet_number(doc, "Detail", logger)
            next_section = find_next_sheet_number(doc, "Section", logger)
            print("Next Detail sheet: {}".format(next_detail))
            print("Next Section sheet: {}".format(next_section))
            
            # Test 4: Full placement test (commented out to avoid actually creating sheets)
            print("\n=== TEST 4: Full Placement Test (Dry Run) ===")
            print("To test full placement, uncomment the lines below and specify a real view name:")
            # result = place_view_on_new_sheet(doc, "Level 1", logger, exact_match=False)
            # print("Placement result: {}".format(result))
            
            print("\n=== ALL TESTS COMPLETED ===")
            
        except Exception as e:
            print("ERROR in test: {}".format(e))
            logger.error("Test error: {}".format(e), exc_info=True)
    
    # Run the test
    test_sheet_placement()
    
except ImportError as ie:
    print("ERROR importing modules: {}".format(ie))
except Exception as e:
    print("ERROR: {}".format(e)) 