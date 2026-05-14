"""Tests for ``sdk.core.service_client``."""

from __future__ import annotations

import json
from typing import Any
import httpx
import pytest

from sdk.core.auth import AuthConfig
from sdk.core.exceptions import (
    EndpointNotFoundError,
    NotFoundError,
    ServiceNotFoundError,
)
from sdk.core.endpoint import build_endpoint_locator, CatalogEntry
from sdk.core.provider import ProviderClient
from sdk.core.service_client import ServiceClient, _ensure_trailing_slash


# ======================================================================
# Fixtures
# ======================================================================


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
        {
            "type": "network",
            "endpoints": [
                {
                    "interface": "public",
                    "region_id": "eu-de",
                    "url": "https://vpc.eu-de.otc.t-systems.com",
                },
                {
                    "interface": "public",
                    "region_id": "eu-nl",
                    "url": "https://vpc.eu-nl.otc.t-systems.com",
                },
            ],
        },
    ]
    return [CatalogEntry.model_validate(entry) for entry in raw]


def _make_provider(
    handler: Any = None,
    *,
    catalog: list[CatalogEntry] | None = None,
) -> ProviderClient:
    """Create an authenticated ProviderClient with mock transport."""
    if handler is None:
        handler = lambda req: httpx.Response(200, json={})

    cfg = AuthConfig(
        identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
        username="user",
        password="pass",
        domain_name="dom",
    )
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    provider = ProviderClient(cfg, http_client=http_client)
    provider.token_id = "test-token"
    provider.region_id = "eu-de"

    cat = catalog if catalog is not None else _sample_catalog()
    provider.endpoint_locator = build_endpoint_locator(cat, "eu-de")

    return provider


# ======================================================================
# _ensure_trailing_slash
# ======================================================================


class TestEnsureTrailingSlash:
    def test_adds_slash(self) -> None:
        assert _ensure_trailing_slash("https://example.com") == "https://example.com/"

    def test_keeps_existing_slash(self) -> None:
        assert _ensure_trailing_slash("https://example.com/") == "https://example.com/"

    def test_with_path(self) -> None:
        assert _ensure_trailing_slash("https://example.com/v2.1") == "https://example.com/v2.1/"


# ======================================================================
# Construction & endpoint resolution
# ======================================================================


class TestServiceClientConstruction:
    """Test endpoint resolution and attribute setup."""

    def test_resolves_compute_from_catalog(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(provider, "compute")
        assert sc.endpoint == "https://ecs.eu-de.otc.t-systems.com/v2.1/"

    def test_resolves_dns_from_catalog(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(provider, "dns")
        assert sc.endpoint == "https://dns.eu-de.otc.t-systems.com/v2/"

    def test_endpoint_override_bypasses_catalog(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(
            provider, "compute",
            endpoint_override="https://custom.example.com/v2",
        )
        assert sc.endpoint == "https://custom.example.com/v2/"
        assert sc.resource_base == "https://custom.example.com/v2/"

    def test_resource_base_override(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(
            provider, "compute",
            resource_base="https://ecs.eu-de.otc.t-systems.com/v2.1/proj-123",
        )
        assert sc.resource_base == "https://ecs.eu-de.otc.t-systems.com/v2.1/proj-123/"
        assert sc.endpoint == "https://ecs.eu-de.otc.t-systems.com/v2.1/"

    def test_resource_base_defaults_to_endpoint(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(provider, "compute")
        assert sc.resource_base == sc.endpoint

    def test_service_not_found_raises(self) -> None:
        provider = _make_provider()
        with pytest.raises(ServiceNotFoundError):
            ServiceClient(provider, "nonexistent_service")

    def test_endpoint_not_found_wrong_region(self) -> None:
        raw = [
            {
                "type": "compute",
                "endpoints": [
                    {
                        "interface": "public",
                        "region_id": "eu-de",
                        "url": "https://ecs.eu-de.example.com/v2.1",
                    },
                ],
            },
        ]
        catalog = [CatalogEntry.model_validate(entry) for entry in raw]
        provider = _make_provider(catalog=catalog)
        with pytest.raises(EndpointNotFoundError):
            ServiceClient(provider, "compute", region="us-east-1")

    def test_region_override(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(provider, "network", region="eu-nl")
        assert "eu-nl" in sc.endpoint

    def test_extra_headers_stored(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(
            provider, "compute",
            extra_headers={"X-Custom": "value"},
        )
        assert sc.extra_headers == {"X-Custom": "value"}

    def test_no_endpoint_locator_gives_empty(self) -> None:
        """If provider has no locator, endpoint is empty string."""
        provider = _make_provider()
        provider.endpoint_locator = None
        sc = ServiceClient(provider, "compute")
        assert sc.endpoint == ""

    def test_no_service_type_gives_empty(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(provider)
        assert sc.endpoint == ""


# ======================================================================
# service_url
# ======================================================================


class TestServiceUrl:
    """Test URL construction."""

    def test_single_part(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(provider, "compute")
        url = sc.service_url("servers")
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/servers"

    def test_multiple_parts(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(provider, "compute")
        url = sc.service_url("servers", "abc-123", "action")
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/servers/abc-123/action"

    def test_no_parts(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(provider, "compute")
        url = sc.service_url()
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/"

    def test_with_custom_resource_base(self) -> None:
        provider = _make_provider()
        sc = ServiceClient(
            provider, "compute",
            resource_base="https://ecs.eu-de.otc.t-systems.com/v2.1/proj-123",
        )
        url = sc.service_url("servers")
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/proj-123/servers"


# ======================================================================
# HTTP methods
# ======================================================================


class TestHttpMethods:
    """Test that convenience methods delegate correctly to provider."""

    def _service_client(self, handler: Any) -> ServiceClient:
        """Build a ServiceClient with mocked transport."""
        provider = _make_provider(handler)
        return ServiceClient(
            provider, endpoint_override="https://api.example.com/v1",
        )

    def test_get(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={"items": []})

        sc = self._service_client(handler)
        resp = sc.get("resources")

        assert resp.status_code == 200
        assert len(captured) == 1
        assert captured[0].method == "GET"
        assert str(captured[0].url) == "https://api.example.com/v1/resources"

    def test_post_with_json(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(201, json={"id": "new-1"})

        sc = self._service_client(handler)
        resp = sc.post("resources", json={"name": "test"})

        assert resp.status_code == 201
        body = json.loads(captured[0].content)
        assert body["name"] == "test"

    def test_put(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={"updated": True})

        sc = self._service_client(handler)
        resp = sc.put("resources/123", json={"name": "updated"})

        assert captured[0].method == "PUT"
        assert "resources/123" in str(captured[0].url)

    def test_patch(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        sc = self._service_client(handler)
        sc.patch("resources/123", json={"field": "val"})

        assert captured[0].method == "PATCH"

    def test_delete(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(204, text="")

        sc = self._service_client(handler)
        resp = sc.delete("resources/123")

        assert resp.status_code == 204
        assert captured[0].method == "DELETE"

    def test_delete_with_body(self) -> None:
        """Go SDK has DeleteWithBody — our delete() supports json param."""
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        sc = self._service_client(handler)
        sc.delete("resources/batch", json={"ids": ["a", "b"]})

        body = json.loads(captured[0].content)
        assert body["ids"] == ["a", "b"]

    def test_head(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(204, text="")

        sc = self._service_client(handler)
        sc.head("resources/123", ok_codes=[204])

        assert captured[0].method == "HEAD"

    def test_error_propagates(self) -> None:
        """Non-ok status from provider should raise HttpError."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not found")

        sc = self._service_client(handler)
        with pytest.raises(NotFoundError):
            sc.get("missing")


# ======================================================================
# Headers
# ======================================================================


class TestHeaders:
    """Test header merging between service and request levels."""

    def test_extra_headers_sent(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = _make_provider(handler)
        sc = ServiceClient(
            provider,
            endpoint_override="https://api.example.com/v1",
            extra_headers={"X-Service-Level": "important"},
        )
        sc.get("stuff")

        assert captured[0].headers["x-service-level"] == "important"

    def test_per_request_headers_override(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = _make_provider(handler)
        sc = ServiceClient(
            provider,
            endpoint_override="https://api.example.com/v1",
            extra_headers={"X-Level": "service"},
        )
        sc.get("stuff", headers={"X-Level": "request"})

        # Per-request header wins
        assert captured[0].headers["x-level"] == "request"

    def test_auth_header_present(self) -> None:
        """Token auth header should be set by provider."""
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = _make_provider(handler)
        sc = ServiceClient(
            provider, endpoint_override="https://api.example.com/v1",
        )
        sc.get("stuff")

        assert captured[0].headers["x-auth-token"] == "test-token"


# ======================================================================
# Custom ok_codes
# ======================================================================


class TestCustomOkCodes:
    def test_custom_ok_codes(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(204, text="")

        provider = _make_provider(handler)
        sc = ServiceClient(
            provider, endpoint_override="https://api.example.com/v1",
        )
        resp = sc.post("action", ok_codes=[204])
        assert resp.status_code == 204
