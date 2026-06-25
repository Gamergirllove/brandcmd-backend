from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.db import get_supabase

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(body: RefreshRequest):
    """
    Exchange a Supabase refresh token for a new access token.
    Proxies to Supabase's auth.refresh_session() method.
    """
    supabase = get_supabase()
    try:
        response = supabase.auth.refresh_session(body.refresh_token)
        if response is None or response.session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )
        session = response.session
        return RefreshResponse(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            expires_in=session.expires_in or 3600,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token refresh failed: {str(exc)}",
        ) from exc
