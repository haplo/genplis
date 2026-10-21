# AGENTS.md

This document provides essential information for agentic coding agents working in the genplis repository.

## Project Overview

Genplis is a Python 3.12+ music playlist generator that:
- Parses music file tags using TinyTag
- Caches tag data in SQLite database
- Processes M3UG filter files to generate M3U playlists
- Uses a custom domain-specific language for filtering

## Development Commands

### Testing
```bash
# Run all tests
uv run python -m pytest

# Run specific test file
uv run python -m pytest tests/test_core.py

# Run single test function
uv run python -m pytest tests/test_core.py::test_process_audio_file

# Run with verbose output
uv run python -m pytest -v

# Run with coverage
uv run python -m pytest --cov=genplis
```

### Code Quality
```bash
# Run ty type checker
uv run ty check

# Run ty in watch mode
uv run ty check --watch

# Run ruff linter (with auto-fix)
uv run ruff check --fix .

# Run ruff formatter
uv run ruff format .

# Run pre-commit hooks on staged files only (run after staging, before committing)
uv run pre-commit run

# Run pre-commit hooks on all files
uv run pre-commit run --all-files

# Install pre-commit hooks (run once)
uv run pre-commit install
```

### Building
```bash
# Build package
uv run python -m build

# Install in development mode
uv run python -m pip install -e .
```

### Running the Application
```bash
# Run genplis on music directory
uv run genplis /path/to/music

# Run with verbose output
uv run genplis -v /path/to/music

# Run with exclude patterns
uv run genplis -e "pattern1" -e "pattern2" /path/to/music

# Display tags for specific file
uv run genplis /path/to/music/file.mp3
```

## Code Style Guidelines

### Python Version & Runtime
- Minimum Python 3.12 required (3.10 and 3.11 are untested and unsupported)
- Use modern type hints (PEP 604 union types: `str | None`)
- Prefer pathlib over os.path
- Use f-strings for string formatting

### Import Organization
- Standard library imports first
- Third-party imports second
- Local imports third
- Use `isort` conventions (configured in ruff)
- Known first-party: `genplis`
- Known third-party: `tinytag` (temporary)

Example:
```python
import argparse
import sqlite3
from pathlib import Path

import pytest
import tinytag

from genplis.core import process_file
from genplis.exceptions import GenplisError
```

### Type Hints
- Always use type hints for function signatures; Ruff's `ANN` rules enforce this
- ty is deliberately floating: `[tool.uv] upgrade-package` lets `uv lock`
  select the newest releases allowed by uv's `exclude-newer` window
  (currently 7 days). Do not pin them in `pyproject.toml` or pre-commit.
- Use `dict`, `list`, `tuple` instead of `Dict`, `List`, `Tuple`
- Use the aliases from `genplis.types`: `TagValue` for a single tag value and
  `Tags` for a mapping of tag names to values
- Use PEP 695 `type` statements for new type aliases
- Use `TypeGuard` for helpers that narrow types (e.g. `is_number`)
- Use `Self` for classmethod constructors that return `cls(...)`
- Avoid `Any` in annotations (`ANN401`); prefer `object` plus narrowing
- Use `Path` for file paths, not strings

### Error Handling
- Custom exceptions inherit from `GenplisError` base class
- Use specific exception types: `GenplisDBError`, `GenplisM3UGException`
- Always include context in error messages
- Handle expected errors gracefully, propagate unexpected ones

### Naming Conventions
- Functions: snake_case with descriptive names
- Variables: snake_case, prefer clarity over brevity
- Constants: UPPER_SNAKE_CASE
- Classes: PascalCase
- Private methods: underscore prefix

### Database Patterns
- Use context managers for connections: `with conn:`
- Always close cursors explicitly or use context managers
- Use parameterized queries to prevent SQL injection
- Follow XDG Base Directory spec for cache location

### File Processing
- Check file support before processing: `TinyTag.is_supported()`
- Skip tag values whose combined UTF-8 length exceeds `[tags] max_size`
  (default 1000 bytes, `0` disables the limit) to avoid memory issues;
  calculated audio properties are exempt
- Use file modification time for cache invalidation
- Handle both files and directories in core functions

### Testing Patterns
- Use pytest fixtures for test data and database setup
- Test both success and error cases
- Use session-scoped fixtures for expensive setup
- Test with real media files in `tests/files/`
- Mock external dependencies when appropriate

### Code Structure
- Main entry point: `src/genplis/__main__.py`
- Core logic: `src/genplis/core.py`
- Parsing executors: `src/genplis/executors.py`
- Configuration loading: `src/genplis/config.py`
- Database operations: `src/genplis/db.py`
- Tag parsing: `src/genplis/tags.py`
- M3UG parsing: `src/genplis/m3ug.py`
- M3U generation: `src/genplis/m3u.py`
- Exceptions: `src/genplis/exceptions.py`
- Shared type aliases: `src/genplis/types.py`

### Documentation
- Use docstrings for all public functions and classes
- Keep comments concise and relevant
- User documentation lives in `docs/`: `usage.md`, `m3ug.md`, `config.md`,
  `tags.md`, `scheduling.md`, `dev.md`
- Update README.md and the relevant docs/ page for user-facing changes; keep
  README short and link to docs with absolute GitHub URLs
- Use TODO comments in code for future improvements

### Performance Considerations
- Cache parsed tags in SQLite database
- Parsing may run in worker processes (`executors.py`); keep all DB access in
  the main process and never pass a connection to a worker
- Merge parallel parse results back into walk order so playlists follow the
  directory walk; normal runs release tags after filtering instead of keeping
  an `all_tags` map
- Filter out oversized tag values early (UTF-8 bytes, see `[tags] max_size`)
- Use pathlib for efficient path operations
- Consider memory usage for large music collections

### Staging and Committing
- Run `uv run pre-commit run` every time you stage files, before handing
  them off to be committed. With no arguments pre-commit only checks the
  files in the index, so run it again after staging further changes.
- Fix any hook failures and re-stage the affected files; do not commit with
  failing hooks.
- Use `uv run pre-commit run --all-files` to validate the whole repository
  when hooks or configuration change. The `ty` hook checks the whole project
  even when only some files are staged, and uses the ty version from
  `uv.lock`.

### Development Workflow
1. Write tests first (TDD when possible)
2. Run ruff linting and formatting before commits
3. Run `uv run ty check` and fix any diagnostics
4. Use pre-commit hooks to enforce code quality
5. Run `uv run pre-commit run` after staging files, before they are committed
6. Test with real music files when possible
7. Update documentation when adding new features
8. Use uv for dependency management

## Important Files

- `pyproject.toml`: Project configuration, dependencies, tool settings
- `.pre-commit-config.yaml`: Pre-commit hooks configuration
- `src/genplis/`: Main source code directory
- `src/genplis/types.py`: Shared type aliases (`TagValue`, `Tags`)
- `src/genplis/py.typed`: PEP 561 marker for typed package consumers
- `tests/`: Test files and fixtures
- `examples/`: Sample M3UG filter files and the annotated `config.ini`
- `docs/`: User and developer documentation (`usage.md`, `m3ug.md`,
  `config.md`, `tags.md`, `scheduling.md`, `dev.md`)
