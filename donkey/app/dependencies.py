from fastapi import Header, HTTPException, Depends

from app.config import Settings, get_settings


async def verify_api_key(
    x_api_key: str = Header(..., alias="X-Api-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Invalid API key"},
        )
    return x_api_key
