"""Abstract platform interface."""

import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings


class PlatformError(Exception):
    """Raised by a platform when a post cannot be published.

    The message is returned to API clients, so it must never contain secrets.
    """


@dataclass
class PublishedPost:
    url: str
    # True/False when the platform tells us; None when it cannot be determined.
    is_public: bool | None


class Platform(ABC):
    """A social platform that can publish a text message with a CTA link."""

    name: str

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    def required_settings(self) -> tuple[str, ...]:
        """Names of Settings attributes that must all be set for live posting."""
        return ()

    def missing_settings(self) -> list[str]:
        return [s for s in self.required_settings() if not getattr(self.settings, s)]

    @abstractmethod
    async def _publish_live(self, message: str, link: str) -> PublishedPost:
        """Call the real platform API."""

    @abstractmethod
    def _dry_run_url(self, post_id: str) -> str:
        """Build a placeholder URL for simulated posts."""

    async def publish(self, message: str, link: str) -> PublishedPost:
        if self.settings.dry_run:
            return PublishedPost(url=self._dry_run_url(f"dry-run-{secrets.token_hex(4)}"), is_public=None)
        missing = self.missing_settings()
        if missing:
            raise PlatformError(f"Missing configuration: {', '.join(m.upper() for m in missing)}")
        return await self._publish_live(message, link)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def raise_for_api_error(response: httpx.Response) -> None:
        """Convert non-2xx responses to PlatformError with a readable message."""
        if response.is_success:
            return
        status = response.status_code
        if status == 429:
            raise PlatformError("API rate limit exceeded")

        detail = ""
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message", ""))
            elif isinstance(err, str):
                detail = str(body.get("message") or body.get("error_description") or err)
            else:
                detail = str(body.get("detail") or body.get("message") or body.get("title") or "")
        detail = detail[:300] or response.reason_phrase or "Unknown error"

        if status in (401, 403):
            raise PlatformError(f"Authentication failed (HTTP {status}): {detail}")
        raise PlatformError(f"HTTP {status}: {detail}")

    @staticmethod
    def json(response: httpx.Response) -> dict[str, Any]:
        """Parse a JSON object body, raising PlatformError instead of a decode error."""
        try:
            body = response.json()
        except ValueError as exc:
            raise PlatformError(f"Invalid JSON response from API (HTTP {response.status_code})") from exc
        if not isinstance(body, dict):
            raise PlatformError("Unexpected API response format")
        return body
