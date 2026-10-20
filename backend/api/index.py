"""Vercel entry point: the whole FastAPI app runs as one Python serverless function."""

from app.main import app  # noqa: F401  (VercelPathMiddleware is installed inside the app)
