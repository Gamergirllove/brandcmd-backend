"""
linkedin.py — LinkedInService: OAuth 2.0 via LinkedIn API v2.
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

_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_ME_URL = "https://api.linkedin.com/v2/me"
_EMAIL_URL = "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))"
_NETWORK_SIZE_URL_TMPL = "https://api.linkedin.com/v2/networkSizes/{person_urn}?edgeType=CompanyFollowedByMember"
_SHARE_STATS_URL = "https://api.linkedin.com/v2/organizationalEntityShareStatistics"
_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"

_SCOPES = "r_liteprofile r_emailaddress w_member_social"


class LinkedInService(BasePlatformService):
    """
    OAuth 2.0 integration for LinkedIn (personal profiles and org pages).

    Obtain credentials from https://www.linkedin.com/developers/apps
    """

    async def get_auth_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "scope": _SCOPES,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> PlatformTokens:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(_TOKEN_URL, data=payload, headers=headers)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            raise PlatformAuthError(
                f"LinkedIn token exchange failed: {data.get('error_description', data)}"
            )
        return self._parse_tokens(data)

    async def refresh_token(self, refresh_token: str) -> PlatformTokens:
        """
        LinkedIn issues refresh tokens only for select partner apps.
        For standard apps the access token is valid for 60 days;
        this method attempts refresh and falls back gracefully.
        """
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(_TOKEN_URL, data=payload, headers=headers)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            raise PlatformAuthError(
                f"LinkedIn token refresh failed: {data.get('error_description', data)}"
            )
        tokens = self._parse_tokens(data)
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        return tokens

    async def get_profile(self, tokens: PlatformTokens) -> dict:
        self._assert_token_valid(tokens)
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        async with httpx.AsyncClient() as client:
            me_resp = await client.get(
                _ME_URL,
                params={"projection": "(id,firstName,lastName,profilePicture(displayImage~:playableStreams))"},
                headers=headers,
            )
        if me_resp.status_code != 200:
            raise PlatformAPIError(
                f"LinkedIn /me API error {me_resp.status_code}: {me_resp.text}"
            )
        me = me_resp.json()
        person_id = me.get("id", "")
        person_urn = f"urn:li:person:{person_id}"

        first_name = self._localized(me.get("firstName", {}))
        last_name = self._localized(me.get("lastName", {}))

        # Network size (followers/connections)
        connections = 0
        try:
            async with httpx.AsyncClient() as client:
                net_resp = await client.get(
                    _NETWORK_SIZE_URL_TMPL.format(person_urn=person_urn),
                    headers=headers,
                )
            if net_resp.status_code == 200:
                connections = net_resp.json().get("firstDegreeSize", 0)
        except Exception:
            pass

        return {
            "id": person_id,
            "username": f"{first_name} {last_name}".strip(),
            "first_name": first_name,
            "last_name": last_name,
            "followers": connections,
            "person_urn": person_urn,
        }

    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        """
        Fetches share statistics for the authenticated member's UGC posts.

        Note: Detailed per-day impression data requires the LinkedIn Marketing
        Developer Platform (organization analytics). Personal share stats are
        aggregated here from the shareStatistics endpoint.
        """
        self._assert_token_valid(tokens)
        profile = await self.get_profile(tokens)
        person_urn = profile.get("person_urn", "")

        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        end_ms = int(datetime.utcnow().timestamp() * 1000)
        start_ms = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)

        params = {
            "q": "organizationalEntity",
            "organizationalEntity": person_urn,
            "timeIntervals.timeGranularityType": "DAY",
            "timeIntervals.timeRange.start": start_ms,
            "timeIntervals.timeRange.end": end_ms,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(_SHARE_STATS_URL, params=params, headers=headers)

        daily_data: list[DailyPoint] = []
        total_views = total_likes = total_comments = total_shares = 0

        if resp.status_code == 200:
            elements = resp.json().get("elements", [])
            for element in elements:
                time_range = element.get("timeRange", {})
                start_ts = time_range.get("start", 0) / 1000
                date_str = datetime.utcfromtimestamp(start_ts).date().isoformat()
                stats = element.get("totalShareStatistics", {})
                impressions = int(stats.get("impressionCount", 0))
                likes = int(stats.get("likeCount", 0))
                comments = int(stats.get("commentCount", 0))
                shares = int(stats.get("shareCount", 0))
                total_views += impressions
                total_likes += likes
                total_comments += comments
                total_shares += shares
                daily_data.append(DailyPoint(
                    date=date_str,
                    views=impressions,
                    impressions=impressions,
                    likes=likes,
                    comments=comments,
                    shares=shares,
                ))

        return AnalyticsData(
            followers=profile.get("followers", 0),
            total_views=total_views,
            total_likes=total_likes,
            total_comments=total_comments,
            total_shares=total_shares,
            daily_data=sorted(daily_data, key=lambda p: p.date),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _localized(obj: dict) -> str:
        """Extract a localized string from a LinkedIn localized field."""
        preferred = obj.get("preferredLocale", {})
        lang = preferred.get("language", "en")
        country = preferred.get("country", "US")
        key = f"{lang}_{country}"
        return obj.get("localized", {}).get(key, "")

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
