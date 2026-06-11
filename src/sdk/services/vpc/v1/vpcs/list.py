"""List VPCs with auto-pagination."""

from __future__ import annotations

from collections.abc import Iterator

from sdk.core.opts import BaseQueryOpts
from sdk.core.pagination import marker_paginate
from sdk.core.service_client import ServiceClient

from .common import _BASE_PATH, Vpc


class ListVpcsOpts(BaseQueryOpts):
    """Query parameters for listing VPCs."""

    id: str | None = None
    limit: int | None = None
    marker: str | None = None
    enterprise_project_id: str | None = None


def list(  # noqa: A001 - shadows builtin intentionally; matches Go SDK style
    client: ServiceClient,
    opts: ListVpcsOpts | None = None,
) -> Iterator[Vpc]:
    """List VPCs with auto-pagination.

    ``GET /v1/{project_id}/vpcs``

    Uses marker-based pagination. Yields VPC objects one by one,
    fetching next pages automatically.
    """
    params = opts.to_query_params() if opts else None
    limit = opts.limit if (opts and opts.limit and opts.limit > 0) else 0

    return marker_paginate(
        client=client,
        path=_BASE_PATH,
        items_key="vpcs",
        model=Vpc,
        marker_key="id",
        limit=limit,
        params=params,
    )
