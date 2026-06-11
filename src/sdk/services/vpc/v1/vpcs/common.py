"""Shared VPC v1 models and constants."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import ClassVar
from sdk.core.opts import BaseOpts

_BASE_PATH = "vpcs"


class VpcBaseOpts(BaseOpts):
    _wrapper_key: ClassVar[str | None] = "vpc"


class Route(BaseModel):
    """VPC route entry."""

    destination: str | None = None
    nexthop: str | None = None


class Vpc(BaseModel):
    """VPC resource returned by the API.

    Only ``id`` is guaranteed to be present and non-null. Every other
    field can be missing or ``null`` depending on how the VPC was
    created and which API version returned it.
    """

    id: str
    name: str | None = None
    description: str | None = None
    cidr: str | None = None
    status: str | None = None
    enterprise_project_id: str | None = None
    routes: list[Route] = Field(default_factory=list)
    enable_shared_snat: bool | None = None
    tenant_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
