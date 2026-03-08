from flask import Flask, jsonify

from config import Config
from app.extensions import db
from app.helper.logger import init_logger
from app.helper.oauth_service import init_oauth
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
import time
import uuid
from flask_migrate import Migrate
from app.models import *  # noqa: F403
from app.routes import register_routes
from flask_swagger_ui import get_swaggerui_blueprint
import os
from flask_cors import CORS


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, origins=[Config.FE_BASE_URL], supports_credentials=True)

    # Secret key required for OAuth session
    app.secret_key = app.config.get("JWT_SECRET_KEY", "fallback-secret-key")

    # Initialize extensions
    db.init_app(app)
    Migrate(app, db)

    # Initialize logger with app config
    init_logger(app)
    from app.helper.logger import json_logger

    json_logger.warning("cookie config", Config.COOKIE_OPTS)

    # Initialize OAuth
    init_oauth(app)

    with app.app_context():
        for i in range(3):
            try:
                with db.engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                json_logger.info("Database connection success")
                break
            except OperationalError as e:
                json_logger.warning(f"DB connect failed (attempt {i + 1}/3): {e}")
                time.sleep(3)
        else:
            json_logger.error("Database connection failed after retries", exc_info=True)

    @app.route("/health")
    def health_check():
        """
        Health check endpoint.

        Returns:
            jsonify: A jsonify object containing the health status of the application.
        Status Codes:
            200: Healthy
            503: Degraded (database connection failed)
        """
        health_status = {
            "status": "healthy",
            "database": "connected",
            "timestamp": time.time(),
        }
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception as e:
            json_logger.warning(f"Database health check failed: {str(e)}")
            health_status["database"] = "disconnected"
            health_status["status"] = "degraded"
            return jsonify(health_status), 503
        return jsonify(health_status), 200

    @app.errorhandler(404)
    def not_found_error(error):
        """
        Handles 404 errors and returns a JSON response with the error details.

        Args:
            error: The error object that triggered the error handler.

        Returns:
            A JSON response containing the error details.
        """
        json_logger.warning(f"Not Found: {str(error)}")
        return jsonify(
            {
                "success": False,
                "message": "Not Found",
                "error_id": str(uuid.uuid4()),
                "error": "The requested URL was not found on the server.",
            }
        ), 404

    @app.errorhandler(405)
    def method_not_allowed_error(error):
        """
        Handles 405 errors and returns a JSON response with the error details.

        Args:
            error: The error object that triggered the error handler.

        Returns:
            A JSON response containing the error details.
        """
        json_logger.warning(f"Method Not Allowed: {str(error)}")
        return jsonify(
            {
                "success": False,
                "message": "Method Not Allowed",
                "error_id": str(uuid.uuid4()),
                "error": "The method is not allowed for the requested URL.",
            }
        ), 405

    @app.errorhandler(500)
    def internal_server_error(error):
        """Handle 500 errors and return a JSON response with the error details.

        Args:
            error (Exception): The error object that triggered the error handler.

        Returns:
            A JSON response containing the error details
        """

        json_logger.error(f"Internal Server Error: {str(error)}", exc_info=True)
        return jsonify(
            {
                "success": False,
                "message": "Internal Server Error",
                "error_id": str(uuid.uuid4()),
                "error": "An unexpected error occurred.",
            }
        ), 500

    register_routes(app)

    # Swagger UI

    SWAGGER_URL = "/api/docs"
    API_SPEC_URL = "/api/spec/openapi.yaml"

    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_SPEC_URL,
        config={"app_name": "Movie Web App API"},
    )
    app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)

    @app.route(API_SPEC_URL)
    def serve_openapi_spec():
        docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")
        from flask import send_from_directory

        return send_from_directory(docs_dir, "openapi.yaml")

    # CLI commands
    from app.cli import register_cli

    register_cli(app)

    return app
