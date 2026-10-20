# AGENTS.md

This document provides essential information for agentic coding agents working in the genplis repository.

## Project Overview

Genplis is a Python 3.10+ music playlist generator that:
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
# Run ruff linter (with auto-fix)
uv run ruff check --fix .

# Run ruff formatter
uv run ruff format .

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
- Minimum Python 3.10 required
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
- Always use type hints for function signatures
- Use `dict`, `list`, `tuple` instead of `Dict`, `List`, `Tuple`
- Use `Value = str | float | int | list[str] | None` pattern for tag values
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
- Skip files with large tags (>1000 bytes) to avoid memory issues
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
- Database operations: `src/genplis/db.py`
- Tag parsing: `src/genplis/tags.py`
- M3UG parsing: `src/genplis/m3ug.py`
- M3U generation: `src/genplis/m3u.py`
- Exceptions: `src/genplis/exceptions.py`

### Documentation
- Use docstrings for all public functions and classes
- Keep comments concise and relevant
- Update README.md for user-facing changes
- Use TODO comments in code for future improvements

### Performance Considerations
- Cache parsed tags in SQLite database
- Filter out large tags (>1000 bytes) early
- Use pathlib for efficient path operations
- Consider memory usage for large music collections
- Database operations use WAL mode for better concurrency

### Development Workflow
1. Write tests first (TDD when possible)
2. Run ruff linting and formatting before commits
3. Use pre-commit hooks to enforce code quality
4. Test with real music files when possible
5. Update documentation when adding new features
6. Use uv for dependency management

## Important Files

- `pyproject.toml`: Project configuration, dependencies, tool settings
- `.pre-commit-config.yaml`: Pre-commit hooks configuration
- `src/genplis/`: Main source code directory
- `tests/`: Test files and fixtures
- `examples/`: Sample M3UG filter files for reference
