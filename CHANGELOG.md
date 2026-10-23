# Changelog

All notable changes to Genplis are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The compatibility contract covers the CLI, configuration, and documented
M3UG language; internal Python modules and the disposable tag cache are not
a stable public API.

## [Unreleased]

## [1.0.0] - 2026-10-23

Initial public release.

### Added

- Generate M3U playlists from music tags and calculated audio properties,
  without modifying audio files.
- M3UG rules with text, numeric, boolean, and regex comparisons; tag and
  value sets; case-insensitive matching with an explicit `@CASE` modifier;
  and `@OR` / `@NOT` combinations.
- Explicit calculated properties such as `*duration`, `*filename`, and
  normalized `*rating`, plus readable duration literals.
- Multi-key and seeded random ordering, deduplication, per-tag and total
  song limits, and maximum playlist durations.
- Reusable filter fragments with `@INCLUDE` and `@NO-PLAYLIST`.
- Extended M3U titles and durations, relative paths, optional embedded filter
  comments, and plain path-only output.
- Recursive scanning, exclusion patterns, and explicit filter selection
  with `--filter`.
- SQLite tag caching, batched writes, cache cleaning, configurable tag-size
  limits, and ignored tags.
- Parallel tag parsing with configurable worker counts. Tags are released
  after filtering to reduce memory usage on large collections.
- Single-file tag inspection and collection-wide tag/value statistics.
- Parsed rule trees, per-song evaluation traces, and full playlist-selection
  traces for debugging filters without writing playlists.
- INI configuration, verbose and quiet modes, terminal progress, and
  configurable light/dark color themes.
- Portable AI-agent skill for discovering library tags, writing M3UG filters,
  and validating them, with bundled offline references.
- `genplis --version` and support for Python 3.12 through 3.15.
- Documentation website, downloadable examples, and scheduling guides.

[Unreleased]: https://github.com/haplo/genplis/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/haplo/genplis/releases/tag/v1.0.0
