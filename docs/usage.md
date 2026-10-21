# Usage guide

This page explains how to run genplis, what it writes, and how the cache
behaves. For the filter language, see
[M3UG](https://github.com/haplo/genplis/blob/main/docs/m3ug.md); for settings,
see [Configuration](https://github.com/haplo/genplis/blob/main/docs/config.md).

## Synopsis

```text
genplis [OPTIONS] [PATH]
```

`PATH` is either a directory (your music collection) or a single audio file.
It may be omitted when `[collection] path` is set in the config file. If
neither is available, genplis exits with an error explaining that `PATH` is
required.

## Options

| Option | Meaning |
| --- | --- |
| `PATH` | Directory to scan, or a single file to inspect. |
| `-e REGEX`, `--exclude REGEX` | Skip files and folders whose path matches this regular expression. May be repeated. **Replaces** the config file's `exclude` list entirely. |
| `--config FILE` | Read settings from this file instead of the XDG default. |
| `--no-config` | Ignore all configuration files. |
| `-v`, `--verbose`, `--no-verbose` | Print diagnostics: config and database paths, skipped files, parsed rules, matching songs. |
| `-q`, `--quiet` | Reduce output. Once prints only filter match counts and playlist creation; twice (`-qq`) prints nothing except errors. Cannot be combined with `--verbose`. |
| `--db PATH` | Use this SQLite database instead of the default cache location. |
| `-j N`, `--jobs N` | Parse cache misses with `N` worker processes. `0` uses one worker per CPU, capped at eight; `1` disables the process pool. Default is `0`. |
| `--clean` | Remove cache entries for files that no longer exist. See [Cleaning the cache](#cleaning-the-cache). |
| `--overwrite`, `--no-overwrite` | Whether to replace an existing generated playlist. |
| `--include-source`, `--no-include-source` | Whether to embed the original `.m3ug` text as comments in the playlist. |
| `--extended-m3u`, `--no-extended-m3u` | Whether to write `#EXTM3U` and `#EXTINF` metadata. Enabled by default; `--no-extended-m3u` writes a plain list of paths. |
| `-h`, `--help` | Show the built-in help and exit. |

Every option with an on/off form overrides the corresponding config setting.
`--config` and `--no-config` are mutually exclusive.

## PATH and the config file

`PATH` is optional in two situations:

1. `[collection] path` is set in the config file. Running `genplis` with no
   arguments then scans that collection, which is convenient for
   [scheduled runs](https://github.com/haplo/genplis/blob/main/docs/scheduling.md).
2. `--clean` is used without a path, which cleans the **whole** database
   instead of a subtree.

A path given on the command line always wins over the configured collection
path. Relative command-line paths are resolved against the current directory,
and `~` is normally expanded by your shell. In the config file, genplis
expands `~` itself and resolves relative paths against the config file's
directory.

If you pass any `--exclude` option, genplis uses only those patterns and
ignores `[collection] exclude`. To keep the configured patterns and add one,
edit the config file instead.

## What a run does

1. Loads the config file (unless `--no-config`) and merges it with the
   command-line options.
2. Opens or creates the cache database.
3. Walks `PATH` to find and parse every `.m3ug` file, pruning excluded folders
   and files. Includes are resolved recursively and their directives merged
   as defaults for the including file.
4. Walks `PATH` again for audio files, skipping unsupported formats silently
   (`--verbose` explains why). It parses each file's tags, reusing cached tags
   when the file has not changed, and applies every `.m3ug` file's rules as
   soon as that file's tags are available.
5. Writes a playlist for each `.m3ug` file that matched at least one song.
   Entries are ordered by the file's `@sort` directive, or by `[output] sort`
   (default `filename`) when it has none. `@LIMIT` and `@MAX-DURATION` can cap
   the selected entries after ordering.
6. Prints how many files were processed, how long it took, and the process's
   RAM usage.

A run only filters the files under `PATH`. Cached entries for other folders
are not used to build playlists, and a `.m3ug` file does not pull audio files
in from outside the scanned tree. An `@INCLUDE` may read a filter file from
outside `PATH`, but it only adds rules and defaults.

### Parallel parsing

Cache misses and stale entries can be parsed by several worker processes at
once. This speeds up the first run and runs after files change; cached files
are read directly from SQLite and do not use a worker.

- `--jobs 0` (the default) uses one worker per available CPU, capped at eight.
- `--jobs 1` keeps everything in the main process, which is useful for
  debugging or when starting processes is undesirable.
- `--jobs N` sets an explicit worker limit.

The main process keeps the only database connection and writes all cache rows.
M3UG parsing, filtering, and playlist generation also stay in the main process.
Playlists and cache contents are the same for every value of `--jobs`; only
the order of verbose diagnostics can differ when more than one worker is used,
because results arrive as workers finish.

Small runs stay inline: genplis does not start a process pool when only a few
files need parsing. The setting is also available as `[general] jobs` in the
config file.

### Inspecting one file

```bash
uv run genplis /path/to/song.mp3
```

This prints the cache status and the parsed tags, then exits. Calculated
values are prefixed with `*` (`*filename`, `*duration`, `*bitrate`,
`*samplerate`, `*rating`) to distinguish them from tags embedded in the file.
Filter names do **not** include the `*`.

```bash
uv run genplis /path/to/Favorites.m3ug
```

This prints the parsed rules, and the `@sort` keys when present, then exits.
It does **not** generate a playlist: playlists are only produced when scanning
a directory.

Both forms also warn when the file matches the current exclude configuration.

## Generated playlists

- A `.m3ug` file named `Favorites.m3ug` produces `Favorites.m3u` in the same
  directory.
- Files marked `@NO-PLAYLIST` are parsed and may be included, but they never
  produce an `.m3u` themselves. Any existing playlist is left untouched.
- Only songs that match the filter expression are included. Plain rules are
  ANDed; `@OR`, `@NOT`, and sets can express alternatives.
- Entry order comes from the file's `@sort` directive. Without one,
  `[output] sort` applies; its default is `filename`, the absolute path.
  Equal keys keep directory-walk order. `@sort random` (optionally with an
  integer seed) shuffles entries. See
  [Ordering](https://github.com/haplo/genplis/blob/main/docs/m3ug.md#ordering).
- `@DEDUPE` keeps the first entry for each key after ordering; entries missing
  a key are always kept. `@LIMIT` caps the number of entries and
  `@MAX-DURATION` caps their total duration. These apply after ordering;
  `0` disables either cap.
- If no song matches, no playlist is written. An existing playlist is left
  untouched in that case.
- Playlists are UTF-8 text. By default they are extended M3U files: the first
  line is `#EXTM3U`, and every file is preceded by an
  `#EXTINF:<seconds>,<artist> - <title>` line.
- The `EXTINF` title falls back to the title tag, then the artist tag, then the
  file name. The duration comes from the tag cache; when it is unavailable it
  is written as `-1`.
- Pass `--no-extended-m3u` (or set `extended_m3u = false` in
  `[output]`) to write a plain list with one path per line and no metadata.
- Paths are written relative to the playlist's directory, so nested filter
  files can use `../` entries. This keeps the playlist usable when the
  collection is moved. When no relative path exists (for example on different
  Windows drives), the absolute path is written instead.
- By default the original `.m3ug` text is embedded at the top as comments,
  prefixed with `# `. Every source line is prefixed, including blank lines
  (written as `#`), so directives such as `#EXTINF` in a filter file cannot be
  mistaken for playlist metadata. Use `--no-include-source` to omit it.
- Existing playlists are overwritten by default. With `--no-overwrite`,
  genplis prints a warning and leaves the file alone.
- Only `#EXTM3U` and `#EXTINF` are generated. The remaining `#EXT-X-*` tags in
  [RFC 8216](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3) are
  HTTP Live Streaming signalling and have no meaning for a local music
  playlist, so genplis does not write them.

## Cache

Genplis caches parsed tags in SQLite so later runs do not re-read every file.

- **Location:** `$XDG_CACHE_HOME/genplis/genplis.db`, usually
  `~/.cache/genplis/genplis.db`. Override it with `[database] path` or
  `--db`.
- **Freshness:** the cache stores the file's modification time in whole
  seconds and compares it on each run. A file that is unchanged is a cache
  hit; a changed file is re-parsed and the entry is updated. Each single-file
  run reports the status as `not present`, `stale`, or `valid`.
- **Invalidation:** the cache is discarded and rebuilt automatically when the
  tag library version changes, when `[tags] max_size` or `[tags] ignore`
  change (they affect what gets stored), or when genplis's cache format
  changes. This is why changing tag settings makes the first run slower.
- **Sharing:** by default all collections share one database. Use different
  `--db` paths if you want to keep them separate.
- **Resetting:** the database is disposable. Deleting it is always safe;
  genplis recreates it on the next run.

## Cleaning the cache

Deleted, renamed, or moved files leave stale entries behind. To remove them:

```bash
uv run genplis --clean ~/Music
```

With a path, genplis runs normally first and then removes entries for files
under that path that no longer exist. This keeps the behavior predictable: the
playlists are regenerated and the cache is cleaned in one pass.

Without a path, the whole database is cleaned:

```bash
uv run genplis --clean
```

This ignores `[collection] path` when it is configured. To clean only the
configured collection, pass its path explicitly (`genplis --clean /path`).

Cleaning prints how many entries were removed and how much disk space was
reclaimed. The database is vacuumed only when something was removed, and
vacuuming can take a while and temporarily needs free disk space roughly the
size of the database. If the database does not exist and no path was given,
genplis prints that there is nothing to clean and exits.

## Output and errors

Normal runs print per-file cache updates, a line for each filter file with its
match count, and a final summary. `--verbose` adds config/database paths,
exclusion decisions, parsed rules, the effective sort order, and the list of
matching songs. M3UG rule diagnostics are printed while filters are discovered,
before audio processing.
With `--jobs 1`, audio diagnostics follow the walk order. With `--jobs` greater
than 1, diagnostics for cache misses and cache updates are printed after the
audio walk; a file's own diagnostics stay together.

`-q` limits output to one line per filter file with its match count and, when
a playlist is written, the line announcing it. `-qq` suppresses all normal
output, so scheduled runs stay silent; errors are still printed to standard
error. `-q` and `-v` cannot be used together on the command line; the same
applies to `verbose = true` and `quiet = true` in the config file. A
command-line verbosity flag overrides the configured one.

- An invalid `PATH` (neither a file nor a directory) prints a message to
  standard error and exits with status 1.
- Configuration problems and other fatal errors are reported to standard
  error as `genplis: error: ...` with status 1.
- An invalid `.m3ug` file stops the run with an error describing the problem.
  The same applies to `@INCLUDE` problems: a missing, unreadable, or cyclic
  include, a directory, excessive include depth, or invalid syntax in an
  included file.
- A playlist that exists and cannot be overwritten because of
  `--no-overwrite` produces a warning, not an error. The warning is
  suppressed by `-q`.

## See also

- [M3UG reference](https://github.com/haplo/genplis/blob/main/docs/m3ug.md)
- [Configuration reference](https://github.com/haplo/genplis/blob/main/docs/config.md)
- [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md)
- [Scheduling runs](https://github.com/haplo/genplis/blob/main/docs/scheduling.md)
- [Example filters](https://github.com/haplo/genplis/tree/main/examples)
