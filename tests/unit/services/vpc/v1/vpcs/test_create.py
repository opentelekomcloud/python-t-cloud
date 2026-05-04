"""Tests for ``vpcs.create``."""

from __future__ import annotations

from sdk.services.vpc.v1.vpcs import CreateVpcOpts, Vpc, create

from tests.unit.conftest import make_response


def test_create_calls_post_with_wrapped_body(mock_client, vpc_response):
    mock_client.post.return_value = make_response(vpc_response)

    opts = CreateVpcOpts(name="my-vpc", cidr="192.168.0.0/16")
    create(mock_client, opts)

    mock_client.post.assert_called_once_with(
        "vpcs",
        json={"vpc": {"name": "my-vpc", "cidr": "192.168.0.0/16"}},
    )


def test_create_returns_parsed_vpc(mock_client, vpc_response):
    mock_client.post.return_value = make_response(vpc_response)

    result = create(mock_client, CreateVpcOpts(name="my-vpc"))

    assert isinstance(result, Vpc)
    assert result.id == "vpc-id-1"
    assert result.name == "test-vpc"
    assert result.cidr == "192.168.0.0/16"


def test_create_empty_opts_sends_empty_wrapped_body(mock_client, vpc_response):
    mock_client.post.return_value = make_response(vpc_response)

    create(mock_client, CreateVpcOpts())

    mock_client.post.assert_called_once_with("vpcs", json={"vpc": {}})
