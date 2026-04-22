"""Functional tests for HTTP headers merging.

Verifies that the full pipeline (ProviderClient → ServiceClient →
HTTP request) correctly merges headers from all layers:
default, service-level, per-request, and auth.

Uses httpx.MockTransport to capture actual outgoing requests.
"""

from __future__ import annotations

import httpx

from sdk.core.service_client import ServiceClient

from .conftest import make_provider


class TestDefaultHeaders:
    """Default headers (Accept, User-Agent) are always present."""

    def test_accept_header(self):
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")
        client.get("test-path")

        assert "application/json" in captured[0].headers["accept"]

    def test_user_agent_header(self):
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")
        client.get("test-path")

        assert "user-agent" in captured[0].headers

    def test_content_type_on_json_body(self):
        """POST with json body sets Content-Type: application/json."""
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        client.post("vpcs", json={"vpc": {"name": "test"}})

        assert "application/json" in captured[0].headers["content-type"]


class TestServiceHeaders:
    """ServiceClient.extra_headers arrive in the final request."""

    def test_extra_headers_sent(self):
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        client.extra_headers["X-Language"] = "en-us"
        client.extra_headers["X-Custom-Service"] = "my-value"

        client.get("test-path")

        assert captured[0].headers["x-language"] == "en-us"
        assert captured[0].headers["x-custom-service"] == "my-value"


class TestPerRequestHeaders:
    """Per-request headers override service-level headers."""

    def test_override_service_header(self):
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")
        client.extra_headers["X-Language"] = "en-us"

        client.get("test-path", headers={"X-Language": "de-de"})

        assert captured[0].headers["x-language"] == "de-de"


class TestAuthHeaders:
    """Auth headers are injected into the request."""

    def test_aksk_authorization_present(self):
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")
        client.get("test-path")

        assert "authorization" in captured[0].headers


class TestAllHeadersCombined:
    """All header layers work together in a single request."""

    def test_default_service_request_and_auth(self):
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")
        client.extra_headers["X-Custom"] = "service-level"

        client.get("test-path", headers={"X-Request-Id": "req-123"})

        req = captured[0]
        assert "application/json" in captured[0].headers["accept"]
        assert "user-agent" in req.headers
        assert req.headers["x-custom"] == "service-level"
        assert req.headers["x-request-id"] == "req-123"
        assert "authorization" in req.headers
