"""VPC v1 URL construction helpers.

All VPC v1 endpoints follow the pattern::

    /v1/{project_id}/vpcs[/{vpc_id}]

The ``project_id`` is obtained from the ``ServiceClient`` via
its provider.
"""

from __future__ import annotations

from sdk.core.service_client import ServiceClient


def base_url() -> str:
    """Return the VPC collection URL: ``vpcs``.

    Args:
        client: VPC service client.

    Returns:
        Relative URL string.
    """
    return f"vpcs"


def resource_url(vpc_id: str) -> str:
    """Return a single VPC resource URL: ``vpcs/{vpc_id}``.

    Args:
        client: VPC service client.
        vpc_id: VPC UUID.

    Returns:
        Relative URL string.
    """
    return f"vpcs/{vpc_id}"
