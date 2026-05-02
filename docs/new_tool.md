# RevitMCP New Tool Creation Guide

## Overview
This guide explains how to create new tools for RevitMCP and properly interface with the Revit API through pyRevit routes.

## Key Requirements for Revit API Success

### 1. Essential Imports
Always include these imports at the top of `startup.py`:

```python
from pyrevit import routes, script, DB
from System.Collections.Generic import List  # CRITICAL for .NET collections
```

### 2. Function Signature Rules

**✅ CORRECT:**
```python
@api.route('/your_endpoint', methods=['POST'])
def handle_your_endpoint(request):
    # Single parameter only!
```

**❌ WRONG:**
```python
@api.route('/your_endpoint', methods=['POST'])
def handle_your_endpoint(doc, request_data):
    # Multiple parameters don't work with pyRevit routes
```

### 3. Document Access Pattern

**✅ CORRECT:**
```python
def handle_your_endpoint(request):
    # Always access document through __revit__ global
    current_uiapp = __revit__
    if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
        return routes.Response(status=503, data={"error": "No active UI document"})
    
    uidoc = current_uiapp.ActiveUIDocument
    doc = uidoc.Document
```

**❌ WRONG:**
```python
def handle_your_endpoint(doc, request_data):
    # Don't expect doc to be injected - it won't work
```

### 4. .NET Collection Conversion

**✅ CORRECT:**
```python
# When passing collections to Revit API
element_ids = [el.Id for el in elements]

# Convert Python list to .NET collection
element_ids_collection = List[DB.ElementId]()
for eid in element_ids:
    element_ids_collection.Add(eid)

uidoc.Selection.SetElementIds(element_ids_collection)
```

**❌ WRONG:**
```python
# Python lists cause "expected ICollection[ElementId], got list" errors
element_ids = [el.Id for el in elements]
uidoc.Selection.SetElementIds(element_ids)  # FAILS
```

## Step-by-Step Tool Creation

### Step 1: Define Your Route
Add your new route to the `startup.py` file inside the `try` block:

```python
@api.route('/your_new_tool', methods=['POST'])
def handle_your_new_tool(request):
    """
    Your tool description here.
    
    Args:
        request (routes.Request): Object containing request details.
    """
    route_logger = script.get_logger()
    
    # Your implementation here
```

### Step 2: Handle Request Data
```python
try:
    # Access JSON payload
    payload = request.data if hasattr(request, 'data') else None
    
    if not payload or not isinstance(payload, dict):
        return routes.Response(status=400, data={"error": "Invalid JSON payload"})
    
    # Extract required parameters
    param_value = payload.get('parameter_name')
    if not param_value:
        return routes.Response(status=400, data={"error": "Missing 'parameter_name'"})
        
except Exception as e:
    route_logger.error("Error processing request: {}".format(e))
    return routes.Response(status=500, data={"error": "Request processing failed"})
```

### Step 3: Access Revit Document
```python
try:
    # Get active document
    current_uiapp = __revit__
    if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
        return routes.Response(status=503, data={"error": "No active UI document"})
    
    uidoc = current_uiapp.ActiveUIDocument
    doc = uidoc.Document
    
    if not doc:
        return routes.Response(status=503, data={"error": "No active document"})
        
except Exception as e:
    route_logger.error("Error accessing document: {}".format(e))
    return routes.Response(status=500, data={"error": "Document access failed"})
```

### Step 4: Revit API Operations
```python
try:
    # Example: Filter elements by category
    if hasattr(DB.BuiltInCategory, category_name):
        built_in_category = getattr(DB.BuiltInCategory, category_name)
    else:
        # Handle category name variations
        possible_ost = "OST_" + category_name.replace(" ", "")
        if hasattr(DB.BuiltInCategory, possible_ost):
            built_in_category = getattr(DB.BuiltInCategory, possible_ost)
        else:
            return routes.Response(status=400, data={"error": "Invalid category"})
    
    # Collect elements
    elements = DB.FilteredElementCollector(doc)\
                 .OfCategory(built_in_category)\
                 .WhereElementIsNotElementType()\
                 .ToElements()
    
    # Process results...
    
except Exception as e:
    route_logger.error("Revit API error: {}".format(e), exc_info=True)
    return routes.Response(status=500, data={"error": "Revit operation failed"})
```

### Step 5: Return Response
```python
# Success response
return {
    "status": "success",
    "message": "Operation completed",
    "data": your_data,
    "count": len(your_data)
}

# Or error response
return routes.Response(
    status=400, 
    data={"error": "Operation failed", "details": error_details}
)
```

### Step 6: Add Route Registration
At the end of your route function, add:

```python
logger.info("Route /your_new_tool for API 'revit-mcp-v1' defined in startup.py.")
```

## Complete Template Example

```python
@api.route('/get_elements_by_type', methods=['POST'])
def handle_get_elements_by_type(request):
    """
    Gets elements by element type name.
    
    Expected payload: {"type_name": "Basic Wall"}
    """
    route_logger = script.get_logger()
    
    try:
        # 1. Handle request data
        payload = request.data if hasattr(request, 'data') else None
        if not payload or not isinstance(payload, dict):
            return routes.Response(status=400, data={"error": "Invalid JSON payload"})
        
        type_name = payload.get('type_name')
        if not type_name:
            return routes.Response(status=400, data={"error": "Missing 'type_name'"})
        
        # 2. Access Revit document
        current_uiapp = __revit__
        if not hasattr(current_uiapp, 'ActiveUIDocument') or not current_uiapp.ActiveUIDocument:
            return routes.Response(status=503, data={"error": "No active UI document"})
        
        uidoc = current_uiapp.ActiveUIDocument
        doc = uidoc.Document
        
        # 3. Revit API operations
        elements = DB.FilteredElementCollector(doc)\
                     .WhereElementIsNotElementType()\
                     .ToElements()
        
        matching_elements = []
        for el in elements:
            el_type = doc.GetElement(el.GetTypeId())
            if el_type and el_type.Name == type_name:
                matching_elements.append({
                    "id": el.Id.IntegerValue,
                    "name": el.Name if hasattr(el, 'Name') else "Unnamed",
                    "type": el_type.Name
                })
        
        # 4. Return response
        route_logger.info("Found {} elements of type '{}'".format(len(matching_elements), type_name))
        return {
            "status": "success",
            "message": "Found {} elements of type '{}'".format(len(matching_elements), type_name),
            "elements": matching_elements,
            "count": len(matching_elements)
        }
        
    except Exception as e:
        route_logger.critical("Error in get_elements_by_type: {}".format(e), exc_info=True)
        return routes.Response(status=500, data={"error": "Internal server error", "details": str(e)})

logger.info("Route /get_elements_by_type for API 'revit-mcp-v1' defined in startup.py.")
```

## Common Pitfalls to Avoid

### 1. Collection Type Errors
- **Problem:** `expected ICollection[ElementId], got list`
- **Solution:** Always convert Python lists to .NET collections before passing to Revit API

### 2. Function Signature Errors  
- **Problem:** `'request_data' object is None`
- **Solution:** Use single `request` parameter, not multiple parameters

### 3. Document Access Errors
- **Problem:** Expecting `doc` to be injected automatically
- **Solution:** Always use `__revit__.ActiveUIDocument.Document` pattern

### 4. Category Name Issues
- **Problem:** Category not found errors
- **Solution:** Handle both "Windows" and "OST_Windows" formats

### 5. Missing Error Handling
- **Problem:** Unhandled exceptions crash the route
- **Solution:** Wrap all operations in try-catch blocks with proper logging

## Testing Your New Tool

1. Add your route to `startup.py`
2. Restart Revit to reload the extension
3. Test your endpoint via the MCP server
4. Check logs for any errors
5. Verify the response format matches expectations

## Best Practices

1. **Always use route_logger**: `route_logger = script.get_logger()`
2. **Validate inputs early**: Check payload structure first
3. **Handle missing documents**: Always check for active document
4. **Use descriptive error messages**: Help debug issues quickly
5. **Log important operations**: Track what your tool is doing
6. **Return consistent response format**: Use standard success/error structure
7. **Test with edge cases**: Empty selections, missing elements, etc.

This template ensures your new tools will work reliably with the Revit API through RevitMCP! 