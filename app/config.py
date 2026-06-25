from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = Field(..., validation_alias=AliasChoices("SUPABASE_URL", "supabase_url"))
    supabase_service_key: str = Field(..., validation_alias=AliasChoices("SUPABASE_SERVICE_ROLE_KEY", "supabase_service_key"))

    # YouTube / Google (Render env vars are GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)
    youtube_client_id: str = Field(default="", validation_alias=AliasChoices("GOOGLE_CLIENT_ID", "youtube_client_id"))
    youtube_client_secret: str = Field(default="", validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET", "youtube_client_secret"))

    # Twitch
    twitch_client_id: str = Field(default="")
    twitch_client_secret: str = Field(default="")

    # Instagram
    instagram_client_id: str = Field(default="")
    instagram_client_secret: str = Field(default="")

    # TikTok
    tiktok_client_key: str = Field(default="")
    tiktok_client_secret: str = Field(default="")

    # Twitter / X
    twitter_client_id: str = Field(default="")
    twitter_client_secret: str = Field(default="")

    # Pinterest
    pinterest_client_id: str = Field(default="")
    pinterest_client_secret: str = Field(default="")

    # LinkedIn
    linkedin_client_id: str = Field(default="")
    linkedin_client_secret: str = Field(default="")

    # Facebook
    facebook_client_id: str = Field(default="")
    facebook_client_secret: str = Field(default="")

    # Snapchat
    snapchat_client_id: str = Field(default="")
    snapchat_client_secret: str = Field(default="")

    # App config
    frontend_url: str = Field(default="http://localhost:3000")
    backend_url: str = Field(default="http://localhost:8000")
    secret_key: str = Field(default="changeme")
    token_encryption_key: str = Field(default="")

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
