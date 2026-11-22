"""Reddit integration (OAuth "script" app, link submission).

The password grant only works for script apps on accounts without 2FA.
"""

import logging

from app.platforms.base import Platform, PlatformError, PublishedPost
from app.schemas import extract_links

logger = logging.getLogger(__name__)

# Subreddit types whose posts anyone can read without logging in.
PUBLIC_SUBREDDIT_TYPES = {"public", "restricted", "archived"}


class RedditPlatform(Platform):
    name = "Reddit"
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    SUBMIT_URL = "https://oauth.reddit.com/api/submit"
    ABOUT_URL = "https://oauth.reddit.com/r/{subreddit}/about"

    def required_settings(self) -> tuple[str, ...]:
        return (
            "reddit_client_id",
            "reddit_client_secret",
            "reddit_username",
            "reddit_password",
            "reddit_subreddit",
        )

    def _dry_run_url(self, post_id: str) -> str:
        return f"https://www.reddit.com/r/{self.settings.reddit_subreddit or 'test'}/comments/{post_id}/"

    async def _get_token(self) -> str:
        s = self.settings
        response = await self.client.post(
            self.TOKEN_URL,
            auth=(s.reddit_client_id, s.reddit_client_secret),
            data={"grant_type": "password", "username": s.reddit_username, "password": s.reddit_password},
            headers={"User-Agent": s.reddit_user_agent},
        )
        self.raise_for_api_error(response)
        body = self.json(response)
        token = body.get("access_token")
        if not token:
            # Reddit returns 200 with {"error": "invalid_grant"} on bad credentials.
            raise PlatformError(f"Authentication failed: {body.get('error', 'no access token returned')}")
        return token

    async def _publish_live(self, message: str, link: str) -> PublishedPost:
        s = self.settings
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "User-Agent": s.reddit_user_agent}

        # Link post: the title is the message without the URL; the URL is the link target.
        title = message
        for found in extract_links(message):
            title = title.replace(found, "")
        title = " ".join(title.split()) or link

        response = await self.client.post(
            self.SUBMIT_URL,
            headers=headers,
            data={
                "sr": s.reddit_subreddit,
                "kind": "link",
                "title": title,
                "url": link,
                "api_type": "json",
                "resubmit": "true",
            },
        )
        self.raise_for_api_error(response)
        payload = self.json(response).get("json", {})
        errors = payload.get("errors") or []
        if errors:
            raise PlatformError("; ".join(" ".join(map(str, e)) for e in errors))
        url = payload.get("data", {}).get("url")
        if not url:
            raise PlatformError("Reddit did not return a post URL")
        return PublishedPost(url=url, is_public=await self._subreddit_is_public(headers))

    async def _subreddit_is_public(self, headers: dict[str, str]) -> bool | None:
        """Posts in private subreddits are not publicly accessible. Best effort."""
        try:
            response = await self.client.get(
                self.ABOUT_URL.format(subreddit=self.settings.reddit_subreddit), headers=headers
            )
            self.raise_for_api_error(response)
            sub_type = self.json(response).get("data", {}).get("subreddit_type")
            return None if sub_type is None else sub_type in PUBLIC_SUBREDDIT_TYPES
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reddit: could not determine subreddit visibility: %s", exc)
            return None
