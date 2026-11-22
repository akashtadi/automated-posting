"""Minimal OAuth 1.0a (HMAC-SHA1) request signing, as used by the X API.

Spec: RFC 5849. Only query/form parameters are signed; JSON bodies are not
part of the signature base string.
"""

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote, urlsplit, urlunsplit


def _enc(value: str) -> str:
    return quote(str(value), safe="~")


def signature(
    method: str,
    url: str,
    params: dict[str, str],
    consumer_secret: str,
    token_secret: str,
) -> str:
    """Compute the base64 HMAC-SHA1 signature for the given request."""
    parts = urlsplit(url)
    base_url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
    # Parameters are percent-encoded first, then sorted by encoded key/value (RFC 5849 §3.4.1.3.2).
    param_str = "&".join(f"{k}={v}" for k, v in sorted((_enc(k), _enc(v)) for k, v in params.items()))
    base_string = "&".join([method.upper(), _enc(base_url), _enc(param_str)])
    key = f"{_enc(consumer_secret)}&{_enc(token_secret)}"
    digest = hmac.new(key.encode(), base_string.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def authorization_header(
    method: str,
    url: str,
    *,
    consumer_key: str,
    consumer_secret: str,
    token: str,
    token_secret: str,
    query_params: dict[str, str] | None = None,
) -> str:
    """Build the `Authorization: OAuth ...` header value for a request."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    all_params = {**(query_params or {}), **oauth_params}
    oauth_params["oauth_signature"] = signature(method, url, all_params, consumer_secret, token_secret)
    return "OAuth " + ", ".join(f'{_enc(k)}="{_enc(v)}"' for k, v in sorted(oauth_params.items()))
