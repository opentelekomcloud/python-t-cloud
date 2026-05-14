"""Waiters for eventual consistency and long-running operations."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar, Any

from sdk.core.exceptions import HttpError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def wait_for(
        func: Callable[[], T],
        condition: Callable[[T], bool],
        timeout: int = 60,
        interval: float = 2.0,
        label: str = "resource",
) -> T:
    """Generic waiter that polls 'func' until 'condition' is True."""
    start_time = time.monotonic()

    while True:
        try:
            result = func()
            if condition(result):
                return result
        except Exception as exc:
            logger.debug("Waiter [%s] caught temporary error: %s",
                         label, exc)

        if time.monotonic() - start_time > timeout:
            raise TimeoutError(
                f"Timed out waiting for {label} after {timeout}s"
            )

        time.sleep(interval)


def wait_for_delete(
        get_func: Callable[[], Any],
        timeout: int = 60,
        interval: float = 2.0,
        label: str = "resource",
) -> None:
    """Specialized waiter that polls until the resource returns 404."""
    start_time = time.monotonic()

    while True:
        try:
            get_func()
        except HttpError as exc:
            if exc.status_code == 404:
                return
            raise

        if time.monotonic() - start_time > timeout:
            raise TimeoutError(
                f"Timed out waiting for {label} deletion after {timeout}s"
            )

        time.sleep(interval)
