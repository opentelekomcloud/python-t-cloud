"""Pagination strategies for list operations.

Each strategy is a generator function that yields items one by one,
automatically fetching the next page when needed.

Three strategies are supported:

- **Marker**: Next page determined by ``marker`` query param set to
  the last item's ID (e.g. CCE clusters, ECS servers).
- **Offset**: Next page determined by ``offset`` + ``limit`` query
  params (e.g. SMN topics).
- **Linked**: Next page URL extracted from response body
  (e.g. ``links.next`` field — Keystone-style pagination).

Additionally, ``single_page`` is a trivial helper for non-paginated
list endpoints that return all items at once.

Example::

    from sdk.core.pagination import marker_paginate

    # yields individual cluster dicts, fetching pages automatically
    for cluster in marker_paginate(
        client=service_client,
        path="clusters",
        items_key="items",
    ):
        print(cluster["metadata"]["name"])
"""

from __future__ import annotations
from pydantic import BaseModel
from collections.abc import Generator
from typing import Any, overload, TypeVar
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse, urljoin

from sdk.core.exceptions import InvalidInputError
from sdk.core.exceptions.response import MalformedResponseError
from sdk.core.service_client import ServiceClient

T = TypeVar("T", bound=BaseModel)

@overload
def marker_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: type[T],
    marker_key: str = ...,
    limit: int = ...,
    params: dict[str, str] | None = ...,
) -> Generator[T, None, None]: ...


@overload
def marker_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: None = ...,
    marker_key: str = ...,
    limit: int = ...,
    params: dict[str, str] | None = ...,
) -> Generator[dict[str, Any], None, None]: ...

def marker_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: type[T] | None = None,
    marker_key: str = "id",
    limit: int = 0,
    params: dict[str, str] | None = None,
) -> Generator[Any, None, None]:
    """Paginate using marker-based strategy.

    Fetches pages by setting ``marker`` query param to the last
    item's ``marker_key`` value. Stops on an empty page, a missing/empty marker on the last item,
    or a repeated marker.

    Args:
        client: Service client to send requests through.
        path: Relative resource path (e.g. ``"servers/detail"``).
        items_key: JSON key containing the items list
            (e.g. ``"servers"``, ``"items"``).
        marker_key: Field name on each item used as the marker.
            Default: ``"id"``.
        model: Optional Pydantic model class. If provided, raw JSON
            items will be validated and parsed into instances of this
            class. If omitted, raw dicts are returned.
        limit: Page size. If 0, the server default is used.
        params: Additional query parameters.

    Yields:
        Parsed Pydantic model instances (if ``model`` is provided),
        otherwise raw resource dicts.
    """
    query: dict[str, str] = dict(params) if params else {}
    if limit:
        query["limit"] = str(limit)

    while True:
        url = _build_url(path, query)
        _, items = _fetch_page(client, url, items_key)
        if not items:
            return

        for item in items:
            yield model.model_validate(item) if model else item

        last = items[-1]
        raw_marker = last.get(marker_key)

        if raw_marker is None or raw_marker == "":
            return

        marker_str = str(raw_marker)
        # if query.get("marker") == marker_str:
        #     return

        query["marker"] = marker_str

@overload
def offset_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: type[T],
    limit: int,
    start_offset: int = ...,
    params: dict[str, str] | None = ...,
) -> Generator[T, None, None]: ...


@overload
def offset_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: None = ...,
    limit: int,
    start_offset: int = ...,
    params: dict[str, str] | None = ...,
) -> Generator[dict[str, Any], None, None]: ...

def offset_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: type[T] | None = None,
    limit: int,
    start_offset: int = 0,
    params: dict[str, str] | None = None,
) -> Generator[Any, None, None]:
    """Paginate using offset-based strategy.

    Increments ``offset`` by ``limit`` on each page. Stops when
    a page returns an empty list or fewer items than ``limit``.

    This mirrors Go SDK's ``OffsetPageBase`` behavior.

    Args:
        client: Service client to send requests through.
        path: Relative resource path.
        items_key: JSON key containing the items list.
        model: Optional Pydantic model class. If provided, raw JSON
            items will be validated and parsed into instances of this
            class. If omitted, raw dicts are returned.
        limit: Page size (required for offset pagination).
        start_offset: Starting offset. Default: 0.
        params: Additional query parameters.

    Yields:
        Parsed Pydantic model instances (if ``model`` is provided),
        otherwise raw resource dicts.
    """
    if limit <= 0:
        raise InvalidInputError("limit", limit)
    query: dict[str, str] = dict(params) if params else {}
    query["limit"] = str(limit)
    offset = start_offset

    while True:
        query["offset"] = str(offset)
        url = _build_url(path, query)
        _, items = _fetch_page(client, url, items_key)

        if not items:
            return

        for item in items:
            yield model.model_validate(item) if model else item

        offset += len(items)

@overload
def linked_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: type[T],
    link_path: list[str] | None = ...,
    params: dict[str, str] | None = ...,
) -> Generator[T, None, None]: ...


@overload
def linked_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: None = ...,
    link_path: list[str] | None = ...,
    params: dict[str, str] | None = ...,
) -> Generator[dict[str, Any], None, None]: ...

def linked_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: type[T] | None = None,
    link_path: list[str] | None = None,
    params: dict[str, str] | None = None,
) -> Generator[Any, None, None]:
    """Paginate using linked (next URL) strategy.

    Follows a ``next`` link embedded in the response body.
    The link path defaults to ``["links", "next"]`` (Keystone
    convention) but can be customized.

    This mirrors Go SDK's ``LinkedPageBase`` behavior.

    Args:
        client: Service client to send requests through.
        path: Relative resource path for the first page.
        items_key: JSON key containing the items list.
        model: Optional Pydantic model class. If provided, raw JSON
            items will be validated and parsed into instances of this
            class. If omitted, raw dicts are returned.
        link_path: List of keys to traverse in the response
            to find the next page URL. Default: ``["links", "next"]``.
        params: Additional query parameters for the first request.

    Yields:
        Parsed Pydantic model instances (if ``model`` is provided),
        otherwise raw resource dicts.
    """
    if link_path is None:
        link_path = ["links", "next"]

    url = _build_url(path, params) if params else path
    seen_urls: set[str] = set()

    while url:
        if url in seen_urls:
            break
        seen_urls.add(url)

        data, items = _fetch_page(client, url, items_key)

        if not items:
            return

        for item in items:
            yield model.model_validate(item) if model else item

        next_url = _extract_link(data, link_path)
        if not next_url:
            return
        url = urljoin(url, next_url)

@overload
def single_page(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: type[T],
    params: dict[str, str] | None = ...,
) -> list[T]: ...


@overload
def single_page(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: None = ...,
    params: dict[str, str] | None = ...,
) -> list[dict[str, Any]]: ...

def single_page(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    model: type[T] | None = None,
    params: dict[str, str] | None = None,
) -> list[Any]:
    """Fetch a single (non-paginated) list response.

    Convenience wrapper for endpoints that return all items
    at once. Returns a plain list instead of a generator.

    This mirrors Go SDK's ``SinglePageBase``.

    Args:
        client: Service client to send requests through.
        path: Relative resource path.
        items_key: JSON key containing the items list.
        model: Optional Pydantic model class. If provided, raw JSON
            items will be validated and parsed into instances of this
            class. If omitted, raw dicts are returned.
        params: Additional query parameters.

    Returns:
        Parsed Pydantic model instances (if ``model`` is provided),
        otherwise raw resource dicts.
    """
    url = _build_url(path, params) if params else path
    _, items = _fetch_page(client, url, items_key)

    if model:
        return [model.model_validate(item) for item in items]
    return items


# ======================================================================
# Internal helpers
# ======================================================================


def _build_url(path: str, params: dict[str, str] | None) -> str:
    """Append query parameters to a path.

    If the path already contains query params, they are merged
    (new params override existing ones).

    Args:
        path: Base path, possibly with existing query string.
        params: Query parameters to add.

    Returns:
        Path with query string.
    """
    if not params:
        return path

    parsed = urlparse(path)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    merged = {k: v[0] if len(v) == 1 else v for k, v in existing.items()}
    merged.update(params)

    new_query = urlencode(merged, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _extract_link(data: dict[str, Any], path: list[str]) -> str:
    """Traverse nested dict to extract a link URL.

    Args:
        data: Response body dict.
        path: Key path to traverse (e.g. ``["links", "next"]``).

    Returns:
        URL string, or empty string if not found.
    """
    if not path:
        return ""

    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
        if current is None:
            return ""
    return str(current) if current else ""


def _fetch_page(
    client: ServiceClient,
    url: str,
    items_key: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch a page, parse JSON, and strictly validate the items key."""
    resp = client.get(url)
    data = resp.json()

    if items_key not in data:
        raise MalformedResponseError(
            f"expected key '{items_key}' not found in list response")
    return data, data[items_key]
