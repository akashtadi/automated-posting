"""Pydantic request/response models and message validation."""

import re
from enum import Enum
from urllib.parse import urlparse

from pydantic import BaseModel, Field, computed_field, field_validator

MAX_MESSAGE_LENGTH = 200

TRAILING_PUNCTUATION = ".,!?;:)]}'\""

# Common TLDs used to detect bare domains such as "example.com" (no scheme).
_BARE_TLDS = (
    "com|org|net|io|co|ai|dev|app|in|uk|us|ca|au|de|fr|info|biz|me|xyz|tech|"
    "online|site|store|shop|blog|gov|edu|ly|gg|tv"
)

# Anything that looks like a link, so a second link cannot slip past the
# "exactly one CTA link" rule by using another scheme or no scheme at all.
LINK_PATTERN = re.compile(
    r"""
      \b[a-z][a-z0-9+.\-]*://\S+                      # any scheme://...
    | \b(?:mailto|javascript|tel|data|sms):\S+        # scheme without //
    | \bwww\.\S+                                      # www.example.com
    | (?<![@.\w\-])[a-z0-9\-]+(?:\.[a-z0-9\-]+)*      # bare domain, not an email
      \.(?:"""
    + _BARE_TLDS
    + r""")\b(?:/\S*)?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_links(text: str) -> list[str]:
    """Return every link-like token in the text (any scheme, www., or bare domain)."""
    return [m.rstrip(TRAILING_PUNCTUATION) for m in LINK_PATTERN.findall(text)]


def is_valid_url(url: str) -> bool:
    """A valid CTA link is an absolute http(s) URL with a dotted public hostname."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    try:
        parsed.port  # raises ValueError on a malformed port
    except ValueError:
        return False
    host = parsed.hostname or ""
    return bool(re.fullmatch(r"([a-z0-9-]+\.)+[a-z]{2,}", host, re.IGNORECASE))


class PostRequest(BaseModel):
    message: str = Field(
        ...,
        description="Post text, max 200 characters, containing exactly one CTA link (http/https URL).",
        examples=["Check out our latest business platform and grow your online visibility. https://example.com"],
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be empty")
        if len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message must be at most {MAX_MESSAGE_LENGTH} characters (got {len(value)})")

        links = extract_links(value)
        if len(links) != 1:
            raise ValueError(f"Message must contain exactly one CTA link (found {len(links)})")
        if not is_valid_url(links[0]):
            raise ValueError(f"Invalid URL: {links[0]!r} (CTA link must be a full http:// or https:// URL)")
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cta_link(self) -> str:
        return extract_links(self.message)[0]


class PostStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class PlatformResult(BaseModel):
    platform: str = Field(..., examples=["LinkedIn"])
    status: PostStatus
    posted_url: str | None = Field(None, description="URL of the published post")
    public_access: bool | None = Field(
        None, description="Whether the post is publicly accessible; null if it could not be determined"
    )
    date: str | None = Field(None, description="Posting date (UTC), YYYY-MM-DD", examples=["2026-11-22"])
    time: str | None = Field(None, description="Posting time (UTC), HH:MM:SS", examples=["10:30:00"])
    error: str | None = Field(None, description="Error details, if the post failed")


class PostingResponse(BaseModel):
    success: bool = Field(..., description="True if the message was published on at least one platform")
    dry_run: bool = Field(False, description="True if results are simulated (DRY_RUN=true); nothing was posted")
    results: list[PlatformResult]


class ValidationErrorDetail(BaseModel):
    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    success: bool = False
    errors: list[ValidationErrorDetail]
