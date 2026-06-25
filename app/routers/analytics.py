from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any

from app.dependencies import get_current_user
from app.services.token_store import list_connected_platforms
from app.services.platform_router import get_service
from app.models import AnalyticsOverview, PlatformStats, DailyDataPoint, CompareResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _build_platform_stats(platform: str, user_id: str) -> PlatformStats:
    """
    Fetch stats for a single platform. Returns a PlatformStats with connected=False
    if the platform is not connected or if the API call fails.
    """
    service = await get_service(platform, user_id)
    if service is None:
        return PlatformStats(platform=platform, connected=False)

    try:
        if platform == "youtube":
            channel = await service.get_channel_stats()
            analytics = await service.get_analytics_30d()
            totals = analytics.get("totals", {})
            daily_raw = analytics.get("daily", [])
            followers = channel.get("subscribers", 0)
            engagement = totals.get("likes", 0) + totals.get("comments", 0) + totals.get("shares", 0)
            engagement_rate = round((engagement / totals.get("views", 1)) * 100, 2) if totals.get("views") else 0.0
            return PlatformStats(
                platform="youtube",
                connected=True,
                username=channel.get("username"),
                followers=followers,
                views_30d=totals.get("views", 0),
                likes_30d=totals.get("likes", 0),
                comments_30d=totals.get("comments", 0),
                shares_30d=totals.get("shares", 0),
                engagement_rate=engagement_rate,
                daily_data=[DailyDataPoint(**d) for d in daily_raw],
                raw={"total_views_all_time": channel.get("total_views"), "video_count": channel.get("video_count")},
            )

        elif platform == "instagram":
            account = await service.get_account_info()
            insights = await service.get_insights_30d()
            media_stats = await service.get_media_stats_30d()
            totals = insights.get("totals", {})
            daily_raw = insights.get("daily", [])
            followers = int(account.get("followers_count", 0))
            views = totals.get("impressions", 0)
            likes = media_stats.get("likes", 0)
            comments = media_stats.get("comments", 0)
            engagement = likes + comments
            engagement_rate = round((engagement / followers) * 100, 2) if followers else 0.0
            return PlatformStats(
                platform="instagram",
                connected=True,
                username=account.get("username"),
                followers=followers,
                views_30d=views,
                likes_30d=likes,
                comments_30d=comments,
                shares_30d=0,
                engagement_rate=engagement_rate,
                daily_data=[DailyDataPoint(**d) for d in daily_raw],
                raw={"media_count": account.get("media_count"), "reach_30d": totals.get("reach", 0)},
            )

        elif platform == "tiktok":
            user_info = await service.get_user_info()
            video_stats = await service.get_video_stats_30d()
            totals = video_stats.get("totals", {})
            daily_raw = video_stats.get("daily", [])
            followers = int(user_info.get("follower_count", 0))
            views = totals.get("views", 0)
            likes = totals.get("likes", 0)
            comments = totals.get("comments", 0)
            shares = totals.get("shares", 0)
            engagement = likes + comments + shares
            engagement_rate = round((engagement / views) * 100, 2) if views else 0.0
            return PlatformStats(
                platform="tiktok",
                connected=True,
                username=user_info.get("display_name"),
                followers=followers,
                views_30d=views,
                likes_30d=likes,
                comments_30d=comments,
                shares_30d=shares,
                engagement_rate=engagement_rate,
                daily_data=[DailyDataPoint(**d) for d in daily_raw],
                raw={"likes_count_total": user_info.get("likes_count"), "video_count": user_info.get("video_count")},
            )

        elif platform == "twitter":
            user_info = await service.get_user_info()
            tweet_metrics = await service.get_tweet_metrics_30d()
            totals = tweet_metrics.get("totals", {})
            daily_raw = tweet_metrics.get("daily", [])
            followers = user_info.get("followers", 0)
            views = totals.get("views", 0)
            likes = totals.get("likes", 0)
            comments = totals.get("comments", 0)
            shares = totals.get("shares", 0)
            engagement = likes + comments + shares
            engagement_rate = round((engagement / views) * 100, 2) if views else 0.0
            return PlatformStats(
                platform="twitter",
                connected=True,
                username=user_info.get("username"),
                followers=followers,
                views_30d=views,
                likes_30d=likes,
                comments_30d=comments,
                shares_30d=shares,
                engagement_rate=engagement_rate,
                daily_data=[DailyDataPoint(**d) for d in daily_raw],
                raw={"tweet_count": user_info.get("tweet_count"), "following": user_info.get("following")},
            )

    except Exception as exc:
        # Return partial data indicating connected but with fetch error
        return PlatformStats(
            platform=platform,
            connected=True,
            raw={"error": str(exc)},
        )

    # For platforms without a full service (pinterest, linkedin, facebook, snapchat)
    # we just indicate connected status
    return PlatformStats(platform=platform, connected=True)


@router.get("/overview", response_model=AnalyticsOverview)
async def get_overview(user_id: str = Depends(get_current_user)):
    """
    Aggregate stats across all connected platforms:
    total_followers, total_views_30d, total_engagement_30d, platforms_connected.
    """
    connected_records = await list_connected_platforms(user_id)
    connected_platforms = [r["platform"] for r in connected_records]

    platform_stats: List[PlatformStats] = []
    for platform in connected_platforms:
        stats = await _build_platform_stats(platform, user_id)
        platform_stats.append(stats)

    total_followers = sum(p.followers for p in platform_stats)
    total_views = sum(p.views_30d for p in platform_stats)
    total_engagement = sum(
        p.likes_30d + p.comments_30d + p.shares_30d for p in platform_stats
    )

    return AnalyticsOverview(
        total_followers=total_followers,
        total_views_30d=total_views,
        total_engagement_30d=total_engagement,
        platforms_connected=len(connected_platforms),
        platforms=platform_stats,
    )


@router.get("/compare", response_model=CompareResponse)
async def compare_platforms(user_id: str = Depends(get_current_user)):
    """Side-by-side platform comparison with metric leaders."""
    connected_records = await list_connected_platforms(user_id)
    connected_platforms = [r["platform"] for r in connected_records]

    platform_stats: List[PlatformStats] = []
    for platform in connected_platforms:
        stats = await _build_platform_stats(platform, user_id)
        platform_stats.append(stats)

    metric_leaders: Dict[str, str] = {}
    if platform_stats:
        metrics = {
            "followers": lambda p: p.followers,
            "views_30d": lambda p: p.views_30d,
            "likes_30d": lambda p: p.likes_30d,
            "comments_30d": lambda p: p.comments_30d,
            "shares_30d": lambda p: p.shares_30d,
            "engagement_rate": lambda p: p.engagement_rate,
        }
        for metric, key_fn in metrics.items():
            best = max(platform_stats, key=key_fn, default=None)
            if best:
                metric_leaders[metric] = best.platform

    return CompareResponse(platforms=platform_stats, metric_leaders=metric_leaders)


@router.get("/{platform}", response_model=PlatformStats)
async def get_platform_analytics(platform: str, user_id: str = Depends(get_current_user)):
    """
    Platform-specific stats: followers, views, likes, comments, shares,
    daily_data (last 30 days).
    """
    platform = platform.lower()
    from app.routers.connect import OAUTH_CONFIGS
    if platform not in OAUTH_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Platform '{platform}' is not supported")

    stats = await _build_platform_stats(platform, user_id)
    if not stats.connected:
        raise HTTPException(
            status_code=404,
            detail=f"Platform '{platform}' is not connected for this account",
        )
    return stats
