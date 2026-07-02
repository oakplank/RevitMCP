# RevitMCP: Revit API compatibility helpers
# -*- coding: UTF-8 -*-

try:
    import System
except Exception:
    System = None

try:
    TEXT_TYPES = (basestring,)
except NameError:
    TEXT_TYPES = (str,)


def get_element_id_value(element_id):
    """Return an ElementId integer value across Revit 2023 and 2024+."""
    if element_id is None:
        return None

    for attr_name in ("Value", "IntegerValue"):
        try:
            return int(getattr(element_id, attr_name))
        except Exception:
            pass

    try:
        return int(str(element_id))
    except Exception:
        return None


def get_element_id_text(element_id):
    value = get_element_id_value(element_id)
    if value is not None:
        return str(value)
    if element_id is None:
        return None
    try:
        return str(element_id)
    except Exception:
        return None


def make_element_id(db_or_element_id_class, value):
    """Create a DB.ElementId while avoiding Revit 2024+ IronPython overload ambiguity."""
    element_id_class = getattr(db_or_element_id_class, "ElementId", db_or_element_id_class)

    try:
        if isinstance(value, element_id_class):
            return value
    except Exception:
        pass

    if value is None:
        raise ValueError("ElementId value is required.")

    if isinstance(value, TEXT_TYPES):
        text = value.strip()
        if not text:
            raise ValueError("ElementId value is empty.")
        value = int(text)
    else:
        value = int(value)

    if System is not None:
        try:
            return element_id_class(System.Int64(value))
        except Exception:
            pass

    return element_id_class(value)
