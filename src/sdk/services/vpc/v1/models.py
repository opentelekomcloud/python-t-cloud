"""VPC v1 data models.

Pydantic models for VPC API v1 request options and response objects.
Based on OTC VPC API Reference:
https://docs.otc.t-systems.com/virtual-private-cloud/api-ref/vpc_apis_v1_v2/virtual_private_cloud/

All response models use ``model_validate(resp.json()["vpc"])`` pattern,
replacing the Go SDK's ``Result.Extract()`` approach.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Route(BaseModel):
    """VPC route entry.

    Attributes:
        destination: Destination CIDR block (IPv4 or IPv6).
        nexthop: Next hop IP address within the VPC subnet.
    """

    destination: str = ""
    nexthop: str = ""


class Vpc(BaseModel):
    """VPC resource returned by the API.

    Attributes:
        id: VPC UUID.
        name: VPC name (max 64 chars).
        description: Supplementary info (max 255 chars).
        cidr: IP range for subnets in CIDR format.
        status: ``OK`` or ``CREATING``.
        enterprise_project_id: Enterprise project UUID or ``"0"``.
        routes: List of route entries.
        enable_shared_snat: Whether shared SNAT is enabled.
        tenant_id: Project ID (same as project_id).
        created_at: UTC creation time ``yyyy-MM-ddTHH:mm:ss``.
        updated_at: UTC update time ``yyyy-MM-ddTHH:mm:ss``.
    """

    id: str
    name: str = ""
    description: str = ""
    cidr: str = ""
    status: str = ""
    enterprise_project_id: str = Field(default="0", alias="enterprise_project_id")
    routes: list[Route] = Field(default_factory=list)
    enable_shared_snat: bool = False
    tenant_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    model_config = {"populate_by_name": True}


class CreateVpcOpts(BaseModel):
    """Options for creating a VPC.

    All fields are optional per the API spec.

    Attributes:
        name: VPC name (max 64 chars).
        description: Supplementary info (max 255 chars).
        cidr: Available IP address range for subnets.
        enterprise_project_id: Enterprise project UUID or ``"0"``.
    """

    name: str = ""
    description: str = ""
    cidr: str = ""
    enterprise_project_id: str = ""

    def to_request_body(self) -> dict:
        """Build the ``{"vpc": {...}}`` request body.

        Only includes non-empty fields, matching OTC API behavior
        where absent fields keep their defaults.
        """
        body: dict = {}
        if self.name:
            body["name"] = self.name
        if self.description:
            body["description"] = self.description
        if self.cidr:
            body["cidr"] = self.cidr
        if self.enterprise_project_id:
            body["enterprise_project_id"] = self.enterprise_project_id
        return {"vpc": body}


class UpdateVpcOpts(BaseModel):
    """Options for updating a VPC.

    All fields are optional. Only provided fields are sent.

    Attributes:
        name: New VPC name.
        description: New description.
        cidr: New CIDR block (must contain all existing subnets).
        routes: Replacement route list.
    """

    name: str = ""
    description: str = ""
    cidr: str = ""
    routes: list[Route] | None = None

    def to_request_body(self) -> dict:
        """Build the ``{"vpc": {...}}`` request body.

        Only includes non-empty/non-None fields.
        """
        body: dict = {}
        if self.name:
            body["name"] = self.name
        if self.description:
            body["description"] = self.description
        if self.cidr:
            body["cidr"] = self.cidr
        if self.routes is not None:
            body["routes"] = [r.model_dump() for r in self.routes]
        return {"vpc": body}


class ListVpcsOpts(BaseModel):
    """Query parameters for listing VPCs.

    Attributes:
        id: Filter by VPC ID.
        limit: Page size (0 to 2^31-1, default 2000).
        marker: Resource ID to start pagination from.
        enterprise_project_id: Filter by enterprise project.
    """

    id: str = ""
    limit: int = 0
    marker: str = ""
    enterprise_project_id: str = ""

    def to_query_params(self) -> dict[str, str]:
        """Build query parameter dict, omitting empty values."""
        params: dict[str, str] = {}
        if self.id:
            params["id"] = self.id
        if self.limit:
            params["limit"] = str(self.limit)
        if self.marker:
            params["marker"] = self.marker
        if self.enterprise_project_id:
            params["enterprise_project_id"] = self.enterprise_project_id
        return params
