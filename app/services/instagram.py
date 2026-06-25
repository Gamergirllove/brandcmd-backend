"""
instagram.py — InstagramService: OAuth via Facebook Login + Instagram Graph API.
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
)

_GRAPH_BASE = "https://graph.facebook.com/v18.0"
_AUTH_URL = "https://www.facebook.com/v18.0/dialog/oauth"
_TOKEN_URL = f"{_GRAPH_BASE}/oauth/access_token"
_LONG_LIVED_URL = f"{_GRAPH_BASE}/oauth/access_token"

_SCOPES = [
    "instagram_basic",
    "instagram_manage_insights",
    "pages_show_list",
    "pages_read_engagement",
]


class InstagramService(BasePlatformService):
    """
    OAuth 2.0 integration for Instagram via the Facebook Login flow.

    Requires a Facebook App with the Instagram Graph API product enabled.
    The app must be linked to an Instagram Professional (Business/Creator) account.
    """

    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": ",".join(_SCOPES),
            "response_type": "code",
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> PlatformTokens:
        """Exchange short-lived code → short-lived token → long-lived token."""
        # Step 1: short-lived token
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(_TOKEN_URL, params=payload)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            err = data.get("error", {})
            raise PlatformAuthError(
                f"Instagram short-lived token exchange failed: "
                f"{err.get('message', data)}"
            )
        short_lived_token = data["access_token"]

        # Step 2: exchange for long-lived token (60-day expiry)
        ll_params = {
            "grant_type": "fb_exchange_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "fb_exchange_token": short_lived_token,
        }
        async with httpx.AsyncClient() as client:
            ll_resp = await client.get(_LONG_LIVED_URL, params=ll_params)
        ll_data = ll_resp.json()
        if ll_resp.status_code != 200 or "error" in ll_data:
            err = ll_data.get("error", {})
            raise PlatformAuthError(
                f"Instagram long-lived token exchange failed: "
                f"{err.get('message', ll_data)}"
            )

        expires_in = ll_data.get("expires_in")
        expires_at: Optional[datetime] = None
        if expires_in:
            expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))

        # Resolve the IG user ID linked to this token
        ig_user_id, username = await self._resolve_ig_user(ll_data["access_token"])

        return PlatformTokens(
            access_token=ll_data["access_token"],
            refresh_token=None,           # Instagram uses token refresh via /refresh_access_token
            expires_at=expires_at,
            scope=ll_data.get("token_type"),
            platform_user_id=ig_user_id,
            platform_username=username,
        )

    async def refresh_token(self, refresh_token: str) -> PlatformTokens:
        """
        Instagram long-lived tokens are refreshed by calling /refresh_access_token.
        Pass the current (still valid) long-lived access_token as refresh_token.
        """
        params = {
            "grant_type": "ig_refresh_token",
            "access_token": refresh_token,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/refresh_access_token", params=params
            )
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            err = data.get("error", {})
            raise PlatformAuthError(
                f"Instagram token refresh failed: {err.get('message', data)}"
            )
        expires_in = data.get("expires_in")
        expires_at: Optional[datetime] = None
        if expires_in:
            expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))

        ig_user_id, username = await self._resolve_ig_user(data["access_token"])
        return PlatformTokens(
            access_token=data["access_token"],
            refresh_token=None,
            expires_at=expires_at,
            scope=data.get("token_type"),
            platform_user_id=ig_user_id,
            platform_username=username,
        )

    async def get_profile(self, tokens: PlatformTokens) -> dict:
        self._assert_token_valid(tokens)
        ig_user_id = tokens.platform_user_id
        if not ig_user_id:
            ig_user_id, _ = await self._resolve_ig_user(tokens.access_token)

        params = {
            "fields": "username,followers_count,media_count,profile_picture_url,biography",
            "access_token": tokens.access_token,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{_GRAPH_BASE}/{ig_user_id}", params=params)
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"Instagram profile API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        return {
            "id": data.get("id"),
            "username": data.get("username"),
            "followers": data.get("followers_count", 0),
            "media_count": data.get("media_count", 0),
            "profile_picture_url": data.get("profile_picture_url"),
            "biography": data.get("biography"),
        }

    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        self._assert_token_valid(tokens)
        ig_user_id = tokens.platform_user_id
        if not ig_user_id:
            ig_user_id, _ = await self._resolve_ig_user(tokens.access_token)

        params = {
            "metric": "impressions,reach,profile_views",
            "period": "day",
            "access_token": tokens.access_token,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/{ig_user_id}/insights", params=params
            )
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"Instagram insights API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()

        # Pivot the flat metric arrays into per-day dict
        day_map: dict[str, DailyPoint] = {}
        for metric_obj in data.get("data", []):
            metric_name = metric_obj.get("name")
            for value_obj in metric_obj.get("values", []):
                end_time = value_obj.get("end_time", "")[:10]   # YYYY-MM-DD
                if end_time not in day_map:
                    day_map[end_time] = DailyPoint(date=end_time)
                point = day_map[end_time]
                val = int(value_obj.get("value", 0))
                if metric_name == "impressions":
                    point.impressions = val
                    point.views = val
                elif metric_name == "reach":
                    pass  # reach is a separate metric, not mapped to views here

        daily_data = sorted(day_map.values(), key=lambda p: p.date)
        # Limit to `days`
        daily_data = daily_data[-days:]

        total_views = sum(p.views for p in daily_data)
        total_impressions = sum(p.impressions for p in daily_data)

        profile = await self.get_profile(tokens)
        return AnalyticsData(
            followers=profile.get("followers", 0),
            total_views=total_views,
            daily_data=daily_data,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_ig_user(self, access_token: str) -> tuple[str, str]:
        """Find the IG user ID and username linked to this FB access token."""
        # Get the list of FB pages
        async with httpx.AsyncClient() as client:
            me_resp = await client.get(
                f"{_GRAPH_BASE}/me/accounts",
                params={"access_token": access_token, "fields": "instagram_business_account,name"},
            )
        if me_resp.status_code != 200:
            raise PlatformAPIError(
                f"Could not resolve Instagram user: {me_resp.text}"
            )
        pages = me_resp.json().get("data", [])
        for page in pages:
            ig_account = page.get("instagram_business_account")
            if ig_account:
                ig_id = ig_account["id"]
                # fetch username
                async with httpx.AsyncClient() as client:
                    user_resp = await client.get(
                        f"{_GRAPH_BASE}/{ig_id}",
                        params={"fields": "username", "access_token": access_token},
                    )
                username = user_resp.json().get("username", "") if user_resp.status_code == 200 else ""
                return ig_id, username
        raise PlatformAPIError(
            "No Instagram Business/Creator account linked to this Facebook token."
        )
