from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = Field(..., env="SUPABASE_URL")
    supabase_service_key: str = Field(..., env="SUPABASE_SERVICE_KEY")

    # YouTube / Google
    youtube_client_id: str = Field(default="", env="YOUTUBE_CLIENT_ID")
    youtube_client_secret: str = Field(default="", env="YOUTUBE_CLIENT_SECRET")

    # Instagram
    instagram_client_id: str = Field(default="", env="INSTAGRAM_CLIENT_ID")
    instagram_client_secret: str = Field(default="", env="INSTAGRAM_CLIENT_SECRET")

    # TikTok
    tiktok_client_key: str = Field(default="", env="TIKTOK_CLIENT_KEY")
    tiktok_client_secret: str = Field(default="", env="TIKTOK_CLIENT_SECRET")

    # Twitter / X
    twitter_client_id: str = Field(default="", env="TWITTER_CLIENT_ID")
    twitter_client_secret: str = Field(default="", env="TWITTER_CLIENT_SECRET")

    # Pinterest
    pinterest_client_id: str = Field(default="", env="PINTEREST_CLIENT_ID")
    pinterest_client_secret: str = Field(default="", env="PINTEREST_CLIENT_SECRET")

    # LinkedIn
    linkedin_client_id: str = Field(default="", env="LINKEDIN_CLIENT_ID")
    linkedin_client_secret: str = Field(default="", env="LINKEDIN_CLIENT_SECRET")

    # Facebook
    facebook_client_id: str = Field(default="", env="FACEBOOK_CLIENT_ID")
    facebook_client_secret: str = Field(default="", env="FACEBOOK_CLIENT_SECRET")

    # Snapchat
    snapchat_client_id: str = Field(default="", env="SNAPCHAT_CLIENT_ID")
    snapchat_client_secret: str = Field(default="", env="SNAPCHAT_CLIENT_SECRET")

    # App config
    frontend_url: str = Field(default="http://localhost:3000", env="FRONTEND_URL")
    secret_key: str = Field(default="changeme", env="SECRET_KEY")
    token_encryption_key: str = Field(default="", env="TOKEN_ENCRYPTION_KEY")

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
