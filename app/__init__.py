"""
Parrhesepstein — App factory - Tamaladissa.
"""
from flask import Flask
from flask_cors import CORS
from app.config import SECRET_KEY
from app import extensions
from app.routes import register_blueprints


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = SECRET_KEY
    CORS(app)
    extensions.init_app(app)
    register_blueprints(app)
    return app
