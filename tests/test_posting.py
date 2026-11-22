"""API, validation, service and platform-integration tests (all HTTP is mocked)."""

import asyncio
import logging
import re

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_posting_service
from app.platforms import (
    FacebookPlatform,
    InstagramPlatform,
    LinkedInPlatform,
    Platform,
    PlatformError,
    PublishedPost,
    RedditPlatform,
    TwitterPlatform,
    oauth1,
)
from app.schemas import PostRequest
from app.services.posting_service import PostingService

VALID_MESSAGE = "Check out our latest business platform and grow your online visibility. https://example.com"
LINK = "https://example.com"
GRAPH = "https://graph.facebook.com/v24.0"
RESULT_KEYS = {"platform", "status", "posted_url", "public_access", "date", "time", "error"}


# --------------------------------------------------------------------------- helpers


class FakePlatform(Platform):
    def __init__(self, name: str, behavior: str = "ok"):
        self.name = name
        self.behavior = behavior
        self.calls: list[tuple[str, str]] = []

    def _dry_run_url(self, post_id):
        return ""

    async def _publish_live(self, message, link):
        raise NotImplementedError

    async def publish(self, message, link):
        self.calls.append((message, link))
        match self.behavior:
            case "error":
                raise PlatformError("API rate limit exceeded")
            case "crash":
                raise RuntimeError("secret internal detail")
            case "network":
                raise httpx.ConnectError("dns failure")
            case "slow":
                await asyncio.sleep(5)
        return PublishedPost(url=f"https://{self.name.lower()}.com/posts/1", is_public=True)


def live_settings(**overrides) -> Settings:
    base = dict(
        dry_run=False,
        linkedin_access_token="li-token",
        linkedin_author_urn="urn:li:person:abc",
        twitter_api_key="ck",
        twitter_api_secret="cs",
        twitter_access_token="at",
        twitter_access_token_secret="ats",
        facebook_page_id="111",
        facebook_page_access_token="fb-token",
        instagram_user_id="222",
        instagram_access_token="ig-token",
        instagram_image_url="https://example.com/img.jpg",
        reddit_client_id="rid",
        reddit_client_secret="rsecret",
        reddit_username="user",
        reddit_password="pass",
        reddit_subreddit="test",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


async def publish(platform_cls, settings=None):
    async with httpx.AsyncClient() as http:
        return await platform_cls(settings or live_settings(), http).publish(VALID_MESSAGE, LINK)


@pytest.fixture
def client():
    # Never let a developer's local .env leak into tests.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fast_instagram_polling(monkeypatch):
    monkeypatch.setattr(InstagramPlatform, "STATUS_POLL_INTERVAL", 0)


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "message, error_fragment",
    [
        ("", "must not be empty"),
        ("     ", "must not be empty"),
        ("a" * 181 + " https://example.com", "at most 200 characters (got 201)"),
        ("No link here", "exactly one CTA link (found 0)"),
        ("Two links https://a.com and https://b.com", "exactly one CTA link (found 2)"),
        ("Visit example.org or https://example.com", "exactly one CTA link (found 2)"),
        ("Get https://example.com or ftp://files.example.com", "exactly one CTA link (found 2)"),
        ("Malformed https://nodot", "Invalid URL"),
        ("Bare www.example.com", "Invalid URL"),
        ("Wrong scheme ftp://example.com", "Invalid URL"),
        ("Script javascript:alert(1)", "Invalid URL"),
        ("No scheme example.com", "Invalid URL"),
        ("Bad port https://example.com:99999", "Invalid URL"),
    ],
)
def test_validation_rejects_invalid_messages(client, message, error_fragment):
    response = client.post("/posting", json={"message": message})
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["errors"][0]["field"] == "message"
    assert error_fragment in body["errors"][0]["message"]


@pytest.mark.parametrize(
    "message",
    [
        "a" * (200 - len(LINK) - 1) + " " + LINK,  # exactly 200 chars
        "Email us at hello@example.com or visit https://example.com",  # email is not a link
        "Built with Node.js and Python: https://example.com/path?x=1",
    ],
)
def test_validation_accepts_valid_messages(message):
    assert PostRequest(message=message).cta_link.startswith("https://example.com")


def test_cta_link_strips_trailing_punctuation():
    assert PostRequest(message="Visit https://example.com/path?x=1.").cta_link == "https://example.com/path?x=1"


def test_missing_message_field(client):
    response = client.post("/posting", json={})
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "message"


# --------------------------------------------------------------------------- service


async def test_service_isolates_every_failure_type():
    platforms = [
        FakePlatform("LinkedIn"),
        FakePlatform("X", "error"),
        FakePlatform("Facebook", "crash"),
        FakePlatform("Instagram", "slow"),
        FakePlatform("Reddit", "network"),
        FakePlatform("Extra"),
    ]
    results = await PostingService(platforms, timeout_seconds=0.2).post_to_all(VALID_MESSAGE, LINK)
    by_name = {r.platform: r for r in results}

    assert [r.platform for r in results] == [p.name for p in platforms]
    for ok in ("LinkedIn", "Extra"):
        assert by_name[ok].status == "success" and by_name[ok].posted_url and by_name[ok].date
    assert by_name["X"].error == "API rate limit exceeded"
    assert by_name["Facebook"].error == "Unexpected internal error (see server logs)"  # no internals leaked
    assert "timed out" in by_name["Instagram"].error
    assert by_name["Reddit"].error == "Network error: ConnectError"
    for name in ("X", "Facebook", "Instagram", "Reddit"):
        r = by_name[name]
        assert (r.status, r.posted_url, r.public_access, r.date, r.time) == ("failed", None, False, None, None)
    assert all(p.calls == [(VALID_MESSAGE, LINK)] for p in platforms)


# --------------------------------------------------------------------------- API


def test_posting_endpoint_matches_assignment_format(client):
    app.dependency_overrides[get_posting_service] = lambda: PostingService(
        [FakePlatform("LinkedIn"), FakePlatform("X", "error")]
    )
    response = client.post("/posting", json={"message": VALID_MESSAGE})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True and body["dry_run"] is False
    ok, failed = body["results"]
    assert set(ok) == RESULT_KEYS and set(failed) == RESULT_KEYS
    assert ok["status"] == "success" and ok["posted_url"] == "https://linkedin.com/posts/1"
    assert ok["public_access"] is True and ok["error"] is None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", ok["date"]) and re.fullmatch(r"\d{2}:\d{2}:\d{2}", ok["time"])
    assert failed == {
        "platform": "X",
        "status": "failed",
        "posted_url": None,
        "public_access": False,
        "date": None,
        "time": None,
        "error": "API rate limit exceeded",
    }


def test_success_false_when_every_platform_fails(client):
    app.dependency_overrides[get_posting_service] = lambda: PostingService([FakePlatform("X", "error")])
    assert client.post("/posting", json={"message": VALID_MESSAGE}).json()["success"] is False


def test_dry_run_is_flagged_and_covers_five_platforms(client):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, dry_run=True)
    body = client.post("/posting", json={"message": VALID_MESSAGE}).json()
    assert body["dry_run"] is True
    assert [r["platform"] for r in body["results"]] == ["LinkedIn", "X", "Facebook", "Instagram", "Reddit"]
    assert all("dry-run-" in r["posted_url"] and r["public_access"] is None for r in body["results"])


def test_dry_run_is_off_by_default():
    assert Settings(_env_file=None).dry_run is False


def test_live_mode_missing_credentials_fails_gracefully(client):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    body = client.post("/posting", json={"message": VALID_MESSAGE}).json()
    assert body["success"] is False and len(body["results"]) == 5
    assert all(r["status"] == "failed" and "Missing configuration" in r["error"] for r in body["results"])


# --------------------------------------------------------------------------- OAuth 1.0a


def test_oauth1_signature_matches_x_documentation_example():
    # Example from X's "Creating a signature" documentation.
    params = {
        "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
        "include_entities": "true",
        "oauth_consumer_key": "xvz1evFS4wEEPTGEFPHBog",
        "oauth_nonce": "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": "1318622958",
        "oauth_token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
        "oauth_version": "1.0",
    }
    sig = oauth1.signature(
        "POST",
        "https://api.twitter.com/1.1/statuses/update.json",
        params,
        consumer_secret="kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
        token_secret="LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
    )
    assert sig == "hCtSmYh+iHYCEqBWrE7C7hYmtUk="


# --------------------------------------------------------------------------- LinkedIn


@respx.mock
async def test_linkedin_success():
    route = respx.post(LinkedInPlatform.API_URL).respond(201, headers={"x-restli-id": "urn:li:share:123"})
    post = await publish(LinkedInPlatform)
    assert post == PublishedPost("https://www.linkedin.com/feed/update/urn:li:share:123", True)
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer li-token"
    assert req.headers["LinkedIn-Version"] == "202610"


@respx.mock
async def test_linkedin_auth_failure():
    respx.post(LinkedInPlatform.API_URL).respond(401, json={"message": "Invalid access token"})
    with pytest.raises(PlatformError, match=r"Authentication failed \(HTTP 401\): Invalid access token"):
        await publish(LinkedInPlatform)


# --------------------------------------------------------------------------- X


@respx.mock
async def test_twitter_success_oauth1():
    route = respx.post(TwitterPlatform.TWEET_URL).respond(201, json={"data": {"id": "999", "text": "x"}})
    respx.get(TwitterPlatform.ME_URL).respond(200, json={"data": {"username": "acme", "protected": False}})
    post = await publish(TwitterPlatform)
    assert post == PublishedPost("https://x.com/acme/status/999", True)
    assert route.calls.last.request.headers["Authorization"].startswith('OAuth oauth_consumer_key="ck"')


@respx.mock
async def test_twitter_oauth2_token_and_protected_account():
    settings = live_settings(twitter_api_key=None, twitter_oauth2_user_token="o2")
    route = respx.post(TwitterPlatform.TWEET_URL).respond(201, json={"data": {"id": "1"}})
    respx.get(TwitterPlatform.ME_URL).respond(200, json={"data": {"username": "acme", "protected": True}})
    post = await publish(TwitterPlatform, settings)
    assert post.is_public is False
    assert route.calls.last.request.headers["Authorization"] == "Bearer o2"


@respx.mock
async def test_twitter_visibility_lookup_failure_does_not_fail_post():
    respx.post(TwitterPlatform.TWEET_URL).respond(201, json={"data": {"id": "5"}})
    respx.get(TwitterPlatform.ME_URL).respond(429)
    post = await publish(TwitterPlatform)
    assert post == PublishedPost("https://x.com/i/web/status/5", None)


@respx.mock
async def test_twitter_rate_limit():
    respx.post(TwitterPlatform.TWEET_URL).respond(429, json={"title": "Too Many Requests"})
    with pytest.raises(PlatformError, match="rate limit"):
        await publish(TwitterPlatform)


@respx.mock
async def test_twitter_non_json_success_body():
    respx.post(TwitterPlatform.TWEET_URL).respond(200, text="<html>oops</html>")
    with pytest.raises(PlatformError, match="Invalid JSON response"):
        await publish(TwitterPlatform)


async def test_twitter_requires_some_credentials():
    with pytest.raises(PlatformError, match="Missing configuration: TWITTER_API_KEY"):
        await publish(TwitterPlatform, live_settings(twitter_api_key=None))


# --------------------------------------------------------------------------- Facebook


@respx.mock
async def test_facebook_success():
    route = respx.post(f"{GRAPH}/111/feed").respond(200, json={"id": "111_456"})
    respx.get(f"{GRAPH}/111").respond(200, json={"is_published": True, "id": "111"})
    post = await publish(FacebookPlatform)
    assert post == PublishedPost("https://www.facebook.com/111_456", True)
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer fb-token"
    assert "access_token" not in str(req.url) and "fb-token" not in req.content.decode()


@respx.mock
async def test_facebook_unpublished_page():
    respx.post(f"{GRAPH}/111/feed").respond(200, json={"id": "111_456"})
    respx.get(f"{GRAPH}/111").respond(200, json={"is_published": False})
    assert (await publish(FacebookPlatform)).is_public is False


@respx.mock
async def test_facebook_api_error_message():
    respx.post(f"{GRAPH}/111/feed").respond(400, json={"error": {"message": "Invalid OAuth access token."}})
    with pytest.raises(PlatformError, match="HTTP 400: Invalid OAuth access token"):
        await publish(FacebookPlatform)


@respx.mock
async def test_facebook_network_error_isolated():
    respx.post(f"{GRAPH}/111/feed").mock(side_effect=httpx.ConnectError("unreachable"))
    async with httpx.AsyncClient() as http:
        service = PostingService([FacebookPlatform(live_settings(), http)])
        (result,) = await service.post_to_all(VALID_MESSAGE, LINK)
    assert result.status == "failed" and result.error == "Network error: ConnectError"


# --------------------------------------------------------------------------- Instagram


@respx.mock
async def test_instagram_success_waits_for_container():
    respx.post(f"{GRAPH}/222/media").respond(200, json={"id": "c1"})
    status = respx.get(f"{GRAPH}/c1").mock(
        side_effect=[
            httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
            httpx.Response(200, json={"status_code": "FINISHED"}),
        ]
    )
    respx.post(f"{GRAPH}/222/media_publish").respond(200, json={"id": "m1"})
    respx.get(f"{GRAPH}/m1").respond(200, json={"permalink": "https://www.instagram.com/p/789/"})
    post = await publish(InstagramPlatform)
    assert post == PublishedPost("https://www.instagram.com/p/789/", True)
    assert status.call_count == 2


@respx.mock
async def test_instagram_container_error():
    respx.post(f"{GRAPH}/222/media").respond(200, json={"id": "c1"})
    respx.get(f"{GRAPH}/c1").respond(200, json={"status_code": "ERROR"})
    with pytest.raises(PlatformError, match="processing failed"):
        await publish(InstagramPlatform)


@respx.mock
async def test_instagram_token_never_logged(caplog):
    from app.main import configure_logging

    configure_logging("INFO")
    respx.post(f"{GRAPH}/222/media").respond(200, json={"id": "c1"})
    respx.get(f"{GRAPH}/c1").respond(200, json={"status_code": "FINISHED"})
    respx.post(f"{GRAPH}/222/media_publish").respond(200, json={"id": "m1"})
    respx.get(f"{GRAPH}/m1").respond(200, json={"permalink": "https://www.instagram.com/p/1/"})
    with caplog.at_level(logging.DEBUG):
        await publish(InstagramPlatform)
    assert "ig-token" not in caplog.text


# --------------------------------------------------------------------------- Reddit


def _reddit_ok(sub_type="public"):
    respx.post(RedditPlatform.TOKEN_URL).respond(200, json={"access_token": "rt"})
    respx.get(RedditPlatform.ABOUT_URL.format(subreddit="test")).respond(
        200, json={"data": {"subreddit_type": sub_type}}
    )


@respx.mock
async def test_reddit_success():
    _reddit_ok()
    submit = respx.post(RedditPlatform.SUBMIT_URL).respond(
        200, json={"json": {"errors": [], "data": {"url": "https://www.reddit.com/r/test/comments/1011/"}}}
    )
    post = await publish(RedditPlatform)
    assert post == PublishedPost("https://www.reddit.com/r/test/comments/1011/", True)
    sent = submit.calls.last.request.content.decode()
    assert "kind=link" in sent and "url=https%3A%2F%2Fexample.com" in sent
    assert "title=Check+out+our+latest+business+platform+and+grow+your+online+visibility." in sent


@respx.mock
async def test_reddit_private_subreddit_not_public():
    _reddit_ok("private")
    respx.post(RedditPlatform.SUBMIT_URL).respond(
        200, json={"json": {"errors": [], "data": {"url": "https://www.reddit.com/r/test/comments/1/"}}}
    )
    assert (await publish(RedditPlatform)).is_public is False


@respx.mock
async def test_reddit_bad_credentials():
    respx.post(RedditPlatform.TOKEN_URL).respond(200, json={"error": "invalid_grant"})
    with pytest.raises(PlatformError, match="Authentication failed: invalid_grant"):
        await publish(RedditPlatform)


@respx.mock
async def test_reddit_submit_errors():
    _reddit_ok()
    respx.post(RedditPlatform.SUBMIT_URL).respond(
        200, json={"json": {"errors": [["SUBREDDIT_NOEXIST", "that subreddit doesn't exist", "sr"]]}}
    )
    with pytest.raises(PlatformError, match="SUBREDDIT_NOEXIST"):
        await publish(RedditPlatform)
