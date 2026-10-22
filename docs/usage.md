# Usage guide

This page explains how to run genplis, what it writes, and how the cache
behaves. For the filter language, see
[M3UG](https://github.com/haplo/genplis/blob/main/docs/m3ug.md); for settings,
see [Configuration](https://github.com/haplo/genplis/blob/main/docs/config.md).

## Synopsis

```text
genplis [OPTIONS] [PATH]
```

`PATH` is a directory (your music collection) or a single audio file. To
process one specific `.m3ug` filter, name it with `--filter FILE`; `PATH` is
then the collection to scan and may be omitted when `[collection] path` is set
in the config file. If neither `PATH` nor a configured collection is available,
genplis exits with an error explaining that `PATH` is required. A `.m3ug` file
passed as `PATH` is rejected; use `--filter` instead.

## Options

| Option | Meaning |
| --- | --- |
| `PATH` | Directory to scan or an audio file to inspect. Use `--filter` to process a specific `.m3ug` file. |
| `-f FILE`, `--filter FILE` | Process only this `.m3ug` filter. `PATH` (or the configured collection) is the scan root. May be repeated. |
| `-e REGEX`, `--exclude REGEX` | Skip files and folders whose path matches this regular expression. May be repeated. **Replaces** the config file's `exclude` list entirely. |
| `--config FILE` | Read settings from this file instead of the XDG default. |
| `--no-config` | Ignore all configuration files. |
| `-v`, `--verbose`, `--no-verbose` | Print diagnostics: config and database paths, skipped files, rule trees, matching songs. |
| `-q`, `--quiet` | Reduce output. Once prints only filter match counts and playlist creation; twice (`-qq`) prints nothing except errors. Cannot be combined with `--verbose`. |
| `--color`, `--no-color` | Force colored output on or off. By default color follows the terminal and the config file. |
| `--theme THEME` | Color theme: `auto` (default), `dark`, or `light`. `auto` uses `COLORFGBG` when available and otherwise assumes a dark terminal. |
| `--db PATH` | Use this SQLite database instead of the default cache location. |
| `-j N`, `--jobs N` | Parse cache misses with `N` worker processes. `0` uses one worker per CPU, capped at eight; `1` disables the process pool. Default is `0`. |
| `--clean` | Remove cache entries for files that no longer exist. With `PATH`, regenerate that collection first; `PATH` must be a directory. See [Cleaning the cache](#cleaning-the-cache). |
| `--show-rules` | Parse the filters selected with `--filter`, or every `.m3ug` file under `PATH`, and print the rule trees. No cache, audio scan, or playlists. |
| `--trace SONG` | Evaluate the filters selected with `--filter`, or the filters under `PATH`, for one audio file and print an annotated trace. No playlists. |
| `--trace-full SONG` | Like `--trace`, plus an exact dry-run simulation of playlist selection. No playlists. |
| `--tag-stats` | Show every tag found in the collection with file counts. No playlists are written. |
| `-t TAG`, `--tag TAG` | Show every distinct value of `TAG` with file counts. Implies `--tag-stats` and may be repeated. |
| `--overwrite`, `--no-overwrite` | Whether to replace an existing generated playlist. |
| `--include-source`, `--no-include-source` | Whether to embed the original `.m3ug` text as comments in the playlist. |
| `--extended-m3u`, `--no-extended-m3u` | Whether to write `#EXTM3U` and `#EXTINF` metadata. Enabled by default; `--no-extended-m3u` writes a plain list of paths. |
| `-h`, `--help` | Show the built-in help and exit. |

Every option with an on/off form overrides the corresponding config setting.
`--config` and `--no-config` are mutually exclusive.

`--show-rules`, `--trace`, `--trace-full`, `--clean`, and `--tag-stats` are
mutually exclusive modes. `--trace SONG` and `--trace-full SONG` search `PATH`
for filters, or use the filters selected with `--filter`, and take the audio
file as their option value. `--tag` cannot be combined with
`--show-rules`, `--trace`, `--trace-full`, or `--clean`. `--filter` cannot be
combined with `--clean` or `--tag-stats`.

None of the debugging modes writes a playlist. `--show-rules` opens no cache
database and scans no audio. `--trace` loads only `SONG` through the tag cache,
so it may add or refresh that one cache row. `--trace-full` may scan the
collection and update cache rows normally while it simulates selection.

## PATH and the config file

`PATH` is optional in three situations:

1. `[collection] path` is set in the config file. Running `genplis` with no
   arguments then scans that collection, which is convenient for
   [scheduled runs](https://github.com/haplo/genplis/blob/main/docs/scheduling.md).
2. `--clean` is used without a path, which cleans the **whole** database
   instead of a subtree.
3. `--show-rules` is used with `--filter`, which needs no scan root.

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
3. Selects the filters: the files named with `--filter`, or every `.m3ug` file
   found by walking the scan root (pruning excluded folders and files). The
   scan root is always `PATH` (or the configured collection). Includes are
   resolved recursively and their directives merged as defaults for the
   including file.
4. Walks the scan root for audio files, skipping unsupported formats silently
   (`--verbose` explains why). It parses each file's tags, reusing cached tags
   when the file has not changed, and applies every selected `.m3ug` file's
   rules as soon as that file's tags are available.
5. Writes a playlist for each selected `.m3ug` file that matched at least one
   song. Entries are ordered by the file's `@sort` directive, or by
   `[output] sort` (default `filename`) when it has none. `@LIMIT`,
   `@LIMIT N PER tag`, and `@MAX-DURATION` can cap the selected entries after
   ordering.
6. Prints how many files were processed, how long it took, and the process's
   RAM usage.

A run only filters the files under the scan root. Cached entries for other
folders are not used to build playlists, and a `.m3ug` file does not pull
audio files in from outside the scanned tree. An `@INCLUDE` may read a filter
file from outside the scan root, but it only adds rules and defaults.

To regenerate only one filter, name it with `--filter`; the scan root is still
`PATH` (or the configured collection):

```bash
cd ~/Music
genplis . --filter Playlists/Synthwave.m3ug
```

With `[collection] path` configured, the `PATH` argument can be omitted:
`genplis --filter Playlists/Synthwave.m3ug`.

This scans the collection but processes only that filter, writes
`Playlists/Synthwave.m3u` next to it, and leaves every other playlist
untouched. A `.m3ug` file passed as `PATH` is rejected with a message pointing
to `--filter`.

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

### Inspecting or processing one file

```bash
uv run genplis /path/to/song.mp3
```

This prints the cache status and the parsed tags, then exits. Calculated
values are prefixed with `*` (`*filename`, `*duration`, `*bitrate`,
`*samplerate`, `*rating`) to distinguish them from tags embedded in the file.
Filter names do **not** include the `*`.

To process one specific filter, pass the collection as `PATH` (or use the
configured collection) and select the filter with `--filter`:

```bash
uv run genplis ~/Music --filter ~/Music/Favorites.m3ug
```

This prints the rule tree, including inline `@INCLUDE` nodes and the effective
directives. It then scans the collection for audio files using only this
filter, so `Favorites.m3ug` produces its `Favorites.m3u` without processing any
other `.m3ug` files. A file marked `@NO-PLAYLIST` is still parsed and may
satisfy includes, but no playlist is written for it. To inspect the tree
without scanning audio or writing a playlist, use
`genplis --show-rules --filter Favorites.m3ug`.

Both forms also warn when the file matches the current exclude configuration.

### Inspecting tags across a collection

```bash
uv run genplis --tag-stats ~/Music
```

This walks the collection, reuses the tag cache, and prints every tag that at
least one supported file has:

```text
Tag statistics for /home/me/Music
2 of 2 supported files have embedded tags

Embedded tags
Tag               Files  Coverage  Distinct  Examples
----------------  -----  --------  --------  --------------------------------
artist                2    100.0%         1  Test Artist
genre                 2    100.0%         4  Electronic, Retrowave, Synthwave
title                 2    100.0%         1  Test

Calculated tags
Tag           Files  Coverage  Distinct  Examples
------------  -----  --------  --------  ----------------------------------------
*bitrate          2    100.0%         2  112, 127.998
*duration         2    100.0%         2  1, 3.239...
```

- `Files` is the number of files that have the tag. `Coverage` uses all
  supported files as the denominator.
- `Distinct` is the number of different values. It is capped for very common
  high-cardinality tags such as `title`; a `+` marks a capped count.
- `Examples` shows a few values, ordered by how many files contain them.
- Calculated audio properties are listed separately with the same `*` prefix
  used by single-file inspection.
- `[tags] ignore` and `[tags] max_size` still apply, so the report shows what
  filters can actually use. Ignored tags are not listed.
- `.m3ug` files are not parsed and no playlists are written or overwritten.
- The tag cache is updated normally, so a stats run also warms the cache for
  later playlist runs.
- With `-q`, the table is still printed but progress lines are suppressed.
  With `-qq`, nothing is printed. A single audio file uses the normal detailed
  listing instead of the collection table.
- Tag statistics cannot be combined with `--clean`.

Use `-t/--tag` to focus on one or more tags and see every distinct value:

```bash
uv run genplis -t genre ~/Music
uv run genplis --tag-stats -t genre -t year ~/Music
```

```text
Tag statistics for /home/me/Music
2 of 2 supported files have embedded tags

Tag: genre (embedded)
Files: 2 of 2 (100.0%)
Distinct values: 4

Value                             Files  Coverage
--------------------------------  -----  --------
Electronic                            1     50.0%
Retrowave                             1     50.0%
Synthwave                             1     50.0%
Synthwave; Retrowave; Electronic      1     50.0%

A file can contain more than one value, so coverage values can add up to more than 100%.

Files without this tag: 0 (0.0%)
```

Values are counted once per file, so a file with several genres contributes
to each of them. Values are ordered by file count, highest first. Every
distinct value is listed, but extremely long values are shortened in the
table; the file count still refers to the full value. A
requested tag that does not exist prints a message and is not an error. Tag
names are case-insensitive. Use `-t '*rating'` to select only the calculated
rating; `-t rating` shows both the embedded `rating` and the calculated
`*rating` when both are present.

### Debugging filters

```bash
uv run genplis --show-rules --filter Favorites.m3ug
uv run genplis --show-rules ~/Music
uv run genplis --trace song.mp3 --filter Favorites.m3ug
uv run genplis --trace-full song.mp3 --filter Favorites.m3ug
```

- `--show-rules` parses the filters named with `--filter`, or every
  non-excluded `.m3ug` file under a directory, and prints the rule trees. It
  does not open the cache, read audio, or write playlists. A `.m3ug` file or an
  audio file passed as `PATH` is an error; use `--filter` for a single filter.
- `--trace` prints the evaluation tree for one audio file: `PASS`, `FAIL`, and
  `SKIP` nodes, the tags consulted, playlist inputs, and the final match
  result. It loads the target through the normal cache path, so that one file
  may be parsed or refreshed. It never writes a playlist.
- `--trace-full` adds the deterministic selection result for every filter:
  sorted position, dedupe winner, cap failures, and the final playlist
  position. It may scan the collection and update the cache like a normal run,
  but it writes no playlists. Use it when count or duration caps make the
  ordinary trace report `selection: not simulated`.
- `-q` keeps the requested tree or trace and suppresses progress chatter.
  `-qq` suppresses all normal output. Errors still go to standard error.

See [Testing and debugging filters](https://github.com/haplo/genplis/blob/main/docs/m3ug.md#testing-and-debugging-filters)
for annotated examples.

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
  a key are always kept. `@LIMIT` caps the total number of entries,
  `@LIMIT N PER tag` caps how many share one tag value, and `@MAX-DURATION`
  caps their total duration. These apply after ordering; `0` disables any cap.
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
under that path that no longer exist. The path must be a directory; audio files
and `.m3ug` filters are rejected. This keeps the behavior predictable: the
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
exclusion decisions, rule trees, the effective sort order, and the list of
matching songs. M3UG rule trees are printed while filters are discovered,
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

## Color

Colored output is enabled automatically for interactive terminals. Set
`NO_COLOR` to disable it, or use `--color`/`--no-color` to override automatic
detection. `FORCE_COLOR=1` also forces color when output is redirected.
`--theme dark` and `--theme light` choose colors for the terminal
background; the default `auto` reads the last field of `COLORFGBG` when the
terminal provides it and otherwise assumes dark. The `[general] color` and
`theme` settings provide the same controls in the config file. Piped output is
plain unless color is forced, so logs and generated documentation stay free of
escape codes.

Tag names, tag values, rule trees, traces, tag statistics, progress lines,
warnings, and errors all use the same semantic palette.

## See also

- [M3UG reference](https://github.com/haplo/genplis/blob/main/docs/m3ug.md)
- [Configuration reference](https://github.com/haplo/genplis/blob/main/docs/config.md)
- [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md)
- [Scheduling runs](https://github.com/haplo/genplis/blob/main/docs/scheduling.md)
- [Example filters](https://github.com/haplo/genplis/tree/main/examples)
