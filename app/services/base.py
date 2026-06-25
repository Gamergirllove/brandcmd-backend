"""
base.py — Abstract base class and shared dataclasses for all platform OAuth services.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TokenExpiredError(Exception):
    """Raised when an access token is expired and cannot be used."""


class PlatformAuthError(Exception):
    """Raised when OAuth exchange or refresh fails."""


class PlatformAPIError(Exception):
    """Raised when a platform API call returns an unexpected error."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PlatformTokens:
    """Holds all OAuth token data returned after authorization."""
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[datetime]          # UTC datetime when access_token expires
    scope: Optional[str]
    platform_user_id: Optional[str]
    platform_username: Optional[str]


@dataclass
class DailyPoint:
    """Analytics data for a single day."""
    date: str                   # ISO-8601 date string, e.g. "2024-01-15"
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    impressions: int = 0


@dataclass
class AnalyticsData:
    """Aggregate analytics data over a time period."""
    followers: int = 0
    total_views: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_shares: int = 0
    daily_data: list[DailyPoint] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Abstract base service
# ---------------------------------------------------------------------------

class BasePlatformService(abc.ABC):
    """
    Abstract base class for every social-platform OAuth integration.

    Concrete subclasses must implement all abstract methods.  Credentials
    (client_id, client_secret, redirect_uri) are injected at construction
    time so no secrets are stored in source code.
    """

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def get_auth_url(self, state: str) -> str:
        """Build the platform OAuth 2.0 authorization URL."""

    @abc.abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> PlatformTokens:
        """Exchange an authorization code for access/refresh tokens."""

    @abc.abstractmethod
    async def refresh_token(self, refresh_token: str) -> PlatformTokens:
        """Use a refresh token to obtain a new access token."""

    @abc.abstractmethod
    async def get_profile(self, tokens: PlatformTokens) -> dict:
        """Fetch the authenticated user's public profile data."""

    @abc.abstractmethod
    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        """Fetch time-series analytics for the authenticated account."""

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _assert_token_valid(self, tokens: PlatformTokens) -> None:
        """Raise TokenExpiredError if the access token is known to be expired."""
        if tokens.expires_at and tokens.expires_at < datetime.utcnow():
            raise TokenExpiredError(
                f"Access token expired at {tokens.expires_at.isoformat()}. "
                "Call refresh_token() to obtain a new one."
            )
