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
    m3ug.py         filter, directive and @sort parser, rule nodes
    diagnostics.py  rule trees, evaluation traces, selection rendering
    output.py       color themes, terminal detection, output streams
    sorting.py      sort specs, value normalization, comparison
    m3u.py          playlist writer
    stats.py        tag statistics collector and report renderer
    files.py        modification-time helper
    json.py         JSON encoder for cached tags
    exceptions.py   exception hierarchy
    types.py        shared type aliases
tests/              pytest suite and real media fixtures
examples/           working .m3ug files and the annotated config
docs/               user and developer documentation
```

## Data flow

A directory run goes through these stages. `--filter` selects specific filters
and passes them to `process_directory(filters=...)`, so neighbouring playlists
are not touched; `PATH` (or the configured collection) is always the scan root.

```text
resolve config + CLI arguments
        ↓
open/create SQLite cache
        ↓
select filters: --filter files, or walk PATH to discover .m3ug files
    (prune excluded directories)
        ↓
parse every selected .m3ug file in the main process:
    recursively resolve @INCLUDE, detect cycles and depth
    merge included directives as defaults, own directives last
        ↓
walk PATH for audio files:
    .m3ug  → skip (already parsed)
    audio  → cache hit? apply every filter now : queue for parsing
    keep matching entries with walk order, sort, dedupe, limit and duration keys
        ↓
parse queued files (inline, or in worker processes)
        ↓
write results through one WriteBatch in the main process
        ↓
apply every filter to each result as it arrives
        ↓
for each playable .m3ug file (@NO-PLAYLIST files are skipped):
    sort matches by @SORT (including random), or [output] sort
    equal keys keep walk order
    drop duplicate @DEDUPE keys, keeping the first entry
    select with @LIMIT (global and per-tag) and @MAX-DURATION
    if any: write <stem>.m3u next to the .m3ug file
```

Rules are parsed into a `FilterNode` expression tree. Plain rules form AND
groups, consecutive `@OR` rules share an `OrNode`, and `@NOT` wraps one rule in
a `NotNode`. Each leaf `RuleNode` looks up its tag, normalizes multi-value
tags, and calls its own `check()`. `M3UGFile.rules` flattens the leaf rules for
diagnostics; matching always uses `M3UGFile.expression`. Directives are parsed
separately and never participate in filtering.

During directory matching, `m3ug.EvaluationTags` wraps one song's raw tags in
a read-only mapping. It lazily indexes case-insensitive tag names and caches
resolved values (including missing tags and calculated rating) and rule-value
normalization. Filtering and sort/dedupe/per-tag key extraction share this
view; playlist metadata still reads the raw tags. Exact lowercase keys take
precedence over mixed-case aliases, otherwise the first matching key wins.
The underlying mapping must not change while its view is in use. Views are
discarded after each song, so they do not retain the collection's tags.
Standalone rule evaluation and diagnostic traces still accept ordinary tag
mappings and preserve the uncached evaluation path.

Every rule carries a `SourceLocation` and every value keeps its original
literal token. `M3UGFile` stores both the merged `expression` and the file's
`own_expression`, plus an ordered tuple of `IncludeInfo` records with the raw
path, resolved path, directive line and fully parsed included file. These
fields are parser metadata only; they do not affect matching. `diagnostics.py`
is a pure renderer over that metadata and over the trace evaluators, so it can
rebuild include boundaries without reparsing source text.

`output.py` owns ANSI escape codes, the dark and light palettes, `NO_COLOR`
and TTY detection, `COLORFGBG` parsing, and the `Output` stream wrapper.
Renderers accept a `Palette` and paint semantic roles such as `PASS`, `FAIL`,
`SKIP`, directives, tag names, and values. Stream-producing helpers such as
the database cache, playlist writer, M3UG parser, and core display functions
accept an optional `Output`; omitting it uses `Output.plain()`, so tests and
redirected output stay plain. Tag parsing returns structured `TagDiagnostic`
values instead of preformatted strings; workers send those records back and
the main process renders them with the palette. A disabled palette returns
plain text, so tests and redirected output never need ANSI stripping. Theme
resolution is separate from color enablement: `auto` reads `COLORFGBG` and
falls back to dark when the background cannot be determined.

`@INCLUDE` is resolved recursively in the main process. Each file produces a
`Directives` value with `UNSET` markers, merges its includes in include order,
then applies its own directives last. Included expressions become separate
AND groups. Cycles are detected by resolved path, depth is capped at 32, and
missing, unreadable, directory, cyclic, too-deep, or invalid includes raise
`GenplisM3UGException` with the including file and line. `include_loader` on
`parse_m3ug` lets tests supply file contents without touching the filesystem.
When an include path does not already end in `.m3ug` and does not exist, the
loader tries the same path with `.m3ug` appended before reporting it missing. `@NO-PLAYLIST`
lives on `M3UGFile` rather than `Directives`, so it is never
inherited; core skips matching and writing for those files while still parsing
them for includes. Each include is retained as an `IncludeInfo` in source
order, and the included file keeps its own nested includes and
`own_expression`; diagnostics use those records to render evaluation order
instead of flattening everything into one expression string.

Tags are not retained across files in a normal run. `process_directory` only
keeps matching `Match` records (the playlist entry, walk order, normalized
sort keys, dedupe keys, per-tag limit key, and duration). The `retain_tags`
keyword exists for tests and debugging and
restores the old all-tags return value.

`--tag-stats` uses the same walk and cache path with an empty filter map, so
no `.m3ug` file is parsed and no playlist is written. Each supported file's
tags are passed to `stats.TagStatsCollector`, which keeps only aggregate
counters; the tags are still released after every file. `-t/--tag` selects
tags whose distinct values are kept without the usual cardinality cap.
`stats.render_tag_stats` and `stats.render_tag_details` accept a `Palette`;
column widths are measured from plain text and only cell content is painted,
so ANSI codes do not disturb table alignment.

The primary CLI operation is a single `core.Mode` value (`PROCESS`,
`TAG_STATS`, `SHOW_RULES`, `TRACE`, or `TRACE_FULL`) resolved in
`resolve_args`. `--clean` is deliberately not a mode: it remains a
post-processing flag, so `--clean PATH` processes the path before cleaning.
`--show-rules` branches before database setup. The trace modes branch after
database setup because they load the target through the normal cache path.

`diagnostics.trace_file` mirrors normal matching including short-circuiting,
inline includes and skipped subtrees. `RuleNode.apply` stays allocation-free;
`RuleNode.explain` performs the optional `TagLookup` recording used only by
traces. The directory pipeline accepts `dry_run` and a `SelectionTrace` so
`--trace-full` can simulate sort, dedupe, count, per-tag and duration decisions
without retaining non-target matches or writing playlists. Cache writes still
happen during that scan.

## Parallel parsing

`core.process_directory` first discovers and parses every `.m3ug` file, then
walks the audio files and checks the cache in the main process. With
`--jobs 1`, it calls `core.process_file` inline during the audio walk. With
more workers it resolves cache hits during the walk and queues misses and
stale files. If fewer than `executors.MIN_PARALLEL_FILES` files are queued,
`SequentialExecutor` parses them in the main process after the walk; otherwise
`ProcessExecutor` sends `ParseItem` batches to worker processes. In both
`--jobs > 1` cases the miss/stale diagnostics are printed after the walk.

Invariants:

- **One SQLite connection and one writer, in the main process.** Workers never
  open or receive the connection. Pool contexts are `forkserver` on POSIX and
  `spawn` on Windows, never plain `fork`, so a worker cannot inherit the
  database file descriptor.
- **Workers only parse tags.** They return tags and verbose messages. M3UG
  parsing, filtering, playlist generation, cache reads, and cache writes stay
  in the main process.
- **Playlist order is the effective sort spec, with walk order as the final
  tie-breaker.** Each audio file gets a walk-order index and, for every
  playlist it matches, the normalized keys for that playlist's `@sort` or the
  configured default (`filename`). Cache hits are evaluated during the walk
  and worker results are evaluated as they arrive; matches are sorted by the
  keys before playlists are written. `all_tags` is only rebuilt in walk order
  when `retain_tags=True`. Results are consumed in submission order, so
  verbose lines and cache rows stay in walk order for the files that needed
  parsing.
- **Tags are short-lived.** A file's tags are dropped after it has been
  matched against every filter. Only matching playlist entries are retained.
- **`--jobs 1` is the inline path.** It uses the same `WriteBatch` plumbing,
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
- Pass `retain_tags=True` to `core.process_directory` when a test needs the
  returned `all_tags` map. Normal runs release tags after filtering.
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

### Changing ordering

`sorting.py` owns the sort grammar (`parse_sort_spec`), value normalization,
and comparison. `M3UGFile.sort` is `None` when a file has no `@sort`, so the
configured `[output] sort` applies; an explicit spec (including an empty one
for walk order) overrides it. The special `random` key must be last; core
sorts the preceding keys, then shuffles equal runs with a per-playlist
`random.Random(seed)`. The pipeline stores only the sort values, dedupe keys,
per-tag limit key, and duration needed by each playlist, not the full tag
dictionary. Add tests for direction, numeric strings, case folding, missing
values, random seeds, per-tag limits, and stability when changing this code.

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
| `home.md` | visitors | project website landing page |
| `index.md` | users | documentation overview, installation, first playlist |
| `usage.md` | users | running genplis, options, playlists, cache, cleaning |
| `m3ug.md` | users | filter language, operators, sets, logic, ordering, limits, includes, examples |
| `config.md` | users | every config setting and precedence |
| `tags.md` | users | tag names, calculated properties, rating |
| `scheduling.md` | users | running genplis daily with systemd or cron |
| `dev.md` | contributors | this page |

Guidelines:

- Between guides, use relative Markdown links such as `[M3UG](m3ug.md)`;
  these work on GitHub and are resolved into website URLs during the build.
  Keep **absolute** GitHub links in the README, which is also rendered on
  PyPI, and for repository files outside the documentation.
- Keep `README.md` short: overview, install, quick start, and a table of links
  into `docs/`.
- Keep `examples/config.ini` and `examples/*.m3ug` valid; they are linked from
  the docs and the config is loaded by the test suite.
- Avoid duplicating settings tables or operator semantics across files. Each
  fact should have one home and be linked from the others.

## Website development

The [project website](https://haplo.github.io/genplis/) is built with
[Zensical](https://zensical.org/). Its dependencies are isolated in the
`docs` dependency group; normal application installs do not need them.

### Run the website locally

From the repository root, start the live development server:

```bash
uv run --group docs python scripts/website.py serve
```

`uv run --group docs` installs the website dependencies automatically. Open
**http://localhost:8000/genplis/** (or the preview URL printed by Zensical).
Keep the command running while you work; edits to `docs/` and `examples/`
regenerate the website sources, and Zensical reloads the preview. Stop the
server with **Ctrl+C**. Restart it after changing `scripts/website.py` itself.

Edit the original Markdown, examples, stylesheets, and template overrides,
not the generated `.website-src/` or `site/` directories.

### Build and validate

Before opening a pull request, run the same strict build used in CI:

```bash
uv run --group docs python scripts/website.py build
```

The output is written to `site/`. The build validates every local HTML link,
asset, and anchor, including the `/genplis/` prefix used on GitHub Pages.
To check an existing build without rebuilding it:

```bash
uv run --group docs python scripts/website.py check
```

Search runs locally in the browser, includes all guides and examples, and
excludes the landing page. Try a search in the live preview when changing
navigation or generated examples.

### Sources and deployment

Source files and routes:

| Source | Website path (under `/genplis/`) |
| --- | --- |
| `docs/home.md` | `/` — project landing page |
| `docs/index.md` | `/docs/` — documentation overview and quick start |
| `docs/usage.md`, etc. | `/docs/usage/`, etc. — existing guides |
| `examples/*.m3ug` | `/docs/examples/` — generated gallery |
| `docs/assets/` | `/assets/` — local styles and branding |

`scripts/website.py` prepares ignored `.website-src/` inputs before Zensical
writes `site/`. Neither directory should be edited or committed. It rewrites
source-relative links for the published layout; links to the repository's
`examples/` directory become links to the gallery on the website. Individual
repository-file links still point to GitHub. Source edit links always point
to the original files, not the generated inputs.

The gallery discovers all `examples/*.m3ug` in filename order. Each file gets
a heading, copyable code, and a byte-for-byte download. The generated ZIP
preserves filenames and companion includes. Do not create `docs/examples.md`
or maintain a second copy of an example. Add or edit the original instead.

`zensical.toml` controls navigation and theme settings. Small template
overrides live in `website/overrides/`; custom CSS lives in
`docs/assets/stylesheets/website.css`. Replace the temporary branding in
`docs/assets/branding/` when the final logo, favicon, and social image are
ready. Fonts and assets are served locally; no analytics are installed.

`.github/workflows/pages.yml` builds and validates on pull requests, pushes
to `main`, and manual dispatch. Only `main` push/manual runs can deploy,
using a Pages artifact and the `github-pages` environment. In repository
**Settings → Pages**, select **GitHub Actions** as the source once. No
`gh-pages` branch or personal access token is needed.

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
- [x] Example cron and systemd files and instructions on how to run periodically
- [x] Improve M3U generation
  - [x] Include original M3UG content as comment
  - [x] Support basic extended M3U tags: [`#EXTM3U`](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3.1.1) and [`#EXTINF`](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3.2.1)
- [x] Parallel parsing of files
  - [x] Number of processes for parallel parsing
- [x] Config file support
  - [x] Default music collection path
  - [x] Default exclude
  - [x] Tag size threshold to ignore
  - [x] Tags to ignore
  - [x] Example config in `examples/config.ini`
- [x] Improve M3UG grammar
  - [x] Ordering
  - [x] @OR operator
  - [x] @NOT operator
  - [x] Multi-tag glob (`[<tag1> | <tag2> | <tag3>] OP <value>`)
  - [x] Multi-value glob (`<tag> OP [<value1> | <value2> | <value3>]`)
  - [x] Playlist limits (`@LIMIT`, `@MAX-DURATION`)
  - [x] Limit N per <tag>
  - [x] Dedupe (`@DEDUPE`)
  - [x] Random sort
  - [x] Boolean literals
  - [x] "Starts/ends with" operator
  - [x] Regex operator
  - [x] Duration formats (`mm:ss`, `<n>m`)
  - [x] Include other M3UG
  - [x] Abstract M3UG (doesn't generate an M3U, meant for include)
- [x] Command for DB cleaning
- [x] Optimize memory usage
- [ ] Optimize DB space
- [x] Display all available tags, with stats
- [x] Debug M3UG
- [x] Color output
- [x] Website
- [ ] Improve Windows support (**HELP NEEDED!**)
- [ ] Improve MacOS support (**HELP NEEDED!**)
- [ ] Publish to PyPI! 🚀

Got any ideas to make *genplis* more awesome?
Feel free to [open an issue](https://github.com/haplo/genplis/issues).
