from typing import Optional, Union
from app.services.youtube import YouTubeService, get_youtube_service
from app.services.instagram import InstagramService, get_instagram_service
from app.services.tiktok import TikTokService, get_tiktok_service
from app.services.twitter import TwitterService, get_twitter_service

PlatformService = Union[YouTubeService, InstagramService, TikTokService, TwitterService]

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


async def get_service(platform: str, user_id: str) -> Optional[PlatformService]:
    """
    Factory: returns the appropriate service instance for the given platform,
    loaded with the user's stored tokens. Returns None if not connected.
    """
    platform = platform.lower()
    if platform == "youtube":
        return await get_youtube_service(user_id)
    elif platform == "instagram":
        return await get_instagram_service(user_id)
    elif platform == "tiktok":
        return await get_tiktok_service(user_id)
    elif platform == "twitter":
        return await get_twitter_service(user_id)
    # pinterest, linkedin, facebook, snapchat: tokens stored but no dedicated service yet
    return None
