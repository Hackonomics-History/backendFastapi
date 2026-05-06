import json
import logging

import httpx
import redis as redis_sync
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)
_bearer = HTTPBearer()

# Redis client (sync, shared across requests — thread-safe)
_redis: redis_sync.Redis | None = None


def _get_redis() -> redis_sync.Redis:
    global _redis
    if _redis is None:
        _redis = redis_sync.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _fetch_and_cache_jwks() -> dict:
    resp = httpx.get(settings.jwks_url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    r = _get_redis()
    serialised = json.dumps(data)
    r.setex("ory_jwks_data", 180, serialised)
    r.setex("ory_jwks_stale", 1800, serialised)
    return data


def _get_jwks() -> dict:
    r = _get_redis()
    cached = r.get("ory_jwks_data")
    if cached:
        return json.loads(cached)
    try:
        return _fetch_and_cache_jwks()
    except Exception as exc:
        logger.warning("JWKS fetch failed (%s); trying stale cache", exc)
        stale = r.get("ory_jwks_stale")
        if stale:
            return json.loads(stale)
        raise


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    token = credentials.credentials
    try:
        jwks = _get_jwks()
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )
        sub: str | None = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing sub claim")
        return sub
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc
