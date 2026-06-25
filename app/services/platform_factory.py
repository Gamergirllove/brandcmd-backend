"""
platform_factory.py — Factory function to instantiate the correct platform service.
"""
from __future__ import annotations

from .base import BasePlatformService
from .facebook import FacebookService
from .instagram import InstagramService
from .linkedin import LinkedInService
from .pinterest import PinterestService
from .snapchat import SnapchatService
from .tiktok import TikTokService
from .twitter import TwitterService
from .youtube import YouTubeService

# Map lowercase platform name → service class
_PLATFORM_MAP: dict[str, type[BasePlatformService]] = {
    "youtube": YouTubeService,
    "instagram": InstagramService,
    "tiktok": TikTokService,
    "twitter": TwitterService,
    "x": TwitterService,            # alias
    "pinterest": PinterestService,
    "linkedin": LinkedInService,
    "facebook": FacebookService,
    "snapchat": SnapchatService,
}


def get_platform_service(
    platform: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> BasePlatformService:
    """
    Instantiate and return the OAuth service for the given platform.

    Args:
        platform:      Case-insensitive platform name (e.g. "youtube", "tiktok").
        client_id:     OAuth client / app ID for the platform.
        client_secret: OAuth client secret for the platform.
        redirect_uri:  The OAuth callback URI registered with the platform.

    Returns:
        A concrete BasePlatformService subclass instance.

    Raises:
        ValueError: If the platform name is not recognised.

    Example::

        svc = get_platform_service(
            platform="youtube",
            client_id=os.environ["YOUTUBE_CLIENT_ID"],
            client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
            redirect_uri="https://myapp.com/auth/youtube/callback",
        )
        auth_url = await svc.get_auth_url(state="random-csrf-token")
    """
    key = platform.lower().strip()
    service_cls = _PLATFORM_MAP.get(key)
    if service_cls is None:
        supported = ", ".join(sorted(_PLATFORM_MAP.keys()))
        raise ValueError(
            f"Unknown platform '{platform}'. "
            f"Supported platforms: {supported}"
        )
    return service_cls(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )


def list_supported_platforms() -> list[str]:
    """Return the list of canonical (non-alias) platform names."""
    # Deduplicate: "x" is an alias for "twitter"
    return sorted({
        "youtube", "instagram", "tiktok", "twitter",
        "pinterest", "linkedin", "facebook", "snapchat",
    })
