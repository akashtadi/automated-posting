"""Orchestrates posting a message to every configured platform concurrently."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timezone

import httpx

from app.platforms import Platform, PlatformError
from app.schemas import PlatformResult, PostStatus

logger = logging.getLogger(__name__)


class PostingService:
    def __init__(self, platforms: Sequence[Platform], timeout_seconds: float = 20.0):
        self.platforms = list(platforms)
        self.timeout_seconds = timeout_seconds

    async def post_to_all(self, message: str, link: str) -> list[PlatformResult]:
        """Post to all platforms in parallel; a failure on one never affects the others."""
        tasks = [self._post_one(p, message, link) for p in self.platforms]
        return list(await asyncio.gather(*tasks))

    async def _post_one(self, platform: Platform, message: str, link: str) -> PlatformResult:
        try:
            post = await asyncio.wait_for(platform.publish(message, link), self.timeout_seconds)
        except PlatformError as exc:
            error = str(exc)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            error = f"Request timed out after {self.timeout_seconds:g}s"
        except httpx.HTTPError as exc:
            error = f"Network error: {exc.__class__.__name__}"
        except Exception:  # noqa: BLE001 - one platform must never break the batch
            logger.exception("Unexpected error posting to %s", platform.name)
            error = "Unexpected internal error (see server logs)"
        else:
            posted_at = datetime.now(timezone.utc)
            logger.info("Posted to %s: %s", platform.name, post.url)
            return PlatformResult(
                platform=platform.name,
                status=PostStatus.SUCCESS,
                posted_url=post.url,
                public_access=post.is_public,
                date=posted_at.strftime("%Y-%m-%d"),
                time=posted_at.strftime("%H:%M:%S"),
                error=None,
            )

        logger.warning("Posting to %s failed: %s", platform.name, error)
        return PlatformResult(
            platform=platform.name,
            status=PostStatus.FAILED,
            posted_url=None,
            public_access=False,
            date=None,
            time=None,
            error=error,
        )
