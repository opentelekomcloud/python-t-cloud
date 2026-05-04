"""Tests for VPC v1 Opts.

The generic ``BaseOpts``/``BaseQueryOpts`` semantics are covered in
``tests/unit/core/test_opts.py``. These tests pin VPC-specific behaviour:
the wrapper key, the field set, and the route nested model.
"""

from __future__ import annotations

from sdk.services.vpc.v1.vpcs import (
    CreateVpcOpts,
    ListVpcsOpts,
    Route,
    UpdateVpcOpts,
)


# --- CreateVpcOpts ---


def test_create_opts_empty_returns_wrapped_empty_body():
    assert CreateVpcOpts().to_request_body() == {"vpc": {}}


def test_create_opts_full():
    opts = CreateVpcOpts(
        name="my-vpc",
        description="test",
        cidr="192.168.0.0/16",
        enterprise_project_id="ep-1",
    )
    assert opts.to_request_body() == {
        "vpc": {
            "name": "my-vpc",
            "description": "test",
            "cidr": "192.168.0.0/16",
            "enterprise_project_id": "ep-1",
        }
    }


def test_create_opts_drops_none_fields():
    opts = CreateVpcOpts(name="my-vpc")
    assert opts.to_request_body() == {"vpc": {"name": "my-vpc"}}


# --- UpdateVpcOpts ---


def test_update_opts_explicit_empty_string_clears_field():
    """``description=""`` reaches the wire so the server clears the field."""
    opts = UpdateVpcOpts(description="")
    assert opts.to_request_body() == {"vpc": {"description": ""}}


def test_update_opts_with_routes():
    opts = UpdateVpcOpts(
        routes=[
            Route(destination="10.0.0.0/8", nexthop="192.168.1.1"),
            Route(destination="172.16.0.0/12", nexthop="192.168.1.2"),
        ],
    )
    assert opts.to_request_body() == {
        "vpc": {
            "routes": [
                {"destination": "10.0.0.0/8", "nexthop": "192.168.1.1"},
                {"destination": "172.16.0.0/12", "nexthop": "192.168.1.2"},
            ]
        }
    }


def test_update_opts_empty_routes_list():
    """Empty list is meaningful: clear all routes."""
    opts = UpdateVpcOpts(routes=[])
    assert opts.to_request_body() == {"vpc": {"routes": []}}


def test_update_opts_none_routes_omitted():
    opts = UpdateVpcOpts(name="x")
    assert opts.to_request_body() == {"vpc": {"name": "x"}}


# --- ListVpcsOpts ---


def test_list_opts_empty():
    assert ListVpcsOpts().to_query_params() == {}


def test_list_opts_full():
    opts = ListVpcsOpts(
        id="vpc-1",
        limit=20,
        marker="abc",
        enterprise_project_id="ep-1",
    )
    assert opts.to_query_params() == {
        "id": "vpc-1",
        "limit": "20",
        "marker": "abc",
        "enterprise_project_id": "ep-1",
    }


def test_list_opts_partial():
    opts = ListVpcsOpts(limit=10)
    assert opts.to_query_params() == {"limit": "10"}