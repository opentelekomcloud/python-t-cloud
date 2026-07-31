"""Tests for ``sdk.core.opts``."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel, Field

from sdk.core.exceptions import InvalidInputError
from sdk.core.opts import BaseOpts, BaseQueryOpts


class _Route(BaseModel):
    destination: str = ""
    nexthop: str = ""


class _CreateOpts(BaseOpts):
    _wrapper_key: ClassVar[str | None] = "vpc"

    name: str = ""
    description: str = ""
    cidr: str = ""


class _UpdateOpts(BaseOpts):
    _wrapper_key: ClassVar[str | None] = "vpc"

    name: str | None = None
    description: str | None = None
    cidr: str | None = None
    routes: list[_Route] | None = None


class _UnwrappedOpts(BaseOpts):
    name: str | None = None
    value: int | None = None


class _ListOpts(BaseQueryOpts):
    id: str | None = None
    limit: int | None = None
    marker: str | None = None
    enterprise_project_id: str | None = None


# --- BaseOpts ---


def test_empty_opts_returns_empty_wrapped_body():
    assert _CreateOpts().to_request_body() == {"vpc": {}}


def test_partially_filled_opts_includes_only_set_fields():
    opts = _CreateOpts(name="my-vpc", cidr="192.168.0.0/16")
    assert opts.to_request_body() == {
        "vpc": {"name": "my-vpc", "cidr": "192.168.0.0/16"}
    }


def test_nested_models_serialized_recursively():
    opts = _UpdateOpts(
        name="my-vpc",
        routes=[
            _Route(destination="10.0.0.0/8", nexthop="192.168.1.1"),
            _Route(destination="172.16.0.0/12", nexthop="192.168.1.2"),
        ],
    )
    assert opts.to_request_body() == {
        "vpc": {
            "name": "my-vpc",
            "routes": [
                {"destination": "10.0.0.0/8", "nexthop": "192.168.1.1"},
                {"destination": "172.16.0.0/12", "nexthop": "192.168.1.2"},
            ],
        }
    }


def test_none_fields_excluded_from_body():
    opts = _UpdateOpts(name="my-vpc")
    assert opts.to_request_body() == {"vpc": {"name": "my-vpc"}}


def test_explicit_empty_string_is_preserved():
    opts = _UpdateOpts(name="my-vpc", description="")
    assert opts.to_request_body() == {
        "vpc": {"name": "my-vpc", "description": ""}
    }


def test_wrapper_key_omitted_returns_flat_body():
    opts = _UnwrappedOpts(name="x", value=42)
    assert opts.to_request_body() == {"name": "x", "value": 42}


def test_wrapper_key_with_empty_unwrapped_body():
    assert _UnwrappedOpts().to_request_body() == {}


def test_nested_model_with_partial_fields():
    opts = _UpdateOpts(routes=[_Route(destination="10.0.0.0/8")])
    assert opts.to_request_body() == {
        "vpc": {"routes": [{"destination": "10.0.0.0/8"}]}
    }


def test_empty_routes_list_is_preserved():
    opts = _UpdateOpts(routes=[])
    assert opts.to_request_body() == {"vpc": {"routes": []}}


def test_alias_is_respected_in_body():
    class _Aliased(BaseOpts):
        snake_case: str | None = Field(default=None, alias="camelCase")

    assert _Aliased(camelCase="value").to_request_body() == {"camelCase": "value"}


# --- BaseQueryOpts ---


def test_empty_query_opts_returns_empty_dict():
    assert _ListOpts().to_query_params() == {}


def test_query_params_converts_int_to_string():
    opts = _ListOpts(limit=20, marker="abc")
    assert opts.to_query_params() == {"limit": "20", "marker": "abc"}


def test_query_params_preserves_zero():
    assert _ListOpts(limit=0).to_query_params() == {"limit": "0"}


def test_query_params_skips_empty_string():
    opts = _ListOpts(id="", marker="real")
    assert opts.to_query_params() == {"marker": "real"}


def test_query_params_skips_none():
    opts = _ListOpts(id="real-id", limit=None)
    assert opts.to_query_params() == {"id": "real-id"}


def test_query_params_serializes_bool_lowercase():
    class _BoolQuery(BaseQueryOpts):
        active: bool | None = None

    assert _BoolQuery(active=True).to_query_params() == {"active": "true"}
    assert _BoolQuery(active=False).to_query_params() == {"active": "false"}


def test_query_params_rejects_list_value():
    class _BadQuery(BaseQueryOpts):
        tags: list[str] | None = None

    with pytest.raises(InvalidInputError):
        _BadQuery(tags=["a", "b"]).to_query_params()


def test_query_params_rejects_dict_value():
    class _BadQuery(BaseQueryOpts):
        meta: dict[str, str] | None = None

    with pytest.raises(InvalidInputError):
        _BadQuery(meta={"k": "v"}).to_query_params()