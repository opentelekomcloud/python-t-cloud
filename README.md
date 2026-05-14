# python-t-cloud

Python SDK for T-Cloud.

> **Status:** Early development. Not ready for production use.

## Quick Start

```bash
uv sync              # install dependencies
uv run pytest        # run tests
```

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
uv sync --group dev       # install with dev dependencies
uv run ruff check src/    # lint
uv run mypy src/          # type check
uv run pytest -v          # test core
```

## License

Apache-2.0