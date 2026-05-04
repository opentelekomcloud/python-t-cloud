"""Tests for ``vpcs.delete``."""

from __future__ import annotations

from sdk.services.vpc.v1.vpcs import delete


def test_delete_calls_delete_with_resource_url(mock_client):
    delete(mock_client, "vpc-id-1")
    mock_client.delete.assert_called_once_with("vpcs/vpc-id-1")


def test_delete_returns_none(mock_client):
    result = delete(mock_client, "vpc-id-1")
    assert result is None


def test_delete_passes_id_into_url(mock_client):
    delete(mock_client, "abc-123-xyz")
    mock_client.delete.assert_called_once_with("vpcs/abc-123-xyz")
