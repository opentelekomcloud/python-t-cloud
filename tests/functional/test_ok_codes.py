"""Functional tests for ok_codes error handling.

Verifies that the full pipeline (ProviderClient → ServiceClient →
HTTP request) correctly raises HttpError when the response status
code is not in the expected ok_codes list.

Uses httpx.MockTransport to simulate server responses.
"""

from __future__ import annotations

import httpx
import pytest

from sdk.core.exceptions import HttpError
from sdk.core.service_client import ServiceClient

from .conftest import make_provider


class TestUnexpectedStatusRaises:
    """Non-ok status codes must raise HttpError."""

    def test_500_raises(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        with pytest.raises(HttpError) as exc_info:
            client.get("test-path")

        assert exc_info.value.status_code == 500

    def test_404_raises(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": {"message": "not found"}})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        with pytest.raises(HttpError) as exc_info:
            client.get("vpcs/nonexistent-id")

        assert exc_info.value.status_code == 404

    def test_403_raises(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "forbidden"})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        with pytest.raises(HttpError) as exc_info:
            client.get("test-path")

        assert exc_info.value.status_code == 403


class TestCustomOkCodes:
    """Custom ok_codes override default behavior."""

    def test_custom_ok_codes_accepted(self):
        """ok_codes=[204] allows 204 on GET (normally only 200)."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        resp = client.get("test-path", ok_codes=[204])
        assert resp.status_code == 204

    def test_custom_ok_codes_rejects_unexpected(self):
        """ok_codes=[200] rejects 201."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        with pytest.raises(HttpError) as exc_info:
            client.get("test-path", ok_codes=[200])

        assert exc_info.value.status_code == 201


class TestDefaultOkCodesPerMethod:
    """Each HTTP method has its own default ok_codes."""

    def test_post_accepts_201(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={"vpc": {}})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        resp = client.post("vpcs", json={"vpc": {}})
        assert resp.status_code == 201

    def test_delete_accepts_204(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        resp = client.delete("vpcs/some-id")
        assert resp.status_code == 204

    def test_put_accepts_200(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"vpc": {}})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        resp = client.put("vpcs/some-id", json={"vpc": {}})
        assert resp.status_code == 200


class TestErrorContainsDebugInfo:
    """HttpError must contain enough info for debugging."""

    def test_status_code_in_error(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"error": "conflict"})

        provider = make_provider(handler)
        client = ServiceClient(provider, "vpc")

        with pytest.raises(HttpError) as exc_info:
            client.post("vpcs", json={})

        assert exc_info.value.status_code == 409
