import base64
import mimetypes
import os


MAX_IMAGE_ARTIFACT_BYTES = 20 * 1024 * 1024


def load_image_artifact(tool_result_data: dict, logger=None) -> dict | None:
    if not isinstance(tool_result_data, dict):
        return None
    if tool_result_data.get("artifact_type") != "image":
        return None

    image_path = tool_result_data.get("image_path")
    if not image_path:
        return None

    try:
        normalized_path = os.path.abspath(str(image_path))
        if not os.path.exists(normalized_path):
            if logger:
                logger.warning("Image artifact path does not exist: %s", normalized_path)
            return None

        file_size = os.path.getsize(normalized_path)
        if file_size > MAX_IMAGE_ARTIFACT_BYTES:
            if logger:
                logger.warning(
                    "Image artifact '%s' is %s bytes, exceeding %s bytes; not attaching.",
                    normalized_path,
                    file_size,
                    MAX_IMAGE_ARTIFACT_BYTES,
                )
            return None

        mime_type = tool_result_data.get("mime_type") or mimetypes.guess_type(normalized_path)[0] or "image/png"
        if not str(mime_type).startswith("image/"):
            if logger:
                logger.warning("Artifact '%s' has non-image mime type '%s'; not attaching.", normalized_path, mime_type)
            return None

        with open(normalized_path, "rb") as handle:
            encoded_data = base64.b64encode(handle.read()).decode("ascii")

        return {
            "path": normalized_path,
            "mime_type": str(mime_type),
            "base64_data": encoded_data,
            "file_size_bytes": file_size,
        }
    except Exception as error:
        if logger:
            logger.warning("Failed to load image artifact '%s': %s", image_path, error)
        return None
