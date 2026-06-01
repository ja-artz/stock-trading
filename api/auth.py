"""Simple household API key auth."""

from fastapi import Header, HTTPException
import config


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    expected = config.HOUSEHOLD_API_KEY
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
