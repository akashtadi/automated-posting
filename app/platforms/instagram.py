"""Instagram integration (Graph API content publishing).

Instagram feed posts require media, so a configured image URL is published
with the message as its caption. Links in captions are not clickable.
Only professional (business/creator) accounts can publish via the API, and
professional accounts cannot be private, so published posts are public.
"""

import asyncio

from app.platforms.base import Platform, PlatformError, PublishedPost


class InstagramPlatform(Platform):
    name = "Instagram"
    STATUS_POLL_INTERVAL = 1.0  # seconds
    STATUS_POLL_ATTEMPTS = 10

    def required_settings(self) -> tuple[str, ...]:
        return ("instagram_user_id", "instagram_access_token", "instagram_image_url")

    def _dry_run_url(self, post_id: str) -> str:
        return f"https://www.instagram.com/p/{post_id}/"

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{self.settings.facebook_graph_version}"

    @property
    def _auth(self) -> dict[str, str]:
        # Token goes in a header, never in the URL, so it cannot leak into logs.
        return {"Authorization": f"Bearer {self.settings.instagram_access_token}"}

    async def _publish_live(self, message: str, link: str) -> PublishedPost:
        s = self.settings

        # 1. Create media container
        container = await self.client.post(
            f"{self._base}/{s.instagram_user_id}/media",
            headers=self._auth,
            data={"image_url": s.instagram_image_url, "caption": message},
        )
        self.raise_for_api_error(container)
        creation_id = self.json(container).get("id")
        if not creation_id:
            raise PlatformError("Instagram did not return a media container id")

        # 2. Wait until the container has finished processing
        await self._wait_until_ready(creation_id)

        # 3. Publish container
        published = await self.client.post(
            f"{self._base}/{s.instagram_user_id}/media_publish",
            headers=self._auth,
            data={"creation_id": creation_id},
        )
        self.raise_for_api_error(published)
        media_id = self.json(published).get("id")
        if not media_id:
            raise PlatformError("Instagram did not return a media id")

        # 4. Fetch permalink
        details = await self.client.get(
            f"{self._base}/{media_id}", params={"fields": "permalink"}, headers=self._auth
        )
        self.raise_for_api_error(details)
        permalink = self.json(details).get("permalink")
        if not permalink:
            raise PlatformError("Instagram did not return a permalink")
        return PublishedPost(url=permalink, is_public=True)

    async def _wait_until_ready(self, creation_id: str) -> None:
        for _ in range(self.STATUS_POLL_ATTEMPTS):
            response = await self.client.get(
                f"{self._base}/{creation_id}", params={"fields": "status_code"}, headers=self._auth
            )
            self.raise_for_api_error(response)
            status = self.json(response).get("status_code")
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise PlatformError(f"Instagram media processing failed (status {status})")
            await asyncio.sleep(self.STATUS_POLL_INTERVAL)
        raise PlatformError("Instagram media was not ready in time")
