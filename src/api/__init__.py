"""
FastAPI application and route package.
"""

from src.api.app import app, create_app
from src.api.auth import get_api_key, verify_api_key

__all__ = ["app", "create_app", "get_api_key", "verify_api_key"]
