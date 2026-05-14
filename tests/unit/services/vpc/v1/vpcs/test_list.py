"""Tests for ``vpcs.list``.

``marker_paginate`` is mocked at the module level since pagination
itself is covered by its own unit tests in ``tests/unit/core``.
These tests only verify that ``list()`` wires its arguments correctly.
"""

from __future__ import annotations

from sdk.services.vpc.v1.vpcs import ListVpcsOpts, Vpc, list as vpcs_list


def test_list_passes_correct_path_and_model(mocker, mock_client):
    paginate = mocker.patch(
        "sdk.services.vpc.v1.vpcs.list.marker_paginate",
        return_value=iter([]),
    )

    vpcs_list(mock_client)

    paginate.assert_called_once()
    kwargs = paginate.call_args.kwargs
    assert kwargs["client"] is mock_client
    assert kwargs["path"] == "vpcs"
    assert kwargs["items_key"] == "vpcs"
    assert kwargs["model"] is Vpc
    assert kwargs["marker_key"] == "id"


def test_list_without_opts_passes_no_params_and_zero_limit(mocker, mock_client):
    paginate = mocker.patch(
        "sdk.services.vpc.v1.vpcs.list.marker_paginate",
        return_value=iter([]),
    )

    vpcs_list(mock_client)

    kwargs = paginate.call_args.kwargs
    assert kwargs["params"] is None
    assert kwargs["limit"] == 0


def test_list_with_opts_passes_query_params(mocker, mock_client):
    paginate = mocker.patch(
        "sdk.services.vpc.v1.vpcs.list.marker_paginate",
        return_value=iter([]),
    )

    opts = ListVpcsOpts(id="vpc-1", marker="m")
    vpcs_list(mock_client, opts)

    kwargs = paginate.call_args.kwargs
    assert kwargs["params"] == {"id": "vpc-1", "marker": "m"}


def test_list_with_positive_limit_forwards_it(mocker, mock_client):
    paginate = mocker.patch(
        "sdk.services.vpc.v1.vpcs.list.marker_paginate",
        return_value=iter([]),
    )

    vpcs_list(mock_client, ListVpcsOpts(limit=50))

    kwargs = paginate.call_args.kwargs
    assert kwargs["limit"] == 50
    # And it appears in params too — that's correct per the T Cloud Public API.
    assert kwargs["params"] == {"limit": "50"}


def test_list_with_none_limit_sends_zero(mocker, mock_client):
    """``limit=None`` (default) keeps the explicit-limit guard at zero.

    This is the lesson from the marker_paginate infinite-loop bug:
    forwarding a falsy limit blindly is dangerous, so the function
    coerces to 0 when the caller did not set one.
    """
    paginate = mocker.patch(
        "sdk.services.vpc.v1.vpcs.list.marker_paginate",
        return_value=iter([]),
    )

    vpcs_list(mock_client, ListVpcsOpts(marker="m"))

    kwargs = paginate.call_args.kwargs
    assert kwargs["limit"] == 0


def test_list_returns_paginate_result(mocker, mock_client):
    """``list()`` is a thin pass-through: returns whatever paginate yields."""
    sentinel = iter(["one", "two"])
    mocker.patch(
        "sdk.services.vpc.v1.vpcs.list.marker_paginate",
        return_value=sentinel,
    )

    result = vpcs_list(mock_client)

    assert list(result) == ["one", "two"]
