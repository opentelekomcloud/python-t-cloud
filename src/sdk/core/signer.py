"""AK/SK request signing.

Port of the Go SDK ``signer_helper.go``. Signs HTTP requests using
the AK/SK authentication scheme compatible with OTC services.

The signing process follows these steps:

1. Build a **canonical request** from method, path, query, headers, body.
2. Build a **string to sign** from algorithm, timestamp, scope, and
   the hash of the canonical request.
3. **Derive a signing key** from the secret key, date, region, and service.
4. **Compute the signature** and set the ``Authorization`` header
   on the request.

Example::

    import httpx
    from t_cloud.core.signer import sign_request, SignOptions

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
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx

# Supported signing algorithms.
SIGN_ALGORITHM_HMAC_SHA256 = "SDK-HMAC-SHA256"

_SUPPORTED_ALGORITHMS = frozenset({
    SIGN_ALGORITHM_HMAC_SHA256,
})

# The header key for pre-computed content hash.
_CONTENT_SHA256_HEADER = "x-sdk-content-sha256"

_SPACE_RE = re.compile(r"\s+")


# --- Sign key cache (thread-safe, matches Go MemoryCache) ---


class _SignKeyCache:
    """Thread-safe LRU-like cache for derived signing keys.

    Corresponds to Go SDK's ``MemoryCache``. Evicts the oldest
    entry when ``max_count`` is reached.

    Args:
        max_count: Maximum number of cached entries.
    """

    def __init__(self, max_count: int = 300) -> None:
        self._max_count = max_count
        self._lock = threading.Lock()
        self._store: OrderedDict[str, _SignKeyCacheEntry] = OrderedDict()

    def get(self, key: str) -> _SignKeyCacheEntry | None:
        with self._lock:
            return self._store.get(key)

    def put(self, key: str, entry: _SignKeyCacheEntry) -> None:
        with self._lock:
            if len(self._store) >= self._max_count and self._store:
                self._store.popitem(last=False)
            self._store[key] = entry


@dataclass(frozen=True)
class _SignKeyCacheEntry:
    """Cached signing key with its day-of-epoch stamp.

    Corresponds to Go SDK's ``signKeyCacheEntry``.
    """

    key: bytes
    days_since_epoch: int


# Module-level cache instance (matches Go's ``var cache``).
_cache = _SignKeyCache(max_count=300)


# --- Sign options ---


@dataclass(frozen=True)
class SignOptions:
    """Options for signing a request.

    Corresponds to Go SDK's ``SignOptions``.

    Args:
        access_key: AK/SK access key.
        secret_key: AK/SK secret key.
        region_name: Target region (e.g. ``eu-de``).
        service_name: Service identifier (e.g. ``dns``, ``cce``).
        sign_algorithm: Signing algorithm. Defaults to
            ``SDK-HMAC-SHA256``. Must be a value from
            ``_SUPPORTED_ALGORITHMS``.
        enable_cache_sign_key: Cache the derived signing key for
            one day. Disabled by default (matches Go SDK default).
        time_offset_seconds: Offset in seconds to adjust the
            signing timestamp. Useful when the client clock is
            out of sync with the server.
    """

    access_key: str
    secret_key: str
    region_name: str = ""
    service_name: str = ""
    sign_algorithm: str = SIGN_ALGORITHM_HMAC_SHA256
    enable_cache_sign_key: bool = False
    time_offset_seconds: int = 0


# --- Public API ---


def sign_request(
    request: httpx.Request,
    opts: SignOptions,
    *,
    timestamp: datetime | None = None,
) -> None:
    """Sign an httpx request in place with AK/SK credentials.

    Corresponds to Go SDK's ``Sign``.
    Adds ``X-Sdk-Date``, ``Host``, and ``Authorization`` headers.

    Args:
        request: The httpx request to sign (modified in place).
        opts: Signing credentials and scope.
        timestamp: Override the signing time (for testing).
            Defaults to ``datetime.now(UTC)``.
    """
    params = _build_sign_params(opts, timestamp)

    # Add required headers (matches Go's addRequiredHeaders)
    request.headers["host"] = request.url.host or ""
    request.headers["x-sdk-date"] = params.formatted_datetime

    _sign_with_params(request, params)


def re_sign_request(
    request: httpx.Request,
    opts: SignOptions,
    *,
    timestamp: datetime | None = None,
) -> None:
    """Re-sign a request for redirection.

    Corresponds to Go SDK's ``ReSign``.
    Overwrites ``X-Sdk-Date`` and removes the old ``Authorization``
    header before re-signing.

    Args:
        request: The httpx request to re-sign (modified in place).
        opts: Signing credentials and scope.
        timestamp: Override the signing time (for testing).
    """
    params = _build_sign_params(opts, timestamp)

    # Overwrite date, remove stale auth (matches Go's setRequiredHeaders)
    request.headers["x-sdk-date"] = params.formatted_datetime
    request.headers.pop("authorization", None)

    _sign_with_params(request, params)


# --- Internal: signing parameters ---


@dataclass(frozen=True)
class _SignParams:
    """Resolved signing parameters.

    Corresponds to Go SDK's ``reqSignParams``.
    """

    access_key: str
    secret_key: str
    region_name: str
    service_name: str
    sign_algorithm: str
    enable_cache_sign_key: bool
    signing_time: datetime

    @property
    def formatted_date(self) -> str:
        return _format_date(self.signing_time)

    @property
    def formatted_datetime(self) -> str:
        return _format_datetime(self.signing_time)

    @property
    def scope(self) -> str:
        return (
            f"{self.formatted_date}/"
            f"{self.region_name}/"
            f"{self.service_name}/"
            f"sdk_request"
        )

    @property
    def days_since_epoch(self) -> int:
        """Number of days since Unix epoch for the signing time."""
        ts = int(self.signing_time.timestamp())
        return ts // 86400


def _build_sign_params(
    opts: SignOptions,
    timestamp: datetime | None,
) -> _SignParams:
    """Build resolved signing parameters from options.

    Strips whitespace from keys (matches Go SDK behavior)
    and applies time offset.
    """
    algorithm = opts.sign_algorithm or SIGN_ALGORITHM_HMAC_SHA256
    if algorithm not in _SUPPORTED_ALGORITHMS:
        raise ValueError(
            f"Unsupported signing algorithm '{algorithm}', "
            f"supported: {sorted(_SUPPORTED_ALGORITHMS)}"
        )

    base_time = timestamp if timestamp is not None else datetime.now(UTC)
    signing_time = base_time - timedelta(seconds=opts.time_offset_seconds)

    return _SignParams(
        access_key=opts.access_key.strip(),
        secret_key=opts.secret_key.strip(),
        region_name=opts.region_name,
        service_name=opts.service_name,
        sign_algorithm=algorithm,
        enable_cache_sign_key=opts.enable_cache_sign_key,
        signing_time=signing_time,
    )


# --- Internal: signing core ---


def _sign_with_params(
    request: httpx.Request,
    params: _SignParams,
) -> None:
    """Core signing logic shared by ``sign_request`` and ``re_sign_request``."""
    algorithm = params.sign_algorithm

    # Content hash
    content_sha256 = request.headers.get(
        _CONTENT_SHA256_HEADER,
        _hash_sha256(_read_body(request)),
    )

    # Canonical request
    canonical = _canonical_request(request, content_sha256)

    # String to sign
    string_to_sign = "\n".join([
        algorithm,
        params.formatted_datetime,
        params.scope,
        _hash_sha256(canonical.encode()),
    ])

    # Derive signing key (with optional caching)
    signing_key = _derive_signing_key(params)

    # Compute signature
    signature = _compute_signature(
        string_to_sign, signing_key, algorithm,
    ).hex()

    # Build Authorization header
    signed_headers = _signed_headers_string(request)
    credential = f"{params.access_key}/{params.scope}"
    request.headers["authorization"] = (
        f"{algorithm} "
        f"Credential={credential}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )


# --- Internal: key derivation with cache ---


def _derive_signing_key(params: _SignParams) -> bytes:
    """Derive the signing key, optionally using cache.

    Corresponds to Go SDK's ``deriveSigningKey``.
    When caching is enabled, the key is cached per
    (secret, region, service) and valid for one day.
    """
    if not params.enable_cache_sign_key:
        return _build_sign_key(params)

    cache_key = "-".join([
        params.secret_key,
        params.region_name,
        params.service_name,
    ])

    cached = _cache.get(cache_key)
    if cached is not None and cached.days_since_epoch == params.days_since_epoch:
        return cached.key

    sign_key = _build_sign_key(params)
    _cache.put(cache_key, _SignKeyCacheEntry(
        key=sign_key,
        days_since_epoch=params.days_since_epoch,
    ))
    return sign_key


def _build_sign_key(params: _SignParams) -> bytes:
    """Build signing key from secret + scope components.

    Corresponds to Go SDK's ``buildSignKey``::

        kDate    = HMAC("SDK" + secret, date)
        kRegion  = HMAC(kDate, region)
        kService = HMAC(kRegion, service)
        kSigning = HMAC(kService, "sdk_request")
    """
    algorithm = params.sign_algorithm
    k_secret = f"SDK{params.secret_key}".encode()
    k_date = _compute_signature(params.formatted_date, k_secret, algorithm)
    k_region = _compute_signature(params.region_name, k_date, algorithm)
    k_service = _compute_signature(params.service_name, k_region, algorithm)
    return _compute_signature("sdk_request", k_service, algorithm)


# --- Internal: crypto primitives ---


def _hash_sha256(data: bytes) -> str:
    """Hex-encoded SHA-256 hash."""
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(data: str, key: bytes) -> bytes:
    """HMAC-SHA256 of string data with byte key."""
    return hmac.new(key, data.encode(), hashlib.sha256).digest()


def _compute_signature(data: str, key: bytes, algorithm: str) -> bytes:
    """Compute signature with the specified algorithm.

    Corresponds to Go SDK's ``computeSignature``.

    Raises:
        ValueError: If the algorithm is not supported.
    """
    if algorithm == SIGN_ALGORITHM_HMAC_SHA256:
        return _hmac_sha256(data, key)
    raise ValueError(
        f"Unsupported algorithm '{algorithm}', "
        f"supported: {sorted(_SUPPORTED_ALGORITHMS)}"
    )


# --- Internal: time formatting ---


def _format_datetime(dt: datetime) -> str:
    """Format timestamp as ``20060102T150405Z``."""
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _format_date(dt: datetime) -> str:
    """Format date as ``20060102``."""
    return dt.astimezone(UTC).strftime("%Y%m%d")


# --- Internal: canonical request building ---


def _read_body(request: httpx.Request) -> bytes:
    """Read the request body as bytes.

    For POST with no body, uses the query string as content
    (matches Go SDK's ``calculateContentHash``).
    """
    if _use_payload_for_query(request):
        return str(request.url.params).encode()
    body = request.content
    if body is None:
        return b""
    return body


def _use_payload_for_query(request: httpx.Request) -> bool:
    """Check if query string should be used as payload.

    Corresponds to Go SDK's ``usePayloadForQueryParameters``.
    """
    if request.method.upper() != "POST":
        return False
    body = request.content
    return body is None or body == b""


def _url_encode(value: str, *, is_path: bool = False) -> str:
    """URL-encode a value, preserving ``/`` in paths.

    Matches Go SDK's ``urlEncode`` which keeps ``A-Z a-z 0-9 . - _ ~``
    unreserved, and additionally ``/`` for path segments.
    """
    safe = "/-_.~" if is_path else "-_.~"
    return quote(value, safe=safe)


def _canonical_path(request: httpx.Request) -> str:
    """Build the canonical URI path.

    Corresponds to Go SDK's ``getCanonicalizedResourcePath``.
    Uses the decoded path and re-encodes it to avoid double encoding.
    """
    path = request.url.path
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path = path + "/"
    path = _url_encode(path, is_path=True)
    if not path:
        path = "/"
    return path


def _canonical_query(request: httpx.Request) -> str:
    """Build the canonical query string.

    Corresponds to Go SDK's ``getCanonicalizedQueryString``.
    Parameters are sorted by encoded key (case-insensitive).
    Duplicate keys are preserved.
    """
    if _use_payload_for_query(request):
        return ""

    pairs = request.url.params.multi_items()
    if not pairs:
        return ""

    encoded = [(_url_encode(k), _url_encode(v)) for k, v in pairs]
    encoded.sort(key=lambda p: p[0].lower())

    return "&".join(f"{k}={v}" for k, v in encoded)


def _canonical_headers(request: httpx.Request) -> str:
    """Build canonical header string.

    Corresponds to Go SDK's ``getCanonicalizedHeaderString``.
    Headers are lowercased, sorted, and whitespace-collapsed.
    """
    headers = []
    for key in sorted(request.headers.keys(), key=str.lower):
        name = _SPACE_RE.sub(" ", key.lower().strip())
        value = _SPACE_RE.sub(" ", request.headers[key].strip())
        headers.append(f"{name}:{value}\n")
    return "".join(headers)


def _signed_headers_string(request: httpx.Request) -> str:
    """Build the semicolon-separated signed headers list.

    Corresponds to Go SDK's ``getSignedHeadersString``.
    """
    return ";".join(sorted(request.headers.keys(), key=str.lower))


def _canonical_request(request: httpx.Request, content_sha256: str) -> str:
    """Assemble the full canonical request string.

    Corresponds to Go SDK's ``createCanonicalRequest``.

    Format::

        METHOD
        CanonicalURI
        CanonicalQueryString
        CanonicalHeaders
        SignedHeaders
        ContentHash
    """
    return "\n".join([
        request.method,
        _canonical_path(request),
        _canonical_query(request),
        _canonical_headers(request),
        _signed_headers_string(request),
        content_sha256,
    ])
