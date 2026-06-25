"""
facebook.py — FacebookService: OAuth via Facebook Graph API (Page analytics).
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

_SCOPES = [
    "pages_read_engagement",
    "read_insights",
    "public_profile",
    "pages_show_list",
]


class FacebookService(BasePlatformService):
    """
    OAuth 2.0 integration for Facebook Pages via the Graph API.

    Requires a Facebook App with the Pages API product enabled.
    The authenticated user must be an admin of at least one Facebook Page.
    """

    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "scope": ",".join(_SCOPES),
            "response_type": "code",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> PlatformTokens:
        """Exchange code → short-lived user token → long-lived user token."""
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(_TOKEN_URL, params=params)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            err = data.get("error", {})
            raise PlatformAuthError(
                f"Facebook token exchange failed: {err.get('message', data)}"
            )
        short_token = data["access_token"]

        # Extend to long-lived token
        ll_params = {
            "grant_type": "fb_exchange_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "fb_exchange_token": short_token,
        }
        async with httpx.AsyncClient() as client:
            ll_resp = await client.get(_TOKEN_URL, params=ll_params)
        ll_data = ll_resp.json()
        if ll_resp.status_code != 200 or "error" in ll_data:
            err = ll_data.get("error", {})
            raise PlatformAuthError(
                f"Facebook long-lived token exchange failed: {err.get('message', ll_data)}"
            )

        expires_in = ll_data.get("expires_in")
        expires_at: Optional[datetime] = None
        if expires_in:
            expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))

        # Resolve FB user ID
        fb_user_id, username = await self._get_user_info(ll_data["access_token"])
        return PlatformTokens(
            access_token=ll_data["access_token"],
            refresh_token=None,
            expires_at=expires_at,
            scope=",".join(_SCOPES),
            platform_user_id=fb_user_id,
            platform_username=username,
        )

    async def refresh_token(self, refresh_token: str) -> PlatformTokens:
        """
        Facebook long-lived tokens can be refreshed by re-exchanging them.
        Pass the current long-lived token as refresh_token.
        """
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "fb_exchange_token": refresh_token,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(_TOKEN_URL, params=params)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            err = data.get("error", {})
            raise PlatformAuthError(
                f"Facebook token refresh failed: {err.get('message', data)}"
            )
        expires_in = data.get("expires_in")
        expires_at: Optional[datetime] = None
        if expires_in:
            expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))

        fb_user_id, username = await self._get_user_info(data["access_token"])
        return PlatformTokens(
            access_token=data["access_token"],
            refresh_token=None,
            expires_at=expires_at,
            scope=",".join(_SCOPES),
            platform_user_id=fb_user_id,
            platform_username=username,
        )

    async def get_profile(self, tokens: PlatformTokens) -> dict:
        """Return info about the first Page the user admins."""
        self._assert_token_valid(tokens)
        page = await self._get_first_page(tokens.access_token)
        page_id = page["id"]
        page_token = page.get("access_token", tokens.access_token)

        params = {
            "fields": "id,name,followers_count,fan_count,picture,about",
            "access_token": page_token,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{_GRAPH_BASE}/{page_id}", params=params)
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"Facebook Page profile API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        return {
            "id": data.get("id"),
            "username": data.get("name"),
            "followers": data.get("followers_count", 0),
            "fans": data.get("fan_count", 0),
            "about": data.get("about"),
            "picture": data.get("picture", {}).get("data", {}).get("url"),
        }

    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        self._assert_token_valid(tokens)
        page = await self._get_first_page(tokens.access_token)
        page_id = page["id"]
        page_token = page.get("access_token", tokens.access_token)

        since = int((datetime.utcnow() - timedelta(days=days)).timestamp())
        until = int(datetime.utcnow().timestamp())
        params = {
            "metric": "page_impressions,page_engaged_users,page_post_engagements",
            "period": "day",
            "since": since,
            "until": until,
            "access_token": page_token,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/{page_id}/insights", params=params
            )
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"Facebook Page insights API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()

        day_map: dict[str, DailyPoint] = {}
        for metric_obj in data.get("data", []):
            metric_name = metric_obj.get("name")
            for value_obj in metric_obj.get("values", []):
                end_time = value_obj.get("end_time", "")[:10]
                if end_time not in day_map:
                    day_map[end_time] = DailyPoint(date=end_time)
                val = int(value_obj.get("value", 0))
                point = day_map[end_time]
                if metric_name == "page_impressions":
                    point.impressions = val
                    point.views = val
                elif metric_name == "page_engaged_users":
                    point.likes = val

        daily_data = sorted(day_map.values(), key=lambda p: p.date)

        profile = await self.get_profile(tokens)
        return AnalyticsData(
            followers=profile.get("followers", 0),
            total_views=sum(p.views for p in daily_data),
            total_likes=sum(p.likes for p in daily_data),
            daily_data=daily_data,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_user_info(self, access_token: str) -> tuple[str, str]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/me",
                params={"fields": "id,name", "access_token": access_token},
            )
        data = resp.json()
        return data.get("id", ""), data.get("name", "")

    async def _get_first_page(self, access_token: str) -> dict:
        """Return the first managed Facebook Page (with its page access token)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/me/accounts",
                params={"access_token": access_token, "fields": "id,name,access_token"},
            )
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"Facebook /me/accounts error {resp.status_code}: {resp.text}"
            )
        pages = resp.json().get("data", [])
        if not pages:
            raise PlatformAPIError(
                "No Facebook Pages found for this user. "
                "The user must be an admin of at least one Page."
            )
        return pages[0]
