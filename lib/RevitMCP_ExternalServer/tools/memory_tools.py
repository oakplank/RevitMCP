from RevitMCP_ExternalServer.core.runtime_config import bounded_int
from RevitMCP_ExternalServer.tools.registry import ToolDefinition


GET_MEMORY_CONTEXT_TOOL_NAME = "get_revit_memory_context"
SAVE_MEMORY_NOTE_TOOL_NAME = "save_revit_memory_note"

MEMORY_NOTE_TYPES = [
    "workflow_hint",
    "category_mapping",
    "family_mapping",
    "parameter_mapping",
    "model_context",
    "user_preference",
]
MEMORY_NOTE_SCOPES = ["project", "global"]
MEMORY_CONTEXT_SCOPES = ["auto", "project", "global", "all"]


def get_revit_memory_context_handler(
    services,
    query: str = "",
    scope: str = "auto",
    max_notes: int = 8,
    note_type: str = None,
    **_kwargs,
) -> dict:
    safe_scope = str(scope or "auto").strip().lower()
    if safe_scope not in MEMORY_CONTEXT_SCOPES:
        return {
            "status": "error",
            "message": "Unsupported memory scope '{}'. Supported values: {}.".format(scope, ", ".join(MEMORY_CONTEXT_SCOPES)),
        }

    safe_max_notes = bounded_int(max_notes, 8, min_value=1, max_value=20)
    project_context = services.memory_store.get_current_project_context(services)
    notes = services.memory_store.list_notes(
        query_text=query,
        scope=safe_scope,
        project_context=project_context,
        max_notes=safe_max_notes,
        note_type=note_type,
    )
    services.memory_store.touch_notes([note.get("note_id") for note in notes])

    result = {
        "status": "success",
        "count": len(notes),
        "query": str(query or ""),
        "scope": safe_scope,
        "note_type": note_type,
        "project_context": project_context,
        "notes": notes,
        "message": "Loaded {} memory note(s) from '{}' scope.".format(len(notes), safe_scope),
    }
    return result


def save_revit_memory_note_handler(
    services,
    title: str,
    content: str,
    note_type: str = "workflow_hint",
    scope: str = "project",
    keywords: list[str] = None,
    **_kwargs,
) -> dict:
    normalized_scope = str(scope or "project").strip().lower()
    if normalized_scope not in MEMORY_NOTE_SCOPES:
        return {
            "status": "error",
            "message": "Unsupported note scope '{}'. Supported values: {}.".format(scope, ", ".join(MEMORY_NOTE_SCOPES)),
        }

    normalized_type = str(note_type or "workflow_hint").strip().lower()
    if normalized_type not in MEMORY_NOTE_TYPES:
        return {
            "status": "error",
            "message": "Unsupported note_type '{}'. Supported values: {}.".format(note_type, ", ".join(MEMORY_NOTE_TYPES)),
        }

    normalized_title = str(title or "").strip()
    normalized_content = str(content or "").strip()
    if not normalized_title or not normalized_content:
        return {"status": "error", "message": "title and content are required."}

    project_context = services.memory_store.get_current_project_context(services) if normalized_scope == "project" else {}
    note, created = services.memory_store.save_note(
        title=normalized_title,
        content=normalized_content,
        note_type=normalized_type,
        scope=normalized_scope,
        keywords=keywords,
        project_context=project_context,
    )

    return {
        "status": "success",
        "created": created,
        "note_id": note.get("note_id"),
        "note": note,
        "message": "{} memory note '{}' in {} scope.".format(
            "Saved" if created else "Updated",
            normalized_title,
            normalized_scope,
        ),
    }


def build_memory_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=GET_MEMORY_CONTEXT_TOOL_NAME,
            description=(
                "Loads persistent Revit user/project memory notes. Use this before repeating category, family, "
                "parameter, or workflow clarification questions when the project may already have known conventions."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "scope": {"type": "string", "enum": MEMORY_CONTEXT_SCOPES},
                    "max_notes": {"type": "integer"},
                    "note_type": {"type": "string", "enum": MEMORY_NOTE_TYPES},
                },
            },
            handler=get_revit_memory_context_handler,
        ),
        ToolDefinition(
            name=SAVE_MEMORY_NOTE_TOOL_NAME,
            description=(
                "Persists a stable Revit user/project note such as category mappings, family naming conventions, "
                "parameter conventions, or recurring workflow hints for future chats."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "note_type": {"type": "string", "enum": MEMORY_NOTE_TYPES},
                    "scope": {"type": "string", "enum": MEMORY_NOTE_SCOPES},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "content"],
            },
            handler=save_revit_memory_note_handler,
        ),
    ]
