"""Get a VPC by ID."""

from __future__ import annotations

from sdk.core.service_client import ServiceClient

from .common import _BASE_PATH, Vpc


def get(client: ServiceClient, vpc_id: str) -> Vpc:
    """Get VPC details.

    ``GET /v1/{project_id}/vpcs/{vpc_id}``
    """
    resp = client.get(f"{_BASE_PATH}/{vpc_id}")
    return Vpc.model_validate(resp.json()["vpc"])
