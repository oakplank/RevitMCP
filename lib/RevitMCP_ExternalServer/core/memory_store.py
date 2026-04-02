import datetime
import json
import os
import re
import uuid


def _now_timestamp() -> str:
    return datetime.datetime.now().isoformat()


class MemoryStore:
    def __init__(self, logger, storage_path: str = None):
        self.logger = logger
        self.storage_path = storage_path or self._default_storage_path()

    @staticmethod
    def _default_storage_path() -> str:
        user_profile_dir = os.path.expanduser("~")
        documents_dir = os.path.join(user_profile_dir, "Documents")
        if os.path.isdir(documents_dir):
            base_dir = os.path.join(documents_dir, "RevitMCP", "user_data")
        else:
            base_dir = os.path.join(user_profile_dir, "RevitMCP", "user_data")
        return os.path.join(base_dir, "revitmcp_memory.json")

    @staticmethod
    def _default_payload() -> dict:
        return {"version": "1.0", "notes": []}

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 3)].rstrip() + "..."

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token for token in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(token) >= 2]

    @staticmethod
    def _project_key(project_context: dict = None) -> str:
        data = project_context or {}
        return str(data.get("project_key") or "").strip()

    @staticmethod
    def _normalize_scope(scope: str, default_value: str = "project") -> str:
        normalized = str(scope or default_value).strip().lower()
        if normalized in ("project", "global", "auto", "all"):
            return normalized
        return default_value

    def _ensure_parent_dir(self) -> None:
        parent_dir = os.path.dirname(self.storage_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)

    def _load_payload(self) -> dict:
        if not os.path.exists(self.storage_path):
            return self._default_payload()

        try:
            with open(self.storage_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("memory payload is not a dictionary")
            notes = payload.get("notes", [])
            if not isinstance(notes, list):
                payload["notes"] = []
            return payload
        except Exception as exc:
            self.logger.warning("Failed to load memory store '%s': %s", self.storage_path, exc)
            return self._default_payload()

    def _save_payload(self, payload: dict) -> None:
        self._ensure_parent_dir()
        with open(self.storage_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

    def _normalize_keywords(self, keywords=None, title: str = "", content: str = "") -> list[str]:
        normalized = []
        seen = set()
        for keyword in keywords or []:
            candidate = str(keyword or "").strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(candidate)

        for token in self._tokenize("{} {}".format(title, content)):
            if len(normalized) >= 12:
                break
            if token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized

    def get_current_project_context(self, services) -> dict:
        if not services or not getattr(services, "revit_client", None):
            return {}

        try:
            project_info = services.revit_client.call_listener(command_path="/project_info", method="GET")
        except Exception as exc:
            self.logger.warning("Failed to load project info for memory context: %s", exc)
            return {}

        if not isinstance(project_info, dict) or project_info.get("status") == "error":
            return {}

        file_path = str(project_info.get("file_path") or "").strip()
        project_name = str(project_info.get("project_name") or "").strip()
        project_number = str(project_info.get("project_number") or "").strip()
        project_key = "{}|{}|{}".format(file_path, project_name, project_number).strip("|")

        return {
            "project_key": project_key,
            "file_path": file_path,
            "project_name": project_name,
            "project_number": project_number,
        }

    def save_note(
        self,
        title: str,
        content: str,
        note_type: str = "workflow_hint",
        scope: str = "project",
        keywords: list[str] = None,
        project_context: dict = None,
    ) -> tuple[dict, bool]:
        normalized_scope = self._normalize_scope(scope, default_value="project")
        if normalized_scope in ("auto", "all"):
            normalized_scope = "project"

        payload = self._load_payload()
        notes = payload.get("notes", [])
        project_key = self._project_key(project_context)
        normalized_title = str(title or "").strip()
        normalized_content = str(content or "").strip()
        normalized_type = str(note_type or "workflow_hint").strip().lower()
        normalized_keywords = self._normalize_keywords(keywords=keywords, title=normalized_title, content=normalized_content)
        now = _now_timestamp()

        existing_note = None
        for note in notes:
            if (
                str(note.get("title") or "").strip().lower() == normalized_title.lower()
                and str(note.get("scope") or "").strip().lower() == normalized_scope
                and str(note.get("project_key") or "").strip() == (project_key if normalized_scope == "project" else "")
            ):
                existing_note = note
                break

        if existing_note:
            existing_note["content"] = normalized_content
            existing_note["keywords"] = normalized_keywords
            existing_note["note_type"] = normalized_type
            existing_note["updated_at"] = now
            if normalized_scope == "project":
                existing_note["project_key"] = project_key
                existing_note["project_name"] = str((project_context or {}).get("project_name") or "").strip()
                existing_note["project_number"] = str((project_context or {}).get("project_number") or "").strip()
                existing_note["file_path"] = str((project_context or {}).get("file_path") or "").strip()
            else:
                existing_note["project_key"] = ""
                existing_note["project_name"] = ""
                existing_note["project_number"] = ""
                existing_note["file_path"] = ""
            note = dict(existing_note)
            created = False
        else:
            note = {
                "note_id": "mem_{}".format(uuid.uuid4().hex[:12]),
                "title": normalized_title,
                "content": normalized_content,
                "keywords": normalized_keywords,
                "note_type": normalized_type,
                "scope": normalized_scope,
                "project_key": project_key if normalized_scope == "project" else "",
                "project_name": str((project_context or {}).get("project_name") or "").strip() if normalized_scope == "project" else "",
                "project_number": str((project_context or {}).get("project_number") or "").strip() if normalized_scope == "project" else "",
                "file_path": str((project_context or {}).get("file_path") or "").strip() if normalized_scope == "project" else "",
                "created_at": now,
                "updated_at": now,
                "last_used_at": None,
                "use_count": 0,
            }
            notes.append(note)
            created = True

        payload["notes"] = notes
        self._save_payload(payload)
        return note, created

    def touch_notes(self, note_ids: list[str]) -> None:
        normalized_ids = {str(note_id or "").strip() for note_id in (note_ids or []) if str(note_id or "").strip()}
        if not normalized_ids:
            return

        payload = self._load_payload()
        updated = False
        now = _now_timestamp()
        for note in payload.get("notes", []):
            if str(note.get("note_id") or "").strip() in normalized_ids:
                note["last_used_at"] = now
                note["use_count"] = int(note.get("use_count") or 0) + 1
                updated = True
        if updated:
            self._save_payload(payload)

    def _matches_scope(self, note: dict, scope: str, project_context: dict = None) -> bool:
        normalized_scope = self._normalize_scope(scope, default_value="auto")
        note_scope = str(note.get("scope") or "").strip().lower()
        project_key = self._project_key(project_context)
        note_project_key = str(note.get("project_key") or "").strip()

        if normalized_scope == "global":
            return note_scope == "global"
        if normalized_scope == "project":
            return note_scope == "project" and project_key and note_project_key == project_key
        if normalized_scope in ("auto", "all"):
            if note_scope == "global":
                return True
            if note_scope == "project" and project_key and note_project_key == project_key:
                return True
            return False
        return True

    def _score_note(self, note: dict, query_text: str = "", project_context: dict = None) -> int:
        score = 0
        note_scope = str(note.get("scope") or "").strip().lower()
        note_project_key = str(note.get("project_key") or "").strip()
        project_key = self._project_key(project_context)

        if note_scope == "project" and project_key and note_project_key == project_key:
            score += 120
        elif note_scope == "global":
            score += 20

        query_tokens = set(self._tokenize(query_text))
        note_text = " ".join(
            [
                str(note.get("title") or ""),
                str(note.get("content") or ""),
                " ".join(note.get("keywords") or []),
                str(note.get("note_type") or ""),
            ]
        ).lower()
        note_tokens = set(self._tokenize(note_text))
        overlap_count = len(query_tokens.intersection(note_tokens))
        score += overlap_count * 10

        query_normalized = str(query_text or "").strip().lower()
        if query_normalized:
            if str(note.get("title") or "").strip().lower() in query_normalized:
                score += 15
            for keyword in note.get("keywords") or []:
                keyword_value = str(keyword or "").strip().lower()
                if keyword_value and keyword_value in query_normalized:
                    score += 6

        score += min(int(note.get("use_count") or 0), 10)
        return score

    def list_notes(
        self,
        query_text: str = "",
        scope: str = "auto",
        project_context: dict = None,
        max_notes: int = 8,
        note_type: str = None,
    ) -> list[dict]:
        safe_max = max(1, min(50, int(max_notes if max_notes is not None else 8)))
        normalized_type = str(note_type or "").strip().lower()

        payload = self._load_payload()
        candidates = []
        for note in payload.get("notes", []):
            if not self._matches_scope(note, scope=scope, project_context=project_context):
                continue
            if normalized_type and str(note.get("note_type") or "").strip().lower() != normalized_type:
                continue
            note_copy = dict(note)
            note_copy["_score"] = self._score_note(note_copy, query_text=query_text, project_context=project_context)
            candidates.append(note_copy)

        candidates.sort(
            key=lambda note: (
                int(note.get("_score") or 0),
                str(note.get("updated_at") or ""),
                str(note.get("created_at") or ""),
            ),
            reverse=True,
        )

        trimmed = []
        for note in candidates[:safe_max]:
            note_copy = dict(note)
            note_copy.pop("_score", None)
            trimmed.append(note_copy)
        return trimmed

    def build_prompt_context(
        self,
        query_text: str = "",
        scope: str = "auto",
        project_context: dict = None,
        max_notes: int = 6,
    ) -> str:
        notes = self.list_notes(
            query_text=query_text,
            scope=scope,
            project_context=project_context,
            max_notes=max_notes,
        )
        if not notes:
            return ""

        self.touch_notes([note.get("note_id") for note in notes])

        lines = ["Relevant persistent Revit memory:"]
        project_name = str((project_context or {}).get("project_name") or "").strip()
        if project_name:
            lines.append("Current project: {}".format(project_name))

        for note in notes:
            scope_label = str(note.get("scope") or "global").strip().lower()
            note_type = str(note.get("note_type") or "note").strip()
            title = self._truncate(note.get("title"), 80)
            content = self._truncate(note.get("content"), 220)
            lines.append("- [{}|{}] {}: {}".format(scope_label, note_type, title, content))

        return "\n".join(lines)
