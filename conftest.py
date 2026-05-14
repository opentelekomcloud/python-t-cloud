# conftest.py at project root — registers the 'acceptance' marker
# and separates acceptance tests from unit tests.

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests under acceptance/ directory."""
    for item in items:
        if "acceptance" in str(item.fspath):
            item.add_marker(pytest.mark.acceptance)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "acceptance: marks tests that hit real T Cloud Public API (deselect with '-m \"not acceptance\"')",
    )
