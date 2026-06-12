import secrets
import logging

from fastapi import Header, HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)


def get_current_user_id(
    authorization: str = Header(...),
    x_user_id: str = Header(...),
) -> str:
    """
    Validates requests from BackendKotlin using a shared internal service token.
    The caller must supply:
      Authorization: Bearer <AI_SERVICE_INTERNAL_TOKEN>
      X-User-ID: <kratosID>
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must use Bearer scheme",
        )

    token = authorization[len("Bearer "):]

    if not secrets.compare_digest(token, settings.ai_service_internal_token):
        logger.warning("Rejected request with invalid internal service token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
        )

    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-ID header is required",
        )

    return x_user_id
