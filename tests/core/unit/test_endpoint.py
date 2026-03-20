"""Tests for ``sdk.core.endpoint``."""

from __future__ import annotations

from typing import Any

import pytest

from sdk.core.endpoint import (
    Availability,
    EndpointOpts,
    build_endpoint_locator,
    find_endpoint,
    _normalize_url,
)
from sdk.core.exceptions import EndpointNotFoundError, ServiceNotFoundError


# ======================================================================
# Test data
# ======================================================================


def _sample_catalog() -> list[dict[str, Any]]:
    return [
        {
            "type": "compute",
            "name": "nova",
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
                {
                    "interface": "public",
                    "region_id": "eu-nl",
                    "url": "https://ecs.eu-nl.otc.t-systems.com/v2.1",
                },
            ],
        },
        {
            "type": "dns",
            "name": "dns",
            "endpoints": [
                {
                    "interface": "public",
                    "region_id": "eu-de",
                    "url": "https://dns.eu-de.otc.t-systems.com/v2",
                },
            ],
        },
        {
            "type": "identity",
            "name": "keystone",
            "endpoints": [
                {
                    "interface": "public",
                    "region_id": "*",
                    "url": "https://iam.otc.t-systems.com/v3",
                },
                {
                    "interface": "admin",
                    "region_id": "*",
                    "url": "https://iam-admin.otc.t-systems.com/v3",
                },
            ],
        },
    ]


# ======================================================================
# _normalize_url
# ======================================================================


class TestNormalizeUrl:
    def test_adds_slash(self) -> None:
        assert _normalize_url("https://example.com") == "https://example.com/"

    def test_keeps_slash(self) -> None:
        assert _normalize_url("https://example.com/") == "https://example.com/"

    def test_with_path(self) -> None:
        assert _normalize_url("https://example.com/v2.1") == "https://example.com/v2.1/"


# ======================================================================
# EndpointOpts
# ======================================================================


class TestEndpointOpts:
    def test_defaults(self) -> None:
        opts = EndpointOpts(service_type="compute")
        assert opts.service_type == "compute"
        assert opts.name == ""
        assert opts.region == ""
        assert opts.availability == Availability.PUBLIC

    def test_frozen(self) -> None:
        opts = EndpointOpts(service_type="compute")
        with pytest.raises(AttributeError):
            opts.region = "eu-de"  # type: ignore[misc]

    def test_all_fields(self) -> None:
        opts = EndpointOpts(
            service_type="compute",
            name="nova",
            region="eu-de",
            availability=Availability.INTERNAL,
        )
        assert opts.name == "nova"
        assert opts.region == "eu-de"
        assert opts.availability == Availability.INTERNAL


# ======================================================================
# find_endpoint
# ======================================================================


class TestFindEndpoint:
    """Test direct catalog search."""

    def test_finds_public_compute_eu_de(self) -> None:
        catalog = _sample_catalog()
        opts = EndpointOpts(service_type="compute", region="eu-de")
        url = find_endpoint(catalog, opts)
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/"

    def test_finds_public_compute_eu_nl(self) -> None:
        catalog = _sample_catalog()
        opts = EndpointOpts(service_type="compute", region="eu-nl")
        url = find_endpoint(catalog, opts)
        assert url == "https://ecs.eu-nl.otc.t-systems.com/v2.1/"

    def test_finds_internal_endpoint(self) -> None:
        catalog = _sample_catalog()
        opts = EndpointOpts(
            service_type="compute",
            region="eu-de",
            availability=Availability.INTERNAL,
        )
        url = find_endpoint(catalog, opts)
        assert url == "https://ecs-internal.eu-de.otc.t-systems.com/v2.1/"

    def test_finds_dns(self) -> None:
        catalog = _sample_catalog()
        opts = EndpointOpts(service_type="dns", region="eu-de")
        url = find_endpoint(catalog, opts)
        assert url == "https://dns.eu-de.otc.t-systems.com/v2/"

    def test_wildcard_region_fallback(self) -> None:
        """Wildcard ``*`` region used when no exact match."""
        catalog = _sample_catalog()
        opts = EndpointOpts(service_type="identity", region="eu-de")
        url = find_endpoint(catalog, opts)
        assert url == "https://iam.otc.t-systems.com/v3/"

    def test_wildcard_admin(self) -> None:
        catalog = _sample_catalog()
        opts = EndpointOpts(
            service_type="identity",
            availability=Availability.ADMIN,
        )
        url = find_endpoint(catalog, opts)
        assert url == "https://iam-admin.otc.t-systems.com/v3/"

    def test_no_region_matches_first(self) -> None:
        """Empty region returns the first matching endpoint."""
        catalog = _sample_catalog()
        opts = EndpointOpts(service_type="compute")
        url = find_endpoint(catalog, opts)
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/"

    def test_name_filter(self) -> None:
        catalog = _sample_catalog()
        opts = EndpointOpts(
            service_type="compute", name="nova", region="eu-de",
        )
        url = find_endpoint(catalog, opts)
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/"

    def test_name_filter_no_match(self) -> None:
        """Wrong name on correct type → ServiceNotFoundError."""
        catalog = _sample_catalog()
        opts = EndpointOpts(
            service_type="compute", name="wrong_name", region="eu-de",
        )
        with pytest.raises(ServiceNotFoundError):
            find_endpoint(catalog, opts)

    def test_service_not_found(self) -> None:
        catalog = _sample_catalog()
        opts = EndpointOpts(service_type="nonexistent")
        with pytest.raises(ServiceNotFoundError):
            find_endpoint(catalog, opts)

    def test_endpoint_not_found_wrong_region(self) -> None:
        catalog = _sample_catalog()
        opts = EndpointOpts(service_type="dns", region="us-west-1")
        with pytest.raises(EndpointNotFoundError):
            find_endpoint(catalog, opts)

    def test_endpoint_not_found_wrong_availability(self) -> None:
        """DNS has only public, asking for admin → EndpointNotFoundError."""
        catalog = _sample_catalog()
        opts = EndpointOpts(
            service_type="dns",
            region="eu-de",
            availability=Availability.ADMIN,
        )
        with pytest.raises(EndpointNotFoundError):
            find_endpoint(catalog, opts)

    def test_empty_catalog(self) -> None:
        opts = EndpointOpts(service_type="compute")
        with pytest.raises(ServiceNotFoundError):
            find_endpoint([], opts)

    def test_uses_region_field_fallback(self) -> None:
        """Some catalogs use ``region`` instead of ``region_id``."""
        catalog = [
            {
                "type": "object-store",
                "endpoints": [
                    {
                        "interface": "public",
                        "region": "eu-de",
                        "url": "https://obs.eu-de.example.com",
                    },
                ],
            },
        ]
        opts = EndpointOpts(service_type="object-store", region="eu-de")
        url = find_endpoint(catalog, opts)
        assert url == "https://obs.eu-de.example.com/"


# ======================================================================
# build_endpoint_locator
# ======================================================================


class TestBuildEndpointLocator:
    """Test the locator closure factory."""

    def test_locator_uses_default_region(self) -> None:
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog, default_region="eu-de")

        opts = EndpointOpts(service_type="compute")
        url = locator(opts)
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/"

    def test_locator_region_in_opts_overrides_default(self) -> None:
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog, default_region="eu-de")

        opts = EndpointOpts(service_type="compute", region="eu-nl")
        url = locator(opts)
        assert url == "https://ecs.eu-nl.otc.t-systems.com/v2.1/"

    def test_locator_propagates_service_not_found(self) -> None:
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog, default_region="eu-de")

        opts = EndpointOpts(service_type="nope")
        with pytest.raises(ServiceNotFoundError):
            locator(opts)

    def test_locator_propagates_endpoint_not_found(self) -> None:
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog, default_region="eu-de")

        opts = EndpointOpts(service_type="dns", region="us-east-1")
        with pytest.raises(EndpointNotFoundError):
            locator(opts)

    def test_locator_no_default_region(self) -> None:
        """Without default region, opts.region is used as-is."""
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog)

        opts = EndpointOpts(service_type="compute", region="eu-nl")
        url = locator(opts)
        assert url == "https://ecs.eu-nl.otc.t-systems.com/v2.1/"

    def test_locator_no_region_at_all_returns_first(self) -> None:
        """No default, no opts.region → returns first public endpoint."""
        catalog = _sample_catalog()
        locator = build_endpoint_locator(catalog)

        opts = EndpointOpts(service_type="compute")
        url = locator(opts)
        assert url == "https://ecs.eu-de.otc.t-systems.com/v2.1/"
