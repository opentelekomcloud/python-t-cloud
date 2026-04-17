"""VPC v1 API operations.

Free functions implementing CRUD for Virtual Private Clouds.
Each function takes a ``ServiceClient`` as first argument —
the functional style from our architecture (no class methods,
easy to mock and generate).

Usage::

    from sdk.services.vpc.v1 import requests as vpc
    from sdk.services.vpc.v1.models import CreateVpcOpts

    # client is a ServiceClient for service_type="vpc"
    new_vpc = vpc.create(client, CreateVpcOpts(
        name="my-vpc",
        cidr="192.168.0.0/16",
    ))
    print(new_vpc.id, new_vpc.status)

    all_vpcs = vpc.list(client)
    for v in all_vpcs:
        print(v.name)
"""

from __future__ import annotations

from collections.abc import Generator, Iterator

from sdk.core.pagination import marker_paginate
from sdk.core.service_client import ServiceClient

from .models import CreateVpcOpts, ListVpcsOpts, UpdateVpcOpts, Vpc
from .urls import base_url, resource_url


def create(client: ServiceClient, opts: CreateVpcOpts) -> Vpc:
    """Create a VPC.

    ``POST /v1/{project_id}/vpcs``

    Args:
        client: VPC service client.
        opts: Creation options.

    Returns:
        Created VPC resource.
    """
    url = base_url()
    resp = client.post(url, json=opts.to_request_body())
    return Vpc.model_validate(resp.json()["vpc"])


def get(client: ServiceClient, vpc_id: str) -> Vpc:
    """Get VPC details.

    ``GET /v1/{project_id}/vpcs/{vpc_id}``

    Args:
        client: VPC service client.
        vpc_id: VPC UUID.

    Returns:
        VPC resource.
    """
    url = resource_url(vpc_id)
    resp = client.get(url)
    return Vpc.model_validate(resp.json()["vpc"])


def list(
    client: ServiceClient,
    opts: ListVpcsOpts | None = None,
) -> Iterator[Vpc]:
    """List VPCs with auto-pagination.

    ``GET /v1/{project_id}/vpcs``

    Uses marker-based pagination. Yields VPC objects one by one,
    fetching next pages automatically.

    Args:
        client: VPC service client.
        opts: Optional query filters (limit, marker, etc.).

    Yields:
        VPC resources.
    """
    params = opts.to_query_params() if opts else None
    limit = opts.limit if (opts and opts.limit is not None
                           and opts.limit > 0) else 0

    return marker_paginate(
        client=client,
        path=base_url(),
        items_key="vpcs",
        model=Vpc,
        marker_key="id",
        limit=limit,
        params=params,
    )


def update(
    client: ServiceClient,
    vpc_id: str,
    opts: UpdateVpcOpts,
) -> Vpc:
    """Update a VPC.

    ``PUT /v1/{project_id}/vpcs/{vpc_id}``

    Args:
        client: VPC service client.
        vpc_id: VPC UUID.
        opts: Fields to update.

    Returns:
        Updated VPC resource.
    """
    url = resource_url(vpc_id)
    resp = client.put(url, json=opts.to_request_body())
    return Vpc.model_validate(resp.json()["vpc"])


def delete(client: ServiceClient, vpc_id: str) -> None:
    """Delete a VPC.

    ``DELETE /v1/{project_id}/vpcs/{vpc_id}``

    Args:
        client: VPC service client.
        vpc_id: VPC UUID.
    """
    url = resource_url(vpc_id)
    client.delete(url)
