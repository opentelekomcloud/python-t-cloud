"""Service client factories for acceptance tests.

Centralised here so that adding support for a new service in tests is
just one new fixture line rather than copying provider/auth setup.

To add a client for a new service:

1. Add a fixture in your test's ``conftest.py`` (typically alongside the
   test files, e.g. ``tests/acceptance/services/<svc>/conftest.py``)::

       from tests.acceptance.clients import make_service_client

       @pytest.fixture
       def dns_client(provider):
           return make_service_client(provider, "dns")

2. Use it in tests like any other fixture::

       def test_something(dns_client):
           ...

If a service needs a custom region, microversion, or extra headers,
pass them through to ``make_service_client`` - it forwards keyword
arguments to ``ServiceClient``.
"""

from __future__ import annotations

from sdk.core.provider import ProviderClient
from sdk.core.service_client import ServiceClient


def make_service_client(
    provider: ProviderClient,
    service_type: str,
    **kwargs,
) -> ServiceClient:
    """Build a :class:`ServiceClient` for the given service type.

    Extra keyword arguments are forwarded to :class:`ServiceClient`
    (``region``, ``microversion``, ``endpoint_override``, ...).
    """
    return ServiceClient(provider, service_type=service_type, **kwargs)
