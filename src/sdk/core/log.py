"""Logging configuration for the SDK.

Uses the standard ``logging`` module with no external dependencies.
Each SDK module creates its own logger via ``logging.getLogger(__name__)``,
so users can fine-tune verbosity per component::

    import logging

    # See all SDK debug output
    logging.getLogger("sdk").setLevel(logging.DEBUG)

    # Only auth-related messages
    logging.getLogger("sdk.core.auth").setLevel(logging.DEBUG)

    # Silence HTTP noise, keep warnings
    logging.getLogger("sdk.core.provider").setLevel(logging.WARNING)

The SDK never calls ``logging.basicConfig()`` or adds handlers —
that's the user's responsibility. If no handlers are configured,
log messages are silently discarded (Python's default behavior).

Attributes:
    LOG_SENSITIVE_HEADERS: Header names that should be redacted in
        debug output to avoid leaking credentials.
"""

from __future__ import annotations

import logging
from typing import Any


LOG_SENSITIVE_HEADERS: frozenset[str] = frozenset({
    "x-auth-token",
    "authorization",
    "x-security-token",
})


def get_logger(name: str) -> logging.Logger:
    """Get a logger within the ``sdk`` namespace.

    Convenience wrapper that ensures all SDK loggers share the
    ``sdk.`` prefix for easy filtering.

    Args:
        name: Module ``__name__`` (e.g. ``sdk.core.provider``).

    Returns:
        A standard library logger.
    """
    return logging.getLogger(name)


def _redact_headers(headers: dict[str, Any]) -> dict[str, str]:
    """Redact sensitive headers for safe logging.

    Args:
        headers: Raw response/request headers.

    Returns:
        Copy of headers with sensitive values replaced by ``***``.
    """
    return {
        k: "***" if k.lower() in LOG_SENSITIVE_HEADERS else str(v)
        for k, v in headers.items()
    }


def log_request(
    logger: logging.Logger,
    *,
    method: str,
    url: str,
    status_code: int,
    duration_ms: float,
    request_id: str = "",
) -> None:
    """Log an HTTP request/response at the appropriate level.

    - 2xx → DEBUG
    - 4xx → WARNING
    - 5xx → ERROR

    Args:
        logger: Logger instance (typically from the provider module).
        method: HTTP method.
        url: Request URL.
        status_code: Response status code.
        duration_ms: Round-trip time in milliseconds.
        request_id: Value of ``X-Request-Id`` response header, if present.
    """
    rid = f" [{request_id}]" if request_id else ""
    msg = f"{method} {url} → {status_code} ({duration_ms:.0f}ms){rid}"

    if status_code >= 500:
        logger.error(msg)
    elif status_code >= 400:
        logger.warning(msg)
    else:
        logger.debug(msg)
