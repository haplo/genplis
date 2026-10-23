# Development guide

Start here to work on genplis: set up a checkout, run the checks, and find
the code responsible for your change. For installation and normal use, see
the [user documentation](index.md).

## Setup

You need Python 3.12 or later and [uv](https://github.com/astral-sh/uv):

```bash
git clone https://github.com/haplo/genplis.git
cd genplis
uv sync
uv run pre-commit install
```

`uv sync` installs runtime and development dependencies into `.venv`.
The pre-commit hook runs checks automatically when you commit.

## Running

Run from the checkout with `uv run`:

```bash
uv run genplis ~/Music
uv run genplis --verbose /path/to/song.mp3
```

See [Usage](usage.md) for playlist commands and [Filter
debugging](m3ug.md#testing-and-debugging-filters) for rule trees and traces.

## Tests

| Task | Command |
| --- | --- |
| Whole suite | `uv run python -m pytest` |
| One file | `uv run python -m pytest tests/test_m3ug.py` |
| One test | `uv run python -m pytest tests/test_m3ug.py::test_multiple_rules` |
| Verbose results | `uv run python -m pytest -v` |
| Branch coverage | `uv run python -m pytest --cov=genplis --cov-branch --cov-report=term-missing` |

### Testing patterns

- Reuse the `file_mp3`, `file_ogg`, and `file_m3ug` session fixtures from
  `tests/conftest.py`. Copy them to `tmp_path` before writing playlists or
  changing modification times; don't modify `tests/files/`.
- Use `genplis_db` for a temporary database and `make_args` to build
  `core.Args` without invoking argparse.
- Use `retain_tags=True` with `process_directory` only when a test needs the
  returned `all_tags` map. Normal runs release tags after filtering.
- Monkeypatch `genplis.tags.TinyTag` for synthetic tag data; see
  `_patch_tinytag` in `tests/test_tags.py`.
- Cover success, missing values, and error paths. `tests/test_m3ug.py`
  exercises rule semantics; the suite also validates `examples/config.ini`.

## Linting, formatting, and typing

```bash
uv run ruff check --fix .
uv run ruff format .
uv run ty check
```

`pyproject.toml` configures Ruff and ty for Python 3.12. Keep function
signatures typed, imports ordered, and use the shared `TagValue` and `Tags`
aliases from `src/genplis/types.py` rather than ad-hoc types or `Any`.
See [AGENTS.md](https://github.com/haplo/genplis/blob/main/AGENTS.md)
for the full coding guidelines.

Ruff and ty are intentionally unpinned in the development dependencies and
pre-commit configuration. `[tool.uv] upgrade-package` lets lockfile updates
refresh them; keep the seven-day dependency cutoff used by CI.

## Pre-commit

After staging changes, run the hooks before committing:

```bash
uv run pre-commit run
```

Fix failures, re-stage affected files, and run the hooks again. Repeat this
after staging more changes. When hooks or configuration change, also run:

```bash
uv run pre-commit run --all-files
```

The hooks cover whitespace, TOML, large files, the uv lockfile, Ruff, and ty.
The ty hook checks the whole project even when only a few files are staged.
Definitions live in `.pre-commit-config.yaml`.

## CI

Pull requests and pushes to `main` run:

| Check | Coverage |
| --- | --- |
| Pre-commit | Locked dependencies and hooks on all files |
| Tests | Python 3.12, 3.13, 3.14, and 3.15; Python 3.12 also produces coverage reports |
| Website | Strict build and local link, asset, and anchor validation |

See [ci.yml](https://github.com/haplo/genplis/blob/main/.github/workflows/ci.yml)
and [pages.yml](https://github.com/haplo/genplis/blob/main/.github/workflows/pages.yml).
Both workflows use `UV_EXCLUDE_NEWER="7 days"` to match the lockfile policy.

## Project layout

Application modules live under `src/genplis/`:

| Module | Responsibility |
| --- | --- |
| `__main__.py` | Entry point |
| `core.py` | CLI resolution, directory scans, filtering, selection |
| `config.py` | INI loading and validation |
| `executors.py` | Sequential and worker-process tag parsing |
| `tags.py` | Tag extraction and calculated properties |
| `db.py` | SQLite cache and batched writes |
| `m3ug.py` | Rule trees, directives, includes, tag lookup |
| `sorting.py` | Sort grammar, normalization, comparison |
| `m3u.py` | Playlist writing |
| `diagnostics.py` | Rule trees, evaluation traces, selection output |
| `output.py` | Output streams, palettes, terminal detection, progress |
| `stats.py` | Tag statistics collection and rendering |
| `types.py` | Shared types |
| `files.py` | File helpers |
| `json.py` | JSON serialization |
| `exceptions.py` | Exception classes |

Tests and media fixtures live in `tests/`; copyable filters and the annotated
config live in `examples/`. Website sources are covered [below](#website-development).

## Data flow

A normal directory run in `core.process_directory`:

1. Uses the resolved CLI/config settings and the main process's database
   connection.
2. Discovers and parses `.m3ug` files, or uses the filters passed explicitly
   through `filters=`. Excluded directories are pruned.
3. Walks audio files: applies filters immediately to cache hits and queues
   missing or stale files for parsing.
4. Parses the queue, writes cache updates, and evaluates each result against
   the filters.
5. Sorts matches, removes duplicates, applies count/per-tag/duration limits,
   and writes playlists with selected entries. `@NO-PLAYLIST` files are skipped.

Each `Match` retains only the playlist entry, walk order, selection keys,
and duration—not the whole tag map. `retain_tags=True` is an opt-in exception
for tests and debugging. See the [selection rules](m3ug.md#playlist-limits)
for user-visible behavior.

### CLI modes

`resolve_args` chooses one `core.Mode`: `PROCESS`, `TAG_STATS`, `SHOW_RULES`,
`TRACE`, or `TRACE_FULL`.

- `SHOW_RULES` branches before database setup.
- Trace modes load the target through the cache. Full traces use `dry_run`
  and `SelectionTrace` to record selection decisions without writing playlists;
  cache updates still happen.
- Statistics reuse the walk/cache pipeline with an empty filter map.
  `TagStatsCollector` keeps aggregate counts, not song mappings. Explicitly
  requested tags have uncapped distinct-value counts.
- `--clean` is a post-processing flag, not a mode: with a collection path,
  normal processing happens before cleaning.

## Parsing pipeline

Cache misses and stale files are queued during the walk so progress reporting
knows the parsing total. With `--jobs 1`, `core.process_file` handles that
queue in the main process. Otherwise, `make_executor` chooses a
`SequentialExecutor` for small queues or a `ProcessExecutor` for larger ones.
See [executors.py](https://github.com/haplo/genplis/blob/main/src/genplis/executors.py)
for batching and worker thresholds.

Keep these invariants when changing the pipeline:

- **Only the main process accesses SQLite.** Workers parse tags and return
  `ParseResult` values with structured diagnostics. M3UG parsing, filtering,
  selection, and output also stay in the main process.
- **Do not inherit database connections.** Worker contexts use `forkserver`
  on POSIX and `spawn` elsewhere, never plain `fork`.
- **Preserve ordering.** Worker results are consumed in submission order;
  each file's walk index remains the final tie-breaker for playlist sorting.
  Changing the worker count must not change deterministic playlist results.
- **Release tags after use.** Keep `Match` records, not an `all_tags` map,
  unless retention was explicitly requested.
- **Flush on exit.** `db.WriteBatch` commits every `core.COMMIT_EVERY` writes
  and flushes at the end of parsing, including errors and interrupts.
  Interrupted executors cancel pending work and shut down without waiting.

### Benchmarking

Use a test copy of a collection on a real filesystem, not tmpfs. Choose a
new database path for a cold run:

```bash
/usr/bin/time -f '%e s, %M KiB' \
    uv run genplis --db ./benchmark-sequential.db --jobs 1 /path/to/test-collection
```

Repeat the command against that database for a warm run. Compare with
`--jobs 0` using a separate fresh database. Run each case three times and
take the median. Compare playlist checksums too; use fixed random seeds and
identical inputs/settings so byte-for-byte comparisons are meaningful.

## Filter engine

The rule engine lives in
[m3ug.py](https://github.com/haplo/genplis/blob/main/src/genplis/m3ug.py).
These are the main structures to understand before changing it:

| Structure | Role |
| --- | --- |
| `FilterNode`, `RuleNode` | Expression tree; plain rules form AND groups, `@OR` forms `OrNode` groups, and `@NOT` wraps one rule |
| `M3UGFile.expression` | The expression used for matching; `rules` is only a flattened leaf view |
| `Directives` | Playlist controls, separate from matching; `UNSET` distinguishes missing values from explicit overrides |
| `SourceLocation`, literal tokens, `IncludeInfo` | Preserve source and include boundaries for diagnostics without reparsing |

### Tag lookup and comparison caching

`EvaluationTags` provides a read-only per-song view shared by filtering and
selection-key extraction. It lazily resolves names, calculated values, and
normalized rule inputs. Don't mutate the underlying tags while the view is
in use. Exact lowercase names win over mixed-case aliases; otherwise the
first matching spelling wins. The view is discarded after the song.

`PredicateCache` shares pure built-in comparisons across equivalent rules
for one scan. Its keys distinguish rule types, tag names, value types,
expected values, and case sensitivity. Custom rule checks aren't cached.
The cache is bounded—by default 16,384 results total, at most 1,024 per
predicate—and bypasses oversized keys and unsupported values. Admission
checks live alongside the class; don't remove them when changing caching.

Neither cache retains whole song mappings across the scan. Short-circuiting,
per-rule warnings, and distinctions such as booleans versus numbers must stay
unchanged. Standalone rules and traces also support ordinary tag mappings.

### Includes and diagnostics

`parse_m3ug` recursively resolves includes in the main process, detects
cycles and depth errors, then merges included defaults before local
directives. `include_loader` lets tests supply included content without files.
`@NO-PLAYLIST` belongs to `M3UGFile`, not `Directives`, so it isn't inherited.
See [Includes](m3ug.md#including-other-files) for path and precedence rules.

`own_expression` and ordered `IncludeInfo` records retain each file's
boundaries alongside the merged expression. `diagnostics.py` renders this
metadata and trace results. `RuleNode.explain` records optional `TagLookup`
details; normal `apply` avoids that trace-recording overhead.

### Output and statistics

Use `Output` and `Palette` from `output.py` rather than emitting ANSI codes
in parsers or workers. Helpers default to `Output.plain()`; workers return
`TagDiagnostic` records for the main process to render. Theme choice and
color enablement are separate decisions.

Statistics renderers measure plain-text widths before coloring cells, so
table alignment doesn't depend on escape sequences. Keep collection of
statistics separate from rendering and avoid retaining per-file tags.

## Cache internals

The disposable SQLite cache is implemented in
[db.py](https://github.com/haplo/genplis/blob/main/src/genplis/db.py):

- `files(path TEXT PRIMARY KEY, last_modified TIMESTAMP, tags JSONB)` stores
  one row per audio file. Tags are JSON-serialized `Tags` values.
- `db.get_db_key` normalizes absolute paths and collapses `.` / `..`, but
  doesn't resolve symlinks.
- Freshness compares whole-second modification times. A file whose timestamp
  is no newer than the cached value is a hit. M3UG files aren't cached.
- `cache_meta` stores `tag_version`, built from
  `CACHE_SCHEMA_VERSION:tinytag_version:max_size:ignored-tags` with ignored
  names sorted. A version change makes `create_files_table` rebuild `files`.
- Cleaning removes rows for missing files and runs `VACUUM` only when rows
  were removed.

Bump `CACHE_SCHEMA_VERSION` when changing tag extraction or storage in a way
that makes old rows incompatible. For location and maintenance commands,
see [Cleaning the cache](usage.md#cleaning-the-cache).

## Extending the code

### Adding an operator

1. Subclass `RuleNode`, define `OPERATOR` for diagnostics, and follow the
   existing `OPERATOR_NAME` naming convention. Set `IS_TEXT = True` for text
   operators so boolean-tag warnings are preserved. Implement `check()` and
   override `check_params()` when argument types need validation. Raise
   `GenplisM3UGException` for invalid syntax or values.
2. Register the symbol in `RuleNode.build` and the operator sets used during
   parsing. Decide whether it is eligible for `PredicateCache`.
3. Test text, numbers, lists, missing values, invalid inputs, and cached versus
   uncached behavior in `tests/test_m3ug.py`.
4. Document its semantics in [M3UG](m3ug.md).

### Adding a rating source

Extend `get_rating()` in `m3ug.py`, normalize to 0–5, and add tests alongside
the `fmps_rating` cases. Check explicit `*rating`, raw-rating precedence,
unusable values, and diagnostic traces. Update [Tags](tags.md#rating).

### Changing ordering

Start with `sorting.py` for grammar, normalization, and comparison, then the
selection helpers in `core.py`. Preserve the distinction between an absent
sort (`None`, use the configured default) and an empty sort (walk order).

Test direction, numeric strings, case folding, missing and multi-valued keys,
random seeds, dedupe, limits, and worker-count stability. See
[Ordering](m3ug.md#ordering) for the behavior to preserve.

### Changing CLI or config behavior

Update `core.setup_argparse()` / `resolve_args()`, `config.py`'s known
settings and parsing, and tests for CLI-over-config and default behavior.
Keep [Usage](usage.md), [Configuration](config.md), and
`examples/config.ini` consistent with the change.

## Documentation

User guides are Markdown files under `docs/`; the [documentation index](index.md)
lists their subjects. Keep each fact in one guide and link to it elsewhere,
rather than duplicating settings or language rules.

- Use relative Markdown links between guides, such as `[Tags](tags.md)`.
  The website build resolves them to published routes.
- Use absolute GitHub links in `README.md` and for repository files outside
  `docs/`. Keep the README short and link to detailed guides.
- Edit examples in `examples/`, not copies in documentation. Keep filters
  and `config.ini` valid.
- Check incoming links when renaming headings, then run the strict website
  build to validate local links and anchors.

## Website development

The [website](https://haplo.github.io/genplis/) uses Zensical. Its dependencies
live in the separate `docs` group and aren't needed to run genplis.

### Run the website locally

```bash
uv run --group docs python scripts/website.py serve
```

Open `http://localhost:8000/genplis/`, or the printed preview URL. Source edits
in `docs/` and `examples/` regenerate the site and reload the preview. Stop
with **Ctrl+C**; restart after editing `scripts/website.py` itself.

### Build and validate

Run the strict build before submitting documentation changes:

```bash
uv run --group docs python scripts/website.py build
```

It writes `site/` and validates local links, assets, and anchors under the
`/genplis/` prefix. To validate existing output without rebuilding, use:

```bash
uv run --group docs python scripts/website.py check
```

Try browser search in the preview after changing navigation or examples.
Search is local, covers the guides and examples, and excludes the landing page.

### Sources and deployment

| Source | Purpose |
| --- | --- |
| `docs/home.md` | Landing page at `/genplis/` |
| `docs/index.md`, other guides | Documentation at `/genplis/docs/` and its subpages |
| `examples/*.m3ug` | Generated gallery at `/genplis/docs/examples/`, individual downloads, and ZIP |
| `docs/assets/` | Stylesheets and branding assets |
| `website/overrides/` | Template overrides |
| `zensical.toml` | Navigation and theme configuration |
| `scripts/website.py` | Source preparation, preview, and link validation |

**Edit original sources, not `.website-src/` or `site/`.** Both are ignored
build outputs. The preparation step rewrites documentation links and adds
source-edit links pointing back to the originals.

The gallery reads `examples/*.m3ug` in filename order and provides copyable
code and byte-for-byte downloads. Its ZIP preserves companion include files.
Don't create a separate `docs/examples.md` or maintain duplicate examples.

`pages.yml` builds on pull requests, `main` pushes, and manual dispatches;
only non-PR runs on `main` deploy through a Pages artifact and the
`github-pages` environment. Set the repository's **Settings → Pages** source
to **GitHub Actions**. No `gh-pages` branch or personal token is needed.

## Release

Update the version in `pyproject.toml`, then build the distributions:

```bash
uv build
```

The wheel packages `src/genplis`; documentation and examples remain in the
repository. PyPI publishing is still pending.

## Roadmap

- [x] Parse tags of all files in music collection
- [x] Cache tags to local DB
- [x] Implement parser for filter grammar
- [x] Implement filtering logic
- [x] Filter files in collection
- [x] Generate playlists (MVP complete!)
- [x] Display tags when receiving a file as parameter
- [x] `--exclude` option
- [x] Install as `genplis` command
- [x] pre-commit
- [x] Tests
- [x] PR check
  - [x] Run pre-commit on whole project
  - [x] Test on every supported Python version
- [x] Documentation
- [x] Example cron and systemd files and instructions on how to run periodically
- [x] Improve M3U generation
  - [x] Include original M3UG content as comment
  - [x] Support basic extended M3U tags: [`#EXTM3U`](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3.1.1) and [`#EXTINF`](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3.2.1)
- [x] Parallel parsing of files
- [x] Config file support
- [x] Improve M3UG grammar
- [x] Command for DB cleaning
- [x] Optimize memory usage
- [ ] Optimize DB space
- [x] Display all available tags, with stats
- [x] Debug M3UG
- [x] Color output
- [x] Website
- [ ] Improve Windows support (**help wanted**).
- [ ] Improve macOS support (**help wanted**).
- [ ] Publish to PyPI.

Suggestions and contributions are welcome in
[GitHub issues](https://github.com/haplo/genplis/issues).
