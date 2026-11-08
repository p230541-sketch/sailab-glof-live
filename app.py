"""Start the SailAb GLOF web app:  .venv/bin/uvicorn app:app"""
from webapp.main import create_app

app = create_app()
