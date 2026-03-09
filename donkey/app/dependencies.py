import hashlib

from fastapi import Header, HTTPException, Depends

from app.config import get_settings
from app.db.repository import get_api_key_context_by_hash
from app.db.session import get_session
from app.schemas.error import ERROR_401, error_response


async def verify_api_key(
    x_api_key: str = Header(..., alias="X-Api-Key"),
) -> tuple[int, int]:
    """X-Api-Key로 DB api_key 조회. 유효하면 (client_id, project_id) 반환."""
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    async with get_session() as session:
        ctx = await get_api_key_context_by_hash(session, key_hash)
    if ctx is None:
        raise HTTPException(
            status_code=401,
            detail=error_response(*ERROR_401),
        )
    return ctx
