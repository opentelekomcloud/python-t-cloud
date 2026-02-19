"""Smoke test — verify the package is importable."""
import sdk

def test_import():

    assert sdk.__version__ == "0.1.0"