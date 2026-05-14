"""Tests for ``vpcs.update``."""

from __future__ import annotations

from sdk.services.vpc.v1.vpcs import Route, UpdateVpcOpts, Vpc, update

from tests.unit.conftest import make_response


def test_update_calls_put_with_resource_url(mock_client, vpc_response):
    mock_client.put.return_value = make_response(vpc_response)

    update(mock_client, "vpc-id-1", UpdateVpcOpts(name="renamed"))

    mock_client.put.assert_called_once_with(
        "vpcs/vpc-id-1",
        json={"vpc": {"name": "renamed"}},
    )


def test_update_clear_description_sends_empty_string(mock_client, vpc_response):
    """Sending ``description=""`` clears the field on the server."""
    mock_client.put.return_value = make_response(vpc_response)

    update(mock_client, "vpc-id-1", UpdateVpcOpts(description=""))

    mock_client.put.assert_called_once_with(
        "vpcs/vpc-id-1",
        json={"vpc": {"description": ""}},
    )


def test_update_with_routes_serializes_nested(mock_client, vpc_response):
    mock_client.put.return_value = make_response(vpc_response)

    update(
        mock_client,
        "vpc-id-1",
        UpdateVpcOpts(
            routes=[Route(destination="10.0.0.0/8", nexthop="192.168.1.1")],
        ),
    )

    mock_client.put.assert_called_once_with(
        "vpcs/vpc-id-1",
        json={
            "vpc": {
                "routes": [
                    {"destination": "10.0.0.0/8", "nexthop": "192.168.1.1"},
                ]
            }
        },
    )


def test_update_returns_parsed_vpc(mock_client, vpc_response):
    mock_client.put.return_value = make_response(vpc_response)

    result = update(mock_client, "vpc-id-1", UpdateVpcOpts(name="renamed"))

    assert isinstance(result, Vpc)
    assert result.id == "vpc-id-1"


def test_update_empty_opts_sends_empty_wrapped_body(mock_client, vpc_response):
    mock_client.put.return_value = make_response(vpc_response)

    update(mock_client, "vpc-id-1", UpdateVpcOpts())

    mock_client.put.assert_called_once_with(
        "vpcs/vpc-id-1",
        json={"vpc": {}},
    )
