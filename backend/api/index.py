"""Vercel entry point: the whole FastAPI app runs as one Python serverless function."""

from app.main import app as fastapi_app
from app.vercel_path import VercelPathMiddleware

app = VercelPathMiddleware(fastapi_app)
