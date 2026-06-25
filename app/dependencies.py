from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from app.db import get_supabase
from app.config import get_settings

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """
    Validates a Supabase JWT from the Authorization header.
    Returns the user_id (sub claim) on success.
    Raises 401 if the token is invalid or expired.
    """
    token = credentials.credentials
    settings = get_settings()

    try:
        # Decode without signature verification first to get the header/claims
        # Then verify using Supabase's JWT secret embedded in the service key.
        # Supabase JWTs are signed with the project JWT secret (HS256).
        # The service key itself encodes the secret in its payload — we use the
        # Supabase auth API to verify instead of local decode when we have the
        # service role client available.
        supabase = get_supabase()
        user_response = supabase.auth.get_user(token)
        if user_response is None or user_response.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return str(user_response.user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
