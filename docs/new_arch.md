# New Python SDK Architecture for OpenTelekomCloud

**Status:** Proposal for review

---

## 1. Problems with Current python-otcextensions

The current Python SDK is built on top of openstacksdk and inherits its architectural decisions, causing systemic issues:

- **Heavy dependencies.** openstacksdk, keystoneauth1, os-service-types and the entire OpenStack ecosystem pull in dozens of transitive dependencies. Updating or debugging any of them affects the entire SDK.
- **Auth model incompatibility.** AK/SK authentication (AWS Signature V4) does not fit well into keystoneauth — SigV4 requires signing an already-formed HTTP request, while keystoneauth provides headers before request formation. Each new service with AK/SK requires individual workarounds.
- **Implicit contracts.** Request and response models are spread across proxy classes and resources with no clear boundary between input parameters and API responses.

---

## 2. Go SDK Architecture Analysis (gophertelekomcloud)

### 2.1. Overall Structure

The Go SDK has a minimalistic structure with **3 dependencies** (testify, golang.org/x/crypto, yaml.v2) and a clean layered organization:

```
gophertelekomcloud/
├── golangsdk (root package)
│   ├── auth_options.go          # AuthOptions — token/password auth
│   ├── auth_aksk_options.go     # AKSKAuthOptions — AK/SK auth
│   ├── auth_option_provider.go  # AuthOptionsProvider — unified interface
│   ├── provider_client.go       # ProviderClient — HTTP client with auth
│   ├── service_client.go        # ServiceClient — base service client
│   ├── endpoint_search.go       # EndpointOpts — endpoint discovery
│   ├── results.go               # Result — base response type
│   ├── params.go                # Parameter serialization utilities
│   └── signer_helper.go         # AK/SK signing (AWS SigV4)
│
├── internal/
│   ├── build/                   # Request body, query strings, headers
│   └── extract/                 # JSON response deserialization
│
├── openstack/
│   ├── client.go                # Factories: NewDNSV2(), NewComputeV2(), etc.
│   ├── common/                  # Shared utilities (tags, metadata, pointerto)
│   │
│   ├── dns/v2/                  # ← Typical service
│   │   ├── clusters/
│   │   │   ├── common.py     # Cluster, Spec, Status (shared models)
│   │   │   ├── create.py     # CreateOpts + create()
│   │   │   ├── get.py        # get()
│   │   │   ├── list.py       # ListOpts + list_clusters()
│   │   │   ├──  delete.py     # DeleteOpts + delete()
│   │   │   └── update.py     # UpdateOpts + update()
│   │   ├── recordsets/
│   │   └── ...
│   │
│   ├── vpc/v1/                  # Each service is isolated
│   ├── cce/v3/
│   ├── elb/v3/
│   └── ... (59+ services)
│
└── pagination/                  # Pagination (linked, marker, offset, single)
```

### 2.2. Key Architectural Patterns

#### Pattern 1: Unified Auth Interface

A minimal `AuthOptionsProvider` interface with a single method `GetIdentityEndpoint()`. Two auth types — `AuthOptions` (token/password) and `AKSKAuthOptions` (AK/SK) — both implement this interface. Dispatch in `Authenticate()` determines the auth type via type assertion and calls the appropriate strategy:

```
AuthOptionsProvider (interface)
   ├── AuthOptions         → v3auth() or v3authWithAgency()
   └── AKSKAuthOptions     → v3AKSKAuth() or authWithAgencyByAKSK()
```

AK/SK signing is applied transparently at the `ProviderClient.Request()` level — if `AKSKAuthOptions.AccessKey` is set, the request is signed via `Sign()` before sending.

#### Pattern 2: Two-Level Client System

- **ProviderClient** — a single HTTP client that holds auth state (token, project ID, domain ID), reauth logic, retry/backoff. All requests go through its `Request()`.
- **ServiceClient** — a lightweight wrapper that adds endpoint and convenience methods (`Get`, `Post`, `Put`, `Patch`, `Delete`). Created via factories in `client.go` (e.g. `NewDNSV2(provider, endpointOpts)`).

#### Pattern 3: Each Resource Is an Isolated Package

Each resource (zones, recordsets, publicips, ...) is a separate package with three files:

| File | Contents |
|------|----------|
| `requests.go` | CRUD functions (free functions, not methods). Input parameter types (`CreateOpts`, `ListOpts`) with builder interfaces (`CreateOptsBuilder`). Validation via struct tags. |
| `results.go` | Response models (`Zone`, `CreateResult`, `GetResult`). Inherit from `golangsdk.Result` for lazy extraction via `Extract()`. |
| `urls.go` | Pure URL construction functions using `ServiceClient.ServiceURL()`. |

Functions take `*ServiceClient` as their first argument — no magic proxies or resource classes.

#### Pattern 4: Minimal External Dependencies

The Go SDK deliberately avoids OpenStack-specific libraries. Everything, including AK/SK signing, is implemented inside the repository. This provides full control and eliminates breaking changes from upstream.

---

## 3. Target Architecture for New Python SDK

### 3.1. Package Structure

```
otc-sdk-python/
├── pyproject.toml               # Minimal deps: httpx, pydantic
│
├── src/sdk/
│   ├── __init__.py
│   │
│   ├── core/                    # ← Analogue of root golangsdk package
│   │   ├── auth.py              # AuthOptions, AKSKAuthOptions, AuthProvider (Protocol)
│   │   ├── signer.py            # AK/SK signing (SigV4) — own implementation
│   │   ├── provider.py          # ProviderClient — HTTP client + auth
│   │   ├── service_client.py    # ServiceClient — base client for services
│   │   ├── endpoint.py          # EndpointOpts, endpoint discovery
│   │   ├── result.py            # Base result types
│   │   ├── exceptions.py        # Exception hierarchy
│   │   └── pagination.py        # Pagination strategies (linked, marker, offset)
│   │
│   ├── services/                # ← Analogue of openstack/
│   │   ├── __init__.py
│   │   │
│   │   ├── dns/                 # Each service is a subpackage
│   │   │   ├── __init__.py
│   │   │   ├── v2/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── client.py    # DnsV2Client with factory methods
│   │   │   │   ├── clusters/
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── common.py     # Cluster, Spec, Status (shared models)
│   │   │   │   │   ├──create.py     # CreateOpts + create()
│   │   │   │   │   ├── get.py        # get()
│   │   │   │   │   ├── list.py       # ListOpts + list_clusters()
│   │   │   │   │   ├──  delete.py     # DeleteOpts + delete()
│   │   │   │   │   └──  update.py     # UpdateOpts + update()
│   │   │   │   ├── recordsets/
│   │   │   │   └── ...
│   │   │   └── ...
│   │   │
│   │   ├── vpc/
│   │   ├── cce/
│   │   ├── elb/
│   │   └── ...
│   │
│   └── common/                  # Shared utilities
│       ├── tags.py
│       └── metadata.py
│
├── tests/
│   ├── unit/
│   │   ├── core/
│   │   └── services/
│   └── acceptance/
│       └── services/
│
└── docs/
```

### 3.2. Core Abstractions

#### AuthConfig

A single config model that accepts all possible auth parameters. The provider auto-detects which auth strategy to use based on what fields are provided:

- `access_key` + `secret_key` present → **AK/SK** (AWS Signature V4)
- `password` present → **Token** (Keystone V3 password auth)
- `token_id` present → **Token** (Keystone V3 token auth)

```python
from pydantic import BaseModel, model_validator

class AuthConfig(BaseModel):
    """Single auth config. Provider auto-selects strategy based on provided fields."""

    identity_endpoint: str

    # Token/Password auth fields
    username: str | None = None
    user_id: str | None = None
    password: str | None = None
    token_id: str | None = None
    domain_id: str | None = None
    domain_name: str | None = None
    tenant_id: str | None = None
    tenant_name: str | None = None
    allow_reauth: bool = False

    # AK/SK auth fields
    access_key: str | None = None
    secret_key: str | None = None
    security_token: str | None = None

    # Common fields
    project_id: str | None = None
    project_name: str | None = None
    region: str | None = None

    # Agency delegation
    agency_name: str | None = None
    agency_domain_name: str | None = None
    delegated_project: str | None = None

    @property
    def auth_mode(self) -> str:
        """Auto-detect auth strategy from provided fields."""
        if self.access_key and self.secret_key:
            return "aksk"
        if self.password:
            return "password"
        if self.token_id:
            return "token"
        raise ValueError("Cannot determine auth mode: provide access_key+secret_key, password, or token_id")

    @model_validator(mode="after")
    def _validate_fields(self):
        # Ensure minimum required fields per strategy
        self.auth_mode  # triggers ValueError if nothing matches
        return self
```

The user never picks a strategy class — they just pass whatever credentials they have.

#### ProviderClient

```python
import httpx

class ProviderClient:
    """Central HTTP client. Manages auth, retry, reauth."""

    def __init__(self, auth: AuthConfig):
        self.auth = auth
        self.identity_endpoint: str = auth.identity_endpoint
        self.token_id: str | None = None
        self.project_id: str | None = None
        self.domain_id: str | None = None
        self._http: httpx.Client = httpx.Client()
        self._reauth_func: Callable | None = None

    def authenticate(self) -> None:
        """Auto-select and execute auth strategy."""
        match self.auth.auth_mode:
            case "aksk":
                self._aksk_auth()
            case "password":
                self._token_auth()
            case "token":
                self._token_reuse()

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send request with auth, retry, reauth."""
        # 1. Add auth headers:
        #    - aksk mode → sign request with AK/SK (SigV4)
        #    - token mode → add X-Auth-Token header
        # 2. Send request
        # 3. Handle 401 → reauth → retry
        # 4. Handle 429 → backoff → retry
        # 5. Handle errors → typed exceptions
        ...
```

#### ServiceClient

```python
class ServiceClient:
    """Base client for a specific service."""

    def __init__(self, provider: ProviderClient, endpoint: str,
                 resource_base: str | None = None):
        self.provider = provider
        self.endpoint = endpoint
        self.resource_base = resource_base or endpoint

    def service_url(self, *parts: str) -> str:
        return self.resource_base + "/".join(parts)

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.provider.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.provider.request("POST", url, **kwargs)

    # put, patch, delete similarly
```

### 3.3. Service Implementation Example (DNS Zones)

#### models.py

```python
from pydantic import BaseModel

class CreateZoneOpts(BaseModel):
    name: str
    email: str | None = None
    description: str | None = None
    ttl: int | None = None
    zone_type: str | None = None

class Zone(BaseModel):
    id: str
    name: str
    email: str | None = None
    description: str | None = None
    ttl: int | None = None
    status: str | None = None
    zone_type: str | None = None
    record_num: int | None = None
    pool_id: str | None = None
    project_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

class ListZonesOpts(BaseModel):
    limit: int | None = None
    marker: str | None = None
    name: str | None = None
    status: str | None = None
    type: str | None = None
```

#### urls.py

```python
from otc_sdk.core.service_client import ServiceClient

ROOT = "zones"

def base_url(client: ServiceClient) -> str:
    return client.service_url(ROOT)

def zone_url(client: ServiceClient, zone_id: str) -> str:
    return client.service_url(ROOT, zone_id)
```

#### requests.py

```python
from typing import Iterator
from otc_sdk.core.service_client import ServiceClient
from .models import CreateZoneOpts, Zone, ListZonesOpts
from . import urls

def create(client: ServiceClient, opts: CreateZoneOpts) -> Zone:
    resp = client.post(
        urls.base_url(client),
        json=opts.model_dump(exclude_none=True),
    )
    return Zone.model_validate(resp.json())

def get(client: ServiceClient, zone_id: str) -> Zone:
    resp = client.get(urls.zone_url(client, zone_id))
    return Zone.model_validate(resp.json())

def list_zones(client: ServiceClient, opts: ListZonesOpts | None = None) -> Iterator[Zone]:
    """Iterator that automatically walks through all pages."""
    url = urls.base_url(client)
    params = opts.model_dump(exclude_none=True) if opts else {}
    while url:
        resp = client.get(url, params=params)
        data = resp.json()
        for z in data["zones"]:
            yield Zone.model_validate(z)
        url = data.get("links", {}).get("next")
        params = {}  # params already embedded in next URL

def delete(client: ServiceClient, zone_id: str) -> None:
    client.delete(urls.zone_url(client, zone_id))
```

> **Proposal: Generator-based pagination.** In Go, pagination uses `pagination.Pager` with callbacks. In Python, the natural approach is an iterator with `yield` that automatically fetches subsequent pages. The user should never have to think about markers:
>
> ```python
> for zone in zones.list_zones(client):
>     print(zone.name)
> ```

### 3.4. Client Factory

```python
# otc_sdk/client.py — main entry point

class OTCClient:
    """Main entry point. Creates ProviderClient and service factories."""

    def __init__(self, **kwargs):
        """Accept auth params directly. Provider auto-detects strategy.

        Usage:
            OTCClient(identity_endpoint="...", username="...", password="...")
            OTCClient(identity_endpoint="...", access_key="...", secret_key="...")
        """
        auth = AuthConfig(**kwargs)
        self.provider = ProviderClient(auth)
        self.provider.authenticate()

    def dns_v2(self, region: str | None = None) -> ServiceClient:
        endpoint = self.provider.find_endpoint("dns", region=region)
        return ServiceClient(self.provider, endpoint,
                             resource_base=endpoint + "v2/")

    def vpc_v1(self, region: str | None = None) -> ServiceClient:
        ...
```

> **Proposal: Lazy imports for services.** Eagerly importing all 50+ services in `__init__.py` would slow down `import otc_sdk`. Instead, use lazy properties that import a service only on first access:
>
> ```python
> class OTCClient:
>     @property
>     def dns(self):
>         from otc_sdk.services.dns.v2 import client as dns_client
>         return dns_client.DnsV2Client(self.provider)
> ```
>
> This ensures fast application startup — only services that are actually used get imported. No entry point or plugin magic needed.

### 3.5. Usage Example

```python
from otc_sdk import OTCClient
from otc_sdk.services.dns.v2 import zones

# Token authentication — just pass credentials, provider figures out the rest
client = OTCClient(
    identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
    username="user",
    password="pass",
    domain_name="domain",
    tenant_name="eu-de",
)

# Or AK/SK — same constructor, different fields
client = OTCClient(
    identity_endpoint="https://iam.eu-de.otc.t-systems.com/v3",
    access_key="AK...",
    secret_key="SK...",
    project_id="...",
    region="eu-de",
)

# API works identically regardless of auth type
dns = client.dns_v2()
zone = zones.create(dns, zones.CreateZoneOpts(name="example.com.", email="admin@example.com"))

for z in zones.list_zones(dns):
    print(z.name)
```

---

## 4. Go → Python Mapping

| Go SDK | Python SDK | Notes |
|--------|-----------|-------|
| `AuthOptionsProvider` (interface) | `AuthConfig` (single pydantic model) | Auto-detects strategy from fields |
| `AuthOptions` + `AKSKAuthOptions` (separate structs) | `AuthConfig.auth_mode` property | User never picks strategy manually |
| `ProviderClient` | `ProviderClient` | httpx instead of net/http |
| `ServiceClient` | `ServiceClient` | Thin wrapper |
| `Sign()` | `sign_request()` | Own SigV4 implementation |
| `openstack/client.go` (factories) | `OTCClient` | Factory methods |
| `openstack/dns/v2/zones/` package | `services/dns/v2/zones/` package | 1:1 mapping |
| `requests.go` (free functions) | `requests.py` (free functions) | Not class methods |
| `results.go` (struct + Extract) | `models.py` (pydantic BaseModel) | model_validate instead of Extract |
| `urls.go` | `urls.py` | Pure functions |
| `CreateOptsBuilder` (interface) | pydantic `BaseModel` | Validation via pydantic |
| struct tags (`json:`, `q:`, `required:`) | pydantic Field + model_dump | exclude_none for optionals |
| `golangsdk.Result.ExtractInto()` | `pydantic.BaseModel.model_validate()` | Automatic deserialization |
| `pagination.Pager` | Iterator/generator | Pythonic approach |
| `go.mod` (3 dependencies) | `pyproject.toml` (httpx + pydantic) | Minimal dependencies |

---

## 5. Dependencies

| Dependency | Purpose | Notes |
|------------|---------|-------|
| `httpx` | HTTP client | Sync + async out of the box. MVP is sync-only, architecture is async-ready |
| `pydantic` | Model validation | Replaces Go struct tags |

Everything else (SigV4 signing, retry, pagination) is **implemented internally**. No openstacksdk, keystoneauth, or os-service-types.

### 5.1. Dev Tooling: uv

We use [uv](https://docs.astral.sh/uv/) as the project manager. uv is a Rust-based drop-in replacement for pip, virtualenv, and poetry — 10–50x faster, single binary, no Python required to bootstrap.

`pyproject.toml` remains the standard project config file. uv simply reads it and handles everything else:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "otc-sdk"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-httpx>=0.30",
    "ruff>=0.5",
    "mypy>=1.10",
]
```

Daily workflow:

```bash
# Setup (replaces python -m venv + pip install -e .)
uv sync                          # creates .venv + installs everything from pyproject.toml
uv sync --group dev              # includes dev dependencies

# Running
uv run pytest                    # runs in the correct venv automatically
uv run mypy src/                 # type checking
uv run ruff check src/           # linting

# Dependency management
uv add httpx                     # adds to pyproject.toml + installs
uv remove some-package           # removes from pyproject.toml + uninstalls

# Python version management (optional)
uv python install 3.12           # installs Python 3.12 if not present
uv python pin 3.12               # pins project to 3.12
```

uv generates a `uv.lock` file (replaces `poetry.lock` / `pip-compile` output) — deterministic, cross-platform lock file that should be committed to the repository.

Why uv over poetry/pip:
- **Speed.** Cold install of the project takes ~1s instead of 15–30s.
- **Standards-based.** Uses standard `pyproject.toml`, no vendor lock-in. The project works with plain `pip install -e .` for anyone who doesn't want uv.
- **Single tool.** Replaces pip + virtualenv + pip-tools + pyenv. Simplifies CI and onboarding.

---

## 6. Principles

1. **Zero service coupling.** Each service is an isolated subpackage. Depends only on `core/`.
2. **Explicit contracts.** Typed pydantic models for every request and response. No `dict` or `**kwargs` in the public API.
3. **Own auth implementation.** Single `AuthConfig` model — provider auto-detects strategy (AK/SK, password, token) from the fields provided. SigV4 signing implemented inside the SDK. The user never needs to know which auth class to use.
4. **Free functions for operations.** `zones.create(client, opts)` instead of `client.zones.create(opts)`. Follows the Go pattern — easier to test and generate.
5. **Minimal dependencies.** Only httpx + pydantic. Full control over the codebase.
6. **Type hinting & IDE support.** 100% type hint coverage thanks to pydantic and explicit function signatures.

> **Proposal: Functional style justification.** The functional approach may look unusual to Python developers accustomed to boto3 or azure-sdk (`client.zones.create(opts)`). However, free functions are stateless — `create`, `list` are pure and take a client as a dependency. This simplifies mocking in tests, eliminates circular imports, and dramatically simplifies code generation. We keep the functional approach.

> **Proposal: Type hinting as a selling point.** In the current SDK (dynamic proxies from openstacksdk), autocomplete in VS Code and PyCharm barely works. In the new SDK — pydantic models with typed fields + explicit function signatures mean IDEs will suggest `CreateZoneOpts` fields and `Zone` response field types. This is a significant developer experience improvement.

---

## 7. Code Generation Benefits (gen-sdk-tooling)

This architecture is well suited for automatic SDK generation from RST documentation:

- **Uniform structure** for every service → Jinja2 templates for `models.py`, `requests.py`, `urls.py`.
- **Pydantic models** are generated directly from request/response specs found in RST.
- **Free functions** instead of classes → simpler templates, less inheritance.
- **No OpenStack dependency** → no need to maintain compatibility with external code.

---

## 8. Implementation Plan

### Phase 1: Core (2–3 weeks)

- `core/auth.py` — AuthConfig with auto-detection (AK/SK, password, token)
- `core/signer.py` — AK/SK signing (ported from Go)
- `core/provider.py` — ProviderClient with auth, retry, reauth
- `core/service_client.py` — ServiceClient
- `core/exceptions.py` — exception hierarchy
- `core/pagination.py` — pagination strategies

### Phase 2: Pilot Service (1–2 weeks)

- Implement DNS v2 manually as a reference
- Write acceptance tests against real OTC
- Debug auth flow for both token and AK/SK

### Phase 3: Generation (parallel with gen-sdk-tooling)

- Jinja2 templates for models.py, requests.py, urls.py
- Generate SDK for 2–3 services, compare with reference
- Iterate on generation quality

### Phase 4: Scaling

- Generate remaining 50+ services
- CI/CD pipeline for automatic regeneration

---

## 9. Decisions on Open Questions

> **Proposal:** Close the open questions with the following decisions so this section reads as an action plan rather than uncertainty.

1. **Async support.**
   *Decision:* MVP (Phases 1–2) implements sync API only (`httpx.Client`). The architecture is async-ready: httpx has an identical API for sync and async, and free functions allow adding `async def create(...)` + `httpx.AsyncClient` later with minimal generator changes (template swap).

2. **Package naming.**
   *Decision:* `otc-sdk` (PyPI) / `import otc_sdk`. Short and clear. `otcextensions` is a bad legacy name.

3. **Service discovery.**
   *Decision:* Lazy properties in `OTCClient` (see proposal in section 3.4). Only services that are actually used get imported. No entry points or plugin magic.

4. **Backward compatibility.**
   *Decision:* Full replacement (major version). Maintaining compatibility with the openstacksdk architecture is impossible and counterproductive — it is the root of the problems. The old and new SDKs can be installed side by side (`pip install otc-sdk` alongside `pip install python-otcextensions`).

5. **Paginators.**
   *Decision:* Python iterators with `yield` (see proposal in section 3.3). `for zone in zones.list_zones(client)` — automatic traversal of all pages.