# Automatic music playlist generator

This script generates M3U playlists from a collection of music files by looking at some of their attributes and tags and applying user-defined filters.

It scratches my own itch where I have a local music collection curated over 30 years and I wanted to have playlists like "great Synthwave songs", "80s music" or "musicals" without having to manually update them when something gets added to the collection.

## Requirements

Python 3.8 or later.

[Rye](https://rye.astral.sh/).

## Install

This program is a work in progress and hence not yet published to [PyPI](https://pypi.org/).

For now you have to get this repository and run the script manually:

    $ git clone https://github.com/haplo/genplis.git
    $ rye sync

## Usage

    $ rye run genplis ~/Music

*genplis* takes the path to the music collection.
It will parse the tags of all music files within.
Results will be saved in a SQLite database, so in subsequent runs the script will parse only the modified files.

In a second step *genplis* will look for `.m3ug` files among the music collection.
These files define one or more filters (see Defining filters section below for details).
*genplis* will then apply the filters to the whole music collection, create a M3U playlist and save it in the same directory as the original M3UG file.

## Defining filters

TODO

Lines starting with `#` are treated as comments and ignored.
Same with empty lines.

Look at [these example M3UG files](examples).
They can be copied directly or used for inspiration.

## Running periodically

TODO
