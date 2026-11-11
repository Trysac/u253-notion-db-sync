# notion-db-sync

[![PyPI version](https://img.shields.io/pypi/v/trysac-notion-db-sync)](https://pypi.org/project/trysac-notion-db-sync/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-notion-db-sync)](LICENSE)
[![CI](https://github.com/Trysac/u253-notion-db-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u253-notion-db-sync/actions/workflows/ci.yml)

Pull a Notion database into local Markdown files with front matter: incremental by last edit time, deletions mirrored and local edits detected as conflicts, never overwritten

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-notion-db-sync
# or
uv add trysac-notion-db-sync
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import notion_db_sync

# normalize() trims surrounding whitespace and lower-cases the text.
print(notion_db_sync.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    notion_db_sync.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
