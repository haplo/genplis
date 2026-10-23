# Genplis: a music playlist generator

[![CI](https://github.com/haplo/genplis/actions/workflows/ci.yml/badge.svg)](https://github.com/haplo/genplis/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/genplis)](https://pypi.org/project/genplis/)
[![Python](https://img.shields.io/pypi/pyversions/genplis)](https://pypi.org/project/genplis/)

*Genplis* generates M3U playlists from a collection of music files by looking
at their tags and audio properties, applying user-defined filters, and
ordering the results.

Filters are written in `.m3ug` files using a small language called M3UG. Put a
filter file in your collection, run genplis, and a matching `.m3u` playlist
appears next to it. There is no manual list to maintain: add music, run again,
and the playlist updates.

It scratches my own itch where I have a local music collection curated over 30
years and I wanted playlists like "my favorite songs", "80s music", or
"musicals" without updating them by hand.

## Requirements

Python 3.12 or later. Python 3.10 and 3.11 might work, but they are untested
and unsupported.

## Install

With [uv](https://github.com/astral-sh/uv):

```bash
uv tool install genplis
```

With [pipx](https://pipx.pypa.io/stable/):

```bash
pipx install genplis
```

You can also `pip install genplis` inside a virtual environment.

Verify the installation with `genplis --version`.

## Quick start

Create a filter in your music collection, for example
`~/Music/Favorites.m3ug`:

```text
# four-star metal
genre ~ "Metal"
*rating >= 4
```

Then scan the collection:

```bash
genplis ~/Music
```

Genplis reads the tags of every supported audio file, caches them in SQLite,
applies the filter, and writes `~/Music/Favorites.m3u` if anything matched.
Later runs only re-read files that changed. See the
[usage guide](https://github.com/haplo/genplis/blob/main/docs/usage.md)
for common commands and troubleshooting.

To regenerate just one playlist without processing the other filters in the
collection, select the filter with `--filter`:

```bash
genplis ~/Music --filter ~/Music/Favorites.m3ug
```

To see which tags a file actually has (useful when writing filters):

```bash
genplis ~/Music/some-song.mp3
```

To inventory every tag in the collection, or every value of one tag:

```bash
genplis --tag-stats ~/Music
genplis -t genre ~/Music
```

Rating scales vary between players, so check a real file before trusting a
rule. Genplis tries its best to calculate a normalized `*rating`, if it doesn't
work for you [open an issue asking for
support](https://github.com/haplo/genplis/issues).

## AI agents

**Using an AI agent?** Run `genplis --install-skill` for Codex/OpenCode or
`genplis --install-skill claude` for Claude Code. The bundled skill teaches
your agent to inspect your library and write and validate M3UG filters.
See the [agent guide](https://github.com/haplo/genplis/blob/main/docs/agents.md).

## Documentation

Visit the **[Genplis website](https://haplo.github.io/genplis/)** for the
[documentation index](https://haplo.github.io/genplis/docs/) and
[copyable, downloadable M3UG examples](https://haplo.github.io/genplis/docs/examples/).
The guides below are the same Markdown sources used by the website.

| Guide | Contents |
| --- | --- |
| [Usage](https://github.com/haplo/genplis/blob/main/docs/usage.md) | Common commands, tag inspection, playlist behavior, troubleshooting, cache cleaning |
| [Configuration](https://github.com/haplo/genplis/blob/main/docs/config.md) | Config locations, precedence, all settings and defaults, cache invalidation |
| [M3UG reference](https://github.com/haplo/genplis/blob/main/docs/m3ug.md) | Rule syntax, operators, ordering, dedupe, limits, includes, filter debugging |
| [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md) | Tag names and units, multi-value rules, ratings, statistics, missing tags |
| [AI agents](https://github.com/haplo/genplis/blob/main/docs/agents.md) | Install the portable skill or use the agent instructions directly |
| [Scheduling](https://github.com/haplo/genplis/blob/main/docs/scheduling.md) | Systemd and cron setup, logs, missed runs, troubleshooting |
| [Development](https://github.com/haplo/genplis/blob/main/docs/dev.md) | Contributor setup, checks, architecture, website, releases, roadmap |
| [Examples](https://github.com/haplo/genplis/tree/main/examples) | Ready-to-copy `.m3ug` filters and `config.ini` |
| [Changelog](https://github.com/haplo/genplis/blob/main/CHANGELOG.md) | Notable changes in each release |

## Acknowledgments

*Genplis* uses the [tinytag library](https://github.com/tinytag/tinytag) for
parsing tags in audio files. It was chosen for being a pure Python library
with no additional dependencies.

## License

[GPL-3.0-or-later](https://github.com/haplo/genplis/blob/main/LICENSE): GNU
General Public License, either version 3 or (at your option) any later version.
