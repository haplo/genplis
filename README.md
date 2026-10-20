# Genplis: a music playlist generator

[![CI](https://github.com/haplo/genplis/actions/workflows/ci.yml/badge.svg)](https://github.com/haplo/genplis/actions/workflows/ci.yml)

*Genplis* is a program that generates M3U playlists from a collection of music files by looking at some of their attributes and tags and applying user-defined filters.

*Genplis* defines its own language to define filters, called M3UG.

It scratches my own itch where I have a local music collection curated over 30 years and I wanted to have playlists like "my favorite songs", "80s music" or "musicals" without having to manually update them when something gets added to the collection.

## Requirements

Python 3.12 or later.

Python 3.10 and 3.11 might work, but they are untested and unsupported.

*genplis* is not published to [PyPI](https://pypi.org/) yet, so you cannot just use *pip* to install it.

If you want to give it a try first install [uv](https://github.com/astral-sh/uv) and then follow the *Install* and *Usage* instructions below.

## Install

This program is a work in progress and hence not yet published to [PyPI](https://pypi.org/).

For now you have to get this repository and run the script manually:

    $ git clone https://github.com/haplo/genplis.git
    $ cd genplis
    $ uv sync

## Usage

    $ uv run genplis ~/Music

*genplis* takes the path to the music collection.
It will parse the tags of all music files within, ignoring ones deemed too long (over 1 KB).
Results will be saved in a SQLite database, so in subsequent runs the script will parse only the modified files according to the OS modification date.

When `PATH` points to a single audio file, *genplis* prints its parsed tags.
Tags that are not embedded in the file are prefixed with `*`. This includes
audio properties calculated by *genplis*'s tag library, such as `*filename`,
`*duration`, `*bitrate`, and `*samplerate`, as well as `*rating`, the
normalized 0–5 rating derived from tags such as `fmps_rating`. `*rating` is
omitted when the file already has a `rating` tag, since that value is used
directly.

In a second step *genplis* will look for `.m3ug` files among the music collection.
These files define one or more filters (see *Defining filters* section below for details).
*genplis* will then apply the filters to the whole music collection, create a M3U playlist with all the file matches and save it in the same directory as the original M3UG file.
This generated playlist can then be used in any M3U-compatible music player.
By default the original M3UG source is embedded at the top of the playlist as
`#` comments, so the playlist documents how it was generated. Pass
`--no-include-source` to omit it.

Currently *genplis* saves all parsed data in RAM for simplicity and speed.
Exact RAM usage will depend on the music tags used, but estimate 10 MiB per 1,000 files, or even less for lightly-tagged collections.

## Cleaning the cache

To remove cache entries for files that were deleted, renamed, or moved:

    $ uv run genplis --clean ~/Music

With a `PATH`, *genplis* runs normally first and then removes the entries under
that path only. Without a path (and without `[collection] path` in the config),
it cleans the whole database:

    $ uv run genplis --clean

Cleaning reports how many entries were removed and how much space the database
reclaimed. The database is vacuumed afterward, so the operation can take a
while and temporarily needs free disk space roughly the size of the database.

## Configuration

*genplis* reads optional settings from an INI file in the XDG configuration
directory:

    $XDG_CONFIG_HOME/genplis/config.ini

If `XDG_CONFIG_HOME` is not set, this is `~/.config/genplis/config.ini`.

The file is optional: when it is missing, *genplis* uses its built-in defaults.
Command-line options take precedence over the config file. In particular:

- `PATH` may be omitted when `[collection] path` is set.
- Passing one or more `--exclude` options replaces `[collection] exclude`.
- `--config FILE` reads a different config file; `--no-config` ignores
  configuration entirely.
- `--db`, `--verbose`/`--no-verbose`, `--overwrite`/`--no-overwrite`, and
  `--include-source`/`--no-include-source` override the corresponding settings.

A complete example:

```ini
[general]
# Same as --verbose.
verbose = false

[collection]
# Used when PATH is omitted on the command line.
path = ~/Music

# Regular expressions matched against file and folder paths, one per line.
# Files and folders matching any pattern are skipped. The contents of an
# excluded folder are not scanned.
exclude =
    /\.Trash/
    /@eaDir/
    \.tmp$

[tags]
# Tag values larger than this many bytes are discarded.
max_size = 1000

# Tag names to discard before caching and filtering, one per line.
# Calculated values such as filename and filesize are also controlled by
# this list: omit them to keep them available to filters and show them as
# *filename / *filesize.
ignore =
    comment
    encoder
    encoder_settings
    lyrics

[database]
# Optional cache location. Defaults to
# $XDG_CACHE_HOME/genplis/genplis.db
# path = ~/.cache/genplis/genplis.db

[output]
# Overwrite generated .m3u files that already exist.
overwrite = true

# Embed the original M3UG source as comments in generated playlists.
include_source = true
```

Paths may start with `~`. Relative paths are resolved relative to the config
file, not the current directory. `exclude` patterns are matched against both
file and folder paths; an excluded folder is skipped entirely. `exclude` and
`ignore` take one entry per line. The percent sign (`%`) has no special
meaning in values.

A copy of this example is available at [examples/config.ini](examples/config.ini).

## Defining filters

TODO

Lines starting with `#` are treated as comments and ignored.
Same with empty lines.

Look at [these example M3UG files](examples).
Copy them directly or use for inspiration to make your own filters!

## Developers

First make sure you have [uv](https://github.com/astral-sh/uv) installed.

Then clone the *genplis* repository and install dependencies:

    $ git clone https://github.com/haplo/genplis.git
    $ cd genplis
    $ uv sync

This project uses [pre-commit](https://pre-commit.com/) to check code for common errors.
Just run `uv run pre-commit install`, this will run the checks when you try to commit.

Type checking is done with [ty](https://docs.astral.sh/ty/):

    $ uv run ty check

Pull requests and pushes to `main` run the same pre-commit checks across the
whole project, plus the test suite on Python 3.12 through 3.15. The Actions
run summary also includes a coverage report for Python 3.12.

## Roadmap

- [x] Parse tags of all files in music collection
- [x] Cache tags to local DB
- [x] Implement parser for filter grammar
- [x] Implement filtering logic
- [x] Filter files in collection
- [x] Generate playlists (MVP complete!)
- [x] Display tags when receiving a file as parameter (useful for creating rules or debugging)
- [x] --exclude option
- [x] Install as genplis command
- [x] pre-commit
- [x] Tests
  - [x] m3ug
  - [x] db
  - [x] tags
  - [x] file processing
  - [x] dir processing
  - [x] PR check
    - [x] Run pre-commit on whole project
    - [x] Test on every supported Python version
- [ ] Documentation
- [ ] Publish to PyPI! 🚀
- [ ] Example systemd files and instructions on how to run periodically
- [ ] Improve M3U generation
  - [x] Include original M3UG content as comment
  - [ ] Support [basic extended M3U playlist tags](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3)
- [ ] Parallel parsing of files
  - [ ] Number of processes for parallel parsing
- [ ] Support narrowing of valid tag names
- [x] Config file support
  - [x] Default music collection path
  - [x] Default exclude
  - [x] Tag size threshold to ignore
  - [x] Tags to ignore
  - [x] Example config in README
- [ ] Support OR conditionals
- [x] Command for DB cleaning
- [ ] Optimize memory usage
- [ ] Optimize DB space
- [ ] Improve Windows support (**HELP NEEDED!**)
- [ ] Improve MacOS support (**HELP NEEDED!**)

Got any ideas to make *genplis* more awesome?
Feel free to [open an issue](https://github.com/haplo/genplis/issues).

## Acknowledgments

*Genplis* uses the [tinytag library](https://github.com/tinytag/tinytag/releases) for
parsing the tags in the audio files. It was chosen for being a pure Python library with
no additional dependencies.
