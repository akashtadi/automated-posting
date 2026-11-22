"""X (Twitter) integration (API v2).

Auth options (first configured one wins):
1. OAuth 1.0a user context: TWITTER_API_KEY/SECRET + TWITTER_ACCESS_TOKEN/SECRET.
   Tokens do not expire, which suits a server-side poster.
2. OAuth 2.0 user-context token (TWITTER_OAUTH2_USER_TOKEN, scope tweet.write).
   Expires after ~2 hours. Note: an app-only "Bearer Token" cannot post (HTTP 403).
"""

import logging

from app.platforms import oauth1
from app.platforms.base import Platform, PlatformError, PublishedPost

logger = logging.getLogger(__name__)

OAUTH1_SETTINGS = ("twitter_api_key", "twitter_api_secret", "twitter_access_token", "twitter_access_token_secret")


class TwitterPlatform(Platform):
    name = "X"
    TWEET_URL = "https://api.twitter.com/2/tweets"
    ME_URL = "https://api.twitter.com/2/users/me"

    def _uses_oauth1(self) -> bool:
        return all(getattr(self.settings, s) for s in OAUTH1_SETTINGS)

    def missing_settings(self) -> list[str]:
        if self._uses_oauth1() or self.settings.twitter_oauth2_user_token:
            return []
        return [*OAUTH1_SETTINGS, "twitter_oauth2_user_token (alternative)"]

    def _dry_run_url(self, post_id: str) -> str:
        return f"https://x.com/i/web/status/{post_id}"

    def _auth_header(self, method: str, url: str, query: dict[str, str] | None = None) -> str:
        s = self.settings
        if self._uses_oauth1():
            return oauth1.authorization_header(
                method,
                url,
                consumer_key=s.twitter_api_key,
                consumer_secret=s.twitter_api_secret,
                token=s.twitter_access_token,
                token_secret=s.twitter_access_token_secret,
                query_params=query,
            )
        return f"Bearer {s.twitter_oauth2_user_token}"

    async def _publish_live(self, message: str, link: str) -> PublishedPost:
        response = await self.client.post(
            self.TWEET_URL,
            headers={"Authorization": self._auth_header("POST", self.TWEET_URL)},
            json={"text": message},
        )
        self.raise_for_api_error(response)
        tweet_id = self.json(response).get("data", {}).get("id")
        if not tweet_id:
            raise PlatformError("X did not return a post id")

        username, is_public = await self._account_visibility()
        url = f"https://x.com/{username}/status/{tweet_id}" if username else f"https://x.com/i/web/status/{tweet_id}"
        return PublishedPost(url=url, is_public=is_public)

    async def _account_visibility(self) -> tuple[str | None, bool | None]:
        """Posts are public unless the account is protected. Best effort: never fails the post."""
        query = {"user.fields": "protected"}
        try:
            response = await self.client.get(
                self.ME_URL,
                params=query,
                headers={"Authorization": self._auth_header("GET", self.ME_URL, query)},
            )
            self.raise_for_api_error(response)
            user = self.json(response).get("data", {})
            protected = user.get("protected")
            return user.get("username"), (None if protected is None else not protected)
        except Exception as exc:  # noqa: BLE001
            logger.warning("X: could not determine account visibility: %s", exc)
            return None, None
