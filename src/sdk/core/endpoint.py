"""Endpoint discovery from the IAM service catalog.

Extracts the endpoint lookup logic into a reusable module.

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
from enum import StrEnum

from pydantic import BaseModel, Field, AliasChoices

from sdk.core.exceptions import EndpointNotFoundError, ServiceNotFoundError


class Availability(StrEnum):
    """Endpoint visibility level.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    ADMIN = "admin"


class EndpointOpts(BaseModel):
    """Search criteria for locating a service endpoint.
    At minimum, ``service_type`` must be provided.

    Attributes:
        service_type: Catalog service type (e.g. ``compute``, ``dns``).
        name: Optional service name filter (e.g. ``nova``).
        region: Region to match. Empty means accept any region.
        availability: Endpoint interface visibility.
    """
    model_config = {"frozen": True}

    service_type: str
    name: str = ""
    region: str = ""
    availability: Availability = Availability.PUBLIC


class CatalogEndpoint(BaseModel):
    interface: str
    region_id: str = Field(default="",
                           validation_alias=AliasChoices("region_id", "region")
                           )
    url: str


class CatalogEntry(BaseModel):
    type: str
    name: str = ""
    endpoints: list[CatalogEndpoint] = Field(default_factory=list)


def find_endpoint(
    catalog: list[CatalogEntry],
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
        if entry.type != opts.service_type:
            continue
        if opts.name and entry.name != opts.name:
            continue

        service_found = True

        for ep in entry.endpoints:
            if ep.interface != opts.availability:
                continue

            if not ep.url:
                continue

            url = _normalize_url(ep.url)

            if not opts.region or ep.region_id == opts.region:
                matched.append(url)
            elif ep.region_id == "*":
                wildcard.append(url)

    if not matched:
        matched = wildcard

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
    catalog: list[CatalogEntry],
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
            opts = opts.model_copy(update={"region": default_region})
        return find_endpoint(catalog, opts)

    return locator


def _normalize_url(url: str) -> str:
    """Ensure URL ends with ``/``."""
    return url if url.endswith("/") else url + "/"
