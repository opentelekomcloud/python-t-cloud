"""Tests for ``sdk.core.pagination``."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sdk.core.auth import AuthConfig
from sdk.core.pagination import (
    _build_url,
    _extract_link,
    linked_paginate,
    marker_paginate,
    offset_paginate,
    single_page,
)
from sdk.core.provider import ProviderClient
from sdk.core.service_client import ServiceClient


# ======================================================================
# Fixtures
# ======================================================================


def _make_service_client(handler: Any) -> ServiceClient:
    """Build a ServiceClient with mocked transport."""
    cfg = AuthConfig(
        identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
        username="user",
        password="pass",
        domain_name="dom",
    )
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    provider = ProviderClient(cfg, http_client=http_client)
    provider.token_id = "test-token"
    return ServiceClient(
        provider, endpoint_override="https://api.example.com/v1",
    )


# ======================================================================
# _build_url
# ======================================================================


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("servers", None) == "servers"

    def test_adds_params(self) -> None:
        url = _build_url("servers", {"limit": "10"})
        assert "limit=10" in url
        assert url.startswith("servers?")

    def test_merges_existing_params(self) -> None:
        url = _build_url("servers?status=ACTIVE", {"limit": "5"})
        assert "status=ACTIVE" in url
        assert "limit=5" in url

    def test_overrides_existing(self) -> None:
        url = _build_url("servers?limit=20", {"limit": "5"})
        assert "limit=5" in url
        assert "limit=20" not in url


# ======================================================================
# _extract_link
# ======================================================================


class TestExtractLink:
    def test_simple_path(self) -> None:
        data = {"links": {"next": "https://example.com/page2"}}
        assert _extract_link(data, ["links", "next"]) == "https://example.com/page2"

    def test_missing_key(self) -> None:
        data = {"links": {"prev": "..."}}
        assert _extract_link(data, ["links", "next"]) == ""

    def test_null_value(self) -> None:
        data = {"links": {"next": None}}
        assert _extract_link(data, ["links", "next"]) == ""

    def test_deep_path(self) -> None:
        data = {"a": {"b": {"c": "url"}}}
        assert _extract_link(data, ["a", "b", "c"]) == "url"

    def test_not_a_dict(self) -> None:
        data = {"links": "not-a-dict"}
        assert _extract_link(data, ["links", "next"]) == ""

    def test_empty_path(self) -> None:
        data = {"links": {"next": "url"}}
        assert _extract_link(data, []) == ""


# ======================================================================
# marker_paginate
# ======================================================================


class TestMarkerPaginate:
    def test_single_page(self) -> None:
        """Single page with fewer items than limit."""

        def handler(req: httpx.Request) -> httpx.Response:
            if "marker=" in str(req.url):
                return httpx.Response(200, json={"servers": []})
            return httpx.Response(200, json={
                "servers": [
                    {"id": "s1", "name": "a"},
                    {"id": "s2", "name": "b"},
                ],
            })

        sc = _make_service_client(handler)
        items = list(marker_paginate(sc, "servers", items_key="servers", limit=10))

        assert len(items) == 2
        assert items[0]["id"] == "s1"

    def test_multi_page(self) -> None:
        """Two pages, second page is shorter → stops."""
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url = str(req.url)
            if "marker=" not in url:
                return httpx.Response(200, json={
                    "items": [{"id": "1"}, {"id": "2"}],
                })
            elif "marker=2" in url:
                return httpx.Response(200, json={
                    "items": [{"id": "3"}],
                })
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        items = list(marker_paginate(sc, "items", items_key="items", limit=2))

        assert len(items) == 3
        assert call_count == 3
        assert items[-1]["id"] == "3"

    def test_empty_first_page(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        items = list(marker_paginate(sc, "items", items_key="items"))

        assert items == []

    def test_marker_param_passed(self) -> None:
        """Second request should include marker from last item."""
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            url = str(req.url)
            if "marker=" not in url:
                return httpx.Response(200, json={
                    "items": [{"id": "abc"}, {"id": "def"}],
                })
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        list(marker_paginate(sc, "items", items_key="items", limit=2))

        assert len(captured) == 2
        assert "marker=def" in str(captured[1].url)

    def test_custom_marker_key(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            url = str(req.url)
            if "marker=" not in url:
                return httpx.Response(200, json={
                    "items": [{"uid": "x1"}],
                })
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        list(marker_paginate(
            sc, "items", items_key="items", marker_key="uid", limit=1,
        ))

        assert "marker=x1" in str(captured[1].url)

    def test_no_limit_stops_on_empty(self) -> None:
        """Without limit, pagination stops when page is empty."""
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json={
                    "items": [{"id": "a"}],
                })
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        items = list(marker_paginate(sc, "items", items_key="items"))

        assert len(items) == 1
        assert call_count == 2

    def test_extra_params_forwarded(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        list(marker_paginate(
            sc, "items", items_key="items",
            params={"status": "ACTIVE"},
        ))

        assert "status=ACTIVE" in str(captured[0].url)

    def test_server_caps_page_size(self) -> None:
        """Server caps pages at 2 even though we asked limit=100 —
        Go-parity pagination must traverse everything (stops on empty
        page only), not at the first short page."""
        ids = ["a", "b", "c", "d", "e"]

        def handler(req: httpx.Request) -> httpx.Response:
            url = str(req.url)
            tail = ids
            for i in ids:
                if f"marker={i}" in url:
                    tail = ids[ids.index(i) + 1:]
                    break
            return httpx.Response(200, json={
                "items": [{"id": x} for x in tail[:2]],  # cap wins over limit
            })

        sc = _make_service_client(handler)
        items = list(marker_paginate(sc, "items", items_key="items", limit=100))

        assert [i["id"] for i in items] == ids


# ======================================================================
# offset_paginate
# ======================================================================


class TestOffsetPaginate:
    def test_single_page(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if "offset=0" in str(req.url):
                return httpx.Response(200, json={
                    "topics": [{"id": "t1"}, {"id": "t2"}],
                })
            return httpx.Response(200, json={"topics": []})

        sc = _make_service_client(handler)
        items = list(offset_paginate(
            sc, "topics", items_key="topics", limit=10,
        ))

        assert len(items) == 2

    def test_multi_page(self) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url = str(req.url)
            if "offset=0" in url or "offset" not in url:
                return httpx.Response(200, json={
                    "items": [{"id": "1"}, {"id": "2"}],
                })
            elif "offset=2" in url:
                return httpx.Response(200, json={
                    "items": [{"id": "3"}],
                })
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        items = list(offset_paginate(
            sc, "items", items_key="items", limit=2,
        ))

        assert len(items) == 3
        assert call_count == 3

    def test_offset_increments(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            url = str(req.url)
            if "offset=0" in url:
                return httpx.Response(200, json={
                    "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                })
            if "offset=3" in url:
                return httpx.Response(200, json={
                    "items": [{"id": "d"}],
                })
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        items = list(offset_paginate(
            sc, "items", items_key="items", limit=3,
        ))

        assert len(items) == 4
        assert "offset=0" in str(captured[0].url)
        assert "offset=3" in str(captured[1].url)

    def test_start_offset(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        list(offset_paginate(
            sc, "items", items_key="items", limit=5, start_offset=10,
        ))

        assert "offset=10" in str(captured[0].url)

    def test_empty_first_page(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        items = list(offset_paginate(
            sc, "items", items_key="items", limit=10,
        ))

        assert items == []

    def test_server_caps_page_size(self) -> None:
        """Server caps pages below the requested limit — offset must
        advance by the actual page size and not stop early."""
        ids = ["a", "b", "c", "d", "e"]

        def handler(req: httpx.Request) -> httpx.Response:
            from urllib.parse import parse_qs, urlparse
            offset = int(parse_qs(urlparse(str(req.url)).query)["offset"][0])
            return httpx.Response(200, json={
                "items": [{"id": x} for x in ids[offset:offset + 2]],
            })

        sc = _make_service_client(handler)
        items = list(offset_paginate(sc, "items", items_key="items", limit=100))

        assert [i["id"] for i in items] == ids


# ======================================================================
# linked_paginate
# ======================================================================


class TestLinkedPaginate:
    def test_single_page_no_next(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "items": [{"id": "1"}],
                "links": {"next": None},
            })

        sc = _make_service_client(handler)
        items = list(linked_paginate(sc, "items", items_key="items"))

        assert len(items) == 1

    def test_follows_next_link(self) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url = str(req.url)
            if "page2" not in url:
                return httpx.Response(200, json={
                    "items": [{"id": "1"}],
                    "links": {"next": "items?page=page2"},
                })
            return httpx.Response(200, json={
                "items": [{"id": "2"}],
                "links": {"next": None},
            })

        sc = _make_service_client(handler)
        items = list(linked_paginate(sc, "items", items_key="items"))

        assert len(items) == 2
        assert call_count == 2

    def test_custom_link_path(self) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json={
                    "data": [{"id": "1"}],
                    "pagination": {"next_url": "data?cursor=abc"},
                })
            return httpx.Response(200, json={
                "data": [{"id": "2"}],
                "pagination": {"next_url": None},
            })

        sc = _make_service_client(handler)
        items = list(linked_paginate(
            sc, "data", items_key="data",
            link_path=["pagination", "next_url"],
        ))

        assert len(items) == 2

    def test_empty_first_page(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "items": [],
                "links": {"next": "irrelevant"},
            })

        sc = _make_service_client(handler)
        items = list(linked_paginate(sc, "items", items_key="items"))

        assert items == []

    def test_missing_links_key(self) -> None:
        """No 'links' in response → stops after first page."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "items": [{"id": "1"}],
            })

        sc = _make_service_client(handler)
        items = list(linked_paginate(sc, "items", items_key="items"))

        assert len(items) == 1


# ======================================================================
# single_page
# ======================================================================


class TestSinglePage:
    def test_returns_list(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "servers": [{"id": "s1"}, {"id": "s2"}],
            })

        sc = _make_service_client(handler)
        items = single_page(sc, "servers", items_key="servers")

        assert isinstance(items, list)
        assert len(items) == 2

    def test_empty_list(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"servers": []})

        sc = _make_service_client(handler)
        items = single_page(sc, "servers", items_key="servers")

        assert items == []

    def test_with_params(self) -> None:
        captured: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json={"items": []})

        sc = _make_service_client(handler)
        single_page(sc, "items", items_key="items", params={"foo": "bar"})

        assert "foo=bar" in str(captured[0].url)
