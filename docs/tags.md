# Tags

Genplis uses two kinds of information when filtering music:

- **Embedded tags**, such as artist, genre, and year, stored in the audio file.
- **Calculated properties**, such as duration and bitrate, read from the file
  or its audio stream.

This page covers their names, units, and behavior in filters. For commands,
see [Usage](usage.md); for rule syntax, see the [M3UG reference](m3ug.md).

## Inspect your tags

Check a few songs before writing a filter: available tags depend on the file
format and the software that tagged it.

```bash
genplis ~/Music/some-song.mp3
```

This prints the cache status and available tags. An excerpt might look like:

```text
Parsed tags:
    *duration = 245.5
    *is_lossless = True
    album = ['Out of Body (2023 Remastered Edition)']
    artist = ['DANCE WITH THE DEAD]
    genre = ['Metal', 'Rock']
    title = ['Robeast']
    track = ['2']
```

The `*` marks a calculated value and can be used in filters: write
`*duration >= 1m` to explicitly select the calculated playing time.
Unprefixed names such as `duration` still work, but an embedded tag with the
same name takes precedence. Brackets show a list of tag values, even when
there is only one.

Add `--verbose` for diagnostics about skipped files or discarded tags when
they are parsed. For collection-wide commands, see
[Inspecting tags across a collection](usage.md#inspecting-tags-across-a-collection).

## Common tags

Genplis uses [tinytag](https://github.com/tinytag/tinytag) to read metadata.
Supported formats include MP3, Ogg Vorbis, Opus, FLAC, MP4/M4A, WAV, AIFF,
and WMA; unsupported files are skipped.

These are common embedded tags, not a list that every file is guaranteed to
have:

| Name | Meaning |
| --- | --- |
| `artist` | Track artist |
| `albumartist` | Album artist |
| `album` | Album title |
| `title` | Track title |
| `genre` | One or more genres |
| `year` | Release year |
| `original_year` | Original release year, when the format stores it separately |
| `track`, `track_total` | Track number and total tracks |
| `disc`, `disc_total` | Disc number and total discs |
| `composer` | Composer |
| `comment` | Comment |
| `bpm` | Beats per minute, when present |
| `copyright`, `isrc` | Format-dependent extra fields |

Any extra fields tinytag exposes are available too, unless discarded by
[tag settings](#missing-or-discarded-tags). Use the names shown by inspection,
not the labels in your music player's interface. For example, `year` and
`original_year` are separate tags; use the one your files actually have.

## Calculated audio properties

These properties don't require embedded metadata. Prefix any name below with
`*` in a rule, sort key, dedupe key, or per-tag limit to force the calculated
value, even if an embedded tag has the same name. Unprefixed names remain
supported.

| Name | Meaning | Unit / type |
| --- | --- | --- |
| `filename` | Path of the file as genplis encountered it | string |
| `filesize` | File size | bytes (integer) |
| `mime_type` | MIME type reported by tinytag | string |
| `duration` | Playing time | seconds (float) |
| `channels` | Number of audio channels | integer |
| `bitrate` | Bitrate | kilobits per second (float) |
| `bitdepth` | Sample bit depth, when available | bits (integer) |
| `samplerate` | Sample rate | hertz (integer) |
| `is_lossless` | Whether the format is lossless | boolean |

For example:

```text
duration < 5m
samplerate >= 44100
is_lossless = true
```

Both `duration` and `*duration` accept [duration literals](m3ug.md#duration-literals) such
as `10m` or `1:30`. Use `= true` or `= false` for `is_lossless`, not text
operators such as `~`.

Some properties may be absent: `bitdepth`, for example, is often unavailable
for lossy formats. `filename` contains a path, not just the file's base name;
it may be relative if the file was read using a relative path. Sorting by
`filename` always uses the absolute path; see [Ordering](m3ug.md#ordering).

## Using tags in rules

- **Tag names ignore case:** `Artist` and `artist` are the same. Names have
  no wildcards; a leading `*` selects a calculated value, not a wildcard match.
  Use the spelling from inspection, such as `albumartist` or `original_year`.
- **Text values ignore case by default:** `genre = metal` matches `Metal`.
  Add `@CASE` to a rule when case matters.
- **Numbers in rules should be unquoted:** `track = 7` matches a tag stored
  as either `7` or `"7"`. Quoting the rule value makes it text instead.

See [Values and types](m3ug.md#values-and-types) for conversion rules and
[Operators](m3ug.md#operators) for all comparisons.

### Multi-valued tags

A song can have several artists or genres. For a tag displayed as
`genre = ['Metal', 'Rock']`:

- `genre = Metal` and `genre ~ Metal` match because **at least one** value
  passes. Numeric comparisons also match when any value passes.
- `genre != Metal` does not match: **every** value must differ.
- `genre = [Metal | Pop]` matches either listed genre. See
  [Multi-value rules](m3ug.md#multi-value-rules) for sets of tags and values.

Genplis does not split a single string into separate values. If inspection
shows only `['Rock; Metal']`, `genre = Metal` won't match, but
`genre ~ Metal` will. For sorting, multi-valued tags use their first non-empty
value; see [Ordering](m3ug.md#ordering).

## Rating

**Use `*rating` for a normalized 0–5 rating**, for example:

```text
*rating >= 4
@SORT *rating desc, artist, album, track
```

Each music player stores ratings in a different way, as there is no real
standard. Some use 0-1 range, others 0-5, 0-100, 0-255... Genplis calculates
`*rating` from a variety of tags, normalizing their range to a scale of 0–5
stars (with decimals). If you have files with ratings that genplis does not
recognize, please [open an issue](https://github.com/haplo/genplis/issues)!

If you know exactly which rating tag your files use, you can just use it
instead of `*rating`, just be aware of the range. Use `--tag <tag-name>`
to see all the values in your collection and infer the range.

## Reading tag statistics

Use `genplis --tag-stats ~/Music` to summarize available tags, or
`genplis -t genre ~/Music` to list every value of one tag. See
[Usage](usage.md#inspecting-tags-across-a-collection) for inspection commands.

The summary separates embedded and calculated tags:

| Column | Meaning |
| --- | --- |
| `Files` | Number of supported files with this tag |
| `Coverage` | Percentage of all supported files that have it |
| `Distinct` | Number of different values; a `+` means the count was capped |
| `Examples` | A few values, most common first |

With `-t`, every distinct value is listed, most common first, with a file
count and coverage. Each value counts at most once per file, but a file can
contribute to several values, so their coverage can total more than 100%.
Long values may be shortened for display; counts still refer to the full
values. A requested tag that isn't found prints a message, not an error.

Tag names are case-insensitive. `-t rating` shows both embedded `rating` and
calculated `*rating` when present; use `-t '*rating'` for only the calculated
form. As in filters, this `*` explicitly selects the calculated value; it is
not a wildcard.

Reports use the same tag settings as filters and update the cache without
writing playlists.

## Missing or discarded tags

An absent or unknown tag is not an error. Positive tests such as
`genre = Metal`, `genre ~ Metal`, or `rating >= 4` don't match it, but
`genre != Metal` does. Zero, `false`, and an empty string are values, not
missing tags; see [Missing values](m3ug.md#missing-values).

A tag may also be missing because of [tag settings](config.md#tags):

- [`max_size`](config.md#max_size) discards tag values over 1000 UTF-8 bytes
  by default, often lyrics or long comments. For multiple values, their sizes
  are added together. Calculated audio properties are exempt.
- [`ignore`](config.md#ignore) discards named tags, including calculated
  properties. Use names without `*`, such as `duration`.

Discarded tags behave like absent ones. Changing either setting rebuilds
the cache automatically. If a song doesn't match as expected, inspect its
tags first, then use the [filter debugging tools](m3ug.md#testing-and-debugging-filters).

## See also

- [M3UG reference](m3ug.md)
- [Configuration](config.md)
- [Usage guide](usage.md)
- [tinytag documentation](https://github.com/tinytag/tinytag)
