import datetime
import logging
import uuid

from .runtime_config import RuntimeConfig


class ResultStore:
    def __init__(self, config: RuntimeConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.element_storage = {}
        self.result_handle_storage = {}
        self.view_naming_analysis_storage = {}
        self.schema_context_cache = {"doc_fingerprint": None, "context": None}

    @staticmethod
    def _now_timestamp() -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def normalize_storage_key(name: str) -> str:
        return str(name or "").lower().replace("ost_", "").replace(" ", "_")

    @staticmethod
    def _new_result_handle() -> str:
        return "res_{}".format(uuid.uuid4().hex[:12])

    @staticmethod
    def _new_view_analysis_handle() -> str:
        return "vna_{}".format(uuid.uuid4().hex[:12])

    def store_elements(self, category_name: str, element_ids: list, count: int) -> tuple[str, str]:
        timestamp = self._now_timestamp()
        storage_key = self.normalize_storage_key(category_name)
        normalized_ids = [str(element_id) for element_id in (element_ids or [])]
        result_handle = self._new_result_handle()

        record = {
            "element_ids": normalized_ids,
            "count": int(count if count is not None else len(normalized_ids)),
            "category": category_name,
            "timestamp": timestamp,
            "storage_key": storage_key,
            "result_handle": result_handle,
        }

        self.element_storage[storage_key] = record
        self.result_handle_storage[result_handle] = record
        self.logger.info(
            "Stored %s element IDs for category '%s' with key '%s' and handle '%s'",
            record["count"],
            category_name,
            storage_key,
            result_handle,
        )
        return storage_key, result_handle

    def get_result_by_handle(self, result_handle: str):
        if not result_handle:
            return None
        return self.result_handle_storage.get(str(result_handle).strip())

    def get_stored_elements(self, storage_key: str):
        key = str(storage_key or "").strip()
        if not key:
            return None
        if key.startswith("res_"):
            return self.get_result_by_handle(key)
        return self.element_storage.get(self.normalize_storage_key(key))

    def list_stored_categories(self) -> dict:
        return {
            key: {
                "category": data["category"],
                "count": data["count"],
                "timestamp": data["timestamp"],
                "result_handle": data.get("result_handle"),
            }
            for key, data in self.element_storage.items()
        }

    def resolve_element_ids(self, element_ids=None, result_handle: str = None, category_name: str = None):
        if element_ids:
            return [str(element_id) for element_id in element_ids], None, None

        if result_handle:
            record = self.get_result_by_handle(result_handle)
            if not record:
                return None, None, {"status": "error", "message": "Unknown result_handle '{}'".format(result_handle)}
            return list(record.get("element_ids", [])), record, None

        if category_name:
            record = self.get_stored_elements(category_name)
            if not record:
                return None, None, {"status": "error", "message": "No stored elements found for '{}'".format(category_name)}
            return list(record.get("element_ids", [])), record, None

        return None, None, {
            "status": "error",
            "message": "No elements were provided. Use element_ids, result_handle, or category_name.",
        }

    def store_view_analysis(self, record: dict) -> str:
        analysis_handle = self._new_view_analysis_handle()
        self.view_naming_analysis_storage[analysis_handle] = record
        return analysis_handle

    def get_view_analysis(self, analysis_handle: str):
        return self.view_naming_analysis_storage.get(str(analysis_handle or "").strip())

    def get_cached_schema_context(self, doc_fingerprint: str):
        if (
            self.schema_context_cache["context"]
            and self.schema_context_cache["doc_fingerprint"] == doc_fingerprint
        ):
            cached = dict(self.schema_context_cache["context"])
            cached["cache"] = {"status": "hit", "doc_fingerprint": doc_fingerprint}
            return cached
        return None

    def set_cached_schema_context(self, doc_fingerprint: str, context: dict) -> None:
        self.schema_context_cache["doc_fingerprint"] = doc_fingerprint
        self.schema_context_cache["context"] = context

    def compact_result_payload(self, result: dict, preserve_keys: list = None) -> dict:
        if not isinstance(result, dict):
            return result

        preserve_keys = preserve_keys or []
        compact = dict(result)

        if isinstance(compact.get("element_ids"), list):
            element_ids = compact.get("element_ids", [])
            if len(element_ids) > self.config.max_elements_in_response:
                compact["element_ids_sample"] = element_ids[: self.config.max_elements_in_response]
                compact["element_ids_truncated"] = True
                compact["element_ids_total"] = len(element_ids)
                compact.pop("element_ids", None)

        if isinstance(compact.get("elements"), list):
            records = compact.get("elements", [])
            if len(records) > self.config.max_records_in_response:
                compact["elements_sample"] = records[: self.config.max_records_in_response]
                compact["elements_truncated"] = True
                compact["elements_total"] = len(records)
                compact.pop("elements", None)

        if isinstance(compact.get("views"), list):
            views = compact.get("views", [])
            if len(views) > self.config.max_views_in_response:
                compact["views_sample"] = views[: self.config.max_views_in_response]
                compact["views_truncated"] = True
                compact["views_total"] = len(views)
                compact.pop("views", None)

        if isinstance(compact.get("family_types"), list):
            family_types = compact.get("family_types", [])
            if len(family_types) > self.config.max_family_types_in_response:
                compact["family_types_sample"] = family_types[: self.config.max_family_types_in_response]
                compact["family_types_truncated"] = True
                compact["family_types_total"] = len(family_types)
                compact.pop("family_types", None)

        if isinstance(compact.get("outliers_sample"), list):
            outliers_sample = compact.get("outliers_sample", [])
            if len(outliers_sample) > self.config.max_outliers_in_response:
                compact["outliers_sample"] = outliers_sample[: self.config.max_outliers_in_response]
                compact["outliers_truncated"] = True
                compact["outliers_total"] = int(compact.get("outliers_total", len(outliers_sample)))

        if isinstance(compact.get("suggestions"), list):
            suggestions = compact.get("suggestions", [])
            if len(suggestions) > self.config.max_suggestions_in_response:
                compact["suggestions_sample"] = suggestions[: self.config.max_suggestions_in_response]
                compact["suggestions_truncated"] = True
                compact["suggestions_total"] = len(suggestions)
                compact.pop("suggestions", None)

        if isinstance(compact.get("data"), dict):
            data_dict = dict(compact["data"])
            if isinstance(data_dict.get("selected_ids_processed"), list):
                selected_ids = data_dict.get("selected_ids_processed", [])
                if len(selected_ids) > self.config.max_elements_in_response:
                    data_dict["selected_ids_sample"] = selected_ids[: self.config.max_elements_in_response]
                    data_dict["selected_ids_truncated"] = True
                    data_dict["selected_ids_total"] = len(selected_ids)
                    data_dict.pop("selected_ids_processed", None)
            compact["data"] = data_dict

        if isinstance(compact.get("message"), str) and len(compact["message"]) > 1200:
            compact["message"] = compact["message"][:1200] + "... [truncated]"
            compact["message_truncated"] = True

        for key in preserve_keys:
            if key in result:
                compact[key] = result[key]

        return compact

    @staticmethod
    def summarize_for_log(payload):
        if isinstance(payload, dict):
            summary = {}
            for key, value in payload.items():
                if isinstance(value, list):
                    summary[key] = "<list len={}>".format(len(value))
                elif isinstance(value, dict):
                    summary[key] = "<dict keys={}>".format(len(value))
                elif isinstance(value, str) and len(value) > 180:
                    summary[key] = value[:180] + "... [truncated]"
                else:
                    summary[key] = value
            return summary
        return payload

