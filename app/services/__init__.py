"""
services/__init__.py — Public API for the platform OAuth services package.
"""
from .base import (
    AnalyticsData,
    BasePlatformService,
    DailyPoint,
    PlatformAPIError,
    PlatformAuthError,
    PlatformTokens,
    TokenExpiredError,
)
from .facebook import FacebookService
from .instagram import InstagramService
from .linkedin import LinkedInService
from .pinterest import PinterestService
from .pkce import generate_code_challenge, generate_code_verifier
from .platform_factory import get_platform_service, list_supported_platforms
from .snapchat import SnapchatService
from .tiktok import TikTokService
from .twitter import TwitterService
from .youtube import YouTubeService

__all__ = [
    # Base types
    "BasePlatformService",
    "PlatformTokens",
    "AnalyticsData",
    "DailyPoint",
    # Exceptions
    "TokenExpiredError",
    "PlatformAuthError",
    "PlatformAPIError",
    # Services
    "YouTubeService",
    "InstagramService",
    "TikTokService",
    "TwitterService",
    "PinterestService",
    "LinkedInService",
    "FacebookService",
    "SnapchatService",
    # Factory
    "get_platform_service",
    "list_supported_platforms",
    # PKCE helpers
    "generate_code_verifier",
    "generate_code_challenge",
]
