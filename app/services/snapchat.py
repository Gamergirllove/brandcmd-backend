"""
snapchat.py — SnapchatService: OAuth 2.0 via Snapchat Marketing / Creator API.
"""
from __future__ import annotations

import base64
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

_AUTH_URL = "https://accounts.snapchat.com/login/oauth2/authorize"
_TOKEN_URL = "https://accounts.snapchat.com/login/oauth2/access_token"
_ME_URL = "https://adsapi.snapchat.com/v1/me"
_ORGANIZATIONS_URL = "https://adsapi.snapchat.com/v1/me/organizations"
# Public Profile / Creator API (Snap Kit)
_SNAP_ME_URL = "https://kit.snapchat.com/v1/me"

_SCOPES = "snapchat-marketing-api"


class SnapchatService(BasePlatformService):
    """
    OAuth 2.0 integration for Snapchat.

    Supports both the Ads API (for business accounts) and the
    Snap Kit Login API (for creator / public profiles).

    Register your app at https://kit.snapchat.com/ or
    https://business.snapchat.com/ depending on use case.
    """

    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> PlatformTokens:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        headers = {
            "Authorization": f"Basic {self._basic_auth()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(_TOKEN_URL, data=payload, headers=headers)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            raise PlatformAuthError(
                f"Snapchat token exchange failed: {data.get('error_description', data)}"
            )
        return self._parse_tokens(data)

    async def refresh_token(self, refresh_token: str) -> PlatformTokens:
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        headers = {
            "Authorization": f"Basic {self._basic_auth()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(_TOKEN_URL, data=payload, headers=headers)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            raise PlatformAuthError(
                f"Snapchat token refresh failed: {data.get('error_description', data)}"
            )
        tokens = self._parse_tokens(data)
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        return tokens

    async def get_profile(self, tokens: PlatformTokens) -> dict:
        """
        Fetch authenticated user profile.

        Tries the Snap Kit /me endpoint (creator login) first; falls back to
        the Ads API /me endpoint for business accounts.
        """
        self._assert_token_valid(tokens)
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "Content-Type": "application/json",
        }
        # Try Snap Kit (creator)
        async with httpx.AsyncClient() as client:
            snap_resp = await client.get(_SNAP_ME_URL, headers=headers)
        if snap_resp.status_code == 200:
            data = snap_resp.json().get("data", {}).get("me", {})
            return {
                "id": data.get("externalId"),
                "username": data.get("displayName"),
                "bitmoji_avatar": data.get("bitmojiTwoDAvatarUrl"),
                "followers": 0,   # not available in Snap Kit
            }

        # Fall back to Ads API
        async with httpx.AsyncClient() as client:
            ads_resp = await client.get(_ME_URL, headers=headers)
        if ads_resp.status_code != 200:
            raise PlatformAPIError(
                f"Snapchat profile API error {ads_resp.status_code}: {ads_resp.text}"
            )
        data = ads_resp.json().get("me", {})
        return {
            "id": data.get("id"),
            "username": data.get("display_name"),
            "email": data.get("email"),
            "followers": 0,
        }

    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        """
        Fetch campaign/creative analytics from the Snapchat Ads API.

        For creator accounts without ad accounts this returns empty analytics;
        actual Story analytics require Snap Audience Network access.
        """
        self._assert_token_valid(tokens)
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "Content-Type": "application/json",
        }

        # Get list of ad accounts via organizations
        async with httpx.AsyncClient() as client:
            orgs_resp = await client.get(_ORGANIZATIONS_URL, headers=headers)

        daily_data: list[DailyPoint] = []
        total_views = total_impressions = 0

        if orgs_resp.status_code != 200:
            # No ad account — return empty analytics with profile data
            profile = await self.get_profile(tokens)
            return AnalyticsData(followers=0, daily_data=[])

        orgs = orgs_resp.json().get("organizations", [])
        if not orgs:
            return AnalyticsData(daily_data=[])

        org_id = orgs[0].get("organization", {}).get("id")
        if not org_id:
            return AnalyticsData(daily_data=[])

        # Fetch ad accounts under this org
        async with httpx.AsyncClient() as client:
            accts_resp = await client.get(
                f"https://adsapi.snapchat.com/v1/organizations/{org_id}/adaccounts",
                headers=headers,
            )
        if accts_resp.status_code != 200:
            return AnalyticsData(daily_data=[])

        ad_accounts = accts_resp.json().get("adaccounts", [])
        if not ad_accounts:
            return AnalyticsData(daily_data=[])

        ad_account_id = ad_accounts[0].get("adaccount", {}).get("id")
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days - 1)

        params = {
            "start_time": f"{start_date.isoformat()}T00:00:00.000-0000",
            "end_time": f"{end_date.isoformat()}T23:59:59.000-0000",
            "granularity": "DAY",
            "fields": "impressions,swipe_up_count,spend",
            "breakdown": "ad",
            "report_dimension": "ad",
        }
        async with httpx.AsyncClient() as client:
            stats_resp = await client.get(
                f"https://adsapi.snapchat.com/v1/adaccounts/{ad_account_id}/stats",
                params=params,
                headers=headers,
            )

        if stats_resp.status_code == 200:
            for item in stats_resp.json().get("timeseries_stats", []):
                for ts in item.get("timeseries_stat", {}).get("timeseries", []):
                    date_str = ts.get("start_time", "")[:10]
                    stats = ts.get("stats", {})
                    impressions = int(stats.get("impressions", 0))
                    total_impressions += impressions
                    total_views += impressions
                    daily_data.append(DailyPoint(
                        date=date_str,
                        impressions=impressions,
                        views=impressions,
                        shares=int(stats.get("swipe_up_count", 0)),
                    ))

        profile = await self.get_profile(tokens)
        return AnalyticsData(
            followers=profile.get("followers", 0),
            total_views=total_views,
            daily_data=sorted(daily_data, key=lambda p: p.date),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _basic_auth(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(raw.encode()).decode()

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
