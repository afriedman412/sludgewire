"""HTTP Basic authentication for protected endpoints."""
from __future__ import annotations

import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.settings import load_settings

security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Verify admin credentials using constant-time comparison.

    Returns the username if valid, raises HTTPException otherwise.
    """
    settings = load_settings()

    if not settings.config_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Config password not configured",
        )

    correct_username = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        b"admin",
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.config_password.encode("utf-8"),
    )

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
