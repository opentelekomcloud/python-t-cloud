"""Service client — per-service wrapper over ``ProviderClient``.

Mirrors the Go SDK's ``ServiceClient`` struct. Each OTC service
(compute, DNS, CCE, etc.) gets its own ``ServiceClient`` with
a resolved endpoint and convenience HTTP methods.

A ``ServiceClient`` delegates all HTTP work to the underlying
``ProviderClient``, adding service-level headers and URL
construction via ``service_url()``.

Example::

    from sdk.core.provider import ProviderClient
    from sdk.core.service_client import ServiceClient

    provider = ProviderClient(auth_config)
    provider.authenticate()

    # Resolve endpoint from catalog
    compute = ServiceClient(
        provider,
        service_type="compute",
        region="eu-de",
    )
    resp = compute.get("servers/detail")

    # With project-scoped resource base
    cce = ServiceClient(
        provider,
        service_type="ccev2.0",
        resource_base=endpoint + "api/v1/projects/" + project_id + "/",
    )
    url = cce.service_url("clusters")
"""

from __future__ import annotations

from typing import Any

import httpx

from sdk.core.endpoint import EndpointOpts
from sdk.core.provider import ProviderClient


class ServiceClient:
    """Client for a specific OTC service API.

    Wraps a ``ProviderClient`` and holds the resolved service
    endpoint. Provides ``service_url()`` for building resource URLs
    and convenience HTTP methods that mirror the Go SDK's
    ``Get``, ``Post``, ``Put``, ``Patch``, ``Delete``, ``Head``.

    Args:
        provider: Authenticated ``ProviderClient``.
        service_type: Catalog service type (e.g. ``compute``, ``dns``).
        region: Region override. Falls back to ``provider.region_id``.
        endpoint_override: Bypass catalog lookup and use this URL
            directly.
        resource_base: Custom base URL for resource paths. Some
            services need a project-scoped base that differs from the
            catalog endpoint (see CCE example above). If not set,
            ``endpoint`` is used.
        extra_headers: Headers merged into every request from this
            service client (Go SDK ``MoreHeaders``).

    Attributes:
        provider: Reference to the parent ``ProviderClient``.
        endpoint: Resolved service endpoint URL (always ends with ``/``).
        resource_base: Base URL for ``service_url()`` path building.
        service_type: Service type string.
        extra_headers: Service-wide headers.
    """

    def __init__(
        self,
        provider: ProviderClient,
        service_type: str = "",
        *,
        region: str = "",
        endpoint_override: str = "",
        resource_base: str = "",
        extra_headers: dict[str, str] | None = None,
        microversion: str = "",
    ) -> None:
        self.provider = provider
        self.service_type = service_type
        self.extra_headers: dict[str, str] = extra_headers or {}
        self.microversion = microversion
        # Resolve endpoint
        if endpoint_override:
            self.endpoint = _ensure_trailing_slash(endpoint_override)
        elif provider.endpoint_locator and service_type:
            opts = EndpointOpts(service_type=service_type, region=region)
            self.endpoint = provider.endpoint_locator(opts)
        else:
            self.endpoint = ""

        # Resource base — defaults to endpoint
        self.resource_base = (
            _ensure_trailing_slash(resource_base)
            if resource_base
            else self.endpoint
        )

    # ------------------------------------------------------------------
    # URL building
    # ------------------------------------------------------------------

    def service_url(self, *parts: str) -> str:
        """Build a full URL from the resource base and path segments.

        Joins ``resource_base`` with the given path parts using ``/``.

        Example::

            client.service_url("servers", server_id, "action")
            # → "https://ecs.eu-de.../v2.1/servers/{id}/action"

        Args:
            *parts: URL path segments to join.

        Returns:
            Full URL string.
        """
        return self.resource_base + "/".join(parts)

    # ------------------------------------------------------------------
    # HTTP convenience methods
    # ------------------------------------------------------------------

    def get(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        ok_codes: list[int] | None = None,
    ) -> httpx.Response:
        """GET request. Default ok: 200.

        Args:
            path: Relative path appended to ``resource_base``.
            headers: Extra request headers.
            ok_codes: Acceptable status codes.

        Returns:
            httpx.Response.
        """
        return self._request("GET", path, headers=headers, ok_codes=ok_codes)

    def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        ok_codes: list[int] | None = None,
    ) -> httpx.Response:
        """POST request. Default ok: 200, 201, 202.

        Args:
            path: Relative path.
            json: JSON-serializable body.
            content: Raw bytes body.
            headers: Extra request headers.
            ok_codes: Acceptable status codes.

        Returns:
            httpx.Response.
        """
        return self._request(
            "POST", path, json=json, content=content,
            headers=headers, ok_codes=ok_codes,
        )

    def put(
        self,
        path: str,
        *,
        json: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        ok_codes: list[int] | None = None,
    ) -> httpx.Response:
        """PUT request. Default ok: 200, 201, 202.

        Args:
            path: Relative path.
            json: JSON-serializable body.
            content: Raw bytes body.
            headers: Extra request headers.
            ok_codes: Acceptable status codes.

        Returns:
            httpx.Response.
        """
        return self._request(
            "PUT", path, json=json, content=content,
            headers=headers, ok_codes=ok_codes,
        )

    def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        ok_codes: list[int] | None = None,
    ) -> httpx.Response:
        """PATCH request. Default ok: 200, 204.

        Args:
            path: Relative path.
            json: JSON-serializable body.
            content: Raw bytes body.
            headers: Extra request headers.
            ok_codes: Acceptable status codes.

        Returns:
            httpx.Response.
        """
        return self._request(
            "PATCH", path, json=json, content=content,
            headers=headers, ok_codes=ok_codes,
        )

    def delete(
        self,
        path: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
        ok_codes: list[int] | None = None,
    ) -> httpx.Response:
        """DELETE request. Default ok: 200, 202, 204.

        Supports optional JSON body for APIs that require
        delete-with-body (Go SDK ``DeleteWithBody``).

        Args:
            path: Relative path.
            json: Optional JSON body.
            headers: Extra request headers.
            ok_codes: Acceptable status codes.

        Returns:
            httpx.Response.
        """
        return self._request(
            "DELETE", path, json=json,
            headers=headers, ok_codes=ok_codes,
        )

    def head(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        ok_codes: list[int] | None = None,
    ) -> httpx.Response:
        """HEAD request. Default ok: 204, 206.

        Args:
            path: Relative path.
            headers: Extra request headers.
            ok_codes: Acceptable status codes.

        Returns:
            httpx.Response.
        """
        return self._request("HEAD", path, headers=headers, ok_codes=ok_codes)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_microversion_header(self, headers: dict[str, str]) -> None:
        """Set microversion headers based on service type.

        Corresponds to Go SDK's ``setMicroversionHeader``.
        """
        if not self.microversion:
            return

        mv_header_map = {
            "compute": "X-OpenStack-Nova-API-Version",
            "sharev2": "X-OpenStack-Manila-API-Version",
            "volume": "X-OpenStack-Volume-API-Version",
        }

        specific = mv_header_map.get(self.service_type)
        if specific:
            headers[specific] = self.microversion

        if self.service_type:
            headers["OpenStack-API-Version"] = (
                f"{self.service_type} {self.microversion}"
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        ok_codes: list[int] | None = None,
    ) -> httpx.Response:
        """Build full URL, merge service headers, delegate to provider.

        Args:
            method: HTTP method.
            path: Relative resource path.
            json: JSON body.
            content: Raw body.
            headers: Per-request headers.
            ok_codes: Acceptable status codes.

        Returns:
            httpx.Response.
        """
        url = self.service_url(path)
        merged: dict[str, str] = {**self.extra_headers}
        if headers:
            merged.update(headers)
        self._set_microversion_header(merged)
        return self.provider.request(
            method,
            url,
            json=json,
            content=content,
            headers=merged or None,
            ok_codes=ok_codes,
        )


def _ensure_trailing_slash(url: str) -> str:
    """Ensure a URL ends with ``/``."""
    return url if url.endswith("/") else url + "/"
