# Genplis: a music playlist generator

*Genplis* is a program that generates M3U playlists from a collection of music files by looking at some of their attributes and tags and applying user-defined filters.

*Genplis* defines its own language to define filters, called M3UG.

It scratches my own itch where I have a local music collection curated over 30 years and I wanted to have playlists like "my favorite songs", "80s music" or "musicals" without having to manually update them when something gets added to the collection.

## Requirements

Python 3.10 or later.

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

## Developers

First make sure you have [uv](https://github.com/astral-sh/uv) installed.

Then clone the *genplis* repository and install dependencies:

    $ git clone https://github.com/haplo/genplis.git
    $ cd genplis
    $ uv sync

This project uses [pre-commit](https://pre-commit.com/) to check code for common errors.
Just run `uv run pre-commit install`, this will run the checks when you try to commit.

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
- [ ] Tests
  - [x] m3ug
  - [ ] db
  - [x] tags
  - [ ] file processing
  - [ ] dir processing
  - [ ] PR check
    - [ ] Run pre-commit on whole project
    - [ ] Test on every supported Python version
- [ ] Documentation
- [ ] Publish to PyPI! 🚀
- [ ] Example systemd files and instructions on how to run periodically
- [ ] Improve M3U generation
  - [ ] Include original M3UG content as comment
  - [ ] Support [basic extended M3U playlist tags](https://datatracker.ietf.org/doc/html/rfc8216#section-4.3)
- [ ] Parallel parsing of files
- [ ] Support narrowing of valid tag names
- [ ] Config file support
  - [ ] Default music collection path
  - [ ] Default exclude
  - [ ] Number of processes for parallel parsing
  - [ ] Tag size threshold to ignore
  - [ ] Tags to ignore
- [ ] Support OR conditionals
- [ ] Command for DB cleaning
- [ ] Optimize memory usage
- [ ] Optimize DB space
- [ ] Improve Windows support (**HELP NEEDED!**)
- [ ] Improve MacOS support (**HELP NEEDED!**)

Got any ideas to make *genplis* more awesome?
Feel free to [open an issue](https://github.com/haplo/genplis/issues).
