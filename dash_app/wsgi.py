"""Production entry point for Gunicorn."""
from dash_app.app import create_app

app = create_app()
server = app.server
