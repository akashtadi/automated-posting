"""Environment-driven configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # General
    app_name: str = "Automated Multi-Platform Posting"
    # When true, platforms simulate posts instead of calling real APIs and the
    # response is flagged with "dry_run": true. Off by default: real results only.
    dry_run: bool = False
    request_timeout_seconds: float = 20.0
    log_level: str = "INFO"

    # LinkedIn (Posts API)
    linkedin_access_token: str | None = None
    linkedin_author_urn: str | None = None  # e.g. urn:li:person:abc123 or urn:li:organization:123
    linkedin_api_version: str = "202610"  # YYYYMM; LinkedIn retires versions after ~1 year

    # X / Twitter (API v2). Preferred: OAuth 1.0a user context (tokens do not expire).
    twitter_api_key: str | None = None  # consumer key
    twitter_api_secret: str | None = None  # consumer secret
    twitter_access_token: str | None = None
    twitter_access_token_secret: str | None = None
    # Alternative: OAuth 2.0 user-context access token (tweet.write scope, expires after ~2h).
    twitter_oauth2_user_token: str | None = None

    # Meta Graph API (Facebook + Instagram)
    facebook_graph_version: str = "v24.0"

    # Facebook Page
    facebook_page_id: str | None = None
    facebook_page_access_token: str | None = None

    # Instagram (Graph API, business/creator account; requires an image)
    instagram_user_id: str | None = None
    instagram_access_token: str | None = None
    instagram_image_url: str | None = None

    # Reddit (script app, password grant)
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_username: str | None = None
    reddit_password: str | None = None
    reddit_subreddit: str | None = None
    reddit_user_agent: str = "python:automated-posting:1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
