"""AK/SK request signing (SDK-HMAC-SHA256).

Port of the Go SDK ``signer_helper.go``. Signs HTTP requests using
the ``SDK-HMAC-SHA256`` algorithm, compatible with OTC's AK/SK
authentication.

The signing process follows these steps:

1. Build a **canonical request** from method, path, query, headers, body.
2. Build a **string to sign** from algorithm, timestamp, scope, and
   the hash of the canonical request.
3. **Derive a signing key** from the secret key, date, region, and service.
4. **Compute the signature** (HMAC-SHA256) and set the ``Authorization``
   header on the request.

Example::

    import httpx
    from sdk.core.signer import sign_request, SignOptions

    opts = SignOptions(
        access_key="AK...",
        secret_key="SK...",
        region_name="eu-de",
        service_name="dns",
    )
    request = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
    sign_request(request, opts)
    # request now has Authorization and X-Sdk-Date headers
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

ALGORITHM = "SDK-HMAC-SHA256"
"""Default signing algorithm."""

_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SignOptions:
    """Options for signing a request.

    Args:
        access_key: AK/SK access key.
        secret_key: AK/SK secret key.
        region_name: Target region (e.g. ``eu-de``).
        service_name: Service identifier (e.g. ``dns``, ``cce``).
    """

    access_key: str
    secret_key: str
    region_name: str = ""
    service_name: str = ""


def sign_request(
    request: httpx.Request,
    opts: SignOptions,
    *,
    timestamp: datetime | None = None,
) -> None:
    """Sign an httpx request in place with AK/SK credentials.

    Adds ``X-Sdk-Date``, ``Host``, and ``Authorization`` headers
    to the request.

    Args:
        request: The httpx request to sign (modified in place).
        opts: Signing credentials and scope.
        timestamp: Override the signing time (for testing).
            Defaults to ``datetime.now(UTC)``.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    formatted_dt = _format_datetime(timestamp)
    formatted_date = _format_date(timestamp)

    # Set required headers
    request.headers["host"] = request.url.host or ""
    request.headers["x-sdk-date"] = formatted_dt

    # Content hash
    content_sha256 = request.headers.get(
        "x-sdk-content-sha256",
        _hash_sha256(_read_body(request)),
    )

    # Canonical request
    canonical = _canonical_request(request, content_sha256)

    # Scope
    scope = f"{formatted_date}/{opts.region_name}/{opts.service_name}/sdk_request"

    # String to sign
    string_to_sign = "\n".join([
        ALGORITHM,
        formatted_dt,
        scope,
        _hash_sha256(canonical.encode()),
    ])

    # Derive signing key
    signing_key = _derive_key(opts.secret_key, formatted_date, opts.region_name, opts.service_name)

    # Compute signature
    signature = _hmac_sha256(string_to_sign, signing_key).hex()

    # Build Authorization header
    signed_headers = _signed_headers_string(request)
    credential = f"{opts.access_key}/{scope}"
    request.headers["authorization"] = (
        f"{ALGORITHM} "
        f"Credential={credential}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )


# --- Internal helpers ---


def _format_datetime(dt: datetime) -> str:
    """Format timestamp as ``20060102T150405Z``."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _format_date(dt: datetime) -> str:
    """Format date as ``20060102``."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%d")


def _hash_sha256(data: bytes) -> str:
    """Hex-encoded SHA-256 hash."""
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(data: str, key: bytes) -> bytes:
    """HMAC-SHA256 of string data with byte key."""
    return hmac.new(key, data.encode(), hashlib.sha256).digest()


def _derive_key(secret_key: str, date: str, region: str, service: str) -> bytes:
    """Derive signing key from secret + scope components.

    Mirrors Go SDK's ``buildSignKey``::

        kDate    = HMAC("SDK" + secret, date)
        kRegion  = HMAC(kDate, region)
        kService = HMAC(kRegion, service)
        kSigning = HMAC(kService, "sdk_request")

    Args:
        secret_key: AK/SK secret key.
        date: Formatted date string (``YYYYMMDD``).
        region: Region name.
        service: Service name.

    Returns:
        Derived signing key bytes.
    """
    k_secret = f"SDK{secret_key}".encode()
    k_date = _hmac_sha256(date, k_secret)
    k_region = _hmac_sha256(region, k_date)
    k_service = _hmac_sha256(service, k_region)
    return _hmac_sha256("sdk_request", k_service)


def _read_body(request: httpx.Request) -> bytes:
    """Read the request body as bytes.

    For POST with no body, uses the query string as content
    (matches Go SDK behavior).

    Args:
        request: httpx request.

    Returns:
        Body bytes for hashing.
    """
    if request.method == "POST" and request.content == b"":
        return str(request.url.params).encode()
    return request.content


def _url_encode(value: str, *, is_path: bool = False) -> str:
    """URL-encode a value, preserving ``/`` in paths.

    Matches Go SDK's ``urlEncode`` which keeps ``A-Z a-z 0-9 . - _ ~``
    unreserved, and additionally ``/`` for path segments.

    Args:
        value: String to encode.
        is_path: If True, preserve forward slashes.

    Returns:
        Encoded string.
    """
    safe = "/" if is_path else ""
    return quote(value, safe=safe)


def _canonical_path(request: httpx.Request) -> str:
    """Build the canonical URI path.

    Ensures leading and trailing ``/``, then URL-encodes.

    Args:
        request: httpx request.

    Returns:
        Encoded canonical path.
    """
    path = request.url.raw_path.decode().split("?")[0]
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path = path + "/"
    return _url_encode(path, is_path=True)


def _canonical_query(request: httpx.Request) -> str:
    """Build the canonical query string.

    Parameters are sorted by encoded key name, then encoded.
    For POST with no body, returns empty string (body is used instead).
    Handles duplicate keys correctly (e.g. ``?tag=a&tag=b``).

    Args:
        request: httpx request.

    Returns:
        Sorted, encoded query string.
    """
    if request.method == "POST" and request.content == b"":
        return ""

    pairs = request.url.params.multi_items()
    if not pairs:
        return ""

    encoded = [(_url_encode(k), _url_encode(v)) for k, v in pairs]
    encoded.sort(key=lambda p: p[0].lower())

    return "&".join(f"{k}={v}" for k, v in encoded)


def _canonical_headers(request: httpx.Request) -> str:
    """Build canonical header string.

    Headers are lowercased, sorted, and whitespace-collapsed.

    Args:
        request: httpx request.

    Returns:
        Canonical header string (trailing newline included).
    """
    headers = []
    for key in sorted(request.headers.keys(), key=str.lower):
        name = _SPACE_RE.sub(" ", key.lower().strip())
        value = _SPACE_RE.sub(" ", request.headers[key].strip())
        headers.append(f"{name}:{value}\n")
    return "".join(headers)


def _signed_headers_string(request: httpx.Request) -> str:
    """Build the semicolon-separated signed headers list.

    Args:
        request: httpx request.

    Returns:
        Signed headers string (e.g. ``host;x-sdk-date``).
    """
    return ";".join(sorted(request.headers.keys(), key=str.lower))


def _canonical_request(request: httpx.Request, content_sha256: str) -> str:
    """Assemble the full canonical request string.

    Format::

        METHOD
        CanonicalURI
        CanonicalQueryString
        CanonicalHeaders
        SignedHeaders
        ContentHash

    Args:
        request: httpx request.
        content_sha256: Hex-encoded SHA-256 of the body.

    Returns:
        Canonical request string.
    """
    return "\n".join([
        request.method,
        _canonical_path(request),
        _canonical_query(request),
        _canonical_headers(request),
        _signed_headers_string(request),
        content_sha256,
    ])
