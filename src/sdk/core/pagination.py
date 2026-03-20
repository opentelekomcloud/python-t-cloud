"""Pagination strategies for list operations.

Replaces the Go SDK's ``pagination`` package (Pager, LinkedPageBase,
MarkerPageBase, OffsetPageBase, SinglePageBase) with Python generators.
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

from collections.abc import Generator
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sdk.core.service_client import ServiceClient


def marker_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    marker_key: str = "id",
    limit: int = 0,
    params: dict[str, str] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Paginate using marker-based strategy.

    Fetches pages by setting ``marker`` query param to the last
    item's ``marker_key`` value. Stops when a page returns
    fewer items than ``limit`` or an empty list.

    This mirrors Go SDK's ``MarkerPageBase`` behavior.

    Args:
        client: Service client to send requests through.
        path: Relative resource path (e.g. ``"servers/detail"``).
        items_key: JSON key containing the items list
            (e.g. ``"servers"``, ``"items"``).
        marker_key: Field name on each item used as the marker.
            Default: ``"id"``.
        limit: Page size. If 0, the server default is used.
        params: Additional query parameters.

    Yields:
        Individual resource dicts, one at a time.
    """
    query: dict[str, str] = dict(params) if params else {}
    if limit:
        query["limit"] = str(limit)

    while True:
        url = _build_url(path, query)
        resp = client.get(url)
        data = resp.json()

        items = data.get(items_key, [])
        if not items:
            return

        yield from items

        # If server returned fewer than limit, we're on the last page
        if limit and len(items) < limit:
            return

        # Set marker to last item's key
        last = items[-1]
        marker = last.get(marker_key, "")
        if not marker:
            return
        query["marker"] = str(marker)


def offset_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    limit: int,
    start_offset: int = 0,
    params: dict[str, str] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Paginate using offset-based strategy.

    Increments ``offset`` by ``limit`` on each page. Stops when
    a page returns an empty list or fewer items than ``limit``.

    This mirrors Go SDK's ``OffsetPageBase`` behavior.

    Args:
        client: Service client to send requests through.
        path: Relative resource path.
        items_key: JSON key containing the items list.
        limit: Page size (required for offset pagination).
        start_offset: Starting offset. Default: 0.
        params: Additional query parameters.

    Yields:
        Individual resource dicts.
    """
    query: dict[str, str] = dict(params) if params else {}
    query["limit"] = str(limit)
    offset = start_offset

    while True:
        query["offset"] = str(offset)
        url = _build_url(path, query)
        resp = client.get(url)
        data = resp.json()

        items = data.get(items_key, [])
        if not items:
            return

        yield from items

        if len(items) < limit:
            return

        offset += limit


def linked_paginate(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    link_path: list[str] | None = None,
    params: dict[str, str] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Paginate using linked (next URL) strategy.

    Follows a ``next`` link embedded in the response body.
    The link path defaults to ``["links", "next"]`` (Keystone
    convention) but can be customized.

    This mirrors Go SDK's ``LinkedPageBase`` behavior.

    Args:
        client: Service client to send requests through.
        path: Relative resource path for the first page.
        items_key: JSON key containing the items list.
        link_path: List of keys to traverse in the response
            to find the next page URL. Default: ``["links", "next"]``.
        params: Additional query parameters for the first request.

    Yields:
        Individual resource dicts.
    """
    if link_path is None:
        link_path = ["links", "next"]

    url = _build_url(path, params) if params else path

    while url:
        resp = client.get(url)
        data = resp.json()

        items = data.get(items_key, [])
        if not items:
            return

        yield from items

        # Traverse link_path to find next URL
        url = _extract_link(data, link_path)


def single_page(
    client: ServiceClient,
    path: str,
    *,
    items_key: str,
    params: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch a single (non-paginated) list response.

    Convenience wrapper for endpoints that return all items
    at once. Returns a plain list instead of a generator.

    This mirrors Go SDK's ``SinglePageBase``.

    Args:
        client: Service client to send requests through.
        path: Relative resource path.
        items_key: JSON key containing the items list.
        params: Additional query parameters.

    Returns:
        List of resource dicts.
    """
    url = _build_url(path, params) if params else path
    resp = client.get(url)
    data = resp.json()
    return data.get(items_key, [])


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
    # Flatten single-value lists from parse_qs
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
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
        if current is None:
            return ""
    if current is data:
        # Empty path — no traversal happened
        return ""
    return str(current) if current else ""
