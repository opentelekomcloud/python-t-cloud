"""Tests for ``vpcs.get``."""

from __future__ import annotations

from sdk.services.vpc.v1.vpcs import Vpc, get

from tests.unit.conftest import make_response


def test_get_calls_get_with_resource_url(mock_client, vpc_response):
    mock_client.get.return_value = make_response(vpc_response)

    get(mock_client, "vpc-id-1")

    mock_client.get.assert_called_once_with("vpcs/vpc-id-1")


def test_get_returns_parsed_vpc(mock_client, vpc_response):
    mock_client.get.return_value = make_response(vpc_response)

    result = get(mock_client, "vpc-id-1")

    assert isinstance(result, Vpc)
    assert result.id == "vpc-id-1"
    assert result.name == "test-vpc"


def test_get_passes_id_into_url(mock_client, vpc_response):
    mock_client.get.return_value = make_response(vpc_response)

    get(mock_client, "abc-123-xyz")

    mock_client.get.assert_called_once_with("vpcs/abc-123-xyz")
