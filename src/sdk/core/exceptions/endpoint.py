"""Endpoint discovery exceptions.

Corresponds to Go SDK's ``ErrServiceNotFound`` and
``ErrEndpointNotFound``.
"""

from __future__ import annotations

from .base import SDKError


class EndpointError(SDKError):
    """Endpoint discovery error."""


class ServiceNotFoundError(EndpointError):
    """No matching service found in the service catalog.

    Corresponds to Go SDK's ``ErrServiceNotFound``.

    Args:
        service: Name of the service that was not found.
    """

    def __init__(self, service: str = "") -> None:
        self.service = service
        msg = (
            f"No suitable service could be found in the "
            f"service catalog: {service}"
            if service
            else "No suitable service could be found in the service catalog"
        )
        super().__init__(msg)


class EndpointNotFoundError(EndpointError):
    """No matching endpoint found for the service.

    Corresponds to Go SDK's ``ErrEndpointNotFound``.

    Args:
        service: Name of the service.
        region: Region where the endpoint was expected.
    """

    def __init__(self, service: str = "", region: str = "") -> None:
        self.service = service
        self.region = region
        parts = ["No suitable endpoint could be found in the service catalog"]
        if service:
            parts.append(f"for service '{service}'")
        if region:
            parts.append(f"in region '{region}'")
        super().__init__(" ".join(parts))
