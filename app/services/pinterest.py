"""
pinterest.py — PinterestService: OAuth 2.0 via Pinterest API v5.
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

_AUTH_URL = "https://www.pinterest.com/oauth/"
_TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
_USER_ACCOUNT_URL = "https://api.pinterest.com/v5/user_account"
_ANALYTICS_URL = "https://api.pinterest.com/v5/user_account/analytics"

_SCOPES = "boards:read,pins:read,user_accounts:read"


class PinterestService(BasePlatformService):
    """
    OAuth 2.0 integration for Pinterest API v5.

    Register your app at https://developers.pinterest.com/ to obtain
    client_id and client_secret.
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
                f"Pinterest token exchange failed: {data.get('error_description', data)}"
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
                f"Pinterest token refresh failed: {data.get('error_description', data)}"
            )
        tokens = self._parse_tokens(data)
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        return tokens

    async def get_profile(self, tokens: PlatformTokens) -> dict:
        self._assert_token_valid(tokens)
        headers = {"Authorization": f"Bearer {tokens.access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(_USER_ACCOUNT_URL, headers=headers)
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"Pinterest user_account API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        return {
            "id": data.get("profile_image"),          # Pinterest has no numeric ID in this endpoint
            "username": data.get("username"),
            "business_name": data.get("business_name"),
            "account_type": data.get("account_type"),
            "profile_image": data.get("profile_image"),
            "website": data.get("website_url"),
            "followers": data.get("follower_count", 0),
            "following": data.get("following_count", 0),
            "monthly_views": data.get("monthly_views", 0),
            "pin_count": data.get("pin_count", 0),
        }

    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        self._assert_token_valid(tokens)
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days - 1)
        params = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "metric_types": "IMPRESSION,SAVE,PIN_CLICK,OUTBOUND_CLICK",
        }
        headers = {"Authorization": f"Bearer {tokens.access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(_ANALYTICS_URL, params=params, headers=headers)
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"Pinterest analytics API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()

        daily_data: list[DailyPoint] = []
        total_views = total_shares = 0

        # Pinterest returns a list of daily metric objects
        for day_obj in data.get("all", {}).get("daily_metrics", []):
            date_str = day_obj.get("date", "")
            metrics = day_obj.get("metrics", {})
            impressions = int(metrics.get("IMPRESSION", 0))
            saves = int(metrics.get("SAVE", 0))
            clicks = int(metrics.get("PIN_CLICK", 0))
            total_views += impressions
            total_shares += saves
            daily_data.append(DailyPoint(
                date=date_str,
                views=impressions,
                impressions=impressions,
                shares=saves,
                likes=clicks,
            ))

        profile = await self.get_profile(tokens)
        return AnalyticsData(
            followers=profile.get("followers", 0),
            total_views=total_views,
            total_shares=total_shares,
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
