"""Base classes for request options."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from sdk.core.exceptions import InvalidInputError


class BaseOpts(BaseModel):
    """Base class for request body options.

    Subclasses set ``_wrapper_key`` to wrap the payload in a named object
    (e.g. ``{"vpc": {...}}``). Without it the body is returned flat.

    Field-omission rules (``exclude_none=True, exclude_defaults=True``):

    * ``name: str = ""`` -> omitted when caller does not set it.
    * ``name: str | None = None`` -> ``None`` is omitted, but any other
      value (including ``""``) is sent, allowing callers to clear
      server-side fields.
    """

    _wrapper_key: ClassVar[str | None] = None

    def to_request_body(self) -> dict[str, Any]:
        body = self.model_dump(
            exclude_none=True,
            exclude_defaults=True,
            by_alias=True,
        )
        if self._wrapper_key is not None:
            return {self._wrapper_key: body}
        return body


class BaseQueryOpts(BaseModel):
    """Base class for query string options.

    Output is a flat ``dict[str, str]`` ready for an HTTP client's
    ``params=`` argument. ``None`` and empty strings are dropped; numeric
    zero and ``False`` are preserved. Nested models or collections raise
    :class:`TypeError`.
    """

    def to_query_params(self) -> dict[str, str]:
        raw = self.model_dump(exclude_none=True, by_alias=True)
        params: dict[str, str] = {}
        for key, value in raw.items():
            if value == "":
                continue
            if isinstance(value, (dict, list)):
                raise InvalidInputError(key, value)
            if isinstance(value, bool):
                params[key] = "true" if value else "false"
            else:
                params[key] = str(value)
        return params
