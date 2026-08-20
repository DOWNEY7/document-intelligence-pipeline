"""
Authentication and Authorization Module for Document Intelligence API.

Provides API Key authentication via 'X-API-Key' header and 'Authorization: Bearer <key>'.
Supports optional development mode or enforced production authentication via REQUIRE_AUTH.
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from src.config import Settings, get_settings

logger = logging.getLogger("document_intelligence.auth")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_api_key(
    header_key: Annotated[str | None, Security(api_key_header)] = None,
    bearer_cred: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
) -> str | None:
    """Extract API key from either 'X-API-Key' header or 'Authorization: Bearer <key>'."""
    if header_key:
        return header_key.strip()
    if bearer_cred and bearer_cred.credentials:
        return bearer_cred.credentials.strip()
    return None


async def verify_api_key(
    provided_key: Annotated[str | None, Depends(get_api_key)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str | None:
    """
    Verify the client API Key against configured settings.
    - If REQUIRE_AUTH is False and no API_KEY is set: permits anonymous access.
    - If REQUIRE_AUTH is True or API_KEY is set:
      - Validates provided_key.
      - If missing -> 401 Unauthorized.
      - If invalid -> 403 Forbidden.
    """
    if not settings.REQUIRE_AUTH and not settings.API_KEY:
        return provided_key

    expected_key = settings.API_KEY or "doc-intel-secret-key"

    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key. Provide via 'X-API-Key' header or 'Authorization: Bearer <key>'.",
            headers={"WWW-Authenticate": "ApiKey, Bearer"},
        )

    if not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key provided.",
        )

    return provided_key
