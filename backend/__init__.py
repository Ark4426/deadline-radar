"""DeadlineRadar application factory."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

from backend.auth import auth_bp
from backend.config import Config
from backend.database import init_app as init_database
from backend.security import init_security

APP_VERSION = "0.1.0"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(FRONTEND_DIR),
        static_url_path="",
    )
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("DATABASE"):
        app.config["DATABASE"] = Config.default_database(app.instance_path)

    database_dir = Path(app.config["DATABASE"]).parent
    database_dir.mkdir(parents=True, exist_ok=True)

    if not app.config.get("MODEL_PATH"):
        app.config["MODEL_PATH"] = str(
            Path(__file__).resolve().parent / "risk_engine" / "artifacts" / "risk_model.joblib"
        )

    init_database(app)
    init_security(app)
    app.register_blueprint(auth_bp)

    @app.get("/api/health")
    def health():
        model_exists = Path(app.config["MODEL_PATH"]).exists()
        return jsonify(
            {
                "status": "ok",
                "app": "DeadlineRadar",
                "version": APP_VERSION,
                "model": "ready" if model_exists else "rules-fallback",
                "time": datetime.now(timezone.utc).isoformat(),
            }
        )

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def frontend(path: str):
        if path.startswith("api/"):
            return jsonify({"error": "Not found"}), 404
        target = FRONTEND_DIR / path
        if path and target.is_file():
            return send_from_directory(FRONTEND_DIR, path)
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        if error.code == 404:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"error": error.description}), error.code

    return app
