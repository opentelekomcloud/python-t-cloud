"""Tests for ``sdk.services.vpc.v1.requests``."""

from __future__ import annotations
from unittest.mock import MagicMock, PropertyMock

import httpx

from sdk.services.vpc.v1 import requests as vpc
from sdk.services.vpc.v1.models import (
    CreateVpcOpts,
    ListVpcsOpts,
    Route,
    UpdateVpcOpts,
)


# ======================================================================
# Helpers
# ======================================================================

VPC_RESPONSE = {
    "id": "99d9d709-8478-4b46-9f3f-2206b1023fd3",
    "name": "vpc",
    "description": "test",
    "cidr": "192.168.0.0/16",
    "status": "OK",
    "enterprise_project_id": "0",
    "routes": [],
    "enable_shared_snat": False,
    "tenant_id": "087679f0aa80d32a2f4ec0172f5e902b",
    "created_at": "2022-12-15T02:25:11",
    "updated_at": "2022-12-15T02:25:11",
}

PROJECT_ID = "087679f0aa80d32a2f4ec0172f5e902b"


def _make_response(body: dict) -> httpx.Response:
    """Create a fake httpx.Response with JSON body."""
    resp = httpx.Response(
        status_code=200,
        json=body,
        request=httpx.Request("GET", "https://example.com"),
    )
    return resp


def _make_client() -> MagicMock:
    """Create a mock ServiceClient with project_id."""
    client = MagicMock()
    # provider.project_id accessed via urls.py
    type(client.provider).project_id = PropertyMock(return_value=PROJECT_ID)
    return client


# ======================================================================
# Create
# ======================================================================


class TestCreate:
    def test_create_sends_post(self):
        client = _make_client()
        client.post.return_value = _make_response({"vpc": VPC_RESPONSE})

        opts = CreateVpcOpts(name="vpc", cidr="192.168.0.0/16")
        result = vpc.create(client, opts)

        client.post.assert_called_once_with(
            f"vpcs",
            json={"vpc": {"name": "vpc", "cidr": "192.168.0.0/16"}},
        )
        assert result.id == "99d9d709-8478-4b46-9f3f-2206b1023fd3"
        assert result.name == "vpc"
        assert result.status == "OK"

    def test_create_with_enterprise_project(self):
        client = _make_client()
        client.post.return_value = _make_response({"vpc": VPC_RESPONSE})

        opts = CreateVpcOpts(
            name="vpc",
            enterprise_project_id="0aad99bc",
        )
        vpc.create(client, opts)

        call_body = client.post.call_args[1]["json"]
        assert call_body["vpc"]["enterprise_project_id"] == "0aad99bc"


# ======================================================================
# Get
# ======================================================================


class TestGet:
    def test_get_sends_get(self):
        client = _make_client()
        client.get.return_value = _make_response({"vpc": VPC_RESPONSE})

        vpc_id = "99d9d709-8478-4b46-9f3f-2206b1023fd3"
        result = vpc.get(client, vpc_id)

        client.get.assert_called_once_with(
            f"vpcs/{vpc_id}",
        )
        assert result.id == vpc_id
        assert result.cidr == "192.168.0.0/16"


# ======================================================================
# List
# ======================================================================


class TestList:
    def test_list_single_page(self):
        """List with limit — returns fewer items than limit, stops."""
        client = _make_client()
        vpcs_data = [
            {**VPC_RESPONSE, "id": "aaa", "name": "vpc1"},
            {**VPC_RESPONSE, "id": "bbb", "name": "vpc2"},
        ]

        client.get.return_value = _make_response({"vpcs": vpcs_data})

        # limit=5, but only 2 returned → single page
        opts = ListVpcsOpts(limit=5)
        results = list(vpc.list(client, opts))

        assert len(results) == 2
        assert results[0].id == "aaa"
        assert results[1].id == "bbb"
        assert client.get.call_count == 1

    def test_list_with_opts(self):
        client = _make_client()
        client.get.return_value = _make_response({"vpcs": []})

        opts = ListVpcsOpts(limit=10, enterprise_project_id="0")
        list(vpc.list(client, opts))

        call_url = client.get.call_args[0][0]
        assert f"vpcs" in call_url

    def test_list_pagination(self):
        """List follows marker pagination across two pages."""
        client = _make_client()

        page1 = [
            {**VPC_RESPONSE, "id": "id-1", "name": "vpc1"},
            {**VPC_RESPONSE, "id": "id-2", "name": "vpc2"},
        ]
        page2 = [
            {**VPC_RESPONSE, "id": "id-3", "name": "vpc3"},
        ]

        client.get.side_effect = [
            _make_response({"vpcs": page1}),
            _make_response({"vpcs": page2}),
        ]

        # limit=2: page1 has 2 items (==limit) → fetch next;
        # page2 has 1 item (<limit) → stop
        opts = ListVpcsOpts(limit=2)
        results = list(vpc.list(client, opts))

        assert len(results) == 3
        assert results[0].name == "vpc1"
        assert results[2].name == "vpc3"
        assert client.get.call_count == 2

    def test_list_empty(self):
        client = _make_client()
        client.get.return_value = _make_response({"vpcs": []})

        opts = ListVpcsOpts(limit=10)
        results = list(vpc.list(client, opts))
        assert results == []


# ======================================================================
# Update
# ======================================================================


class TestUpdate:
    def test_update_sends_put(self):
        client = _make_client()
        updated = {**VPC_RESPONSE, "name": "vpc1", "description": "test1"}
        client.put.return_value = _make_response({"vpc": updated})

        vpc_id = "99d9d709-8478-4b46-9f3f-2206b1023fd3"
        opts = UpdateVpcOpts(name="vpc1", description="test1")
        result = vpc.update(client, vpc_id, opts)

        client.put.assert_called_once_with(
            f"vpcs/{vpc_id}",
            json={"vpc": {"name": "vpc1", "description": "test1"}},
        )
        assert result.name == "vpc1"
        assert result.description == "test1"

    def test_update_with_routes(self):
        client = _make_client()
        updated = {
            **VPC_RESPONSE,
            "routes": [{"destination": "10.0.0.0/8", "nexthop": "192.168.0.1"}],
        }
        client.put.return_value = _make_response({"vpc": updated})

        vpc_id = "99d9d709-8478-4b46-9f3f-2206b1023fd3"
        opts = UpdateVpcOpts(
            routes=[Route(destination="10.0.0.0/8", nexthop="192.168.0.1")]
        )
        result = vpc.update(client, vpc_id, opts)

        assert len(result.routes) == 1
        assert result.routes[0].destination == "10.0.0.0/8"


# ======================================================================
# Delete
# ======================================================================


class TestDelete:
    def test_delete_sends_delete(self):
        client = _make_client()
        client.delete.return_value = _make_response({})

        vpc_id = "13551d6b-755d-4757-b956-536f674975c0"
        vpc.delete(client, vpc_id)

        client.delete.assert_called_once_with(
            f"vpcs/{vpc_id}",
        )

    def test_delete_returns_none(self):
        client = _make_client()
        client.delete.return_value = _make_response({})

        result = vpc.delete(client, "some-id")
        assert result is None
