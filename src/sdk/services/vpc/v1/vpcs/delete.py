"""Delete a VPC."""

from __future__ import annotations

from sdk.core.service_client import ServiceClient

from .common import _BASE_PATH


def delete(client: ServiceClient, vpc_id: str) -> None:
    """Delete a VPC.

    ``DELETE /v1/{project_id}/vpcs/{vpc_id}``
    """
    client.delete(f"{_BASE_PATH}/{vpc_id}")
