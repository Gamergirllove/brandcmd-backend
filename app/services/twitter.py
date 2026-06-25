"""
twitter.py — TwitterService: OAuth 2.0 with PKCE (Twitter/X API v2).
"""
from __future__ import annotations

import base64
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

_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
_ME_URL = "https://api.twitter.com/2/users/me"
_TWEETS_URL_TMPL = "https://api.twitter.com/2/users/{user_id}/tweets"

_SCOPES = "tweet.read users.read offline.access"

# In-memory PKCE verifier store keyed by state.
_pkce_store: dict[str, str] = {}


class TwitterService(BasePlatformService):
    """
    OAuth 2.0 + PKCE integration for Twitter / X API v2.

    Obtain client_id and client_secret from the Twitter Developer Portal
    (OAuth 2.0 section of your app settings).
    """

    async def get_auth_url(self, state: str) -> str:
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        _pkce_store[state] = verifier

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": _SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str, state: str = "") -> PlatformTokens:
        verifier = _pkce_store.pop(state, None)
        if not verifier:
            raise PlatformAuthError(
                "PKCE verifier not found for state. Call get_auth_url() first."
            )
        payload = {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
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
                f"Twitter token exchange failed: {data.get('error_description', data)}"
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
                f"Twitter token refresh failed: {data.get('error_description', data)}"
            )
        return self._parse_tokens(data)

    async def get_profile(self, tokens: PlatformTokens) -> dict:
        self._assert_token_valid(tokens)
        params = {
            "user.fields": "public_metrics,profile_image_url,description,username,name",
        }
        headers = {"Authorization": f"Bearer {tokens.access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(_ME_URL, params=params, headers=headers)
        if resp.status_code != 200:
            raise PlatformAPIError(
                f"Twitter users/me API error {resp.status_code}: {resp.text}"
            )
        data = resp.json().get("data", {})
        metrics = data.get("public_metrics", {})
        return {
            "id": data.get("id"),
            "username": data.get("username"),
            "name": data.get("name"),
            "description": data.get("description"),
            "profile_image_url": data.get("profile_image_url"),
            "followers": metrics.get("followers_count", 0),
            "following": metrics.get("following_count", 0),
            "tweet_count": metrics.get("tweet_count", 0),
            "listed_count": metrics.get("listed_count", 0),
        }

    async def get_analytics(self, tokens: PlatformTokens, days: int = 30) -> AnalyticsData:
        self._assert_token_valid(tokens)
        user_id = tokens.platform_user_id
        if not user_id:
            profile = await self.get_profile(tokens)
            user_id = profile["id"]

        start_time = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        tweets_url = _TWEETS_URL_TMPL.format(user_id=user_id)
        headers = {"Authorization": f"Bearer {tokens.access_token}"}

        all_tweets: list[dict] = []
        pagination_token: Optional[str] = None

        while True:
            params: dict = {
                "tweet.fields": "public_metrics,created_at",
                "max_results": 100,
                "start_time": start_time,
            }
            if pagination_token:
                params["pagination_token"] = pagination_token

            async with httpx.AsyncClient() as client:
                resp = await client.get(tweets_url, params=params, headers=headers)
            if resp.status_code != 200:
                raise PlatformAPIError(
                    f"Twitter tweets API error {resp.status_code}: {resp.text}"
                )
            body = resp.json()
            tweets = body.get("data", [])
            all_tweets.extend(tweets)
            meta = body.get("meta", {})
            pagination_token = meta.get("next_token")
            if not pagination_token:
                break

        # Aggregate by day
        day_map: dict[str, DailyPoint] = defaultdict(lambda: DailyPoint(date=""))
        for tweet in all_tweets:
            created_at = tweet.get("created_at", "")
            date_str = created_at[:10]  # YYYY-MM-DD
            metrics = tweet.get("public_metrics", {})
            if not day_map[date_str].date:
                day_map[date_str].date = date_str
            day_map[date_str].likes += int(metrics.get("like_count", 0))
            day_map[date_str].comments += int(metrics.get("reply_count", 0))
            day_map[date_str].shares += int(metrics.get("retweet_count", 0))
            # impressions_count available on v2 with Elevated access
            day_map[date_str].impressions += int(metrics.get("impression_count", 0))

        daily_data = sorted(day_map.values(), key=lambda p: p.date)

        profile = await self.get_profile(tokens)
        return AnalyticsData(
            followers=profile.get("followers", 0),
            total_likes=sum(p.likes for p in daily_data),
            total_comments=sum(p.comments for p in daily_data),
            total_shares=sum(p.shares for p in daily_data),
            daily_data=daily_data,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _basic_auth(self) -> str:
        """Return base64-encoded client_id:client_secret for Basic auth header."""
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
