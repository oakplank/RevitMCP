import logging

import requests

from .runtime_config import RuntimeConfig


class RevitClient:
    def __init__(self, config: RuntimeConfig, logger: logging.Logger, startup_logger: logging.Logger, result_store):
        self.config = config
        self.logger = logger
        self.startup_logger = startup_logger
        self.result_store = result_store
        self.base_url = None

    def detect_port(self) -> bool:
        for port in self.config.revit_possible_ports:
            test_url = f"http://localhost:{port}/revit-mcp-v1"
            try:
                response = requests.get(f"{test_url}/project_info", timeout=2)
                if response.status_code in [200, 404, 405]:
                    self.base_url = test_url
                    self.startup_logger.info("Detected Revit MCP API running on port %s", port)
                    return True
            except requests.exceptions.RequestException:
                continue

        self.startup_logger.warning("Could not detect Revit MCP API on any common ports. Defaulting to 48884.")
        self.base_url = "http://localhost:48884/revit-mcp-v1"
        return False

    def _ensure_base_url(self):
        if self.base_url is None:
            self.logger.error("Revit MCP API base URL is not set. Attempting auto-detection...")
            if not self.detect_port():
                self.logger.error("Failed to detect Revit MCP API port. Listener might not be running or accessible.")
                return {
                    "status": "error",
                    "message": "Could not connect to Revit Listener: API URL not configured.",
                }
        return None

    @staticmethod
    def is_route_not_defined(result: dict, route_hint: str = None) -> bool:
        if not isinstance(result, dict):
            return False
        if result.get("error_type") == "route_not_defined":
            return True
        text_parts = [str(result.get("message", "")), str(result.get("details", ""))]
        if route_hint:
            text_parts.append(str(route_hint))
        text = " ".join(text_parts)
        return "RouteHandlerNotDefinedException" in text

    def call_listener(self, command_path: str, method: str = "POST", payload_data: dict = None):
        not_ready = self._ensure_base_url()
        if not_ready:
            return not_ready

        self.logger.info("Using pre-configured Revit MCP API base URL: %s", self.base_url)

        def attempt_api_call():
            full_url = self.base_url.rstrip("/") + "/" + command_path.lstrip("/")
            self.logger.debug(
                "Calling Revit MCP API: %s %s with payload: %s",
                method,
                full_url,
                payload_data,
            )

            if method.upper() == "POST":
                listener_response = requests.post(
                    full_url,
                    json=payload_data,
                    headers={"Content-Type": "application/json"},
                    timeout=60,
                )
            elif method.upper() == "GET":
                listener_response = requests.get(full_url, params=payload_data, timeout=60)
            else:
                self.logger.error("Unsupported HTTP method: %s for call_listener", method)
                raise ValueError("Unsupported HTTP method: {}".format(method))

            listener_response.raise_for_status()
            return listener_response.json()

        try:
            response_json = attempt_api_call()
            self.logger.info(
                "Revit MCP API success for %s: %s",
                command_path,
                self.result_store.summarize_for_log(response_json),
            )
            return response_json
        except requests.exceptions.ConnectionError:
            self.logger.warning("Connection failed to %s. Attempting to re-detect port...", self.base_url)
            old_url = self.base_url
            if self.detect_port() and self.base_url != old_url:
                self.logger.info("Port re-detected. Retrying with new URL: %s", self.base_url)
                try:
                    response_json = attempt_api_call()
                    self.logger.info(
                        "Revit MCP API success after retry for %s: %s",
                        command_path,
                        self.result_store.summarize_for_log(response_json),
                    )
                    return response_json
                except Exception as retry_err:
                    self.logger.error("Retry failed: %s", retry_err)

            message = (
                f"Could not connect to the Revit MCP API for command {command_path}. "
                f"Tried {old_url} and {self.base_url}"
            )
            self.logger.error(message)
            return {"status": "error", "message": message}
        except requests.exceptions.Timeout:
            message = f"Request to Revit MCP API at {self.base_url} for command {command_path} timed out."
            self.logger.error(message)
            return {"status": "error", "message": message}
        except requests.exceptions.RequestException as request_error:
            message_prefix = f"Error communicating with Revit MCP API at {self.base_url} for {command_path}"
            if hasattr(request_error, "response") and request_error.response is not None:
                status_code = request_error.response.status_code
                try:
                    listener_error_data = request_error.response.json()
                    listener_message = str(
                        listener_error_data.get("message", listener_error_data.get("error", "Unknown API error"))
                    )
                    route_exception_message = ""
                    if isinstance(listener_error_data.get("exception"), dict):
                        route_exception_message = str(listener_error_data["exception"].get("message", ""))
                    is_missing_route = (
                        "RouteHandlerNotDefinedException" in listener_message
                        or "RouteHandlerNotDefinedException" in route_exception_message
                    )
                    full_message = (
                        f"{message_prefix}: HTTP {status_code}. API Response: "
                        f"{listener_error_data.get('message', listener_error_data.get('error', 'Unknown API error'))}"
                    )
                    self.logger.error(full_message, exc_info=False)
                    result = {"status": "error", "message": full_message, "details": listener_error_data}
                    if is_missing_route:
                        result["error_type"] = "route_not_defined"
                        result["missing_route"] = command_path
                    return result
                except ValueError:
                    full_message = f"{message_prefix}: HTTP {status_code}. Response: {request_error.response.text[:200]}"
                    self.logger.error(full_message, exc_info=True)
                    return {"status": "error", "message": full_message}

            self.logger.error("%s: %s", message_prefix, request_error, exc_info=True)
            return {"status": "error", "message": f"{message_prefix}: {request_error}"}
        except Exception as generic_error:
            self.logger.error(
                "Unexpected error in call_listener for %s at %s: %s",
                command_path,
                self.base_url,
                generic_error,
                exc_info=True,
            )
            return {
                "status": "error",
                "message": f"Unexpected error processing API response for {command_path}.",
            }

    def forward_direct_command(self, payload: dict):
        listener_url = self.config.direct_revit_listener_url
        self.logger.info(
            "External Server (/send_revit_command): Forwarding %s to %s",
            payload,
            listener_url,
        )
        try:
            response = requests.post(
                listener_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            response_data = response.json()
            self.logger.info("External Server: Response from Revit Listener: %s", response_data)
            return response_data, response.status_code
        except requests.exceptions.ConnectionError as error:
            message = f"Could not connect to Revit Listener at {listener_url}. Error: {error}"
            self.logger.error(message)
            return {"status": "error", "message": message}, 503
        except requests.exceptions.Timeout as error:
            message = f"Request to Revit Listener timed out. Error: {error}"
            self.logger.error(message)
            return {"status": "error", "message": message}, 504
        except requests.exceptions.RequestException as error:
            message = f"Error communicating with Revit Listener. Error: {error}"
            self.logger.error(message)
            details = "No response details."
            if hasattr(error, "response") and error.response is not None:
                try:
                    details = error.response.json()
                except ValueError:
                    details = error.response.text
            status = error.response.status_code if hasattr(error, "response") and error.response is not None else 500
            return {"status": "error", "message": message, "details": details}, status
        except Exception as error:
            message = f"Unexpected error in /send_revit_command. Error: {error}"
            self.logger.error(message, exc_info=True)
            return {"status": "error", "message": message}, 500

