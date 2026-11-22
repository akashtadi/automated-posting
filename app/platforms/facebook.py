"""Facebook Page integration (Graph API)."""

import logging

from app.platforms.base import Platform, PlatformError, PublishedPost

logger = logging.getLogger(__name__)


class FacebookPlatform(Platform):
    name = "Facebook"

    def required_settings(self) -> tuple[str, ...]:
        return ("facebook_page_id", "facebook_page_access_token")

    def _dry_run_url(self, post_id: str) -> str:
        return f"https://www.facebook.com/{post_id}"

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{self.settings.facebook_graph_version}"

    @property
    def _auth(self) -> dict[str, str]:
        # Token goes in a header, never in the URL, so it cannot leak into logs.
        return {"Authorization": f"Bearer {self.settings.facebook_page_access_token}"}

    async def _publish_live(self, message: str, link: str) -> PublishedPost:
        page_id = self.settings.facebook_page_id
        response = await self.client.post(
            f"{self._base}/{page_id}/feed",
            headers=self._auth,
            data={"message": message, "link": link},
        )
        self.raise_for_api_error(response)
        post_id = self.json(response).get("id")  # format: {page_id}_{post_id}
        if not post_id:
            raise PlatformError("Facebook did not return a post id")
        return PublishedPost(url=f"https://www.facebook.com/{post_id}", is_public=await self._page_is_public())

    async def _page_is_public(self) -> bool | None:
        """Page posts are public only if the Page itself is published. Best effort."""
        try:
            response = await self.client.get(
                f"{self._base}/{self.settings.facebook_page_id}",
                params={"fields": "is_published"},
                headers=self._auth,
            )
            self.raise_for_api_error(response)
            value = self.json(response).get("is_published")
            return value if isinstance(value, bool) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Facebook: could not determine page visibility: %s", exc)
            return None
