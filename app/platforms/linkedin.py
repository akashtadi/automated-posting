"""LinkedIn integration (Posts API, versioned REST)."""

from app.platforms.base import Platform, PlatformError, PublishedPost


class LinkedInPlatform(Platform):
    name = "LinkedIn"
    API_URL = "https://api.linkedin.com/rest/posts"

    def required_settings(self) -> tuple[str, ...]:
        return ("linkedin_access_token", "linkedin_author_urn")

    def _dry_run_url(self, post_id: str) -> str:
        return f"https://www.linkedin.com/feed/update/urn:li:share:{post_id}"

    async def _publish_live(self, message: str, link: str) -> PublishedPost:
        s = self.settings
        response = await self.client.post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {s.linkedin_access_token}",
                "LinkedIn-Version": s.linkedin_api_version,
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json={
                "author": s.linkedin_author_urn,
                "commentary": message,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            },
        )
        self.raise_for_api_error(response)
        post_urn = response.headers.get("x-restli-id")
        if not post_urn:
            raise PlatformError("LinkedIn did not return a post id")
        # The post was created with visibility=PUBLIC and LinkedIn accepted it (201).
        return PublishedPost(url=f"https://www.linkedin.com/feed/update/{post_urn}", is_public=True)
