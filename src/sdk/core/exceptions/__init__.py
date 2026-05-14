"""Exception hierarchy for the SDK.

Hierarchy::

    SDKError
    ├── MissingInputError
    ├── InvalidInputError
    ├── AuthError
    │   ├── MissingCredentialsError
    │   ├── ReauthError
    │   └── PostReauthError
    ├── EndpointError
    │   ├── ServiceNotFoundError
    │   └── EndpointNotFoundError
    ├── HttpError
    │   ├── BadRequestError          (400)
    │   ├── UnauthorizedError        (401)
    │   ├── ForbiddenError           (403)
    │   ├── NotFoundError            (404)
    │   ├── MethodNotAllowedError    (405)
    │   ├── RequestTimeoutError      (408)
    │   ├── ConflictError            (409)
    │   ├── TooManyRequestsError     (429)
    │   ├── InternalServerError      (500)
    │   └── ServiceUnavailableError  (503)
    ├── ResourceNotFoundError
    ├── MultipleResourcesFoundError
    └── SDKTimeoutError
"""

from .auth import (
    AuthError,
    MissingCredentialsError,
    PostReauthError,
    ReauthError,
)
from .base import (
    InvalidInputError,
    MissingInputError,
    SDKError,
)
from .endpoint import (
    EndpointError,
    EndpointNotFoundError,
    ServiceNotFoundError,
)
from .response import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    HttpError,
    InternalServerError,
    MethodNotAllowedError,
    NotFoundError,
    RequestTimeoutError,
    ServiceUnavailableError,
    TooManyRequestsError,
    UnauthorizedError,
    raise_for_status,
)
from .lookup import (
    MultipleResourcesFoundError,
    ResourceNotFoundError,
)
from .timeout import SDKTimeoutError

__all__ = [
    # base
    "SDKError",
    "MissingInputError",
    "InvalidInputError",
    # auth
    "AuthError",
    "MissingCredentialsError",
    "ReauthError",
    "PostReauthError",
    # endpoint
    "EndpointError",
    "ServiceNotFoundError",
    "EndpointNotFoundError",
    # response
    "HttpError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
    "MethodNotAllowedError",
    "RequestTimeoutError",
    "ConflictError",
    "TooManyRequestsError",
    "InternalServerError",
    "ServiceUnavailableError",
    "raise_for_status",
    # lookup
    "ResourceNotFoundError",
    "MultipleResourcesFoundError",
    # timeout
    "SDKTimeoutError",
]
