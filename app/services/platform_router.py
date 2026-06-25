"""
platform_router.py — Thin adapter between routers and platform service classes.
Loads stored tokens and instantiates the appropriate service.
"""
from __future__ import annotations

from typing import Optional

from app.config import get_settings
from app.services.platform_factory import get_platform_service
from app.services.token_store import retrieve_tokens

SUPPORTED_PLATFORMS = {
    "youtube",
    "instagram",
    "tiktok",
    "twitter",
    "pinterest",
    "linkedin",
    "facebook",
    "snapchat",
}

# Map platform → (client_id_attr, client_secret_attr) on Settings
_CREDS_MAP = {
    "youtube":   ("youtube_client_id",   "youtube_client_secret"),
    "instagram": ("instagram_client_id", "instagram_client_secret"),
    "tiktok":    ("tiktok_client_key",   "tiktok_client_secret"),
    "twitter":   ("twitter_client_id",   "twitter_client_secret"),
    "pinterest": ("pinterest_client_id", "pinterest_client_secret"),
    "linkedin":  ("linkedin_client_id",  "linkedin_client_secret"),
    "facebook":  ("facebook_client_id",  "facebook_client_secret"),
    "snapchat":  ("snapchat_client_id",  "snapchat_client_secret"),
}


async def get_service(platform: str, user_id: str):
    """
    Returns a service instance preloaded with the user's stored tokens,
    or None if the user hasn't connected that platform.
    """
    platform = platform.lower()
    if platform not in SUPPORTED_PLATFORMS:
        return None

    token_data = await retrieve_tokens(user_id, platform)
    if not token_data:
        return None

    settings = get_settings()
    creds = _CREDS_MAP.get(platform)
    if not creds:
        return None

    client_id = getattr(settings, creds[0], "")
    client_secret = getattr(settings, creds[1], "")
    if not client_id:
        return None

    redirect_uri = f"{settings.frontend_url}/connect/{platform}/callback"
    svc = get_platform_service(platform, client_id, client_secret, redirect_uri)
    # Attach raw token_data so callers can build PlatformTokens if needed
    svc._token_data = token_data
    return svc
