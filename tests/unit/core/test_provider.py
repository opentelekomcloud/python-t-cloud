"""Tests for ``sdk.core.provider``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch
from pydantic import BaseModel
import httpx
import pytest

from sdk.core.auth import AuthConfig, AuthMode
from sdk.core.exceptions import (
    UnauthorizedError,
    BadRequestError,
    EndpointNotFoundError,
    InternalServerError,
    NotFoundError,
    ReauthError,
    ServiceNotFoundError,
    TooManyRequestsError,
)
from sdk.core.provider import (
    ProviderClient,
    _build_agency_auth_body,
    _build_scope,
    _build_v3_auth_body,
)
from sdk.core.endpoint import build_endpoint_locator, CatalogEntry


# ======================================================================
# Fixtures
# ======================================================================


def _password_config(**overrides: Any) -> AuthConfig:
    """Create a password AuthConfig with defaults."""
    defaults = {
        "identity_endpoint": "https://iam.eu-de.otc.t-systems.com/v3",
        "username": "testuser",
        "password": "secret",
        "domain_name": "testdomain",
        "tenant_name": "eu-de",
        "allow_reauth": True,
    }
    defaults.update(overrides)
    return AuthConfig(**defaults)


def _aksk_config(**overrides: Any) -> AuthConfig:
    """Create an AK/SK AuthConfig with defaults."""
    defaults = {
        "identity_endpoint": "https://iam.eu-de.otc.t-systems.com/v3",
        "access_key": "MYACCESSKEY",
        "secret_key": "MYSECRETKEY",
        "region": "eu-de",
        "project_id": "project-123",
    }
    defaults.update(overrides)
    return AuthConfig(**defaults)


def _token_response(
    *,
    token_id: str = "tok-abc-123",
    project_id: str = "proj-123",
    project_name: str = "eu-de",
    domain_id: str = "dom-456",
    user_id: str = "user-789",
    catalog: list[dict[str, Any]] | None = None,
) -> httpx.Response:
    """Build a mock IAM token response."""
    body: dict[str, Any] = {
        "token": {
            "project": {
                "id": project_id,
                "name": project_name,
                "domain": {"id": domain_id},
            },
            "user": {
                "id": user_id,
                "domain": {"id": domain_id},
            },
        },
    }
    raw_catalog = catalog if catalog is not None else _sample_catalog()
    serialized_catalog = []
    for entry in raw_catalog:
        if isinstance(entry, BaseModel):
            serialized_catalog.append(entry.model_dump(by_alias=True))
        else:
            serialized_catalog.append(entry)

    body["token"]["catalog"] = serialized_catalog

    resp = httpx.Response(
        201,
        json=body,
        headers={"x-subject-token": token_id},
    )
    return resp


def _sample_catalog() -> list[CatalogEntry]:
    raw = [
        {
            "type": "compute",
            "endpoints": [
                {
                    "interface": "public",
                    "region_id": "eu-de",
                    "url": "https://ecs.eu-de.otc.t-systems.com/v2.1",
                },
                {
                    "interface": "internal",
                    "region_id": "eu-de",
                    "url": "https://ecs-internal.eu-de.otc.t-systems.com/v2.1",
                },
            ],
        },
        {
            "type": "dns",
            "endpoints": [
                {
                    "interface": "public",
                    "region_id": "eu-de",
                    "url": "https://dns.eu-de.otc.t-systems.com/v2",
                },
            ],
        },
    ]
    return [CatalogEntry.model_validate(raw) for raw in raw]


def _catalog_response() -> httpx.Response:
    serialized_catalog = [
        entry.model_dump(by_alias=True)
        for entry in _sample_catalog()
    ]
    return httpx.Response(200, json={"catalog": serialized_catalog})


# ======================================================================
# ProviderClient: basic properties
# ======================================================================


class TestProviderClientProperties:
    """Test basic ProviderClient attributes and properties."""

    def test_identity_base_strips_v3(self) -> None:
        cfg = _password_config()
        client = ProviderClient(cfg)
        assert client.identity_base == "https://iam.eu-de.otc.t-systems.com/"

    def test_identity_base_strips_v3_slash(self) -> None:
        cfg = _password_config(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3/"
        )
        client = ProviderClient(cfg)
        assert client.identity_base == "https://iam.eu-de.otc.t-systems.com/"

    def test_identity_base_no_version(self) -> None:
        cfg = _password_config(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com"
        )
        client = ProviderClient(cfg)
        assert client.identity_base == "https://iam.eu-de.otc.t-systems.com/"

    def test_identity_v3_endpoint(self) -> None:
        cfg = _password_config()
        client = ProviderClient(cfg)
        assert client.identity_v3_endpoint == "https://iam.eu-de.otc.t-systems.com/v3/"

    def test_initial_state_empty(self) -> None:
        cfg = _password_config()
        client = ProviderClient(cfg)
        assert client.token_id == ""
        assert client.project_id == ""
        assert client.user_id == ""
        assert client.domain_id == ""
        # region_id is "" because _password_config has no region field
        assert client.region_id == ""

    def test_region_from_config(self) -> None:
        cfg = _password_config(region="eu-nl")
        client = ProviderClient(cfg)
        assert client.region_id == "eu-nl"

    def test_context_manager(self) -> None:
        cfg = _password_config()
        with ProviderClient(cfg) as client:
            assert isinstance(client, ProviderClient)


# ======================================================================
# Auth body builders
# ======================================================================


class TestBuildV3AuthBody:
    """Test ``_build_v3_auth_body`` for password and token modes."""

    def test_password_with_username_domain_name(self) -> None:
        cfg = _password_config()
        body = _build_v3_auth_body(cfg)

        auth = body["auth"]
        assert auth["identity"]["methods"] == ["password"]
        user = auth["identity"]["password"]["user"]
        assert user["name"] == "testuser"
        assert user["password"] == "secret"
        assert user["domain"] == {"name": "testdomain"}

    def test_password_with_user_id(self) -> None:
        cfg = _password_config(username=None, user_id="uid-123")
        body = _build_v3_auth_body(cfg)

        user = body["auth"]["identity"]["password"]["user"]
        assert user["id"] == "uid-123"
        assert "name" not in user

    def test_password_with_domain_id(self) -> None:
        cfg = _password_config(domain_name=None, domain_id="did-456")
        body = _build_v3_auth_body(cfg)

        user = body["auth"]["identity"]["password"]["user"]
        assert user["domain"] == {"id": "did-456"}

    def test_password_with_totp(self) -> None:
        cfg = _password_config(passcode="123456")
        body = _build_v3_auth_body(cfg)

        identity = body["auth"]["identity"]
        assert "totp" in identity["methods"]
        assert identity["totp"]["user"]["passcode"] == "123456"

    def test_token_auth(self) -> None:
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            token_id="existing-token",
        )
        body = _build_v3_auth_body(cfg)

        identity = body["auth"]["identity"]
        assert identity["methods"] == ["token"]
        assert identity["token"]["id"] == "existing-token"

    def test_scope_project_by_name(self) -> None:
        cfg = _password_config(tenant_name="eu-de")
        body = _build_v3_auth_body(cfg)

        scope = body["auth"]["scope"]
        assert scope["project"]["name"] == "eu-de"
        assert scope["project"]["domain"]["name"] == "testdomain"

    def test_scope_project_by_id(self) -> None:
        cfg = _password_config(tenant_id="proj-xyz", tenant_name=None)
        body = _build_v3_auth_body(cfg)

        scope = body["auth"]["scope"]
        assert scope["project"]["id"] == "proj-xyz"

    def test_no_scope(self) -> None:
        cfg = _password_config(
            username=None, user_id="uid-1",
            tenant_name=None, domain_name=None, domain_id=None,
        )
        body = _build_v3_auth_body(cfg)
        assert "scope" not in body["auth"]


class TestBuildAgencyAuthBody:
    """Test ``_build_agency_auth_body``."""

    def test_agency_body(self) -> None:
        cfg = _password_config(
            agency_name="my_agency",
            agency_domain_name="agency_domain",
            delegated_project="delegated_proj",
        )
        body = _build_agency_auth_body(cfg)

        identity = body["auth"]["identity"]
        assert identity["methods"] == ["assume_role"]
        assert identity["assume_role"]["xrole_name"] == "my_agency"
        assert identity["assume_role"]["domain_name"] == "agency_domain"

        scope = body["auth"]["scope"]
        assert scope["project"]["name"] == "delegated_proj"

    def test_agency_no_delegated_project(self) -> None:
        cfg = _password_config(
            agency_name="my_agency",
            agency_domain_name="agency_domain",
        )
        body = _build_agency_auth_body(cfg)
        assert "scope" not in body["auth"]


class TestBuildScope:
    """Test ``_build_scope``."""

    def test_project_id(self) -> None:
        cfg = _password_config(tenant_id="proj-1", tenant_name=None)
        scope = _build_scope(cfg)
        assert scope == {"project": {"id": "proj-1"}}

    def test_project_name_with_domain(self) -> None:
        cfg = _password_config(tenant_name="eu-de")
        scope = _build_scope(cfg)
        assert scope == {
            "project": {
                "name": "eu-de",
                "domain": {"name": "testdomain"},
            },
        }

    def test_domain_only(self) -> None:
        cfg = _password_config(tenant_name=None, domain_name=None, domain_id="did-1")
        scope = _build_scope(cfg)
        assert scope == {"domain": {"id": "did-1"}}

    def test_none_when_empty(self) -> None:
        cfg = _password_config(
            username=None, user_id="uid-1",
            tenant_name=None, domain_name=None, domain_id=None,
        )
        assert _build_scope(cfg) is None


# ======================================================================
# Endpoint locator
# ======================================================================


class TestEndpointLocator:
    """Test ``build_endpoint_locator`` (acceptance with provider)."""

    def test_finds_public_endpoint(self) -> None:
        from sdk.core.endpoint import EndpointOpts
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog, "eu-de")

        url = locator(EndpointOpts(service_type="compute"))
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/"

    def test_finds_dns_endpoint(self) -> None:
        from sdk.core.endpoint import EndpointOpts
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog, "eu-de")

        url = locator(EndpointOpts(service_type="dns"))
        assert url == "https://dns.eu-de.otc.t-systems.com/v2/"

    def test_region_override(self) -> None:
        from sdk.core.endpoint import EndpointOpts
        raw = [
            {
                "type": "compute",
                "endpoints": [
                    {
                        "interface": "public",
                        "region_id": "eu-nl",
                        "url": "https://ecs.eu-nl.example.com/v2.1",
                    },
                ],
            },
        ]
        catalog = [CatalogEntry.model_validate(entry) for entry in raw]
        locator = build_endpoint_locator(catalog, "eu-de")

        url = locator(EndpointOpts(service_type="compute", region="eu-nl"))
        assert url == "https://ecs.eu-nl.example.com/v2.1/"

    def test_service_not_found(self) -> None:
        from sdk.core.endpoint import EndpointOpts
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog, "eu-de")

        with pytest.raises(ServiceNotFoundError):
            locator(EndpointOpts(service_type="nonexistent"))

    def test_endpoint_not_found_wrong_region(self) -> None:
        from sdk.core.endpoint import EndpointOpts
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog, "eu-de")

        with pytest.raises(EndpointNotFoundError):
            locator(EndpointOpts(service_type="compute", region="us-west-1"))


# ======================================================================
# ProviderClient: authenticate (v3_auth)
# ======================================================================


class TestV3Auth:
    """Test password/token auth flows using mocked HTTP."""

    def test_password_auth_sets_state(self) -> None:
        """Password auth should set token, project, user, domain."""
        cfg = _password_config()
        token_resp = _token_response()

        transport = httpx.MockTransport(lambda req: token_resp)
        http_client = httpx.Client(transport=transport)

        client = ProviderClient(cfg, http_client=http_client)
        client.authenticate()

        assert client.token_id == "tok-abc-123"
        assert client.project_id == "proj-123"
        assert client.user_id == "user-789"
        assert client.domain_id == "dom-456"
        assert client.endpoint_locator is not None

    def test_password_auth_sends_correct_body(self) -> None:
        """Verify the auth request body is correct."""
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return _token_response()

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)

        client = ProviderClient(cfg, http_client=http_client)
        client.authenticate()

        assert len(captured) == 1
        body = json.loads(captured[0].content)
        assert body["auth"]["identity"]["methods"] == ["password"]
        assert body["auth"]["identity"]["password"]["user"]["name"] == "testuser"

    def test_token_reuse_auth(self) -> None:
        """Token auth should GET and set token from config."""
        cfg = AuthConfig(
            identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
            token_id="existing-tok",
        )
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            serialized_catalog = [
                entry.model_dump(by_alias=True)
                for entry in _sample_catalog()
            ]
            return httpx.Response(
                200,
                json={
                    "token": {
                        "user": {"id": "u-1", "domain": {"id": "d-1"}},
                        "catalog": serialized_catalog,
                    },
                },
                headers={"x-subject-token": "existing-tok"},
            )

        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)

        client = ProviderClient(cfg, http_client=http_client)
        client.authenticate()

        assert len(captured) == 1
        assert captured[0].method == "GET"
        assert client.token_id == "existing-tok"


    def test_auth_failure_raises(self) -> None:
        cfg = _password_config()
        resp_401 = httpx.Response(401, text="Unauthorized")
        transport = httpx.MockTransport(lambda req: resp_401)
        http_client = httpx.Client(transport=transport)

        client = ProviderClient(cfg, http_client=http_client)
        with pytest.raises(UnauthorizedError):
            client.authenticate()


# ======================================================================
# ProviderClient: authenticate (v3_auth_with_agency)
# ======================================================================


class TestV3AuthWithAgency:
    """Test password + agency auth flow."""

    def test_agency_auth_two_requests(self) -> None:
        """Agency auth should issue two requests: normal + assume_role."""
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _token_response(
                token_id=f"tok-{call_count}",
            )

        cfg = _password_config(
            agency_name="ag1",
            agency_domain_name="ag_domain",
            delegated_project="proj_deleg",
        )
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)

        client = ProviderClient(cfg, http_client=http_client)
        client.authenticate()

        assert call_count == 2  # first: v3auth, second: assume_role
        assert client.token_id == "tok-2"


# ======================================================================
# ProviderClient: authenticate (aksk)
# ======================================================================


class TestAKSKAuth:
    """Test AK/SK auth flow."""

    def test_aksk_auth_fetches_catalog(self) -> None:
        """AK/SK auth should fetch catalog and set endpoint_locator."""
        cfg = _aksk_config()

        def handler(req: httpx.Request) -> httpx.Response:
            # Should be a signed catalog request
            assert "authorization" in req.headers
            return _catalog_response()

        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)

        client = ProviderClient(cfg, http_client=http_client)
        client.authenticate()

        assert client.token_id == ""  # No token in AK/SK mode
        assert client.project_id == "project-123"
        assert client.endpoint_locator is not None

    def test_aksk_auth_resolves_project_name(self) -> None:
        """When project_name given but no project_id, resolve via API."""
        cfg = _aksk_config(project_id=None, project_name="eu-de")
        call_idx = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_idx
            call_idx += 1
            url = str(req.url)
            if "projects" in url:
                return httpx.Response(
                    200,
                    json={"projects": [{"id": "resolved-proj-id"}]},
                )
            if "catalog" in url:
                return _catalog_response()
            return httpx.Response(404, text="Not found")

        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)

        client = ProviderClient(cfg, http_client=http_client)
        client.authenticate()

        assert client.project_id == "resolved-proj-id"


# ======================================================================
# ProviderClient: request() with retry logic
# ======================================================================


class TestRequest:
    """Test the ``request()`` method with mocked transport."""

    def _authenticated_client(
        self, handler: Any,
    ) -> ProviderClient:
        """Create an already-authenticated client with a mock transport."""
        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "test-token"
        return client

    def test_successful_get(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "ok"})

        client = self._authenticated_client(handler)
        resp = client.request("GET", "https://api.example.com/resource")

        assert resp.status_code == 200
        assert resp.json() == {"result": "ok"}

    def test_auth_header_set(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        client = self._authenticated_client(handler)
        client.request("GET", "https://api.example.com/resource")

        assert captured[0].headers["x-auth-token"] == "test-token"

    def test_post_with_json(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(201, json={"id": "new-1"})

        client = self._authenticated_client(handler)
        resp = client.request(
            "POST",
            "https://api.example.com/resource",
            json={"name": "test"},
        )

        assert resp.status_code == 201
        body = json.loads(captured[0].content)
        assert body["name"] == "test"

    def test_400_raises_bad_request(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="Bad request body")

        client = self._authenticated_client(handler)
        with pytest.raises(BadRequestError) as exc_info:
            client.request("GET", "https://api.example.com/resource")
        assert "Bad request body" in str(exc_info.value)

    def test_404_raises_not_found(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not found")

        client = self._authenticated_client(handler)
        with pytest.raises(NotFoundError):
            client.request("GET", "https://api.example.com/missing")

    def test_500_raises_internal_server_error(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server error")

        client = self._authenticated_client(handler)
        with pytest.raises(InternalServerError):
            client.request("GET", "https://api.example.com/broken")


class TestRequestRetry:
    """Test retry logic on 401, 429, 502, 504."""

    def test_401_triggers_reauth_and_retry(self) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(401, text="Unauthorized")
            return httpx.Response(200, json={"ok": True})

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "old-token"

        def fake_authenticate() -> None:
            client.token_id = "new-token"

        client.authenticate = fake_authenticate

        resp = client.request("GET", "https://api.example.com/resource")

        assert resp.status_code == 200
        assert call_count == 2
        assert client.token_id == "new-token"

    def test_401_without_reauth_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="Unauthorized")

        cfg = _password_config()
        cfg = cfg.model_copy(update={"allow_reauth": False})
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "tok"

        with pytest.raises(UnauthorizedError):
            client.request("GET", "https://api.example.com/resource")

    def test_401_reauth_failure_raises_reauth_error(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="Unauthorized")

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "tok"

        def bad_reauth() -> None:
            raise RuntimeError("reauth failed")

        client.authenticate = bad_reauth

        with pytest.raises(ReauthError):
            client.request("GET", "https://api.example.com/resource")

    @patch("sdk.core.provider.time.sleep", return_value=None)
    def test_429_backoff_retry(self, mock_sleep: Any) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(429, text="Rate limited")
            return httpx.Response(200, json={"ok": True})

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "tok"

        resp = client.request("GET", "https://api.example.com/resource")

        assert resp.status_code == 200
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("sdk.core.provider.time.sleep", return_value=None)
    def test_429_exhausts_retries(self, mock_sleep: Any) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="Rate limited")

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(
            cfg, http_client=http_client, max_backoff_retries=2,
        )
        client.token_id = "tok"

        with pytest.raises(TooManyRequestsError):
            client.request("GET", "https://api.example.com/resource")

    @patch("sdk.core.provider.time.sleep", return_value=None)
    def test_502_gateway_retry(self, mock_sleep: Any) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(502, text="Bad Gateway")
            return httpx.Response(200, json={"ok": True})

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "tok"

        resp = client.request("GET", "https://api.example.com/resource")

        assert resp.status_code == 200
        assert call_count == 2

    @patch("sdk.core.provider.time.sleep", return_value=None)
    def test_504_gateway_retry(self, mock_sleep: Any) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(504, text="Gateway Timeout")
            return httpx.Response(200, json={"ok": True})

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "tok"

        resp = client.request("GET", "https://api.example.com/resource")

        assert resp.status_code == 200
        assert call_count == 2


class TestRequestAKSKSigning:
    """Test that AK/SK requests are signed."""

    def test_aksk_request_has_authorization(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        cfg = _aksk_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.project_id = "proj-123"

        client.request("GET", "https://ecs.eu-de.otc.t-systems.com/v2.1/servers")

        req = captured[0]
        assert "authorization" in req.headers
        assert "SDK-HMAC-SHA256" in req.headers["authorization"]
        assert "x-project-id" in req.headers

    def test_aksk_request_with_domain_id(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        cfg = _aksk_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.domain_id = "dom-id"

        client.request("GET", "https://ecs.eu-de.otc.t-systems.com/v2.1/servers")

        req = captured[0]
        assert req.headers.get("x-domain-id") == "dom-id"
        assert "x-project-id" not in req.headers  # domain_id present → no project_id

    def test_aksk_request_with_security_token(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        cfg = _aksk_config(security_token="temp-sec-tok")
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.project_id = "proj-123"

        client.request("GET", "https://ecs.eu-de.otc.t-systems.com/v2.1/servers")

        req = captured[0]
        assert req.headers.get("x-security-token") == "temp-sec-tok"


# ======================================================================
# ProviderClient: custom ok_codes
# ======================================================================


class TestCustomOkCodes:
    """Test custom ok_codes parameter."""

    def test_custom_ok_codes_accepted(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(204, text="")

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "tok"

        resp = client.request(
            "POST", "https://api.example.com/action",
            ok_codes=[204],
        )
        assert resp.status_code == 204

    def test_default_post_ok_codes(self) -> None:
        """POST default ok_codes include 201."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={"id": "1"})

        cfg = _password_config()
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        client = ProviderClient(cfg, http_client=http_client)
        client.token_id = "tok"

        resp = client.request("POST", "https://api.example.com/resource")
        assert resp.status_code == 201


# ======================================================================
# SecretStr compatibility
# ======================================================================


class TestSecretStrCompatibility:
    """Verify provider works when AuthConfig uses SecretStr fields."""

    def test_secret_value_with_str(self) -> None:
        from sdk.core.provider import _secret_value
        assert _secret_value("plain") == "plain"

    def test_secret_value_with_secret_str(self) -> None:
        from pydantic import SecretStr
        from sdk.core.provider import _secret_value
        assert _secret_value(SecretStr("hidden")) == "hidden"

    def test_build_body_with_secret_password(self) -> None:
        """If password is SecretStr, body should contain plain string."""
        from pydantic import SecretStr

        cfg = _password_config()
        # Simulate SecretStr by monkey-patching
        object.__setattr__(cfg, "password", SecretStr("secret"))

        body = _build_v3_auth_body(cfg)
        user = body["auth"]["identity"]["password"]["user"]
        assert user["password"] == "secret"
        assert isinstance(user["password"], str)
