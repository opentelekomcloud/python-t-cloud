"""Resource lookup exceptions.

Corresponds to Go SDK's ``ErrResourceNotFound`` and
``ErrMultipleResourcesFound``.
"""

from __future__ import annotations

from .base import SDKError


class ResourceNotFoundError(SDKError):
    """Resource not found during lookup by name.

    Corresponds to Go SDK's ``ErrResourceNotFound``.
    Raised when a find-by-name operation returns no results.

    Args:
        resource_type: Type of resource (e.g. ``"VPC"``, ``"Subnet"``).
        name: Name that was searched for.
    """

    def __init__(self, resource_type: str, name: str) -> None:
        self.resource_type = resource_type
        self.name = name
        super().__init__(f"Unable to find {resource_type} with name {name}")


class MultipleResourcesFoundError(SDKError):
    """Multiple resources found during lookup by name.

    Corresponds to Go SDK's ``ErrMultipleResourcesFound``.
    Raised when a find-by-name operation returns more than
    one result and a single match was expected.

    Args:
        resource_type: Type of resource (e.g. ``"VPC"``, ``"Subnet"``).
        name: Name that was searched for.
        count: Number of matching resources found.
    """

    def __init__(self, resource_type: str, name: str, count: int) -> None:
        self.resource_type = resource_type
        self.name = name
        self.count = count
        super().__init__(
            f"Found {count} {resource_type}s matching {name}"
        )
