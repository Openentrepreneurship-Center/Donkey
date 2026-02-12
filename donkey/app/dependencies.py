from fastapi import Header, HTTPException, Depends

from app.config import Settings, get_settings
from app.schemas.error import ERROR_401, error_response


async def verify_api_key(
    x_api_key: str = Header(..., alias="X-Api-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=401,
            detail=error_response(*ERROR_401),
        )
    return x_api_key
