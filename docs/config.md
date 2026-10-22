# Configuration reference

Configuration is optional: genplis works without a config file, and every
setting has a default. To save your preferences, copy the
[annotated example](https://github.com/haplo/genplis/blob/main/examples/config.ini)
to `~/.config/genplis/config.ini` (the usual location) and edit the settings
you need. For everyday commands, see [Usage](usage.md).

## Location and loading

| Command-line option | Configuration used |
| --- | --- |
| None | `$XDG_CONFIG_HOME/genplis/config.ini`, usually `~/.config/genplis/config.ini` |
| `--config FILE` | The named file; an error if it doesn't exist |
| `--no-config` | Built-in defaults only |

A missing default file is fine. `--config` and `--no-config` cannot be
combined. Use `--verbose` to see which config file was loaded.

## Precedence

Settings are chosen in this order:

1. Command-line options.
2. The config file.
3. Built-in defaults.

The tables below list the CLI overrides. On/off switches work in both
directions: for example, `--overwrite` overrides `overwrite = false`, and
`--no-overwrite` overrides `overwrite = true`. An omitted option leaves the
configured value in effect.

## File format

- Use a UTF-8 INI file; a byte-order mark is accepted. Comments can start
  with `#` or `;` on their own lines.
- Section and option names ignore case. Unknown names and duplicate
  sections or options are errors, helping catch typos.
- **Paths** expand `~`; relative paths start at the config file's directory,
  not the directory where you run genplis.
- **Lists** (`exclude` and `ignore`) use one indented entry per line. Blank
  lines are ignored; commas are literal, except in `sort`.
- **Boolean settings** accept `true`/`false`, `yes`/`no`, `on`/`off`, or
  `1`/`0`, ignoring case. `jobs` and `max_size` accept non-negative integers.
- There is no variable interpolation: `%` is literal and needs no escaping.

Invalid settings stop the run with an error identifying the config file
and, where relevant, the section and option.

## `[general]`

| Option | Default | CLI override | Purpose |
| --- | --- | --- | --- |
| `verbose` | `false` | `--verbose` / `--no-verbose` | Show config/cache paths, rule trees, matches, skipped files, and cache updates. |
| `quiet` | `false` | `-q` / `--quiet` | Show only filter counts and playlist creation during normal runs. |
| `jobs` | `0` | `-j` / `--jobs` | Parsing workers: `0` = automatic (one per CPU, capped at 8); `1` = no multiprocessing. |
| `color` | `true` | `--color` / `--no-color` | Allow colors on interactive terminals; `false` disables them. |
| `theme` | `auto` | `--theme` | Terminal background: `auto`, `dark`, or `light`. |

Don't enable both `verbose` and `quiet`. A command-line verbosity flag
overrides the configured mode, so `-q` can silence a verbose configuration
and `-v` can override a quiet one. See [Output controls](usage.md#control-output-and-get-help)
for normal progress output and `-qq`.

`jobs` only affects uncached or changed audio files; small runs may not start
worker processes. An explicit positive number sets the worker limit without
changing playlist results. See the [Parsing pipeline](dev.md#parsing-pipeline)
for implementation details.

Redirected output is normally plain. `NO_COLOR` disables automatic color;
`--color` and `--no-color` override both this variable and the config setting.
The `auto` theme reads `COLORFGBG` when available and falls back to `dark`
when the terminal background is unknown.

## `[collection]`

| Option | Default | CLI override | Purpose |
| --- | --- | --- | --- |
| `path` | None | `PATH` | Collection to scan when no command-line path is given. |
| `exclude` | Empty list | `-e` / `--exclude` | Skip matching file and folder paths; replaces the configured list. |

### `path`

Set a default collection so you can run plain `genplis`:

```ini
[collection]
path = ~/Music
```

A command-line path overrides this setting. `--filter` selects filters, not
the collection to scan; see [Regenerate one playlist](usage.md#regenerate-one-playlist).
This default also makes [scheduled runs](scheduling.md) simpler.

### `exclude`

Use **Python regular expressions, not shell wildcards**, one per line:

```ini
[collection]
exclude =
    /\.Trash/
    /@eaDir/
    \.tmp$
```

A pattern searches the full path; any match skips the file or folder.
Excluded folders aren't scanned. Folder paths are also tested with a
trailing separator, so `/@eaDir/` matches the folder itself. `\.tmp$` matches
paths ending in `.tmp`.

**Any command-line `--exclude` replaces the whole configured list.** To add
a permanent exclusion without losing the others, edit this list instead.

## `[tags]`

| Option | Default | CLI override | Purpose |
| --- | --- | --- | --- |
| `max_size` | `1000` | None | Maximum combined UTF-8 size of a tag's values, in bytes; `0` disables the limit. |
| `ignore` | Empty list | None | Tag names to discard before caching and filtering. |

### `max_size`

Values above the limit are discarded, often removing lyrics or long comments.
For multi-valued tags, sizes are added together; a total exactly at the limit
is kept. The limit measures UTF-8 bytes, not characters.

Calculated audio properties are exempt from this limit, but can be removed
with `ignore`. See [Missing or discarded tags](tags.md#missing-or-discarded-tags)
for how discarded values affect filters.

### `ignore`

List tag names without quotes or commas; matching ignores case:

```ini
[tags]
ignore =
    comment
    lyrics
```

Ignored tags are removed before size checking. For calculated properties,
use the unprefixed name: `duration`, not `*duration`. Ignoring `rating`
removes the raw tag but doesn't prevent calculation from `fmps_rating`;
ignore both names to hide ratings entirely. See [Rating](tags.md#rating).

## `[database]`

| Option | Default | CLI override | Purpose |
| --- | --- | --- | --- |
| `path` | `$XDG_CACHE_HOME/genplis/genplis.db` | `--db` | Location of the SQLite tag cache. |

The usual location is `~/.cache/genplis/genplis.db`. Like other configured
paths, it expands `~` and resolves relative to the config file. The cache is
disposable; see [Cleaning the cache](usage.md#cleaning-the-cache) for behavior
and maintenance.

## `[output]`

| Option | Default | CLI override | Purpose |
| --- | --- | --- | --- |
| `overwrite` | `true` | `--overwrite` / `--no-overwrite` | Replace existing playlists; `false` leaves them untouched with a warning. |
| `include_source` | `true` | `--include-source` / `--no-include-source` | Embed the `.m3ug` source as playlist comments. |
| `extended_m3u` | `true` | `--extended-m3u` / `--no-extended-m3u` | Write `#EXTM3U` / `#EXTINF` metadata; `false` writes a plain list of paths. |
| `sort` | `filename` | None | Default playlist order, unless the filter has `@SORT`. |

See [Generated playlists](usage.md#generated-playlists) for output behavior.

### `sort`

Use the same comma-separated keys as `@SORT`, highest priority first. Each
key can take `asc` (the default) or `desc`:

```ini
[output]
sort = artist, album, disc, track, title
```

Other useful values:

| Setting | Effect |
| --- | --- |
| `sort = *rating desc, artist, title` | Highest calculated ratings first |
| `sort = random 42` | Reproducible shuffle; omit the seed to vary each run |
| `sort = artist, random` | Shuffle within each artist |
| `sort =` | Keep directory-walk order |

The default `filename` sorts by absolute path. A filter's `@SORT` line
**replaces**, rather than extends, this setting. See [Ordering](m3ug.md#ordering)
for random-key restrictions, missing values, and other comparison rules.

## Settings that invalidate the cache

Changing `[tags] max_size` or `[tags] ignore` discards all cached tags and
forces a full re-parse, because those settings change what is stored. The
cache also resets when the tag library version or genplis's cache format
changes. This happens automatically; the next run is slower, but no manual
cleanup is needed.

## See also

- [Usage guide](usage.md)
- [M3UG reference](m3ug.md)
- [Tags](tags.md)
- [Annotated example config](https://github.com/haplo/genplis/blob/main/examples/config.ini)
