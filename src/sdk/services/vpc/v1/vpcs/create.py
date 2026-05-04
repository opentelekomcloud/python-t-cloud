"""Create a VPC."""

from __future__ import annotations

from typing import ClassVar

from sdk.core.opts import BaseOpts
from sdk.core.service_client import ServiceClient

from .common import _BASE_PATH, Vpc


class CreateVpcOpts(BaseOpts):
    """Options for creating a VPC.

    All fields are optional per the API spec.
    """

    _wrapper_key: ClassVar[str | None] = "vpc"

    name: str | None = None
    description: str | None = None
    cidr: str | None = None
    enterprise_project_id: str | None = None


def create(client: ServiceClient, opts: CreateVpcOpts) -> Vpc:
    """Create a VPC.

    ``POST /v1/{project_id}/vpcs``
    """
    resp = client.post(_BASE_PATH, json=opts.to_request_body())
    return Vpc.model_validate(resp.json()["vpc"])
