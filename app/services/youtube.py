"""
youtube.py — YouTubeService: OAuth 2.0 via Google + YouTube Data/Analytics APIs.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx

from .base import (
    AnalyticsData,
    BasePlatformService,
    DailyPoint,
    PlatformAPIError,
    PlatformAuthError,
    PlatformTokens,
    TokenExpiredError,
)

_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
_ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "openid",
    "email",
    "profile",
]


class YouTubeService(BasePlatformService):
    """
    OAuth 2.0 integration with YouTube (Google).

    Credentials must be obtained from Google Cloud Console
    (OAuth 2.0 Client ID for a Web Application).
    """

    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",          # force refresh_token to be returned
        }
        return f"{_AUTH_BASE}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> PlatformTokens:
        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(_TOKEN_URL, data=payload)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            raise PlatformAuthError(
                f"YouTube token exchange failed: {data.get('error_description', data)}"
            )
        return self._parse_tokens(data)

    async def refresh_token(self, refresh_token: str) -> PlatformTokens:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(_TOKEN_URL, data=payload)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            raise PlatformAuthError(
                f"YouTube token refresh failed: {data.get('error_description', data)}"
            )
        tokens = self._parse_tokens(data)
        # Google does not re-issue a new refresh token on refresh; keep original
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        return tokens

    async def get_profile(self, tokens: PlatformTokens) -> dict:
        self._assert_token_valid(tokens)
        params = {"part": "snippet,statistics", "mine": "true"}
        headers = {"Authorization": f"Bearer {tokens.access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(_CHANNELS_URL, params=params, headers=headers)
        if resp.status_code != 200:
            raise PlatformAPIError(f"YouTube channels API error {resp.status_code}: {resp.text}")
        data = resp.json()
        items = data.get("items", [])
        if not items:
            return {}
        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        return {
            "id": item.get("id"),
            "username": snippet.get("title"),
            "description": snippet.get("description"),
            "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url"),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "view_count": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
        }

    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        self._assert_token_valid(tokens)
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days - 1)
        params = {
            "ids": "channel==MINE",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "metrics": "views,likes,comments,subscribersGained",
            "dimensions": "day",
            "sort": "day",
        }
        headers = {"Authorization": f"Bearer {tokens.access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(_ANALYTICS_URL, params=params, headers=headers)
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"YouTube Analytics API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        column_headers = [h["name"] for h in data.get("columnHeaders", [])]
        rows = data.get("rows", [])

        daily_data: list[DailyPoint] = []
        total_views = total_likes = total_comments = 0

        for row in rows:
            row_dict = dict(zip(column_headers, row))
            date_str = row_dict.get("day", "")
            views = int(row_dict.get("views", 0))
            likes = int(row_dict.get("likes", 0))
            comments = int(row_dict.get("comments", 0))
            total_views += views
            total_likes += likes
            total_comments += comments
            daily_data.append(DailyPoint(
                date=date_str,
                views=views,
                likes=likes,
                comments=comments,
            ))

        # fetch subscriber count for followers field
        profile = await self.get_profile(tokens)
        followers = profile.get("subscribers", 0)

        return AnalyticsData(
            followers=followers,
            total_views=total_views,
            total_likes=total_likes,
            total_comments=total_comments,
            daily_data=daily_data,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tokens(data: dict) -> PlatformTokens:
        expires_in = data.get("expires_in")
        expires_at: Optional[datetime] = None
        if expires_in is not None:
            expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
        return PlatformTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scope=data.get("scope"),
            platform_user_id=None,
            platform_username=None,
        )
