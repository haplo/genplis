# Automatic music playlist generator

This script generates M3U playlists from a collection of music files by looking at some of their attributes and tags and applying user-defined filters.

It scratches my own itch where I have a local music collection curated over 30 years and I wanted to have playlists like "great Synthwave songs", "80s music" or "musicals" without having to manually update them when something gets added to the collection.

## Requirements

Python 3.8 or later.

*genplis* is not published to [PyPI](https://pypi.org/) yet, so you cannot just use *pip* to install it.

If you want to give it a try first install [Rye](https://rye.astral.sh/) and then follow the *Install* and *Usage* instructions below.

## Install

This program is a work in progress and hence not yet published to [PyPI](https://pypi.org/).

For now you have to get this repository and run the script manually:

    $ git clone https://github.com/haplo/genplis.git
    $ cd genplis
    $ rye sync

## Usage

    $ rye run genplis ~/Music

*genplis* takes the path to the music collection.
It will parse the tags of all music files within, ignoring ones deemed too long (over 1 KB).
Results will be saved in a SQLite database, so in subsequent runs the script will parse only the modified files according to the OS modification date.

In a second step *genplis* will look for `.m3ug` files among the music collection.
These files define one or more filters (see *Defining filters* section below for details).
*genplis* will then apply the filters to the whole music collection, create a M3U playlist with all the file matches and save it in the same directory as the original M3UG file.
This generated playlist can then be used in any M3U-compatible music player.

Currently *genplis* saves all parsed data in RAM for simplicity and speed.
Exact RAM usage will depend on the music tags used, but estimate 10 MiB per 1,000 files, or even less for lightly-tagged collections.

## Defining filters

TODO

Lines starting with `#` are treated as comments and ignored.
Same with empty lines.

Look at [these example M3UG files](examples).
Copy them directly or use for inspiration to make your own filters!

## Roadmap

- [x] Parse tags of all files in music collection
- [x] Cache tags to local DB
- [x] Implement parser for filter grammar
- [ ] Implement filtering logic
- [ ] Filter files in collection
- [ ] Generate playlists (MVP complete!)
- [ ] Tests
- [ ] pre-commit
- [ ] Documentation
- [ ] Publish to PyPI! 🚀
- [ ] Example systemd files and instructions on how to run periodically
- [ ] Parallel parsing of files
- [ ] Support narrowing of valid tag names
- [ ] Optimize memory usage
- [ ] Optimize DB space
- [ ] Support OR conditionals
- [ ] Command for DB cleaning

Got any ideas to make *genplis* more awesome?
Feel free to [open an issue](https://github.com/haplo/genplis/issues).
