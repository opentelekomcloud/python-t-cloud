"""Base exception types for the SDK.
"""

# Corresponds to Go SDK's ``BaseError``, ``ErrMissingInput``,
# and ``ErrInvalidInput``.

from __future__ import annotations

from typing import Any


class SDKError(Exception):
    """Base exception for all SDK errors.
    All SDK exceptions inherit from this class, so
    ``except SDKError`` catches every SDK-related error.
    """
    # Corresponds to Go SDK's ``BaseError``.

class MissingInputError(SDKError):
    """Required input argument was not provided.

    Args:
        argument: Name of the missing argument.
    """
    # Corresponds to Go SDK's ``ErrMissingInput``.
    def __init__(self, argument: str) -> None:
        self.argument = argument
        super().__init__(f"Missing input for argument [{argument}]")


class InvalidInputError(SDKError):
    """Invalid value provided for an input argument.

    Args:
        argument: Name of the argument.
        value: The invalid value that was provided.
    """
    # Corresponds to Go SDK's ``ErrInvalidInput``.

    def __init__(self, argument: str, value: Any) -> None:
        self.argument = argument
        self.value = value
        super().__init__(
            f"Invalid input provided for argument [{argument}]: [{value!r}]"
        )
