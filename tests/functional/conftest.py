from __future__ import annotations

from collections.abc import Callable

import httpx

from sdk.core.auth import AuthConfig
from sdk.core.endpoint import CatalogEntry, build_endpoint_locator
from sdk.core.provider import ProviderClient


FAKE_CATALOG = [
    CatalogEntry(
        type="vpc",
        endpoints=[
            {
                "interface": "public",
                "region_id": "eu-de",
                "url": "https://vpc.eu-de.otc.t-systems.com/v1/test-project-id",
            },
        ],
    ),
]


def make_provider(
    handler: Callable[[httpx.Request], httpx.Response],
) -> ProviderClient:
    cfg = AuthConfig(
        identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
        access_key="AK_TEST",
        secret_key="SK_TEST",
        region="eu-de",
    )
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    provider = ProviderClient(cfg, http_client=http_client)

    provider.project_id = "test-project-id"
    provider.token_id = "test-token"
    provider.endpoint_locator = build_endpoint_locator(
        FAKE_CATALOG, "eu-de",
    )

    return provider