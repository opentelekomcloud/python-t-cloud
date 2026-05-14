"""Shared fixtures and helpers for unit tests across all services."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_client():
    """``ServiceClient`` mock with ``get/post/put/delete`` recorded.

    Tests typically configure ``return_value`` per call::

        mock_client.post.return_value = make_response({"vpc": {...}})

    Then assert against ``mock_client.<method>.assert_called_once_with(...)``.
    """
    return MagicMock()


def make_response(payload: dict) -> MagicMock:
    """Build a mock ``httpx.Response`` whose ``.json()`` returns ``payload``.

    Imported explicitly by test modules; not a fixture because tests
    typically build several response objects per test (different payloads
    for different calls), and a fixture would force one-per-test.
    """
    resp = MagicMock()
    resp.json.return_value = payload
    return resp
