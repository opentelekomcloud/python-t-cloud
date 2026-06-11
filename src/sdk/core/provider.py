"""Provider client — central HTTP client for the SDK.

Combines HTTP transport (via ``httpx``), credential management,
and retry logic into a single client.

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

import logging
import re
import time
from typing import Any

import httpx

from sdk.core.auth import AuthConfig, AuthMode
from sdk.core.endpoint import (EndpointLocator,
                               build_endpoint_locator,
                               CatalogEntry)
from sdk.core.exceptions import (
    ReauthError,
    UnauthorizedError,
    raise_for_status, AuthError, ResourceNotFoundError
)
from sdk.core.signer import SignOptions, sign_request

logger = logging.getLogger(__name__)

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

_VERSION_SUFFIX = re.compile(r"/v\d+(\.\d+)?$")


class ProviderClient:
    """Central HTTP client for OTC API interaction.

    Holds authentication state (token, AK/SK credentials),
    project/domain context, and an endpoint locator built from
    the IAM service catalog. All service clients reference a single
    ``ProviderClient`` instance.

    .. note::

        This implementation is not thread-safe. If thread safety is needed,
        add external synchronization around ``authenticate()`` and
        ``request()``.

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
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0),
        )

        self.token_id: str = ""
        self.project_id: str = ""
        self.user_id: str = ""
        self.domain_id: str = ""
        self.region_id: str = auth_config.region or ""
        self.endpoint_locator: EndpointLocator | None = None

        self.max_backoff_retries = max_backoff_retries
        self.backoff_timeout = backoff_timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def identity_base(self) -> str:
        """IAM base URL (without version path).

        Strips ``/v3``, ``/v3.0``, etc. from the identity endpoint.
        """
        endpoint = self.auth_config.identity_endpoint.rstrip("/")
        endpoint = _VERSION_SUFFIX.sub("", endpoint)
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
            UnauthorizedError: If the IAM request fails.
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
            if has_agency:
                self._aksk_auth_with_agency()
            else:
                self._aksk_auth()
        if self.endpoint_locator is None:
            raise AuthError(
                "Endpoint locator not initialized after authentication")

    def request(
        self,
        method: str,
        url: str,
        *,
        service_name: str = "",
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
            service_name: Service name.
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

        return self._do_request(
            method=method,
            url=url,
            service_name=service_name,
            json=json,
            content=content,
            headers=headers,
            ok_codes=ok_codes,
            retry_count=retry_count,
            retry_timeout=retry_timeout,
            backoff_remaining=self.max_backoff_retries,
            _is_retry=False,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._owns_http_client:
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
        service_name: str,
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
        reauthed = _is_retry

        while True:
            req = self._build_request(
                method=method,
                url=url,
                json=json,
                content=content,
                headers=headers,
            )

            self._apply_auth(req, service_name=service_name)

            t0 = time.monotonic()
            resp = self._http.send(req)
            duration_ms = (time.monotonic() - t0) * 1000

            _log_response(
                logger, method, url, resp.status_code,
                duration_ms, resp.headers.get("x-request-id", ""),
            )

            if resp.status_code in ok_codes:
                return resp

            body = resp.text

            if (resp.status_code == 401
                    and self.auth_config.allow_reauth
                    and not reauthed):
                logger.debug("Got 401, attempting re-authentication")
                try:
                    self.authenticate()
                except Exception as exc:
                    raise ReauthError(original=exc) from exc
                reauthed = True
                continue

            if resp.status_code == 429 and backoff_remaining > 0:
                logger.warning(
                    "Rate limited (429), waiting %.1fs (%d retries left)",
                    self.backoff_timeout,
                    backoff_remaining,
                )
                time.sleep(self.backoff_timeout)
                backoff_remaining -= 1
                continue

            if resp.status_code in (502, 504) and retry_count > 0:
                logger.warning(
                    "Gateway error (%d), retrying in %.1fs (%d left)",
                    resp.status_code,
                    retry_timeout,
                    retry_count,
                )
                time.sleep(retry_timeout)
                retry_count -= 1
                continue

            raise_for_status(
                resp.status_code,
                method=method,
                url=url,
                body=body,
                expected=ok_codes,
                headers=dict(resp.headers),
            )

    def _build_request(
        self,
        *,
        method: str,
        url: str,
        json: Any | None,
        content: bytes | None,
        headers: dict[str, str] | None,
    ) -> httpx.Request:
        """Build a httpx.Request with correct content type."""
        req_headers = dict(self._http.headers)
        req_headers["Accept"] = "application/json"
        if headers:
            req_headers.update(headers)
        req_headers.setdefault("User-Agent", USER_AGENT)

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

    def _apply_auth(self, request: httpx.Request,
                    service_name: str) -> None:
        """Apply auth headers to a request.

        Returns the pre-request token for reauth comparison
        (mirrors Go SDK's ``prereqtok`` pattern).
        """
        if self.auth_config.auth_mode == AuthMode.AKSK and self.auth_config.access_key:
            sign_request(
                request,
                SignOptions(
                    access_key=self.auth_config.access_key,
                    secret_key=_secret_value(self.auth_config.secret_key),
                    region_name=self.region_id,
                    service_name=service_name,
                ),
            )
            # Set project/domain scope headers
            if self.project_id and not self.domain_id:
                request.headers["x-project-id"] = self.project_id
            if self.domain_id:
                request.headers["x-domain-id"] = self.domain_id
            if self.auth_config.security_token:
                request.headers["x-security-token"] = (
                    self.auth_config.security_token
                )
        elif self.token_id:
            request.headers["x-auth-token"] = self.token_id

    # ------------------------------------------------------------------
    # Internal: Auth flows
    # ------------------------------------------------------------------

    def _v3_auth(self) -> None:
        """Keystone V3 password/token authentication.

        POST /v3/auth/tokens → extracts token, project, user, catalog.
        Sets ``_reauth_func`` for automatic token refresh on 401.
        """
        cfg = self.auth_config

        if cfg.token_id:
            self.token_id = _secret_value(cfg.token_id)
            resp = self._iam_request(
                "GET",
                self.identity_v3_endpoint + "auth/tokens",
                headers={"x-subject-token": self.token_id},
            )
        else:
            body = _build_v3_auth_body(cfg)
            resp = self._iam_request(
                "POST",
                self.identity_v3_endpoint + "auth/tokens",
                json=body,
            )
            self.token_id = resp.headers.get("x-subject-token", "")

        self._extract_auth_result(resp.json())

    def _v3_auth_with_agency(self) -> None:
        """Keystone V3 auth + agency assume_role.

        First authenticates normally (password/token), then issues
        a second POST with ``assume_role`` identity method to get
        a delegated token.
        """
        cfg = self.auth_config

        if not cfg.token_id:
            self._v3_auth()
        else:
            self.token_id = _secret_value(cfg.token_id)

        body = _build_agency_auth_body(cfg)
        resp = self._iam_request(
            "POST",
            self.identity_v3_endpoint + "auth/tokens",
            json=body,
        )
        self.token_id = resp.headers.get("x-subject-token", "")

        self._extract_auth_result(resp.json())

    def _aksk_auth(self) -> None:
        """AK/SK authentication.

        Does not create a token. Instead, stores AK/SK credentials
        for signing future requests and fetches the service catalog
        via ``GET /v3/auth/catalog``.
        """
        cfg = self.auth_config
        self.project_id = self._resolve_project_id(
            cfg.project_name) if not cfg.project_id and cfg.project_name \
            else cfg.project_id or ""
        self.domain_id = self._resolve_domain_id(
            cfg.domain_name) if not cfg.domain_id and cfg.domain_name \
            else cfg.domain_id or ""
        self.region_id = cfg.region or ""

        catalog = self._fetch_catalog()
        self.endpoint_locator = build_endpoint_locator(catalog, self.region_id)

    def _aksk_auth_with_agency(self) -> None:
        """AK/SK auth + agency assume_role.

        First sets up AK/SK signing, then issues a token request
        with ``assume_role`` to get a delegated token. After this,
        subsequent requests use the token (not AK/SK).
        """
        cfg = self.auth_config
        self._aksk_auth()

        if not self.domain_id:
            raise UnauthorizedError(
                method="POST",
                url=self.identity_v3_endpoint + "auth/tokens",
                body="Agency auth requires domain_id or domain_name",
            )

        body = _build_agency_auth_body(cfg)
        resp = self._iam_request(
            "POST",
            self.identity_v3_endpoint + "auth/tokens",
            json=body,
        )
        self.token_id = resp.headers.get("x-subject-token", "")
        self._extract_auth_result(resp.json())

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
        self._apply_auth(req, service_name="iam")

        t0 = time.monotonic()
        resp = self._http.send(req)
        duration_ms = (time.monotonic() - t0) * 1000

        _log_response(logger, method, url, resp.status_code,
                      duration_ms, resp.headers.get("x-request-id", ""))

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

        if not self.region_id:
            cfg = self.auth_config
            self.region_id = cfg.region or cfg.tenant_name or ""

        catalog = token_data.get("catalog", [])
        if catalog:
            parsed_catalog = [CatalogEntry.model_validate(c) for c in catalog]
            self.endpoint_locator = build_endpoint_locator(parsed_catalog,
                                                           self.region_id)

    def _fetch_catalog(self) -> list[CatalogEntry]:
        """Fetch the service catalog via ``GET /v3/auth/catalog``.

        Used by AK/SK auth where the catalog is not embedded in
        a token response.

        Returns:
            List of catalog entries.
        """
        resp = self._iam_request("GET",
                                 self.identity_v3_endpoint + "auth/catalog")
        raw_catalog = resp.json().get("catalog", [])
        return [CatalogEntry.model_validate(entry) for entry in raw_catalog]

    def _resolve_named_id(
            self, *, resource: str, url_suffix: str, items_key: str, name: str
    ) -> str:
        """Look up a resource ID by name via the IAM API.

        Raises:
            ResourceNotFoundError: If nothing matches ``name``.
        """
        resp = self._iam_request(
            "GET", self.identity_v3_endpoint + f"{url_suffix}?name={name}"
        )
        items = resp.json().get(items_key, [])
        if not items:
            raise ResourceNotFoundError(resource, name)
        return items[0]["id"]

    def _resolve_project_id(self, name: str) -> str:
        return self._resolve_named_id(
            resource="Project", url_suffix="projects",
            items_key="projects", name=name,
        )

    def _resolve_domain_id(self, name: str) -> str:
        return self._resolve_named_id(
            resource="Domain", url_suffix="auth/domains",
            items_key="domains", name=name,
        )

# ======================================================================
# Module-level helpers
# ======================================================================


def _log_response(
    log: logging.Logger,
    method: str,
    url: str,
    status_code: int,
    duration_ms: float,
    request_id: str,
) -> None:
    """Log an HTTP response at the appropriate level.

    - 2xx → DEBUG
    - 4xx → WARNING
    - 5xx → ERROR
    """
    rid = f" [{request_id}]" if request_id else ""
    msg = f"{method} {url} → {status_code} ({duration_ms:.0f}ms){rid}"

    if status_code >= 500:
        log.error(msg)
    elif status_code >= 400:
        log.warning(msg)
    else:
        log.debug(msg)


def _secret_value(value: Any) -> str:
    """Extract the plain string from a value that may be ``SecretStr``.

    Works transparently with both ``str`` and ``pydantic.SecretStr``,
    so callers don't need to know which type ``AuthConfig`` uses
    for sensitive fields.

    Args:
        value: A ``str`` or ``SecretStr`` instance.

    Returns:
        Plain string.
    """
    if value is None:
        return ""
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

        if cfg.passcode:
            auth["identity"]["methods"].append("totp")
            totp_user: dict[str, str] = {
                "passcode": _secret_value(cfg.passcode),
            }
            if cfg.user_id:
                totp_user["id"] = cfg.user_id
            if cfg.username:
                totp_user["name"] = cfg.username
            auth["identity"]["totp"] = {"user": totp_user}

    elif cfg.token_id:
        auth["identity"]["methods"] = ["token"]
        auth["identity"]["token"] = {"id": _secret_value(cfg.token_id)}

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

    if cfg.domain_id:
        return {"domain": {"id": cfg.domain_id}}
    if cfg.domain_name:
        return {"domain": {"name": cfg.domain_name}}

    return None
