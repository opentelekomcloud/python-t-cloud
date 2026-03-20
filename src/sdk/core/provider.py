"""Provider client — central HTTP client for the SDK.

Mirrors the Go SDK's ``ProviderClient`` + ``openstack/client.go``
authentication flows. Combines HTTP transport (via ``httpx``),
credential management, and retry logic into a single client.

The ``authenticate()`` method dispatches to the correct auth flow
based on ``AuthConfig.auth_mode`` and presence of agency fields:

.. code-block:: text

    AuthConfig.auth_mode
        ├── PASSWORD / TOKEN
        │   ├── agency_name? → _v3_auth_with_agency()
        │   └── else         → _v3_auth()
        └── AKSK
            ├── agency_name? → _aksk_auth_with_agency()
            └── else         → _aksk_auth()

Example::

    from sdk.core.auth import AuthConfig
    from sdk.core.provider import ProviderClient

    cfg = AuthConfig(
        identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
        username="user",
        password="secret",
        domain_name="my_domain",
        tenant_name="eu-de",
    )
    client = ProviderClient(cfg)
    client.authenticate()
    # client.token_id is now set, endpoint_locator is ready
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from sdk.core.auth import AuthConfig, AuthMode
from sdk.core.endpoint import EndpointLocator, build_endpoint_locator
from sdk.core.exceptions import (
    AuthenticationError,
    HttpError,
    ReauthError,
    raise_for_status,
)
from sdk.core.log import get_logger, log_request, _redact_headers
from sdk.core.signer import SignOptions, sign_request

logger = get_logger(__name__)

USER_AGENT = "python-t-cloud/0.1.0"
"""Default User-Agent header value."""

_DEFAULT_OK_CODES: dict[str, list[int]] = {
    "GET": [200],
    "POST": [200, 201, 202],
    "PUT": [200, 201, 202],
    "PATCH": [200, 204],
    "DELETE": [200, 202, 204],
    "HEAD": [204, 206],
}

_DEFAULT_MAX_BACKOFF_RETRIES = 20
"""Maximum number of retries on 429 (Too Many Requests)."""

_DEFAULT_BACKOFF_TIMEOUT = 60.0
"""Seconds to wait before retrying on 429."""

_DEFAULT_RETRY_COUNT = 1
"""Number of retries on gateway errors (502, 504)."""

_DEFAULT_RETRY_TIMEOUT = 0.5
"""Seconds to wait before retrying on gateway errors."""


class ProviderClient:
    """Central HTTP client for OTC API interaction.

    Holds authentication state (token, AK/SK credentials),
    project/domain context, and an endpoint locator built from
    the IAM service catalog. All service clients reference a single
    ``ProviderClient`` instance.

    Args:
        auth_config: Authentication configuration.
        http_client: Optional pre-configured httpx client.
            Created automatically if not provided.
        max_backoff_retries: Max retries on 429 responses.
        backoff_timeout: Wait time (seconds) per 429 retry.

    Attributes:
        token_id: Current Keystone token.
        project_id: Scoped project ID from auth response.
        user_id: Authenticated user ID.
        domain_id: Domain ID from auth response.
        region_id: Region derived from auth config.
        endpoint_locator: Callable to resolve service endpoints.
    """

    def __init__(
        self,
        auth_config: AuthConfig,
        *,
        http_client: httpx.Client | None = None,
        max_backoff_retries: int = _DEFAULT_MAX_BACKOFF_RETRIES,
        backoff_timeout: float = _DEFAULT_BACKOFF_TIMEOUT,
    ) -> None:
        self.auth_config = auth_config
        self._http = http_client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0),
        )

        # Auth state — populated by authenticate()
        self.token_id: str = ""
        self.project_id: str = ""
        self.user_id: str = ""
        self.domain_id: str = ""
        self.region_id: str = auth_config.region or ""

        self.endpoint_locator: EndpointLocator | None = None
        self._reauth_func: Callable[[], None] | None = None

        # Retry config
        self.max_backoff_retries = max_backoff_retries
        self.backoff_timeout = backoff_timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def identity_base(self) -> str:
        """IAM base URL (without version path).

        Strips ``/v3``, ``/v3/``, etc. from the identity endpoint.
        """
        endpoint = self.auth_config.identity_endpoint.rstrip("/")
        for suffix in ("/v3", "/v2.0"):
            if endpoint.endswith(suffix):
                return endpoint[: -len(suffix)] + "/"
        return endpoint + "/"

    @property
    def identity_v3_endpoint(self) -> str:
        """IAM v3 endpoint URL (always ends with ``/``)."""
        return self.identity_base + "v3/"

    def authenticate(self) -> None:
        """Run the appropriate auth flow based on ``AuthConfig``.

        Dispatches to one of four internal methods depending on
        ``auth_mode`` and presence of ``agency_name``.

        Raises:
            AuthenticationError: If the IAM request fails.
            MissingCredentialsError: If auth mode cannot be determined.
        """
        mode = self.auth_config.auth_mode
        has_agency = bool(
            self.auth_config.agency_name
            and self.auth_config.agency_domain_name
        )

        if mode in (AuthMode.PASSWORD, AuthMode.TOKEN):
            if has_agency:
                self._v3_auth_with_agency()
            else:
                self._v3_auth()
        else:
            # AKSK
            if has_agency:
                self._aksk_auth_with_agency()
            else:
                self._aksk_auth()

    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        ok_codes: list[int] | None = None,
        retry_count: int | None = None,
        retry_timeout: float | None = None,
    ) -> httpx.Response:
        """Execute an authenticated HTTP request with retry logic.

        Handles:
        - Auth header injection (token or AK/SK signing)
        - 401 → re-authenticate and retry once
        - 429 → backoff retry (up to ``max_backoff_retries``)
        - 502/504 → gateway retry (up to ``retry_count``)

        Args:
            method: HTTP method (GET, POST, etc.).
            url: Full request URL.
            json: JSON-serializable body.
            content: Raw bytes body (mutually exclusive with ``json``).
            headers: Additional request headers.
            ok_codes: Acceptable status codes. Defaults per HTTP method.
            retry_count: Gateway error retries. Default: 1.
            retry_timeout: Gateway retry wait (seconds). Default: 0.5.

        Returns:
            httpx.Response on success.

        Raises:
            HttpError: On non-OK status codes after exhausting retries.
        """
        if ok_codes is None:
            ok_codes = _DEFAULT_OK_CODES.get(method.upper(), [200])
        if retry_count is None:
            retry_count = _DEFAULT_RETRY_COUNT
        if retry_timeout is None:
            retry_timeout = _DEFAULT_RETRY_TIMEOUT

        backoff_remaining = self.max_backoff_retries

        return self._do_request(
            method=method,
            url=url,
            json=json,
            content=content,
            headers=headers,
            ok_codes=ok_codes,
            retry_count=retry_count,
            retry_timeout=retry_timeout,
            backoff_remaining=backoff_remaining,
            _is_retry=False,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> ProviderClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal: HTTP request engine
    # ------------------------------------------------------------------

    def _do_request(
        self,
        *,
        method: str,
        url: str,
        json: Any | None,
        content: bytes | None,
        headers: dict[str, str] | None,
        ok_codes: list[int],
        retry_count: int,
        retry_timeout: float,
        backoff_remaining: int,
        _is_retry: bool = False,
    ) -> httpx.Response:
        """Core request logic with retry/reauth handling."""
        req = self._build_request(
            method=method,
            url=url,
            json=json,
            content=content,
            headers=headers,
        )

        # Inject auth headers
        prereq_token = self._apply_auth(req)

        # Send
        t0 = time.monotonic()
        resp = self._http.send(req)
        duration_ms = (time.monotonic() - t0) * 1000

        log_request(
            logger,
            method=method,
            url=url,
            status_code=resp.status_code,
            duration_ms=duration_ms,
            request_id=resp.headers.get("x-request-id", ""),
        )

        # Check status
        if resp.status_code in ok_codes:
            return resp

        body = resp.text

        # 401 — reauth and retry once
        if resp.status_code == 401 and self._reauth_func is not None and not _is_retry:
            logger.debug("Got 401, attempting re-authentication")
            try:
                self._reauth_func()
            except Exception as exc:
                raise ReauthError(original=exc) from exc
            return self._do_request(
                method=method,
                url=url,
                json=json,
                content=content,
                headers=headers,
                ok_codes=ok_codes,
                retry_count=retry_count,
                retry_timeout=retry_timeout,
                backoff_remaining=backoff_remaining,
                _is_retry=True,
            )

        # 429 — backoff retry
        if resp.status_code == 429 and backoff_remaining > 0:
            logger.warning(
                "Rate limited (429), waiting %.1fs (%d retries left)",
                self.backoff_timeout,
                backoff_remaining,
            )
            time.sleep(self.backoff_timeout)
            return self._do_request(
                method=method,
                url=url,
                json=json,
                content=content,
                headers=headers,
                ok_codes=ok_codes,
                retry_count=retry_count,
                retry_timeout=retry_timeout,
                backoff_remaining=backoff_remaining - 1,
                _is_retry=_is_retry,
            )

        # 502/504 — gateway retry
        if resp.status_code in (502, 504) and retry_count > 0:
            logger.warning(
                "Gateway error (%d), retrying in %.1fs (%d left)",
                resp.status_code,
                retry_timeout,
                retry_count,
            )
            time.sleep(retry_timeout)
            return self._do_request(
                method=method,
                url=url,
                json=json,
                content=content,
                headers=headers,
                ok_codes=ok_codes,
                retry_count=retry_count - 1,
                retry_timeout=retry_timeout,
                backoff_remaining=backoff_remaining,
                _is_retry=_is_retry,
            )

        # Non-retryable error
        raise_for_status(
            resp.status_code,
            method=method,
            url=url,
            body=body,
            headers=dict(resp.headers),
        )
        # raise_for_status always raises, but make mypy happy
        raise AssertionError("unreachable")  # pragma: no cover

    def _build_request(
        self,
        *,
        method: str,
        url: str,
        json: Any | None,
        content: bytes | None,
        headers: dict[str, str] | None,
    ) -> httpx.Request:
        """Build an httpx.Request with correct content type."""
        req_headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if headers:
            req_headers.update(headers)

        if json is not None:
            req_headers.setdefault("Content-Type", "application/json")
            return self._http.build_request(
                method, url, json=json, headers=req_headers,
            )
        if content is not None:
            return self._http.build_request(
                method, url, content=content, headers=req_headers,
            )
        return self._http.build_request(
            method, url, headers=req_headers,
        )

    def _apply_auth(self, request: httpx.Request) -> str:
        """Apply auth headers to a request. Returns pre-request token."""
        prereq_token = self.token_id

        if self.auth_config.auth_mode == AuthMode.AKSK and self.auth_config.access_key:
            # AK/SK — sign the request
            sign_request(
                request,
                SignOptions(
                    access_key=_secret_value(self.auth_config.access_key) if self.auth_config.access_key else "",
                    secret_key=_secret_value(self.auth_config.secret_key) if self.auth_config.secret_key else "",
                ),
            )
            # Set project/domain scope headers
            if self.project_id and not self.domain_id:
                request.headers["x-project-id"] = self.project_id
            if self.domain_id:
                request.headers["x-domain-id"] = self.domain_id
            if self.auth_config.security_token:
                request.headers["x-security-token"] = _secret_value(self.auth_config.security_token)
        elif self.token_id:
            request.headers["x-auth-token"] = self.token_id

        return prereq_token

    # ------------------------------------------------------------------
    # Internal: Auth flows
    # ------------------------------------------------------------------

    def _v3_auth(self) -> None:
        """Keystone V3 password/token authentication.

        POST /v3/auth/tokens → extracts token, project, user, catalog.
        Sets ``reauth_func`` for automatic token refresh on 401.
        """
        cfg = self.auth_config

        if cfg.token_id:
            # Token reuse — validate by GET /v3/auth/tokens
            self.token_id = _secret_value(cfg.token_id)
            resp = self._iam_request(
                "GET",
                self.identity_v3_endpoint + "auth/tokens",
                headers={"x-subject-token": self.token_id},
            )
        else:
            # Password auth — POST /v3/auth/tokens
            body = _build_v3_auth_body(cfg)
            resp = self._iam_request(
                "POST",
                self.identity_v3_endpoint + "auth/tokens",
                json=body,
            )
            # Token is in the X-Subject-Token header
            self.token_id = resp.headers.get("x-subject-token", "")

        data = resp.json()
        self._extract_auth_result(data)

        # Reauth function
        if cfg.allow_reauth:
            self._reauth_func = self._v3_auth

    def _v3_auth_with_agency(self) -> None:
        """Keystone V3 auth + agency assume_role.

        First authenticates normally (password/token), then issues
        a second POST with ``assume_role`` identity method to get
        a delegated token.
        """
        cfg = self.auth_config

        # Step 1: authenticate as the base user
        if not cfg.token_id:
            self._v3_auth()
        else:
            self.token_id = _secret_value(cfg.token_id)

        # Step 2: assume_role with agency credentials
        body = _build_agency_auth_body(cfg)
        resp = self._iam_request(
            "POST",
            self.identity_v3_endpoint + "auth/tokens",
            json=body,
        )
        self.token_id = resp.headers.get("x-subject-token", "")

        data = resp.json()
        self._extract_auth_result(data)

        if cfg.allow_reauth:
            self._reauth_func = self._v3_auth_with_agency

    def _aksk_auth(self) -> None:
        """AK/SK authentication.

        Does not create a token. Instead, stores AK/SK credentials
        for signing future requests and fetches the service catalog
        via ``GET /v3/auth/catalog``.
        """
        cfg = self.auth_config

        # Resolve project_id from name if needed
        if not cfg.project_id and cfg.project_name:
            cfg.project_id = self._resolve_project_id(cfg.project_name)

        # Resolve domain_id from name if needed
        if not cfg.domain_id and cfg.domain_name:
            cfg.domain_id = self._resolve_domain_id(cfg.domain_name)

        self.project_id = cfg.project_id or ""
        self.domain_id = cfg.domain_id or ""
        self.region_id = cfg.region or ""

        # Fetch service catalog (requests are AK/SK-signed)
        catalog = self._fetch_catalog()
        self.endpoint_locator = build_endpoint_locator(
            catalog, self.region_id,
        )

    def _aksk_auth_with_agency(self) -> None:
        """AK/SK auth + agency assume_role.

        First sets up AK/SK signing, then issues a token request
        with ``assume_role`` to get a delegated token. After this,
        subsequent requests use the token (not AK/SK).
        """
        cfg = self.auth_config

        # Step 1: AK/SK auth (for catalog + signing)
        self._aksk_auth()

        if not self.domain_id:
            raise AuthenticationError(
                method="POST",
                url=self.identity_v3_endpoint + "auth/tokens",
                body="Agency auth requires domain_id or domain_name",
            )

        # Step 2: assume_role → get token
        body = _build_agency_auth_body(cfg)
        resp = self._iam_request(
            "POST",
            self.identity_v3_endpoint + "auth/tokens",
            json=body,
        )
        self.token_id = resp.headers.get("x-subject-token", "")

        data = resp.json()
        self._extract_auth_result(data)

        # After agency auth, clear AK/SK so requests use token
        # (mirrors Go SDK: client.AKSKAuthOptions.AccessKey = "")
        # We don't mutate auth_config; instead _apply_auth checks
        # token_id first when AK is empty.

        self._reauth_func = self._aksk_auth_with_agency

    # ------------------------------------------------------------------
    # Internal: IAM helpers
    # ------------------------------------------------------------------

    def _iam_request(
        self,
        method: str,
        url: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send a request to the IAM service.

        AK/SK-signed if in AKSK mode, otherwise uses current token.
        Raises on non-2xx.

        Args:
            method: HTTP method.
            url: Full IAM URL.
            json: JSON body.
            headers: Extra headers.

        Returns:
            httpx.Response.

        Raises:
            HttpError: On non-2xx response.
        """
        req = self._build_request(
            method=method,
            url=url,
            json=json,
            content=None,
            headers=headers,
        )
        self._apply_auth(req)

        t0 = time.monotonic()
        resp = self._http.send(req)
        duration_ms = (time.monotonic() - t0) * 1000

        log_request(
            logger,
            method=method,
            url=url,
            status_code=resp.status_code,
            duration_ms=duration_ms,
            request_id=resp.headers.get("x-request-id", ""),
        )

        if resp.status_code >= 400:
            raise_for_status(
                resp.status_code,
                method=method,
                url=url,
                body=resp.text,
                headers=dict(resp.headers),
            )
        return resp

    def _extract_auth_result(self, data: dict[str, Any]) -> None:
        """Extract project, user, domain, and catalog from auth response.

        Populates ``project_id``, ``user_id``, ``domain_id``,
        ``region_id``, and ``endpoint_locator``.

        Args:
            data: Parsed JSON from IAM auth response.
        """
        token_data = data.get("token", {})

        project = token_data.get("project")
        if project:
            self.project_id = project.get("id", "")
            domain = project.get("domain", {})
            if domain:
                self.domain_id = domain.get("id", "")

        user = token_data.get("user")
        if user:
            self.user_id = user.get("id", "")
            if not self.domain_id:
                domain = user.get("domain", {})
                if domain:
                    self.domain_id = domain.get("id", "")

        # Region from config or derive from project name
        if not self.region_id:
            cfg = self.auth_config
            if cfg.region:
                self.region_id = cfg.region
            elif cfg.tenant_name:
                self.region_id = cfg.tenant_name

        # Service catalog
        catalog = token_data.get("catalog", [])
        if catalog:
            self.endpoint_locator = build_endpoint_locator(
                catalog, self.region_id,
            )

    def _fetch_catalog(self) -> list[dict[str, Any]]:
        """Fetch the service catalog via ``GET /v3/auth/catalog``.

        Used by AK/SK auth where the catalog is not embedded in
        a token response.

        Returns:
            List of catalog entries.
        """
        resp = self._iam_request(
            "GET",
            self.identity_v3_endpoint + "auth/catalog",
        )
        data = resp.json()
        return data.get("catalog", [])

    def _resolve_project_id(self, name: str) -> str:
        """Look up project ID by name via IAM API.

        Args:
            name: Project name.

        Returns:
            Project ID string.

        Raises:
            EndpointNotFoundError: If no project is found.
        """
        resp = self._iam_request(
            "GET",
            self.identity_v3_endpoint + f"projects?name={name}",
        )
        data = resp.json()
        projects = data.get("projects", [])
        if not projects:
            from sdk.core.exceptions import EndpointNotFoundError
            raise EndpointNotFoundError(
                service="identity", region=name,
            )
        return projects[0]["id"]

    def _resolve_domain_id(self, name: str) -> str:
        """Look up domain ID by name via IAM API.

        Args:
            name: Domain name.

        Returns:
            Domain ID string, or empty string if not found.
        """
        try:
            resp = self._iam_request(
                "GET",
                self.identity_v3_endpoint + f"auth/domains?name={name}",
            )
            data = resp.json()
            domains = data.get("domains", [])
            if domains:
                return domains[0]["id"]
        except HttpError:
            logger.debug("Could not resolve domain '%s'", name)
        return ""


# ======================================================================
# Module-level helpers
# ======================================================================


def _secret_value(value: Any) -> str:
    """Extract the plain string from a value that may be ``SecretStr``.

    Works transparently with both ``str`` and ``pydantic.SecretStr``,
    so ``_build_v3_auth_body`` doesn't depend on which type
    ``AuthConfig`` uses for sensitive fields.

    Args:
        value: A ``str`` or ``SecretStr`` instance.

    Returns:
        Plain string.
    """
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    return str(value)


def _build_v3_auth_body(cfg: AuthConfig) -> dict[str, Any]:
    """Build the JSON body for ``POST /v3/auth/tokens``.

    Constructs the identity and scope sections based on
    available credentials (password or token).

    Args:
        cfg: Auth configuration.

    Returns:
        JSON-serializable dict for the request body.
    """
    auth: dict[str, Any] = {"identity": {}}

    if cfg.password:
        # Password authentication
        user: dict[str, Any] = {"password": _secret_value(cfg.password)}
        if cfg.user_id:
            user["id"] = cfg.user_id
        else:
            user["name"] = cfg.username
            domain: dict[str, str] = {}
            if cfg.domain_id:
                domain["id"] = cfg.domain_id
            elif cfg.domain_name:
                domain["name"] = cfg.domain_name
            user["domain"] = domain

        auth["identity"]["methods"] = ["password"]
        auth["identity"]["password"] = {"user": user}

        # MFA TOTP
        if cfg.passcode:
            auth["identity"]["methods"].append("totp")
            totp_user: dict[str, str] = {"passcode": _secret_value(cfg.passcode)}
            if cfg.user_id:
                totp_user["id"] = cfg.user_id
            if cfg.username:
                totp_user["name"] = cfg.username
            auth["identity"]["totp"] = {"user": totp_user}

    elif cfg.token_id:
        auth["identity"]["methods"] = ["token"]
        auth["identity"]["token"] = {"id": _secret_value(cfg.token_id)}

    # Scope
    scope = _build_scope(cfg)
    if scope:
        auth["scope"] = scope

    return {"auth": auth}


def _build_agency_auth_body(cfg: AuthConfig) -> dict[str, Any]:
    """Build the JSON body for agency ``assume_role`` auth.

    Args:
        cfg: Auth configuration with agency fields populated.

    Returns:
        JSON-serializable dict for the request body.
    """
    auth: dict[str, Any] = {
        "identity": {
            "methods": ["assume_role"],
            "assume_role": {
                "domain_name": cfg.agency_domain_name,
                "xrole_name": cfg.agency_name,
            },
        },
    }

    # Scope for delegated project
    if cfg.delegated_project and cfg.agency_domain_name:
        auth["scope"] = {
            "project": {
                "name": cfg.delegated_project,
                "domain": {"name": cfg.agency_domain_name},
            },
        }

    return {"auth": auth}


def _build_scope(cfg: AuthConfig) -> dict[str, Any] | None:
    """Build the ``scope`` section of a V3 auth request.

    Args:
        cfg: Auth configuration.

    Returns:
        Scope dict or None if no scoping fields are set.
    """
    # Project scope (by ID or name)
    project_id = cfg.tenant_id or cfg.project_id
    project_name = cfg.tenant_name or cfg.project_name

    if project_id:
        return {"project": {"id": project_id}}

    if project_name:
        domain: dict[str, str] = {}
        if cfg.domain_id:
            domain["id"] = cfg.domain_id
        elif cfg.domain_name:
            domain["name"] = cfg.domain_name
        scope: dict[str, Any] = {"project": {"name": project_name}}
        if domain:
            scope["project"]["domain"] = domain
        return scope

    # Domain-only scope
    if cfg.domain_id:
        return {"domain": {"id": cfg.domain_id}}
    if cfg.domain_name:
        return {"domain": {"name": cfg.domain_name}}

    return None
