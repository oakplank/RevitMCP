# RevitMCP: This script runs in pyRevit (IronPython).
# -*- coding: UTF-8 -*-
"""
Tool for finding elements in Revit based on category and parameter values.
"""
import sys # For sys.exc_info()
from revit_api_utils import get_bic_by_name # Import from the new utility file

try:
    import Autodesk
    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        ElementId,
        ParameterValueProvider,
        FilterStringRule,
        FilterDoubleRule,
        FilterIntegerRule,
        FilterElementIdRule,
        FilterNumericEquals,
        FilterNumericGreater,
        FilterNumericGreaterOrEqual, # Though our match types are strict <, >
        FilterNumericLess,
        FilterNumericLessOrEqual,  # Though our match types are strict <, >
        FilterRule, # Corrected from FilterRuleبازنگری
        ElementParameterFilter,
        LogicalAndFilter
    )
    from System.Collections.Generic import List # For List[ElementId]
    # BUILT_IN_CATEGORIES is now managed in revit_api_utils.py

except ImportError:
    print("ERROR (element_filter_tools): Revit API modules not found. This script must run in Revit.")
    # BUILT_IN_CATEGORIES = {} # Placeholder is in revit_api_utils

def find_elements(doc, uidoc, category_name_str, parameter_name_str, parameter_value_str, match_type_str, logger):
    """
    Finds elements in Revit based on category, parameter, and value.

    Args:
        doc (Autodesk.Revit.DB.Document): Active Revit Document.
        uidoc (Autodesk.Revit.UIDocument): Active Revit UIDocument.
        category_name_str (str): Name of the category (e.g., "Windows", "OST_Walls").
        parameter_name_str (str): Name of the parameter.
        parameter_value_str (str): Value to match (will be converted as needed).
        match_type_str (str): "equals", "contains", "startswith", "endswith", 
                                "greater_than", "less_than", "is_empty", "is_not_empty".
        logger: Logger instance.

    Returns:
        tuple: (response_dict, status_code)
               response_dict has {"status": "success/error", "message": "...", 
                                  "data": {"found_element_ids": [...], "count": X, "details": "..."}}
    """
    if not doc:
        logger.error("ElementFilterTool: Document is not available.")
        return {"status": "error", "message": "Revit document not accessible."}, 500

    if not match_type_str: # Handles None or empty string
        logger.info("ElementFilterTool: match_type was None or empty, defaulting to 'equals'.")
        match_type_str = "equals"

    logger.info("ElementFilterTool: Received find_elements request. Category: '{}', Param: '{}', Value: '{}', Match: '{}'".format(
        category_name_str, parameter_name_str, parameter_value_str, match_type_str
    ))

    built_in_category = get_bic_by_name(category_name_str, logger)
    if not built_in_category:
        return {"status": "error", "message": "Category '{}' not found or not recognized.".format(category_name_str)}, 400

    collector = FilteredElementCollector(doc).OfCategory(built_in_category).WhereElementIsNotElementType()
    
    # For "is_empty" and "is_not_empty", parameter_value_str is ignored.
    # These types of filters are harder with ElementParameterFilter directly if the parameter might not exist on all elements.
    # A common approach is to iterate or use a more complex filter setup.
    # For now, we'll focus on value-based matching. Handling 'is_empty' / 'is_not_empty' robustly may require iteration.

    # First, get a sample element to determine parameter type
    # This is crucial for choosing the correct FilterRule and parsing parameter_value_str
    first_element = collector.FirstElement()
    if not first_element:
        logger.info("ElementFilterTool: No elements found in category '{}' to check for parameter '{}'.".format(category_name_str, parameter_name_str))
        return {"status": "success", "message": "No elements found in category '{}'.".format(category_name_str), "data": {"found_element_ids": [], "count": 0, "details": "Category is empty or contains only element types."}}, 200

    param = first_element.LookupParameter(parameter_name_str)
    if not param: # Parameter doesn't exist on the first sampled element
        # Check if it's a built-in parameter by trying to get its ID
        # This is more complex as BuiltInParameter enum names don't always match display names
        # For simplicity, we'll assume if LookupParameter fails, it's not a common/easily accessible param.
        logger.warning("ElementFilterTool: Parameter '{}' not found on a sample element of category '{}'.".format(parameter_name_str, category_name_str))
        # We could try to find a BuiltInParameter enum value here, but it's non-trivial
        # For now, if LookupParameter by name fails, we report it.
        elements_with_param = []
        all_elements_in_category = list(collector)
        for el in all_elements_in_category:
            if el.LookupParameter(parameter_name_str):
                elements_with_param.append(el)
        if not elements_with_param:
            return {"status": "error", "message": "Parameter '{}' not found on any elements in category '{}'.".format(parameter_name_str, category_name_str)}, 400
        # If some elements have it, we proceed but it's less efficient as we can't use ElementParameterFilter directly before iteration.
        # For now, let's assume ElementParameterFilter is the primary goal.
        # A more robust implementation would iterate if the direct filter approach is problematic.
        # For now, returning an error if the first element doesn't have it, to simplify filter rule creation
        return {"status": "error", "message": "Parameter '{}' not found on a sample element of category '{}'. Cannot reliably create filter rule.".format(parameter_name_str, category_name_str)}, 400


    param_storage_type = param.Definition.ParameterType # In IronPython, this is ParameterType not StorageType for the rule
                                                        # StorageType is for getting value (AsString, AsDouble etc)
    
    filter_rule = None
    parsed_value_for_rule = None

    try:
        # Determine the ElementId of the parameter for filter rule creation
        param_element_id_for_rule = None
        if param.IsShared:
            param_element_id_for_rule = param.Id # This is SharedParameterElementId
            logger.debug("ElementFilterTool: Parameter '{}' is Shared. Using param.Id: {}".format(parameter_name_str, param_element_id_for_rule.IntegerValue))
        elif param.Definition.BuiltInParameter != Autodesk.Revit.DB.BuiltInParameter.INVALID:
            param_element_id_for_rule = ElementId(param.Definition.BuiltInParameter)
            logger.debug("ElementFilterTool: Parameter '{}' is BuiltInParameter {}. Using ElementId: {}".format(parameter_name_str, param.Definition.BuiltInParameter, param_element_id_for_rule.IntegerValue))
        else: # Could be a project parameter (not shared, not BIP)
            if hasattr(param, 'Id') and isinstance(param.Id, ElementId) and param.Id.IntegerValue != -1:
                param_element_id_for_rule = param.Id
                logger.debug("ElementFilterTool: Parameter '{}' is likely Project Parameter. Using param.Id: {}".format(parameter_name_str, param_element_id_for_rule.IntegerValue))
            elif hasattr(param.Definition, 'Id') and isinstance(param.Definition.Id, ElementId) and param.Definition.Id.IntegerValue != -1:
                param_element_id_for_rule = param.Definition.Id
                logger.debug("ElementFilterTool: Parameter '{}' is likely Project Parameter. Using param.Definition.Id: {}".format(parameter_name_str, param_element_id_for_rule.IntegerValue))

        if not param_element_id_for_rule or param_element_id_for_rule.IntegerValue == -1:
            # Attempt to get BIP by name as a last resort if other methods failed (e.g. for some definition-only params)
            # This is less reliable but can be a fallback.
            bip_name_guess = param.Definition.Name.upper().replace(" ", "_").replace("-", "_")
            if hasattr(Autodesk.Revit.DB.BuiltInParameter, bip_name_guess):
                try:
                    bip_enum_val = getattr(Autodesk.Revit.DB.BuiltInParameter, bip_name_guess)
                    if bip_enum_val != Autodesk.Revit.DB.BuiltInParameter.INVALID:
                        param_element_id_for_rule = ElementId(bip_enum_val)
                        logger.warning("ElementFilterTool: Resolved parameter '{}' to BuiltInParameter {} by name guess as a fallback.".format(parameter_name_str, bip_enum_val))
                except Exception as e_bip_guess:
                    logger.debug("ElementFilterTool: Failed to guess BIP for '{}' ({}): {}".format(parameter_name_str, bip_name_guess, e_bip_guess))

        if not param_element_id_for_rule or param_element_id_for_rule.IntegerValue == -1:
            logger.error("ElementFilterTool: Could not determine a valid ElementId for parameter '{}' for use in a filter rule.".format(parameter_name_str))
            return {"status": "error", "message": "Could not resolve parameter ID for '{}'. It might be a type not directly filterable or its definition ID was not found.".format(parameter_name_str)}, 501
        
        # Common setup for value provider, done once param_element_id_for_rule is confirmed
        value_provider = ParameterValueProvider(param_element_id_for_rule)

        if match_type_str in ["is_empty", "is_not_empty"]:
            # These require iterating elements as ElementParameterFilter doesn't directly support "has value" or "is null"
            # We will perform a manual iteration later for these cases.
            logger.info("ElementFilterTool: Match type '{}' requires manual iteration.".format(match_type_str))
            # filter_rule remains None, handled later by iterating elements
        
        elif param_storage_type == Autodesk.Revit.DB.ParameterType.Text: # String
            parsed_value_for_rule = parameter_value_str
            # Parameter ID determination is now done above more robustly
            # value_provider = ParameterValueProvider(param_element_id_for_rule) # Moved up

            if match_type_str == "equals":
                filter_rule = FilterStringRule(value_provider, Autodesk.Revit.DB.FilterStringEquals(), parsed_value_for_rule, False) # False for case-insensitive
            elif match_type_str == "contains":
                filter_rule = FilterStringRule(value_provider, Autodesk.Revit.DB.FilterStringContains(), parsed_value_for_rule, False)
            elif match_type_str == "startswith":
                filter_rule = FilterStringRule(value_provider, Autodesk.Revit.DB.FilterStringBeginsWith(), parsed_value_for_rule, False)
            elif match_type_str == "endswith":
                filter_rule = FilterStringRule(value_provider, Autodesk.Revit.DB.FilterStringEndsWith(), parsed_value_for_rule, False)
            else:
                logger.warning("ElementFilterTool: Unsupported match_type '{}' for Text parameter '{}'.".format(match_type_str, parameter_name_str))
                return {"status": "error", "message": "Unsupported match_type '{}' for Text parameter '{}'.".format(match_type_str, parameter_name_str)}, 400

        elif param_storage_type == Autodesk.Revit.DB.ParameterType.Integer or param_storage_type == Autodesk.Revit.DB.ParameterType.YesNo:
            try:
                parsed_value_for_rule = int(parameter_value_str)
                if param_storage_type == Autodesk.Revit.DB.ParameterType.YesNo:
                     parsed_value_for_rule = 1 if parsed_value_for_rule else 0 # Normalize boolean to 0 or 1 for filtering
            except ValueError:
                logger.warning("ElementFilterTool: Could not parse '{}' as integer for parameter '{}'.".format(parameter_value_str, parameter_name_str))
                return {"status": "error", "message": "Parameter value '{}' for '{}' must be a valid integer (or 0/1 for Yes/No).".format(parameter_value_str, parameter_name_str)}, 400
            
            # Parameter ID determination is now done above more robustly
            # value_provider = ParameterValueProvider(param_element_id_for_rule) # Moved up

            if match_type_str == "equals":
                filter_rule = FilterIntegerRule(value_provider, FilterNumericEquals(), parsed_value_for_rule)
            elif match_type_str == "greater_than":
                filter_rule = FilterIntegerRule(value_provider, FilterNumericGreater(), parsed_value_for_rule)
            elif match_type_str == "less_than":
                filter_rule = FilterIntegerRule(value_provider, FilterNumericLess(), parsed_value_for_rule)
            else:
                logger.warning("ElementFilterTool: Unsupported match_type '{}' for Integer/YesNo parameter '{}'.".format(match_type_str, parameter_name_str))
                return {"status": "error", "message": "Unsupported match_type '{}' for Integer/YesNo parameter '{}'.".format(match_type_str, parameter_name_str)}, 400

        elif param_storage_type == Autodesk.Revit.DB.ParameterType.Number or param_storage_type == Autodesk.Revit.DB.ParameterType.Length or param_storage_type == Autodesk.Revit.DB.ParameterType.Angle: # Double / Number
            try:
                parsed_value_for_rule = float(parameter_value_str)
            except ValueError:
                logger.warning("ElementFilterTool: Could not parse '{}' as float/number for parameter '{}'.".format(parameter_value_str, parameter_name_str))
                return {"status": "error", "message": "Parameter value '{}' for '{}' must be a valid number.".format(parameter_value_str, parameter_name_str)}, 400

            # Parameter ID determination is now done above more robustly
            # value_provider = ParameterValueProvider(param_element_id_for_rule) # Moved up
            epsilon = 0.000001 

            if match_type_str == "equals":
                filter_rule = FilterDoubleRule(value_provider, FilterNumericEquals(), parsed_value_for_rule, epsilon)
            elif match_type_str == "greater_than":
                filter_rule = FilterDoubleRule(value_provider, FilterNumericGreater(), parsed_value_for_rule, epsilon)
            elif match_type_str == "less_than":
                filter_rule = FilterDoubleRule(value_provider, FilterNumericLess(), parsed_value_for_rule, epsilon)
            else:
                logger.warning("ElementFilterTool: Unsupported match_type '{}' for Number parameter '{}'.".format(match_type_str, parameter_name_str))
                return {"status": "error", "message": "Unsupported match_type '{}' for Number parameter '{}'.".format(match_type_str, parameter_name_str)}, 400
        
        # TODO: Add support for ElementId parameters (e.g. Level, Phase)
        # This would involve FilterElementIdRule and converting parameter_value_str to an ElementId

        else:
            logger.warning("ElementFilterTool: Parameter type '{}' for parameter '{}' is not yet supported for direct filtering.".format(param_storage_type, parameter_name_str))
            return {"status": "error", "message": "Filtering by parameter type '{}' ('{}') is not yet supported.".format(param_storage_type, parameter_name_str)}, 501

    except Exception as e_rule:
        logger.error("ElementFilterTool: Error creating filter rule for param '{}', type '{}': {}".format(parameter_name_str, param_storage_type, e_rule), exc_info=True)
        return {"status": "error", "message": "Error preparing filter for parameter '{}': {}".format(parameter_name_str, e_rule)}, 500

    found_element_ids = []
    if filter_rule:
        ep_filter = ElementParameterFilter(filter_rule)
        collector.WherePasses(ep_filter)
        found_elements = list(collector) # Execute the collector
        for el in found_elements:
            found_element_ids.append(str(el.Id.IntegerValue))
        details_msg = "Filtered using ElementParameterFilter."
    elif match_type_str in ["is_empty", "is_not_empty"]:
        # Manual iteration for is_empty / is_not_empty
        all_elements_in_category = list(collector.ToElements()) # Get all elements if no primary filter rule was made
        logger.info("ElementFilterTool: Manually iterating {} elements for '{}' on parameter '{}'".format(len(all_elements_in_category), match_type_str, parameter_name_str))
        for el in all_elements_in_category:
            p = el.LookupParameter(parameter_name_str)
            has_value = False
            if p: # Parameter exists
                if p.StorageType == Autodesk.Revit.DB.StorageType.String:
                    has_value = bool(p.AsString()) # True if not None and not empty string
                elif p.StorageType == Autodesk.Revit.DB.StorageType.ElementId:
                    has_value = p.AsElementId() is not None and p.AsElementId().IntegerValue != -1
                else: # For numbers, 0 is a value. Check HasValue.
                    has_value = p.HasValue
            
            if match_type_str == "is_empty" and not has_value:
                found_element_ids.append(str(el.Id.IntegerValue))
            elif match_type_str == "is_not_empty" and has_value:
                found_element_ids.append(str(el.Id.IntegerValue))
        details_msg = "Filtered by manual iteration for {}.".format(match_type_str)

    else: # Should not happen if logic is correct, but as a fallback
        logger.warning("ElementFilterTool: No filter rule created and not an is_empty/is_not_empty case. This indicates an issue.")
        return {"status": "error", "message": "Internal error: No filter condition was applied."}, 500


    count = len(found_element_ids)
    logger.info("ElementFilterTool: Found {} elements matching criteria.".format(count))

    return {
        "status": "success", 
        "message": "Found {} elements. {}".format(count, details_msg),
        "data": {
            "found_element_ids": found_element_ids, 
            "count": count,
            "category_searched": category_name_str,
            "parameter_name_searched": parameter_name_str,
            "parameter_value_searched": parameter_value_str,
            "match_type_used": match_type_str
        }
    }, 200 