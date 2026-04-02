# RevitMCP: This script runs in pyRevit (IronPython).
# -*- coding: UTF-8 -*-
"""
Revit API Utilities - common functions for Revit API interactions.
"""

try:
    import Autodesk
    # It's good practice to get all BuiltInCategory names once
    BUILT_IN_CATEGORIES = {name: getattr(Autodesk.Revit.DB.BuiltInCategory, name) for name in dir(Autodesk.Revit.DB.BuiltInCategory) if not name.startswith("_") and name != "INVALID"}
except ImportError:
    print("ERROR (revit_api_utils): Revit API modules not found. This script must run in Revit.")
    BUILT_IN_CATEGORIES = {} # Placeholder

def get_bic_by_name(category_name_str, logger):
    """Tries to get a BuiltInCategory enum value from a string name."""
    # 0. Normalize initial input slightly (e.g. trim spaces)
    normalized_category_name = category_name_str.strip()

    # 1. Direct match (e.g., if user provides "OST_Windows")
    if normalized_category_name in BUILT_IN_CATEGORIES:
        logger.debug("RevitAPIUtils: Category found by direct match: '{}'.".format(normalized_category_name))
        return BUILT_IN_CATEGORIES[normalized_category_name]

    # 2. Try OST_ + various casings of the provided name if it doesn't already start with OST_
    if not normalized_category_name.startswith("OST_"):
        variations_to_try = [
            "OST_" + normalized_category_name,                  # OST_Windows (if input is Windows)
            "OST_" + normalized_category_name.title().replace(" ", ""), # OST_DoorKnobs (if input is door knobs)
            "OST_" + normalized_category_name.upper().replace(" ", ""),  # OST_DOORKNOBS
            "OST_" + normalized_category_name.lower().replace(" ", "")   # ost_doorknobs (less common for BIC names but try)
        ]
        for var in variations_to_try:
            if var in BUILT_IN_CATEGORIES:
                logger.debug("RevitAPIUtils: Category found as variation: '{}' from input '{}'.".format(var, category_name_str))
                return BUILT_IN_CATEGORIES[var]

    # 3. Handle simple pluralization attempts (e.g., Walls -> Wall, Doors -> Door)
    singular_forms = []
    temp_name = normalized_category_name
    if temp_name.endswith("s"): # General plural
        singular_forms.append(temp_name[:-1])
    if temp_name.endswith("es"): # e.g. Matches -> Match
        singular_forms.append(temp_name[:-2])
    if temp_name.lower().endswith("ies"): # e.g. Categories -> Category
        singular_forms.append(temp_name[:-3] + "y")
        singular_forms.append(temp_name[:-3] + "Y") 

    for singular in singular_forms:
        singular_variations = [
            "OST_" + singular,
            "OST_" + singular.title().replace(" ", ""),
            "OST_" + singular.upper().replace(" ", ""),
            "OST_" + singular.lower().replace(" ", "")
        ]
        for var in singular_variations:
            if var in BUILT_IN_CATEGORIES:
                logger.debug("RevitAPIUtils: Category found by singularization: '{}' from input '{}'.".format(var, category_name_str))
                return BUILT_IN_CATEGORIES[var]
    
    if normalized_category_name.startswith("OST_"):
        pass

    logger.warning("RevitAPIUtils: Could not find BuiltInCategory for input '{}' after trying several variations.".format(category_name_str))
    return None 