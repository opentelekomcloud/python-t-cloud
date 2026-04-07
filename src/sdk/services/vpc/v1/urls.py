"""VPC v1 URL construction helpers.

All VPC v1 endpoints follow the pattern::

    /v1/{project_id}/vpcs[/{vpc_id}]

The ``project_id`` is obtained from the ``ServiceClient`` via
its provider.
"""

from __future__ import annotations

from sdk.core.service_client import ServiceClient


def base_url(client: ServiceClient) -> str:
    """Return the VPC collection URL: ``v1/{project_id}/vpcs``.

    Args:
        client: VPC service client.

    Returns:
        Relative URL string.
    """
    project_id = client.provider.project_id
    return f"v1/{project_id}/vpcs"


def resource_url(client: ServiceClient, vpc_id: str) -> str:
    """Return a single VPC resource URL: ``v1/{project_id}/vpcs/{vpc_id}``.

    Args:
        client: VPC service client.
        vpc_id: VPC UUID.

    Returns:
        Relative URL string.
    """
    return f"{base_url(client)}/{vpc_id}"
