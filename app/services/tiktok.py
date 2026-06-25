"""
tiktok.py — TikTokService: OAuth 2.0 with PKCE via TikTok for Developers API v2.
"""
from __future__ import annotations

from collections import defaultdict
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
)
from .pkce import generate_code_challenge, generate_code_verifier

_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
_VIDEO_LIST_URL = "https://open.tiktokapis.com/v2/video/list/"

_SCOPES = "user.info.basic,video.list"

# In-memory PKCE verifier store keyed by state.
# In production replace with Redis or a DB-backed store.
_pkce_store: dict[str, str] = {}


class TikTokService(BasePlatformService):
    """
    OAuth 2.0 + PKCE integration for TikTok.

    Register your app at https://developers.tiktok.com/ and obtain
    a client_key (== client_id) and client_secret.
    """

    async def get_auth_url(self, state: str) -> str:
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        # Persist verifier so exchange_code() can retrieve it
        _pkce_store[state] = verifier

        params = {
            "client_key": self.client_id,
            "scope": _SCOPES,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str, state: str = "") -> PlatformTokens:
        """
        Exchange authorization code for tokens.

        Args:
            code:         Authorization code from callback.
            redirect_uri: Must match the URI used in get_auth_url.
            state:        The state value used in get_auth_url (needed to look
                          up the PKCE verifier).
        """
        verifier = _pkce_store.pop(state, None)
        if not verifier:
            raise PlatformAuthError(
                "PKCE verifier not found for this state. "
                "Ensure get_auth_url() was called with the same state value."
            )
        payload = {
            "client_key": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(_TOKEN_URL, data=payload, headers=headers)
        data = resp.json()
        if resp.status_code != 200 or data.get("error"):
            raise PlatformAuthError(
                f"TikTok token exchange failed: {data.get('error_description', data)}"
            )
        return self._parse_tokens(data)

    async def refresh_token(self, refresh_token: str) -> PlatformTokens:
        payload = {
            "client_key": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(_TOKEN_URL, data=payload, headers=headers)
        data = resp.json()
        if resp.status_code != 200 or data.get("error"):
            raise PlatformAuthError(
                f"TikTok token refresh failed: {data.get('error_description', data)}"
            )
        return self._parse_tokens(data)

    async def get_profile(self, tokens: PlatformTokens) -> dict:
        self._assert_token_valid(tokens)
        payload = {
            "fields": "open_id,display_name,follower_count,following_count,video_count,avatar_url",
        }
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(_USER_INFO_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"TikTok user info API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        if data.get("error", {}).get("code") != "ok":
            raise PlatformAPIError(f"TikTok user info error: {data}")
        user = data.get("data", {}).get("user", {})
        return {
            "id": user.get("open_id"),
            "username": user.get("display_name"),
            "followers": user.get("follower_count", 0),
            "following": user.get("following_count", 0),
            "video_count": user.get("video_count", 0),
            "avatar_url": user.get("avatar_url"),
        }

    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        self._assert_token_valid(tokens)
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "Content-Type": "application/json",
        }
        # Paginate through video list (max 20 per page)
        all_videos: list[dict] = []
        cursor = 0
        has_more = True
        while has_more:
            payload = {
                "fields": "id,create_time,view_count,like_count,comment_count,share_count",
                "max_count": 20,
                "cursor": cursor,
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(_VIDEO_LIST_URL, json=payload, headers=headers)
            if resp.status_code != 200:
                raise PlatformAPIError(
                    f"TikTok video list API error {resp.status_code}: {resp.text}"
                )
            body = resp.json()
            if body.get("error", {}).get("code") != "ok":
                break
            page_data = body.get("data", {})
            videos = page_data.get("videos", [])
            all_videos.extend(videos)
            has_more = page_data.get("has_more", False)
            cursor = page_data.get("cursor", 0)
            if not has_more or len(all_videos) >= 200:
                break

        # Filter to `days` window and aggregate
        cutoff = datetime.utcnow() - timedelta(days=days)
        day_map: dict[str, DailyPoint] = defaultdict(lambda: DailyPoint(date=""))

        for video in all_videos:
            ts = video.get("create_time", 0)
            created = datetime.utcfromtimestamp(ts)
            if created < cutoff:
                continue
            date_str = created.date().isoformat()
            if not day_map[date_str].date:
                day_map[date_str].date = date_str
            day_map[date_str].views += int(video.get("view_count", 0))
            day_map[date_str].likes += int(video.get("like_count", 0))
            day_map[date_str].comments += int(video.get("comment_count", 0))
            day_map[date_str].shares += int(video.get("share_count", 0))

        daily_data = sorted(day_map.values(), key=lambda p: p.date)

        profile = await self.get_profile(tokens)
        return AnalyticsData(
            followers=profile.get("followers", 0),
            total_views=sum(p.views for p in daily_data),
            total_likes=sum(p.likes for p in daily_data),
            total_comments=sum(p.comments for p in daily_data),
            total_shares=sum(p.shares for p in daily_data),
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
            platform_user_id=data.get("open_id"),
            platform_username=None,
        )
