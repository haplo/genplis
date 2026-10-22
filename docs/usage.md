# Usage guide

This guide covers everyday commands and playlist behavior. For installation
and your first playlist, start with the [Quickstart](index.md#quickstart).
For writing filters, see the [M3UG reference](m3ug.md).

The examples use the installed `genplis` command. If you're working from a
clone, prefix commands with `uv run` from the project directory.

## What a run does

When you pass a music directory, genplis:

1. Finds `.m3ug` filters anywhere under that directory.
2. Reads supported audio files under the same directory and tests each song
   against the filters. Tags are cached, so later runs only re-read changed
   files.
3. Writes a playlist next to each filter that has matches, then prints a
   summary.

Each filter sees the **whole collection you scanned**, not just the folder
containing the filter. Music outside that directory is not included, even
if it was cached by an earlier run.

## Regenerate one playlist

Use `--filter` to select a filter while still scanning your collection:

```bash
genplis ~/Music --filter ~/Music/Metal.m3ug
```

Other playlists are left untouched. Repeat `--filter` to select several
filters.

## Find tags for your filters

To see the tags available in one song:

```bash
genplis ~/Music/some-song.mp3
```

Calculated properties such as `*duration` are displayed with a `*` prefix.
Leave it off in filters: write `duration < 5m`, not `*duration < 5m`.

See [Tags](tags.md#common-tags) for commonly available names.

### Inspecting tags across a collection

List all tags in your collection and how many files have each one:

```bash
genplis --tag-stats ~/Music
```

To see the different values of a particular tag, such as the genres you can
filter on:

```bash
genplis -t genre ~/Music
```

Repeat `-t` to inspect more tags. These commands update the tag cache but
don't create or change playlists.

See [Tags](tags.md) for how tag values are interpreted and [Tag
settings](config.md#tags) for ignored or oversized values.

## Find out why a song is missing

Use `--trace` to check a song against a filter without writing a playlist:

```bash
genplis ~/Music --trace ~/Music/some-song.mp3 --filter ~/Music/Metal.m3ug
```

The trace shows which rules pass or fail. If the song matches but still
doesn't appear, use `--trace-full` instead: it also checks ordering,
duplicate removal, and playlist limits across the collection.

To inspect a filter's parsed rules without scanning music, use
`genplis --show-rules --filter ~/Music/Metal.m3ug`.

See [Testing and debugging filters](m3ug.md#testing-and-debugging-filters)
for annotated output and further examples.

## Generated playlists

- `Metal.m3ug` produces `Metal.m3u` in the same directory.
- **Existing generated playlists are replaced by default**; add
  `--no-overwrite` to leave them untouched. Your audio files are not modified.
- If no songs match, no playlist is written; an existing playlist is left
  untouched rather than emptied or deleted.
- Entries are sorted by file path unless the filter or configuration sets
  another order. See [Ordering](m3ug.md#ordering) and
  [Playlist limits](m3ug.md#playlist-limits) to customize the selection.
- Song paths are relative to the playlist where possible, so you can move
  the collection and its playlists together.
- By default, playlists include song titles and durations, plus the original
  filter as comments. Use `--no-extended-m3u` for a plain list of paths or
  `--no-include-source` to omit the filter comments.

See [Output settings](config.md#output) for playlist defaults.

## Save your usual settings

No configuration file is needed to get started. To avoid typing your music
directory each time, create `~/.config/genplis/config.ini` (the usual
location) with:

```ini
[collection]
path = ~/Music
```

You can then run `genplis` with no path, or
`genplis --filter ~/Music/Metal.m3ug` for one playlist. A directory
given on the command line overrides the configured one.

See [Configuration](config.md) for config locations, exclusions, worker
counts, color themes, and other defaults. To update playlists automatically,
see [Scheduling runs](scheduling.md).

## Control output and get help

| Option | Use it to… |
| --- | --- |
| `-v`, `--verbose` | Show more detail about filters, matches, skipped files, and cache updates. |
| `-q`, `--quiet` | Show only filter match counts and playlist creation during normal runs. |
| `-qq` | Suppress everything except errors, useful for scheduled runs. |
| `--no-color` | Turn off colored output. |
| `-h`, `--help` | See the full list of command-line options. |

Normal runs show a progress bar while files that are missing from the tag
cache, or whose tags are stale, are parsed. Redirected output gets one summary
line instead. The bar is omitted when the cache is warm, with `-q` or `-qq`,
and with `--verbose`, which prints a line for every cache update instead.

Don't combine `-q` and `-v`. If a run fails, read the error message; filter
syntax errors identify the file and line to fix.

## Cleaning the cache

Genplis automatically caches tags to make repeat runs faster. You normally
don't need to manage this cache. It lives at `~/.cache/genplis/genplis.db`
on a typical setup; see [Database settings](config.md#database) to change it
and [Cache invalidation](config.md#settings-that-invalidate-the-cache) for
when it is rebuilt automatically.

After deleting or moving music, you can remove entries for missing files:

```bash
genplis --clean ~/Music
```

This regenerates playlists first, then cleans entries under that directory.
To clean missing-file entries across the **whole cache**, without generating
playlists:

```bash
genplis --clean
```

The pathless form ignores the configured collection path. Neither command
deletes music files. For implementation details, see
[Cache internals](dev.md#cache-internals).
