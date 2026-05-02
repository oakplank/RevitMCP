# RevitMCP: JSON serialization helpers for pyRevit/IronPython route responses
# -*- coding: UTF-8 -*-

try:
    TEXT_TYPES = (basestring,)
except NameError:
    TEXT_TYPES = (str,)

try:
    UNICODE_TYPE = unicode
except NameError:
    UNICODE_TYPE = str


def _decode_bytes(value):
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return value.decode(encoding)
        except Exception:
            continue
    try:
        return value.decode("utf-8", "replace")
    except Exception:
        return UNICODE_TYPE(value)


def to_safe_ascii_text(value):
    """Convert text-like values to ASCII-only text for older pyRevit JSON serializers."""
    if value is None:
        return ""

    if isinstance(value, bytes):
        text = _decode_bytes(value)
    else:
        try:
            text = UNICODE_TYPE(value)
        except Exception:
            try:
                text = repr(value)
            except Exception:
                return ""

    try:
        ascii_bytes = text.encode("ascii", "backslashreplace")
    except Exception:
        ascii_bytes = UNICODE_TYPE(text).encode("ascii", "replace")

    try:
        return ascii_bytes.decode("ascii")
    except Exception:
        return ascii_bytes


def sanitize_for_json(value):
    """Recursively sanitize route payload content before pyRevit serializes it."""
    if value is None:
        return None

    if isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out[to_safe_ascii_text(key)] = sanitize_for_json(item)
        return out

    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_json(item) for item in value]

    return to_safe_ascii_text(value)
