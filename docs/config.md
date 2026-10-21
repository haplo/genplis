# Configuration reference

Genplis reads optional settings from an INI file. The annotated starter file
is [`examples/config.ini`](https://github.com/haplo/genplis/blob/main/examples/config.ini):
copy it to `$XDG_CONFIG_HOME/genplis/config.ini` (usually
`~/.config/genplis/config.ini`) and edit it. Every setting is optional; when
the file is missing, genplis uses the defaults below.

For the command-line options and how they interact with these settings, see
[Usage](https://github.com/haplo/genplis/blob/main/docs/usage.md).

## Location and loading

| Situation | What genplis reads |
| --- | --- |
| No option | `$XDG_CONFIG_HOME/genplis/config.ini`, or `~/.config/genplis/config.ini` when `XDG_CONFIG_HOME` is unset |
| `--config FILE` | That file. A missing explicit file is an error. |
| `--no-config` | Nothing; built-in defaults are used. |

A missing default config file is not an error. `--config` and `--no-config`
cannot be used together. Running with `--verbose` prints which config file was
used, if any.

## Precedence

1. Command-line options.
2. The config file.
3. Built-in defaults.

For booleans, the command-line switches are `--verbose`/`--no-verbose`,
`--overwrite`/`--no-overwrite`, `--include-source`/`--no-include-source`, and
`--extended-m3u`/`--no-extended-m3u`. If neither form is given, the config
value is used.

`PATH` is special: it may be omitted when `[collection] path` is set. If a path
is given on the command line, it wins. `--exclude` is also special: any
`--exclude` option replaces the entire configured list rather than adding to
it.

## File format

The file is standard INI syntax with a few strict rules:

- **Encoding:** UTF-8. A byte-order mark is accepted.
- **Sections and options:** names are case-insensitive, so `[Tags]` and
  `[tags]`, `MAX_SIZE` and `max_size` are equivalent.
- **Unknown names are errors.** Unknown sections and unknown options make
  genplis exit with an error instead of being ignored, which catches typos.
- **Duplicate sections are errors**, even when only the case differs.
- **No interpolation.** The percent sign is an ordinary character, so regexes
  such as `/100%/` work as written.
- **Lists are one entry per line.** For `exclude` and `ignore`, each non-empty
  line is one entry. Commas are part of the value, not separators.
- **Paths** may start with `~`. Relative paths are resolved against the config
  file's directory, not the current working directory.

Booleans accept `true`/`false`, `yes`/`no`, `on`/`off`, and `1`/`0`, in any
case. Integers must be whole numbers within the documented range.

Errors identify the file and, where relevant, the section and option, for
example:

```text
genplis: error: /home/me/.config/genplis/config.ini: [tags] max_size: expected an integer, got 'many'
```

## `[general]`

| Option | Type | Default | CLI equivalent | Description |
| --- | --- | --- | --- | --- |
| `verbose` | boolean | `false` | `--verbose` / `--no-verbose` | Print config and database paths, skip decisions, parsed rules, and matching songs. |
| `quiet` | boolean | `false` | `-q` / `--quiet` | Print only filter match counts and playlist creation. |
| `jobs` | integer ≥ 0 | `0` | `--jobs` | Worker processes for cache misses and stale files. `0` = one per CPU (capped at 8), `1` = no pool. |

`verbose = true` and `quiet = true` cannot be enabled at the same time. A
command-line verbosity flag overrides the configured value, so
`verbose = true` with `-q` runs quietly, and `quiet = true` with `-v` runs
verbosely.

`jobs` only affects files that need parsing. Cached files, M3UG parsing,
filtering, and playlist generation stay in the main process, which also keeps
the only database connection. Small runs do not start a pool. The worker count
can be overridden with `--jobs` on the command line.

## `[collection]`

| Option | Type | Default | CLI equivalent | Description |
| --- | --- | --- | --- | --- |
| `path` | path | none | `PATH` | Music collection to scan when `PATH` is omitted. |
| `exclude` | list of regexes | empty | `--exclude` (replaces) | Paths to skip. |

### `path`

Setting this makes `PATH` optional on the command line:

```ini
[collection]
path = ~/Music
```

Relative paths are resolved against the config file's directory. This is what
lets a timer or service run plain `genplis` with no arguments; see [Running
genplis on a schedule](https://github.com/haplo/genplis/blob/main/docs/scheduling.md).

### `exclude`

One regular expression per line, matched with `re.search` against the full
path. Files and folders matching any pattern are skipped. A matching folder is
pruned, so its contents are never scanned. Folder paths are also tested with a
trailing path separator, which is why patterns such as `/@eaDir/` match the
folder itself.

```ini
[collection]
exclude =
    /\.Trash/
    /@eaDir/
    \.tmp$
```

These are Python regular expressions, not shell globs. A pattern is a search,
not a full-path match, so `.tmp$` matches any path ending in `.tmp`. Blank
lines are ignored and `%` needs no escaping.

Any `--exclude` on the command line replaces this whole list.

## `[tags]`

| Option | Type | Default | CLI equivalent | Description |
| --- | --- | --- | --- | --- |
| `max_size` | integer ≥ 0 | `1000` | none | Maximum UTF-8 size of a tag value, in bytes. `0` disables the limit. |
| `ignore` | list of names | empty | none | Tag names to discard before caching and filtering. |

### `max_size`

Tag values larger than this many UTF-8 encoded bytes are discarded before
caching. Multi-valued tags are measured as the sum of their values. A value
exactly at the limit is kept. This usually removes lyrics and long comments.

- `max_size = 0` disables the size limit entirely.
- Calculated audio properties (`filename`, `filesize`, `duration`, and so on)
  are never discarded by this limit. They can still be excluded through
  `ignore`.
- The comparison is against the encoded byte length, so non-ASCII text counts
  more than one byte per character.
- Changing this value invalidates the tag cache, because it changes which tags
  are stored.

### `ignore`

One tag name per line. Names are case-insensitive. Ignored tags are dropped
before the size check and are not cached, so filters behave as if the tag did
not exist.

```ini
[tags]
ignore =
    comment
    encoder
    encoder_settings
    lyrics
```

Calculated values are controlled by their unprefixed names: put `filename` or
`filesize` in this list to remove them, not `*filename`. Ignoring `rating`
drops the raw tag, but a rating can still be derived from `fmps_rating`;
ignore both names to hide ratings entirely.

Changing `ignore` invalidates the cache.

## `[database]`

| Option | Type | Default | CLI equivalent | Description |
| --- | --- | --- | --- | --- |
| `path` | path | `$XDG_CACHE_HOME/genplis/genplis.db` | `--db` | Location of the SQLite tag cache. |

The default is usually `~/.cache/genplis/genplis.db`. `~` is expanded and
relative paths are resolved against the config file. The database is
disposable; deleting it only costs a re-parse on the next run. See
[Usage](https://github.com/haplo/genplis/blob/main/docs/usage.md#cache) for
cache behavior and cleaning.

## `[output]`

| Option | Type | Default | CLI equivalent | Description |
| --- | --- | --- | --- | --- |
| `overwrite` | boolean | `true` | `--overwrite` / `--no-overwrite` | Replace playlists that already exist. |
| `include_source` | boolean | `true` | `--include-source` / `--no-include-source` | Embed the `.m3ug` source as comments at the top of the playlist. |
| `extended_m3u` | boolean | `true` | `--extended-m3u` / `--no-extended-m3u` | Write an `#EXTM3U` header and `#EXTINF` metadata for every entry. |

With `overwrite = false`, an existing playlist is left untouched and a warning
is printed.

With `include_source = false`, the generated `.m3u` contains no record of the
rules that produced it.

With `extended_m3u = true` (the default), the playlist starts with `#EXTM3U`
and each entry is preceded by `#EXTINF:<seconds>,<artist> - <title>`. The title
falls back to the title tag, the artist tag, and finally the file name; an
unknown duration is written as `-1`. Set it to `false` to write a plain list
with one path per line:

```ini
[output]
extended_m3u = false
```

## Settings that invalidate the cache

Changing either of these discards all cached tags and forces a full re-parse:

- `[tags] max_size`
- `[tags] ignore`

The cache also resets when the tag library version or genplis's cache format
changes. This is automatic; no manual cleanup is needed. The first run after
such a change is slower.

## See also

- [Usage guide](https://github.com/haplo/genplis/blob/main/docs/usage.md)
- [M3UG reference](https://github.com/haplo/genplis/blob/main/docs/m3ug.md)
- [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md)
- [Annotated example config](https://github.com/haplo/genplis/blob/main/examples/config.ini)
