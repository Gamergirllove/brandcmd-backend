from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import date


class DailyDataPoint(BaseModel):
    date: str  # ISO date string e.g. "2024-05-01"
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    followers_gained: int = 0


class PlatformStats(BaseModel):
    platform: str
    connected: bool = False
    username: Optional[str] = None
    followers: int = 0
    views_30d: int = 0
    likes_30d: int = 0
    comments_30d: int = 0
    shares_30d: int = 0
    engagement_rate: float = 0.0  # percentage
    daily_data: List[DailyDataPoint] = Field(default_factory=list)
    raw: Optional[Dict[str, Any]] = None  # platform-specific extra fields


class AnalyticsOverview(BaseModel):
    total_followers: int = 0
    total_views_30d: int = 0
    total_engagement_30d: int = 0
    platforms_connected: int = 0
    platforms: List[PlatformStats] = Field(default_factory=list)


class PlatformStatus(BaseModel):
    platform: str
    connected: bool
    username: Optional[str] = None
    connected_at: Optional[str] = None


class ConnectStatusResponse(BaseModel):
    platforms: List[PlatformStatus]


class OAuthURLResponse(BaseModel):
    url: str
    platform: str


class DisconnectResponse(BaseModel):
    success: bool
    platform: str
    message: str


class CompareResponse(BaseModel):
    platforms: List[PlatformStats]
    metric_leaders: Dict[str, str] = Field(default_factory=dict)  # metric -> platform name
