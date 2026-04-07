"""Endpoint discovery from the IAM service catalog.

Mirrors the Go SDK's ``EndpointOpts``, ``EndpointLocator`` type,
and ``V3EndpointURL`` function. Extracts the endpoint lookup logic
into a reusable module.

The ``EndpointOpts`` dataclass specifies search criteria, and
``find_endpoint()`` searches a service catalog for a matching URL.
``build_endpoint_locator()`` returns a closure that captures the
catalog and default region, ready to be stored on ``ProviderClient``.

Example::

    from sdk.core.endpoint import EndpointOpts, find_endpoint

    catalog = [...]  # from IAM auth response
    opts = EndpointOpts(service_type="compute", region="eu-de")
    url = find_endpoint(catalog, opts)
    # → "https://ecs.eu-de.otc.t-systems.com/v2.1/"
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from sdk.core.exceptions import EndpointNotFoundError, ServiceNotFoundError


class Availability(StrEnum):
    """Endpoint visibility level.

    Mirrors Go SDK's ``Availability`` constants.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    ADMIN = "admin"


@dataclass(frozen=True)
class EndpointOpts:
    """Search criteria for locating a service endpoint.

    Mirrors Go SDK's ``EndpointOpts`` struct. At minimum,
    ``service_type`` must be provided.

    Attributes:
        service_type: Catalog service type (e.g. ``compute``, ``dns``).
        name: Optional service name filter (e.g. ``nova``).
        region: Region to match. Empty means accept any region.
        availability: Endpoint interface visibility.
    """

    service_type: str = ""
    name: str = ""
    region: str = ""
    availability: Availability = Availability.PUBLIC

    def apply_defaults(self, service_type: str) -> EndpointOpts:
        """Return a copy with defaults applied.

        Corresponds to Go SDK's ``EndpointOpts.ApplyDefaults``.
        Sets ``service_type`` if not already set and ensures
        ``availability`` has a value.

        Args:
            service_type: Default service type to use if none
                was provided.

        Returns:
            New ``EndpointOpts`` with defaults filled in.
        """
        return replace(
            self,
            service_type=self.service_type or service_type,
            availability=self.availability or Availability.PUBLIC,
        )


def find_endpoint(
    catalog: list[dict[str, Any]],
    opts: EndpointOpts,
) -> str:
    """Find a single endpoint URL from the service catalog.

    Searches catalog entries for a match on ``service_type``,
    optional ``name``, ``region``, and ``availability``.
    Falls back to wildcard (``*``) region entries if no exact
    match is found.

    Args:
        catalog: Service catalog entries from IAM response.
        opts: Search criteria.

    Returns:
        Endpoint URL string (always ends with ``/``).

    Raises:
        ServiceNotFoundError: No catalog entry matches the type.
        EndpointNotFoundError: Entry found but no endpoint matches
            region/availability.
    """
    matched: list[str] = []
    wildcard: list[str] = []
    service_found = False

    for entry in catalog:
        entry_type = entry.get("type", "")
        entry_name = entry.get("name", "")

        if entry_type != opts.service_type:
            continue
        if opts.name and entry_name != opts.name:
            continue

        service_found = True

        for ep in entry.get("endpoints", []):
            ep_interface = ep.get("interface", "")
            if ep_interface != opts.availability:
                continue

            ep_region = ep.get("region_id", "") or ep.get("region", "")
            url = _normalize_url(ep.get("url", ""))

            if not opts.region or ep_region == opts.region:
                matched.append(url)
            elif ep_region == "*":
                wildcard.append(url)

    # Fall back to wildcard endpoints
    if not matched:
        matched = wildcard

    # Use first match (matches Go SDK behavior)
    if matched:
        return matched[0]

    if not service_found:
        raise ServiceNotFoundError(service=opts.service_type)

    raise EndpointNotFoundError(
        service=opts.service_type, region=opts.region,
    )


EndpointLocator = Callable[[EndpointOpts], str]
"""Callable type that resolves an ``EndpointOpts`` → URL string."""


def build_endpoint_locator(
    catalog: list[dict[str, Any]],
    default_region: str = "",
) -> EndpointLocator:
    """Build an endpoint locator closure from a service catalog.

    Returns a callable that accepts ``EndpointOpts`` (or keyword
    shorthand) and resolves the endpoint URL. If the opts have
    no region set, ``default_region`` is used.

    This is the Python equivalent of the Go SDK pattern where
    ``ProviderClient.EndpointLocator`` is a ``func(EndpointOpts) string``.

    Args:
        catalog: Service catalog from IAM.
        default_region: Fallback region from auth config.

    Returns:
        Callable ``(EndpointOpts) → str``.
    """

    def locator(opts: EndpointOpts) -> str:
        if not opts.region and default_region:
            opts = replace(opts, region=default_region)
        return find_endpoint(catalog, opts)

    return locator


def _normalize_url(url: str) -> str:
    """Ensure URL ends with ``/``."""
    return url if url.endswith("/") else url + "/"
