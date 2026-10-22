---
description: Install Genplis, make your first playlist, and find the guides for filtering, configuration, tags, and scheduled runs.
---

# Documentation

Genplis generates M3U playlists from the tags and audio properties in your
local music files. Write your rules in a `.m3ug` file, run Genplis, and it
writes a matching `.m3u` playlist next to it.

## Quickstart

### 1. Install

You need **Python 3.12 or later** and [uv](https://docs.astral.sh/uv/).
Genplis is not published to PyPI yet; install it directly from Git:

```bash
uv tool install git+https://github.com/haplo/genplis.git
```

If you prefer to work from a clone, follow the
[development setup](dev.md#setup).

### 2. Define a playlist

Save this as `~/Music/Metal.m3ug` (adjust the collection path as needed):

```text
# An hour of metal, shuffled
genre ~ "Metal"
@SORT random
@MAX-DURATION 1h
```

`~` means “contains”, so this includes genres such as Heavy Metal.
All ordinary rules in one file must match; directives beginning with `@`
control ordering and selection.

### 3. Generate it

```bash
genplis ~/Music
```

When songs match, `~/Music/Metal.m3u` appears next to your filter. Open it in
a player that supports local M3U playlists. Run Genplis again after adding
music or changing tags to refresh your playlists.

If nothing matches, no playlist is written. Check the tags of a song with:

```bash
genplis ~/Music/some-song.mp3
```

## Where next?

| I want to… | Start here |
| --- | --- |
| Understand commands, options, playlists, or the cache | [Usage guide](usage.md) |
| Write more expressive filters | [M3UG reference](m3ug.md) |
| Copy a ready-made playlist definition | [M3UG Examples](https://github.com/haplo/genplis/tree/main/examples) |
| Set defaults for my collection | [Configuration](config.md) |
| Find usable tags or understand rating scales | [Tags](tags.md) |
| Regenerate playlists automatically | [Scheduling](scheduling.md) |
| Work on Genplis itself | [Development](dev.md) |

Use **Search** in the header to find a command, tag, directive, or example
across the documentation. The search runs in your browser, with no external
search service.

Looking for the project overview? [Back to Home](home.md).
