from flask import jsonify, render_template, request

from RevitMCP_ExternalServer.web.chat_service import run_chat_request


def register_routes(app, services, tool_registry) -> None:
    @app.route("/", methods=["GET"])
    def chat_ui():
        app.logger.info("Serving chat_ui (index.html)")
        return render_template("index.html")

    @app.route("/test_log", methods=["GET"])
    def test_log_route():
        app.logger.info("--- ACCESSED /test_log route successfully (app.logger.info) ---")
        return jsonify({"status": "success", "message": "Test log route accessed. Check server console."}), 200

    @app.route("/chat_api", methods=["POST"])
    def chat_api():
        response_payload, status_code = run_chat_request(
            services=services,
            tool_registry=tool_registry,
            request_data=request.json,
        )
        return jsonify(response_payload), status_code

    @app.route("/send_revit_command", methods=["POST"])
    def send_revit_command():
        client_request_data = request.json
        if not client_request_data or "command" not in client_request_data:
            return jsonify({"status": "error", "message": "Invalid request. 'command' is required."}), 400

        response_payload, status_code = services.revit_client.forward_direct_command(client_request_data)
        return jsonify(response_payload), status_code

