# Automated Multi-Platform Posting System

A FastAPI application that publishes one short message (≤ 200 characters, exactly one CTA link)
to **five platforms** — LinkedIn, X, Facebook, Instagram and Reddit — through their official APIs,
concurrently, and reports the real per-platform outcome.

## Features

- `POST /posting` on port **4000**, interactive docs at `/docs`
- Validation: ≤ 200 characters, not empty, **exactly one** link, link must be a valid `http(s)://` URL
  (other schemes, bare domains and `www.` links are counted, so a second link cannot slip through)
- Platforms are selected internally; the client only sends the message
- All platforms are posted concurrently with a per-platform timeout; **one failure never stops the others**
- Per-platform result: status, posted URL, public access, date, time, error
- Secrets only from environment variables; tokens are sent in headers and never logged

## Architecture

```
Client ──POST /posting──▶ FastAPI (app/main.py)
                             │  Pydantic validation (app/schemas.py) ──▶ 422 on invalid input
                             ▼
                    PostingService (app/services/posting_service.py)
                             │  asyncio.gather + per-platform timeout & exception isolation
       ┌──────────┬──────────┼───────────┬────────────┐
       ▼          ▼          ▼           ▼            ▼
   LinkedIn       X       Facebook   Instagram     Reddit      (app/platforms/*.py, all extend base.Platform)
```

```
app/
  main.py                    # FastAPI app, routes, validation error format, logging
  schemas.py                 # Request/response models + message validation
  config.py                  # Settings from environment / .env
  platforms/
    base.py                  # Abstract Platform: publish(), error mapping, JSON parsing
    oauth1.py                # OAuth 1.0a signing for X
    linkedin.py twitter.py facebook.py instagram.py reddit.py
  services/
    posting_service.py       # Concurrent orchestration and result building
tests/
  test_posting.py            # Validation, API, service and per-platform tests (HTTP mocked)
```

## Requirements

- Python **3.10+** (developed on 3.12)
- Accounts and API credentials for the platforms you want to post to (see [Platform setup](#platform-setup))

## Installation

```bash
git clone <your-repo-url>
cd automated-posting
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in credentials. Any platform without credentials is reported as
`failed` with `Missing configuration: ...` while the others still post.

## Running

```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

Open http://localhost:4000/docs.

Set `DRY_RUN=true` to try the API without credentials: posts are simulated, URLs contain
`dry-run-`, and the response says `"dry_run": true`. Dry-run results are **not** real posts.

## API

### `POST /posting`

```bash
curl -X POST http://localhost:4000/posting \
  -H "Content-Type: application/json" \
  -d '{"message": "Check out our latest business platform and grow your online visibility. https://example.com"}'
```

**200 response** (`success` is true if at least one platform published the message):

```json
{
  "success": true,
  "dry_run": false,
  "results": [
    {
      "platform": "LinkedIn",
      "status": "success",
      "posted_url": "https://www.linkedin.com/feed/update/urn:li:share:7263...",
      "public_access": true,
      "date": "2026-11-22",
      "time": "10:30:00",
      "error": null
    },
    {
      "platform": "X",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Authentication failed (HTTP 401): Unauthorized"
    }
  ]
}
```

- `date` / `time` are UTC.
- `public_access` comes from the platform: LinkedIn post visibility (`PUBLIC`), X account
  `protected` flag, Facebook Page `is_published`, Reddit subreddit type; Instagram professional
  accounts are always public. It is `null` if the platform could not be asked.

**422 response** (invalid input):

```json
{ "success": false, "errors": [{ "field": "message", "message": "Message must contain exactly one CTA link (found 2)" }] }
```

### `GET /health`

Returns `{"status": "ok", "dry_run": false}`.

## Platform setup

| Platform | API used | Credentials (`.env`) | How to get them |
|---|---|---|---|
| **LinkedIn** | `POST https://api.linkedin.com/rest/posts` | `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_AUTHOR_URN` | Create an app at [developer.linkedin.com](https://developer.linkedin.com), add *Share on LinkedIn* (`w_member_social`) or Community Management (`w_organization_social`), generate a token. Author URN: `urn:li:person:<id>` (from `/v2/userinfo` `sub`) or `urn:li:organization:<id>` |
| **X** | `POST https://api.twitter.com/2/tweets` | `TWITTER_API_KEY/SECRET`, `TWITTER_ACCESS_TOKEN/SECRET` | [developer.x.com](https://developer.x.com) → Project/App → set *User authentication* to **Read and write** → regenerate Access Token & Secret (they must be generated after enabling write) |
| **Facebook** | `POST https://graph.facebook.com/v24.0/{page-id}/feed` | `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_ACCESS_TOKEN` | Meta app at [developers.facebook.com](https://developers.facebook.com) → Graph API Explorer → permissions `pages_manage_posts`, `pages_read_engagement` → get a **Page** token (`/me/accounts`) |
| **Instagram** | `/{ig-user}/media` → `/media_publish` | `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_IMAGE_URL` | Professional IG account linked to the Page; permission `instagram_content_publish`; IG user id from `/{page-id}?fields=instagram_business_account` |
| **Reddit** | `POST https://oauth.reddit.com/api/submit` | `REDDIT_CLIENT_ID/SECRET`, `REDDIT_USERNAME/PASSWORD`, `REDDIT_SUBREDDIT` | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → *create app* → type **script**. Use a subreddit you moderate (e.g. your own `u_<username>` profile or a test subreddit) |

## Testing

```bash
pytest -v
```

The tests cover validation rules, the response format, failure isolation (API errors, auth
errors, rate limits, timeouts, network errors, unexpected exceptions), dry-run behaviour, OAuth 1.0a
signing (checked against X's documented example) and each platform's request/response handling.
External HTTP calls are mocked with `respx`; live behaviour is shown in the evidence below.

## Live run evidence

<!-- Add screenshots/logs of a real run here: the /docs request, the JSON response, and each published post. -->

_To be added._

## Known limitations

- **Instagram** requires an image for every post (`INSTAGRAM_IMAGE_URL`); links in captions are not clickable.
- **X** free tier has very low posting quotas; repeated identical posts are rejected as duplicates.
- **LinkedIn** API versions (`LINKEDIN_API_VERSION`) and **Meta** Graph versions retire over time and must be kept current.
- **Reddit** password grant does not work on accounts with 2FA; subreddit rules or spam filters may remove posts after submission.
- `public_access` reflects the platform's visibility setting at publish time; it does not detect later moderation.
- No retries: a rate-limited or failed platform is reported as failed for that request.
- `/posting` has no authentication of its own; do not expose it publicly without adding an API key or similar.
