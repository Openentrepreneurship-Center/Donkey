from datetime import datetime, timezone, timedelta
from typing import Any

from jose import JWTError, jwt

from app.config import get_settings


def create_access_token(sub: str, payload_extra: dict[str, Any] | None = None) -> str:
    """sub(주로 user_id)로 JWT 액세스 토큰 발급."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.admin_jwt_expire_minutes)
    to_encode = {"sub": sub, "exp": expire, "iat": now}
    if payload_extra:
        to_encode.update(payload_extra)
    return jwt.encode(to_encode, settings.admin_jwt_secret, algorithm=settings.admin_jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """토큰 검증 후 payload 반환. 실패 시 None."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.admin_jwt_secret, algorithms=[settings.admin_jwt_algorithm])
    except JWTError:
        return None
