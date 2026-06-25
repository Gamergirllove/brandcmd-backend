import secrets
import httpx
import urllib.parse
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.dependencies import get_current_user
from app.services.token_store import store_tokens, delete_tokens, list_connected_platforms
from app.models import OAuthURLResponse, DisconnectResponse, ConnectStatusResponse, PlatformStatus

router = APIRouter(prefix="/connect", tags=["connect"])

OAUTH_CONFIGS = {
    "youtube": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/youtube.readonly",
        "client_id_key": "youtube_client_id",
        "client_secret_key": "youtube_client_secret",
        "extra_params": {"access_type": "offline", "prompt": "consent"},
    },
    "instagram": {
        "auth_url": "https://api.instagram.com/oauth/authorize",
        "token_url": "https://api.instagram.com/oauth/access_token",
        "scope": "user_profile,user_media,instagram_manage_insights",
        "client_id_key": "instagram_client_id",
        "client_secret_key": "instagram_client_secret",
        "extra_params": {},
    },
    "tiktok": {
        "auth_url": "https://www.tiktok.com/v2/auth/authorize/",
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "scope": "user.info.basic,video.list",
        "client_id_key": "tiktok_client_key",
        "client_secret_key": "tiktok_client_secret",
        "extra_params": {},
    },
    "twitter": {
        "auth_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "scope": "tweet.read users.read offline.access",
        "client_id_key": "twitter_client_id",
        "client_secret_key": "twitter_client_secret",
        "extra_params": {"code_challenge": "challenge", "code_challenge_method": "plain"},
    },
    "pinterest": {
        "auth_url": "https://www.pinterest.com/oauth/",
        "token_url": "https://api.pinterest.com/v5/oauth/token",
        "scope": "boards:read,pins:read,user_accounts:read",
        "client_id_key": "pinterest_client_id",
        "client_secret_key": "pinterest_client_secret",
        "extra_params": {},
    },
    "linkedin": {
        "auth_url": "https://www.linkedin.com/oauth/v2/authorization",
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "scope": "r_liteprofile r_emailaddress r_organization_social",
        "client_id_key": "linkedin_client_id",
        "client_secret_key": "linkedin_client_secret",
        "extra_params": {},
    },
    "facebook": {
        "auth_url": "https://www.facebook.com/v18.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v18.0/oauth/access_token",
        "scope": "pages_show_list,pages_read_engagement,read_insights",
        "client_id_key": "facebook_client_id",
        "client_secret_key": "facebook_client_secret",
        "extra_params": {},
    },
    "snapchat": {
        "auth_url": "https://accounts.snapchat.com/login/oauth2/authorize",
        "token_url": "https://accounts.snapchat.com/login/oauth2/access_token",
        "scope": "snapchat-marketing-api",
        "client_id_key": "snapchat_client_id",
        "client_secret_key": "snapchat_client_secret",
        "extra_params": {},
    },
}


def _callback_url(platform: str, settings) -> str:
    return f"{settings.frontend_url}/connect/{platform}/callback"


@router.get("/status", response_model=ConnectStatusResponse)
async def get_connect_status(user_id: str = Depends(get_current_user)):
    connected_records = await list_connected_platforms(user_id)
    connected_map = {r["platform"]: r for r in connected_records}
    platforms = []
    for platform in OAUTH_CONFIGS.keys():
        record = connected_map.get(platform)
        platforms.append(
            PlatformStatus(
                platform=platform,
                connected=record is not None,
                username=record.get("username") if record else None,
                connected_at=record.get("created_at") if record else None,
            )
        )
    return ConnectStatusResponse(platforms=platforms)


@router.get("/{platform}/url", response_model=OAuthURLResponse)
async def get_oauth_url(platform: str, user_id: str = Depends(get_current_user)):
    platform = platform.lower()
    if platform not in OAUTH_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Platform '{platform}' is not supported")

    settings = get_settings()
    config = OAUTH_CONFIGS[platform]
    client_id = getattr(settings, config["client_id_key"], "")
    if not client_id:
        raise HTTPException(status_code=503, detail=f"{platform} OAuth is not configured")

    state = secrets.token_urlsafe(32)
    params = {
        "client_id": client_id,
        "redirect_uri": _callback_url(platform, settings),
        "response_type": "code",
        "scope": config["scope"],
        "state": f"{user_id}:{state}",
        **config["extra_params"],
    }
    url = config["auth_url"] + "?" + urllib.parse.urlencode(params)
    return OAuthURLResponse(url=url, platform=platform)


@router.get("/{platform}/callback")
async def oauth_callback(
    platform: str,
    code: str = Query(...),
    state: str = Query(default=""),
    error: Optional[str] = Query(default=None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error from {platform}: {error}")

    platform = platform.lower()
    if platform not in OAUTH_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Platform '{platform}' is not supported")

    if ":" not in state:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    user_id = state.split(":")[0]

    settings = get_settings()
    config = OAUTH_CONFIGS[platform]
    client_id = getattr(settings, config["client_id_key"], "")
    client_secret = getattr(settings, config["client_secret_key"], "")

    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            config["token_url"],
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": _callback_url(platform, settings),
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )

    if token_resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Token exchange failed for {platform}: {token_resp.text}",
        )

    token_data = token_resp.json()
    if "error" in token_data:
        raise HTTPException(
            status_code=400,
            detail=f"Token exchange error: {token_data.get('error_description', token_data['error'])}",
        )

    token_data = await _enrich_tokens(platform, token_data, settings)
    await store_tokens(user_id, platform, token_data)

    return RedirectResponse(
        url=f"{settings.frontend_url}/connect/{platform}/success",
        status_code=302,
    )


@router.delete("/{platform}", response_model=DisconnectResponse)
async def disconnect_platform(platform: str, user_id: str = Depends(get_current_user)):
    platform = platform.lower()
    if platform not in OAUTH_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Platform '{platform}' is not supported")
    deleted = await delete_tokens(user_id, platform)
    return DisconnectResponse(
        success=True,
        platform=platform,
        message=f"{'Disconnected' if deleted else 'Was not connected'} from {platform}",
    )


async def _enrich_tokens(platform: str, token_data: dict, settings) -> dict:
    try:
        access_token = token_data.get("access_token", "")
        async with httpx.AsyncClient(timeout=15) as client:
            if platform == "youtube":
                resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "snippet", "mine": "true"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    if items:
                        snippet = items[0].get("snippet", {})
                        token_data["username"] = snippet.get("customUrl") or snippet.get("title")
            elif platform == "instagram":
                resp = await client.get(
                    "https://graph.instagram.com/v18.0/me",
                    params={"fields": "username", "access_token": access_token},
                )
                if resp.status_code == 200:
                    token_data["username"] = resp.json().get("username")
            elif platform == "tiktok":
                resp = await client.post(
                    "https://open.tiktokapis.com/v2/user/info/",
                    params={"fields": "display_name"},
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={},
                )
                if resp.status_code == 200:
                    token_data["username"] = (
                        resp.json().get("data", {}).get("user", {}).get("display_name")
                    )
            elif platform == "twitter":
                resp = await client.get(
                    "https://api.twitter.com/2/users/me",
                    params={"user.fields": "username"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code == 200:
                    user = resp.json().get("data", {})
                    token_data["username"] = user.get("username")
                    token_data["twitter_user_id"] = user.get("id")
            elif platform == "linkedin":
                resp = await client.get(
                    "https://api.linkedin.com/v2/me",
                    params={"projection": "(id,localizedFirstName,localizedLastName)"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code == 200:
                    d = resp.json()
                    token_data["username"] = f"{d.get('localizedFirstName','')} {d.get('localizedLastName','')}".strip()
            elif platform == "facebook":
                resp = await client.get(
                    "https://graph.facebook.com/v18.0/me",
                    params={"fields": "name", "access_token": access_token},
                )
                if resp.status_code == 200:
                    token_data["username"] = resp.json().get("name")
    except Exception:
        pass
    return token_data
