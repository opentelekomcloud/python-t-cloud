"""Update a VPC."""

from __future__ import annotations

from typing import ClassVar

from sdk.core.opts import BaseOpts
from sdk.core.service_client import ServiceClient

from .common import _BASE_PATH, Route, Vpc, VpcBaseOpts


class UpdateVpcOpts(VpcBaseOpts):
    """Options for updating a VPC.

    All fields are optional. ``None`` means "do not touch", an explicit
    empty string clears the field on the server.
    """


    name: str | None = None
    description: str | None = None
    cidr: str | None = None
    routes: list[Route] | None = None


def update(
    client: ServiceClient,
    vpc_id: str,
    opts: UpdateVpcOpts,
) -> Vpc:
    """Update a VPC.

    ``PUT /v1/{project_id}/vpcs/{vpc_id}``
    """
    resp = client.put(f"{_BASE_PATH}/{vpc_id}", json=opts.to_request_body())
    return Vpc.model_validate(resp.json()["vpc"])
