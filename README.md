# Genplis: a music playlist generator

[![CI](https://github.com/haplo/genplis/actions/workflows/ci.yml/badge.svg)](https://github.com/haplo/genplis/actions/workflows/ci.yml)

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

*genplis* is not published to [PyPI](https://pypi.org/) yet, so it cannot be
installed with `pip` at the moment.

## Install

Install [uv](https://github.com/astral-sh/uv), then:

```bash
git clone https://github.com/haplo/genplis.git
cd genplis
uv sync
```

## Quick start

Create a filter in your music collection, for example
`~/Music/Favorites.m3ug`:

```text
# four-star metal
genre ~ "Metal"
rating >= 4
```

Then scan the collection:

```bash
uv run genplis ~/Music
```

Genplis reads the tags of every supported audio file, caches them in SQLite,
applies the filter, and writes `~/Music/Favorites.m3u` if anything matched.
Later runs only re-read files that changed. Large cold scans parse files in
parallel by default; see [Parallel parsing](https://github.com/haplo/genplis/blob/main/docs/usage.md#parallel-parsing)
for `--jobs`.

To regenerate just one playlist without processing the other filters in the
collection, select the filter with `--filter`:

```bash
uv run genplis ~/Music --filter ~/Music/Favorites.m3ug
```

To see which tags a file actually has (useful when writing filters):

```bash
uv run genplis ~/Music/some-song.mp3
```

To inventory every tag in the collection, or every value of one tag:

```bash
uv run genplis --tag-stats ~/Music
uv run genplis -t genre ~/Music
```

Filter values are case-insensitive by default; add `@CASE` when case matters.
Rating scales vary between players, so check a real file before trusting a
rule. The references below cover the details and the common pitfalls.

## Documentation

| Guide | Contents |
| --- | --- |
| [Usage](https://github.com/haplo/genplis/blob/main/docs/usage.md) | Options, single-file inspection, tag statistics, generated playlists, the tag cache, `--clean` |
| [Configuration](https://github.com/haplo/genplis/blob/main/docs/config.md) | Config file location, every setting, precedence, annotated example |
| [M3UG reference](https://github.com/haplo/genplis/blob/main/docs/m3ug.md) | Filter language: operators, sets, OR/NOT, ordering, limits, includes, examples |
| [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md) | Available tag names, calculated audio properties, rating handling |
| [Scheduling](https://github.com/haplo/genplis/blob/main/docs/scheduling.md) | Running genplis daily with systemd or cron |
| [Development](https://github.com/haplo/genplis/blob/main/docs/dev.md) | Setup, tests, pre-commit, typing, CI, internals, roadmap |
| [Examples](https://github.com/haplo/genplis/tree/main/examples) | Ready-to-copy `.m3ug` filters and `config.ini` |

## Acknowledgments

*Genplis* uses the [tinytag library](https://github.com/tinytag/tinytag) for
parsing tags in audio files. It was chosen for being a pure Python library
with no additional dependencies.

## License

[GPL-3.0](https://github.com/haplo/genplis/blob/main/LICENSE).
