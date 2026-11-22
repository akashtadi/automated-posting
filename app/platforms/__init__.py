from app.platforms import oauth1
from app.platforms.base import Platform, PlatformError, PublishedPost
from app.platforms.facebook import FacebookPlatform
from app.platforms.instagram import InstagramPlatform
from app.platforms.linkedin import LinkedInPlatform
from app.platforms.reddit import RedditPlatform
from app.platforms.twitter import TwitterPlatform

ALL_PLATFORMS: tuple[type[Platform], ...] = (
    LinkedInPlatform,
    TwitterPlatform,
    FacebookPlatform,
    InstagramPlatform,
    RedditPlatform,
)

__all__ = [
    "ALL_PLATFORMS",
    "FacebookPlatform",
    "InstagramPlatform",
    "LinkedInPlatform",
    "Platform",
    "PlatformError",
    "PublishedPost",
    "RedditPlatform",
    "TwitterPlatform",
    "oauth1",
]
