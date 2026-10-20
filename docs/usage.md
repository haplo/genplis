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
| `--clean` | Remove cache entries for files that no longer exist. See [Cleaning the cache](#cleaning-the-cache). |
| `--overwrite`, `--no-overwrite` | Whether to replace an existing generated playlist. |
| `--include-source`, `--no-include-source` | Whether to embed the original `.m3ug` text as comments in the playlist. |
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
3. Walks `PATH`, skipping excluded folders and files. A file that is not a
   supported audio format and is not a `.m3ug` file is skipped silently
   (`--verbose` explains why).
4. Parses each audio file's tags, reusing cached tags when the file has not
   changed, and parses every `.m3ug` file it finds.
5. Applies each `.m3ug` file's rules to **all** audio files found during this
   run, and writes a playlist if at least one song matches.
6. Prints how many files were processed, how long it took, and the process's
   RAM usage.

A run only filters the files under `PATH`. Cached entries for other folders
are not used to build playlists, and a `.m3ug` file does not pull in files from
outside the scanned tree.

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

This prints the parsed rules and exits. It does **not** generate a playlist:
playlists are only produced when scanning a directory.

Both forms also warn when the file matches the current exclude configuration.

## Generated playlists

- A `.m3ug` file named `Favorites.m3ug` produces `Favorites.m3u` in the same
  directory.
- Only songs that match **all** rules are included.
- If no song matches, no playlist is written. An existing playlist is left
  untouched in that case.
- Playlists are UTF-8 text, one path per line.
- Paths are written relative to the playlist's directory, so nested filter
  files can use `../` entries. This keeps the playlist usable when the
  collection is moved.
- By default the original `.m3ug` text is embedded at the top as comments,
  prefixed with `# `. Every source line is prefixed, including blank lines
  (written as `#`), so directives such as `#EXTINF` in a filter file cannot be
  mistaken for playlist metadata. Use `--no-include-source` to omit it.
- Existing playlists are overwritten by default. With `--no-overwrite`,
  genplis prints a warning and leaves the file alone.
- The generated M3U is a plain list of files; extended M3U metadata
  (`#EXTINF`) is not generated yet.

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
- **Memory:** tags for the files in the current run are held in RAM while
  filtering. Estimate about 10 MiB per 1,000 files, often less.

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

Cleaning prints how many entries were removed and how much disk space was
reclaimed. The database is vacuumed only when something was removed, and
vacuuming can take a while and temporarily needs free disk space roughly the
size of the database. If the database does not exist and no path was given,
genplis prints that there is nothing to clean and exits.

## Output and errors

Normal runs print per-file cache updates, a line for each filter file with its
match count, and a final summary. `--verbose` adds config/database paths,
exclusion decisions, parsed rules, and the list of matching songs.

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
- A playlist that exists and cannot be overwritten because of
  `--no-overwrite` produces a warning, not an error. The warning is
  suppressed by `-q`.

## See also

- [M3UG reference](https://github.com/haplo/genplis/blob/main/docs/m3ug.md)
- [Configuration reference](https://github.com/haplo/genplis/blob/main/docs/config.md)
- [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md)
- [Scheduling runs](https://github.com/haplo/genplis/blob/main/docs/scheduling.md)
- [Example filters](https://github.com/haplo/genplis/tree/main/examples)
