# Tags

Genplis filters on tags read from your audio files. This page explains where
those tags come from, which names are available, and the special cases such as
`rating` and calculated audio properties.

For the operators that combine tags into rules, see
[M3UG](https://github.com/haplo/genplis/blob/main/docs/m3ug.md). For the
settings that limit which tags are stored, see
[Configuration](https://github.com/haplo/genplis/blob/main/docs/config.md#tags).

## Where tags come from

Genplis uses the [tinytag](https://github.com/tinytag/tinytag) library to read
embedded metadata and audio stream properties. It does not have its own list
of supported tags: everything tinytag exposes for a file is available to
filters, including format-specific extra fields.

Consequences:

- Supported formats are whatever tinytag supports (for example MP3, Ogg
  Vorbis, Opus, FLAC, MP4/M4A, WAV, AIFF, and WMA). Unsupported files are
  skipped.
- The same logical information can have different names in different formats.
  For example, a release year may appear as `year` or as `original_year`.
- A missing tag is normal, not an error. In a filter it simply does not match
  (except with `!=`).

## Inspecting a file's tags

The most reliable way to find the names and values for your collection is to
ask genplis about a real file:

```bash
uv run genplis /path/to/song.mp3
```

This prints the cache status and every parsed tag. Calculated values are
prefixed with `*`, for example:

```text
Parsed tags:
    *bitrate = 127.99768145161289
    *channels = 2
    *duration = 3.239183673469388
    *filename = /music/song.mp3
    *filesize = 53235
    *is_lossless = False
    *mime_type = audio/mpeg
    *samplerate = 44100
    artist = ['Test Artist']
    genre = ['Synthwave; Retrowave; Electronic']
    title = ['Test']
```

The `*` is only a display marker. In a `.m3ug` file you write the name without
it: `duration >= 60`, never `*duration >= 60`.

Use `--verbose` for extra detail about skipped or removed tags:

```bash
uv run genplis --verbose /path/to/song.mp3
```

## Tag names

- Names are matched case-insensitively. `Artist`, `artist`, and `ARTIST` all
  refer to the same tag.
- Tinytag's names are lower-case with underscores: `albumartist`,
  `mime_type`, `is_lossless`, `original_year`, `track_total`.
- There are no wildcards and no aliases beyond the special `rating` handling
  described below.
- Names that look like audio properties are listed in
  [Calculated audio properties](#calculated-audio-properties).

### Common embedded tags

Most files expose some of these:

| Name | Meaning |
| --- | --- |
| `artist` | Track artist |
| `albumartist` | Album artist |
| `album` | Album title |
| `title` | Track title |
| `genre` | Genre (often a single string such as `Metal`, or a list) |
| `year` | Release year |
| `original_year` | Original release year, when the format stores it separately |
| `track`, `track_total` | Track number and total tracks |
| `disc`, `disc_total` | Disc number and total discs |
| `composer` | Composer |
| `comment` | Comment |
| `bpm` | Beats per minute, when present |
| `copyright`, `isrc` | Format-dependent extra fields |

This is not a fixed list. Albums, artists, and other fields come straight from
tinytag's flat dictionary, which also merges format-specific "other" fields
into the same namespace. Inspect a representative sample of your files rather
than assuming a name exists.

### Multi-valued tags

Tinytag stores embedded metadata values as lists, even when there is only one
value. Genplis flattens a one-item list to a single value before filtering, and
keeps longer lists as lists:

- One value: `genre = Metal` and `genre ~= Metal` behave as expected.
- Several values: `=` and `~=` match if **any** value matches; `!=` matches
  only if **all** values differ; numeric comparisons match if any value
  passes.

## Calculated audio properties

These values are derived from the file itself rather than from embedded tags.
They are printed with a `*` prefix but used without it in filters.

| Name | Meaning | Unit / type |
| --- | --- | --- |
| `filename` | Path of the file as genplis encountered it | string |
| `filesize` | File size | bytes (integer) |
| `mime_type` | MIME type reported by tinytag | string |
| `duration` | Duration | seconds (float) |
| `channels` | Number of audio channels | integer |
| `bitrate` | Bitrate | kilobits per second (float) |
| `bitdepth` | Sample bit depth, when available | bits (integer) |
| `samplerate` | Sample rate | hertz (integer) |
| `is_lossless` | Whether the format is lossless | boolean |

Notes:

- `filename` is the path used when reading the file. If you invoke genplis
  with a relative path, it can be relative; the cache itself always stores
  absolute paths.
- `bitdepth` is absent for many lossy formats, so a rule on it will not match
  those files.
- `is_lossless` is a boolean. The filter language currently has no boolean
  literal, and false values are treated as missing, so it cannot be matched
  reliably. Use `mime_type` as a workaround (for example
  `mime_type ~= flac`).
- Calculated properties are exempt from `[tags] max_size`, but can still be
  removed with `[tags] ignore` (use the unprefixed name).

## Rating

`rating` is special because music players store ratings in incompatible ways.

When a file has a `rating` tag, genplis uses it **as-is**. It is not
normalized, and its scale depends on the player or tagger that wrote it
(common scales are 0–5, 0–100, and 0–255). The printed tag has no `*` in this
case, because it came from the file.

When a file has no `rating` tag, genplis derives one from `fmps_rating`:

```text
rating = fmps_rating × 5
```

`fmps_rating` is stored on a 0.0–1.0 scale, so the result is 0–5. The derived
value is printed as `*rating`, with the `*` marking it as calculated.

Rules:

- A raw `rating` always wins over `fmps_rating`.
- The derived rating only exists when `fmps_rating` exists and is not ignored
  by `[tags] ignore`.
- A non-numeric `fmps_rating` is ignored; no derived rating is produced.
- If neither tag is present, there is no rating; `rating >= 4` does not match.
- If your files use a 0–100 or 0–255 scale and you cannot change it, compare
  against that scale (for example `rating >= 80`) or use a player/tagger that
  writes `fmps_rating`.

Because the raw value is not normalized, the examples `rating >= 4` and
`rating >= 5` assume a 0–5 scale. Always inspect a few files before trusting a
rating filter.

## Which tags are stored

Two settings affect the tags available to filters:

- `[tags] max_size` (default 1000) discards values whose combined UTF-8
  encoded length exceeds the limit. `0` disables the limit. Calculated audio
  properties are exempt. See
  [Configuration](https://github.com/haplo/genplis/blob/main/docs/config.md#max_size).
- `[tags] ignore` discards named tags before the size check and before
  caching. Names are case-insensitive. Ignoring `rating` removes the raw tag,
  but a rating is still derived when `fmps_rating` is available; ignore both
  to remove ratings entirely.

An ignored or oversized tag behaves exactly like a missing tag: `=` and
`~=` do not match, `!=` matches, and numeric comparisons do not match. If a
filter does not behave as expected, run genplis on the file (and with
`--verbose`) to confirm the tag survived.

Changing either setting invalidates the whole tag cache, so the first run
afterwards re-reads every file.

## See also

- [M3UG reference](https://github.com/haplo/genplis/blob/main/docs/m3ug.md)
- [Configuration](https://github.com/haplo/genplis/blob/main/docs/config.md)
- [Usage guide](https://github.com/haplo/genplis/blob/main/docs/usage.md)
- [tinytag documentation](https://github.com/tinytag/tinytag)
