# Development guide

This page covers setting up a development environment, running the checks, the
project layout, and how the cache and filter engine work internally. User
documentation lives in the other files under `docs/`; start at the
[README](https://github.com/haplo/genplis/blob/main/README.md) for the user
view.

## Setup

Install [uv](https://github.com/astral-sh/uv) first, then:

```bash
git clone https://github.com/haplo/genplis.git
cd genplis
uv sync
uv run pre-commit install
```

`uv sync` creates the virtual environment and installs both runtime and
development dependencies. `pre-commit install` makes the hooks run
automatically on commit.

## Project layout

```text
src/genplis/
    __main__.py     entry point for `genplis` / `python -m genplis`
    core.py         CLI, config merging, directory walking, filtering
    executors.py    sequential and process-pool tag parsing
    config.py       INI loading and validation
    db.py           SQLite cache
    tags.py         tag extraction and calculated properties
    m3ug.py         filter parser and rule nodes
    m3u.py          playlist writer
    files.py        modification-time helper
    json.py         JSON encoder for cached tags
    exceptions.py   exception hierarchy
    types.py        shared type aliases
tests/              pytest suite and real media fixtures
examples/           working .m3ug files and the annotated config
docs/               user and developer documentation
```

## Data flow

A directory run goes through these stages:

```text
resolve config + CLI arguments
        ↓
open/create SQLite cache
        ↓
walk PATH (prune excluded directories)
        ↓
for each file:
    .m3ug  → parse rules in the main process
    audio  → cache hit? reuse : queue for parsing
        ↓
parse queued files (inline, or in worker processes)
        ↓
write results through one WriteBatch in the main process
        ↓
rebuild all_tags in walk order
        ↓
for each .m3ug file:
    apply all rules to all audio files found in this run
        ↓
if any matches: write <stem>.m3u next to the .m3ug file
```

Rules are ANDed: `core.filter_songs` stops at the first failing rule. Each
`RuleNode` looks up its tag, normalizes multi-value tags, and calls its own
`check()`.

## Parallel parsing

`core.process_directory` walks and checks the cache in the main process. With
`--jobs 1`, it calls `core.process_file` inline during the walk and keeps the
old per-file verbose order. With more workers it resolves cache hits during
the walk and queues misses and stale files. If fewer than
`executors.MIN_PARALLEL_FILES` files are queued, `SequentialExecutor` parses
them in the main process after the walk; otherwise `ProcessExecutor` sends
`ParseItem` batches to worker processes. In both `--jobs > 1` cases the
miss/stale diagnostics are printed after the walk.

Invariants:

- **One SQLite connection and one writer, in the main process.** Workers never
  open or receive the connection. Pool contexts are `forkserver` on POSIX and
  `spawn` on Windows, never plain `fork`, so a worker cannot inherit the
  database file descriptor.
- **Workers only parse tags.** They return tags and verbose messages. M3UG
  parsing, filtering, playlist generation, cache reads, and cache writes stay
  in the main process.
- **Playlist order is walk order.** Cache hits are resolved during the walk and
  misses arrive later, so `all_tags` is rebuilt from the recorded path order
  before filtering. Results are consumed in submission order, so verbose lines
  and cache rows stay in walk order for the files that needed parsing.
- **`--jobs 1` is the old inline path.** It uses the same `WriteBatch` plumbing,
  so output, cache contents, and playlist bytes do not change.
- **Flush points.** `WriteBatch` commits every `core.COMMIT_EVERY` writes
  (currently 128) and flushes at the end of the parse phase, on errors, and on
  `KeyboardInterrupt`; an interrupted pool is shut down with
  `cancel_futures=True` and `wait=False` so it cannot hang the process.

To benchmark, use a cache database on the real filesystem, not a tmpfs, and
compare the cold paths three times each. Checksum the playlists to confirm that
they are byte-identical:

```bash
rm -f ~/.cache/genplis/b-seq.db
/usr/bin/time -f '%e s, %M KiB' \
    uv run genplis --db ~/.cache/genplis/b-seq.db --jobs 1 ~/Music
sha256sum ~/Music/*.m3u

rm -f ~/.cache/genplis/b-auto.db
/usr/bin/time -f '%e s, %M KiB' \
    uv run genplis --db ~/.cache/genplis/b-auto.db ~/Music
sha256sum ~/Music/*.m3u

rm -f ~/.cache/genplis/b-warm.db
uv run genplis --db ~/.cache/genplis/b-warm.db ~/Music
/usr/bin/time -f '%e s, %M KiB' \
    uv run genplis --db ~/.cache/genplis/b-warm.db ~/Music
```

Run each configuration three times and take the median; first runs include
page-cache cold effects. The worker count defaults to the CPU affinity count
capped at eight; `[general] jobs` and `--jobs` override it.

## Running

```bash
uv run genplis ~/Music
uv run genplis --verbose ~/Music
uv run genplis /path/to/song.mp3
uv run python -m genplis ~/Music
```

## Tests

The suite uses pytest with fixtures in `tests/conftest.py`. Real MP3 and Ogg
files live in `tests/files/`, along with a sample `.m3ug` file. Tests that
generate playlists copy the media files to `tmp_path` so nothing is written
into the repository.

```bash
# Whole suite
uv run python -m pytest

# One file
uv run python -m pytest tests/test_m3ug.py

# One test
uv run python -m pytest tests/test_m3ug.py::test_multiple_rules

# Verbose
uv run python -m pytest -v

# Coverage (same flags CI uses)
uv run python -m pytest --cov=genplis --cov-branch --cov-report=term-missing
```

The tests also load the shipped `examples/config.ini`, so a broken example
fails CI instead of silently rotting.

### Testing patterns

- Use the session-scoped `file_mp3`, `file_ogg`, and `file_m3ug` fixtures
  instead of rebuilding paths.
- Use `tmp_path` and copy fixtures when a test writes playlists or modifies
  mtimes.
- Use the `make_args` fixture to build `core.Args` without going through
  argparse.
- Monkeypatch `genplis.tags.TinyTag` (see `_patch_tinytag` in
  `tests/test_tags.py`) to test size filtering without crafting media files.
- Test both success and error paths. `tests/test_m3ug.py` is the reference for
  operator semantics.

## Linting, formatting, and typing

```bash
uv run ruff check --fix .
uv run ruff format .
uv run ty check
```

- Ruff is configured in `pyproject.toml`. It enforces isort import order,
  `ANN` annotations, `UP` modernizations, `S` security checks, and the usual
  `E`/`F` correctness rules. Tests are exempt from `S101` (asserts).
- Type checking uses [ty](https://docs.astral.sh/ty/) with Python 3.12 as the
  target.
- Type aliases `TagValue` and `Tags` live in `src/genplis/types.py`. Use them
  instead of ad-hoc unions or `Any`.
- `ty` and `ruff` are intentionally floating in the `dev` dependency group:
  `[tool.uv] upgrade-package` plus uv's `exclude-newer` window (7 days) select
  recent compatible releases. Do not pin them in `pyproject.toml` or
  `.pre-commit-config.yaml`.

## Pre-commit

The hooks are defined in `.pre-commit-config.yaml`:

- trailing whitespace and end-of-file fixes
- TOML validation and large-file checks
- `uv-lock` (keeps `uv.lock` in sync)
- `ruff check --fix`
- `ruff format`
- `ty check` (whole project, even when only some files are staged)

Run them on staged files after staging, before committing:

```bash
uv run pre-commit run
```

Run them on the whole repository when hooks or configuration change:

```bash
uv run pre-commit run --all-files
```

Fix failures and re-stage the affected files; never commit with failing hooks.

## CI

`.github/workflows/ci.yml` runs on pull requests and pushes to `main`:

- **pre-commit** — `uv sync --locked` and `pre-commit run --all-files`.
- **tests** — the suite on Python 3.12, 3.13, 3.14, and 3.15. Python 3.12 also
  produces a coverage report (terminal, XML artifact, and a Markdown summary in
  the Actions run).

Both jobs use `UV_EXCLUDE_NEWER: "7 days"` to match the lockfile policy.

## Cache internals

The cache is a disposable SQLite database at
`$XDG_CACHE_HOME/genplis/genplis.db` by default.

- `files(path TEXT PRIMARY KEY, last_modified TIMESTAMP, tags JSONB)` stores
  one row per file. `path` is always absolute (`db.get_db_key`).
- `cache_meta(key, value)` stores `tag_version`.
- `tag_version` is `CACHE_SCHEMA_VERSION:tinytag_version:max_size:ignored-tags`,
  with ignored tag names sorted. When it differs from the stored value,
  `create_files_table` drops the `files` table and rebuilds it. This is why
  upgrading tinytag or changing `[tags] max_size`/`ignore` triggers a full
  re-parse.
- Freshness is a whole-second modification-time comparison. A file whose mtime
  is not newer than the cached entry is a hit. M3UG files are never cached.
- `--clean` deletes rows for missing files, then runs `VACUUM` only if
  something was removed.

The cache stores tags as JSON. Values are strings, numbers, booleans, lists of
strings, or null, which is why `types.TagValue` has that shape.

## Extending the code

### Adding an operator

1. Subclass `RuleNode` in `m3ug.py` (for example `StartsWithRuleNode`).
2. Implement `check()` and, if the operator restricts value types, override
   `check_params()` to raise `GenplisM3UGException`.
3. Register the symbol in `RuleNode.build`.
4. Add tests for strings, numbers, lists, missing tags, and invalid values in
   `tests/test_m3ug.py`.
5. Document it in `docs/m3ug.md` and update the limitations section if needed.

### Adding a rating source

Add the alias to `get_rating()` in `m3ug.py`, normalize it to the 0–5 scale,
and add tests next to the existing `fmps_rating` tests. Document the scale in
`docs/tags.md`.

### Changing CLI or config behavior

Update all of:

- `core.setup_argparse()` and `resolve_args()` for options,
- `config.py` (`_KNOWN_SECTIONS` and parsing) for settings,
- `docs/usage.md` for options and runtime behavior,
- `docs/config.md` for settings and defaults,
- `examples/config.ini` if the example should show it,
- tests for both precedence directions (CLI over config, and defaults).

## Documentation

User docs are Markdown files under `docs/`:

| File | Audience | Contents |
| --- | --- | --- |
| `usage.md` | users | running genplis, options, playlists, cache, cleaning |
| `m3ug.md` | users | filter language, operators, examples, limitations |
| `config.md` | users | every config setting and precedence |
| `tags.md` | users | tag names, calculated properties, rating |
| `scheduling.md` | users | running genplis daily with systemd or cron |
| `dev.md` | contributors | this page |

Guidelines:

- Link with **absolute** GitHub URLs, for example
  `https://github.com/haplo/genplis/blob/main/docs/m3ug.md`. The README is
  rendered on PyPI, where relative links do not work. Use the same form
  between docs so links also work outside GitHub.
- Keep `README.md` short: overview, install, quick start, and a table of links
  into `docs/`.
- Keep `examples/config.ini` and `examples/*.m3ug` valid; they are linked from
  the docs and the config is loaded by the test suite.
- Avoid duplicating settings tables or operator semantics across files. Each
  fact should have one home and be linked from the others.

## Release

The version lives in `pyproject.toml`. Build artifacts with:

```bash
uv run python -m build
```

The wheel contains only `src/genplis`; documentation and examples stay in the
repository and are linked from the README. Publishing to PyPI is still
pending; see the roadmap.

## Roadmap

- [x] Parse tags of all files in music collection
- [x] Cache tags to local DB
- [x] Implement parser for filter grammar
- [x] Implement filtering logic
- [x] Filter files in collection
- [x] Generate playlists (MVP complete!)
- [x] Display tags when receiving a file as parameter (useful for creating rules or debugging)
- [x] `--exclude` option
- [x] Install as `genplis` command
- [x] pre-commit
- [x] Tests
  - [x] m3ug
  - [x] db
  - [x] tags
  - [x] file processing
  - [x] dir processing
  - [x] PR check
    - [x] Run pre-commit on whole project
    - [x] Test on every supported Python version
- [x] Documentation
- [ ] Publish to PyPI! 🚀
- [x] Example cron and systemd files and instructions on how to run periodically
- [ ] Improve M3U generation
  - [x] Include original M3UG content as comment
  - [x] Support basic extended M3U tags: [`#EXTM3U`](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3.1.1) and [`#EXTINF`](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3.2.1)
- [x] Parallel parsing of files
  - [x] Number of processes for parallel parsing
- [ ] Support narrowing of valid tag names
- [x] Config file support
  - [x] Default music collection path
  - [x] Default exclude
  - [x] Tag size threshold to ignore
  - [x] Tags to ignore
  - [x] Example config in `examples/config.ini`
- [ ] Support ordering
- [ ] Support OR conditionals
- [x] Command for DB cleaning
- [ ] Optimize memory usage
- [ ] Optimize DB space
- [ ] Improve Windows support (**HELP NEEDED!**)
- [ ] Improve MacOS support (**HELP NEEDED!**)

Got any ideas to make *genplis* more awesome?
Feel free to [open an issue](https://github.com/haplo/genplis/issues).
