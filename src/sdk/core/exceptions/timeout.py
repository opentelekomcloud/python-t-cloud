"""Client-side timeout exception.

Corresponds to Go SDK's ``ErrTimeOut``.
"""

from __future__ import annotations

from .base import SDKError


class SDKTimeoutError(SDKError):
    """Client-side operation timeout.

    Corresponds to Go SDK's ``ErrTimeOut``.

    Distinct from ``RequestTimeoutError`` (HTTP 408) which is a
    server response. This error is raised when the SDK's own
    timeout is exceeded, e.g. waiting for a resource to become active.
    """
