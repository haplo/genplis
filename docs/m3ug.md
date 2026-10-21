# The M3UG filter language

M3UG is the small language *genplis* uses to describe playlists. A `.m3ug`
file contains one rule per line, and every rule must match a song for it to
appear in the generated playlist.

This page is the language reference. For the tags you can use in rules, see
[Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md). For running
genplis and the generated playlist format, see
[Usage](https://github.com/haplo/genplis/blob/main/docs/usage.md).

## How M3UG files work

- Put a `.m3ug` file anywhere inside your music collection. The file name
  becomes the playlist name: `Favorites.m3ug` generates `Favorites.m3u` in the
  same directory.
- One file can define one playlist. To create several playlists, use several
  `.m3ug` files.
- Filters are applied to every music file found under the `PATH` given on the
  command line (or configured in the config file), not just to the folder that
  contains the `.m3ug` file.
- All rules in a file are combined with **AND**: a song must satisfy all of
  them. There is no OR operator yet; use separate `.m3ug` files for separate
  playlists.
- A file may contain one `@sort` directive to choose the playlist order. Without
  it, the `[output] sort` setting applies (default `filename`).
- If no song matches, no playlist file is written.
- An empty `.m3ug` file has no rules and therefore matches every song.

## File syntax

A rule is one line with three parts:

```text
tag operator value
```

For example:

```text
genre ~= "Heavy Metal"
rating >= 4
```

A file may also contain a single `@sort` line; it controls playlist order and
is not a filter rule. See [Ordering](#ordering).

Rules about the file itself:

- **Encoding:** UTF-8. A byte-order mark is accepted and ignored.
- **Comments:** lines whose first character is `#`. Comments must start at
  column 0; `  # comment` is not a comment. There are no inline comments:
  `genre = Rock # my favorite` compares `genre` with the literal string
  `Rock # my favorite`.
- **Blank lines:** ignored.
- **Line endings:** LF or CRLF both work.
- **Whitespace:** use a single space between the tag, the operator, and the
  value. Do not indent rules. Tabs are not separators. The value itself may
  contain spaces (`artist = DANCE WITH THE DEAD`), and extra spaces after the
  operator are trimmed.
- **One rule per line.** A rule that cannot be split into exactly
  `tag operator value` is rejected with `<filename:line>: Invalid filter syntax`,
  and the run stops.
- **Directives:** the optional `@sort` line must also start at column 0.
  Unknown directives are errors.

## Values and types

The value at the end of the line is interpreted as follows:

| Written as | Type | Notes |
| --- | --- | --- |
| `Metal` | string | Bare words may contain spaces. |
| `"Heavy Metal"` | string | Quotes are stripped. Either `'` or `"` works. |
| `'DANCE WITH THE DEAD'` | string | Use quotes to be explicit, or when the value has leading/trailing spaces. |
| `1980` | integer | Only digits. |
| `4.5` | float | Digits, a dot, and digits. |

Details that matter when writing filters:

- Numbers are only recognized in the forms `123` and `123.45`. Negative
  numbers, `+7`, `.5`, `5.`, `1e3`, and `0x10` are treated as strings.
- Quoting always produces a string, even for digits: `rating = "4"` compares
  against the string `"4"`, not the number `4`.
- Quotes cannot be escaped. If a value contains a double quote, use single
  quotes around it (and vice versa).
- Numeric tag values stored as strings by the tag library are compared
  numerically when the rule value is a number. This is why `track = 7` matches
  a track tag of `"7"`.
- Values are case-sensitive. `genre = Metal` does not match `metal`.
  Tag *names* are case-insensitive.

## Operators

| Operator | Meaning | Rule value | Tag value |
| --- | --- | --- | --- |
| `=` | equal | string or number | same type; numeric strings are coerced for numeric rules |
| `!=` | not equal | string or number | inverse of `=` |
| `~=` | contains | string only | string, or a list of strings |
| `<` | less than | number only | number or numeric string |
| `<=` | less than or equal | number only | number or numeric string |
| `>` | greater than | number only | number or numeric string |
| `>=` | greater than or equal | number only | number or numeric string |

### Equality: `=`

- `genre = Metal` matches exactly `Metal`, not `Heavy Metal` or `Metalcore`.
- `rating = 5` matches a numeric rating of 5, including a tag stored as the
  string `"5"`.
- If a tag holds several values, the rule matches when **any** value equals
  the expected value.
- A song without the tag does not match.
- Case matters: `artist = "DANCE WITH THE DEAD"` does not match
  `Dance With The Dead`.

### Inequality: `!=`

- `genre != Pop` matches songs where genre is `Rock`, `Metal`, and so on.
- If a tag holds several values, the rule matches only when **all** values
  differ from the expected value.
- A song **without** the tag matches, because the missing value is not equal
  to the expected value. This is often surprising; use `=` when you want to
  require a tag to exist.

### Contains: `~=`

- This is a case-sensitive substring test, not a regular expression.
  `genre ~= Metal` matches `Metal`, `Heavy Metal`, `Metalcore`, and
  `Nu Metal`. `genre ~= metal` matches `metal` only.
- The expected value must be a string. `comment ~= 42` is a parse error;
  `comment ~= "42"` is a valid string search.
- A list of values matches when any element contains the substring.
- Non-string tag values (numbers, booleans) never match.

### Numeric comparisons: `<`, `<=`, `>`, `>=`

- The expected value must be an unquoted number. `year > "1980"` is a parse
  error because the quoted value is a string; write `year > 1980`.
- Numbers, numeric strings, and lists containing them are compared
  numerically. `track > 7` matches `"8"` as well as `8`.
- A list matches when any element passes the comparison.
- A missing tag, a non-numeric string, or a boolean never matches.
- Units depend on the tag: `duration` is in seconds, `bitrate` in kilobits
  per second, `samplerate` in hertz. See
  [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md).

### Missing values

A tag that is absent is treated as missing. Zero and false are real values,
not missing ones, so `track = 0` and `comment = ""` work as expected. There is
still no boolean literal, so `is_lossless` cannot be compared directly.

## Ordering

By default, entries are ordered by `[output] sort`, which is `filename` (the
absolute path) unless configured otherwise. Add one `@sort` line to a `.m3ug`
file to choose a different order for that playlist:

```text
@sort tag [asc|desc] [, tag [asc|desc]]...
```

Keys are compared from left to right. The direction applies to the key before
it and defaults to `asc`. A second `@sort` line is an error; put all keys on
one line.

```text
# Title, ascending
@sort title

# Newest first
@sort year desc

# Album order
@sort artist, album, disc, track, title

# Highest rated first, then album order
@sort rating desc, artist, album, disc, track, title
```

`duration` and `filename` are ordinary sort keys too:

```text
# Shortest songs first
@sort duration

# Longest songs first
@sort duration desc

# Path order, matching the default
@sort filename
```

`filename` is the absolute path of the file, not the relative path written
into the playlist. `year` and `original_year` are the release-date tags
available from tinytag; there is no separate `date` tag.

### Missing values

A missing value sorts after every present value **for that key only**. It does
not demote the entry past an entry that differs on a higher-priority key. When
both entries are missing the same key, or have the same value, comparison
continues to the lower-priority keys. So an entry with a missing `disc` is not
automatically sent to the bottom of the playlist:

```text
@sort artist, album, disc, track, title
```

| Song | artist | album | disc | track | title |
| --- | --- | --- | --- | --- | --- |
| 1 | Rammstein | Herzeleid | 1 | 4 | Asche zu Asche |
| 2 | Rammstein | Rosenrot | | | Benzin |
| 3 | Rammstein | Mutter | | | Zwitter |
| 4 | VAST | Turquoise & Crimson | 1 | 3 | Lost |

The order is 1, 3, 2, 4. The `Rammstein` group comes before `VAST`, and within
`Rammstein` the albums are ordered `Herzeleid`, `Mutter`, `Rosenrot`. Songs 2 and 3 have
no disc or track tags, but those keys are never reached because their albums already
differ.  Missing values are last in both ascending and descending order, and equal keys
keep directory-walk order.

Numeric-looking values sort numerically, so `track` values `2` and `10` come
out in the expected order. Other text sorts case-insensitively. Multi-valued
tags use their first non-empty value. `rating` uses the same raw-or-derived
handling as filters; see [Rating](https://github.com/haplo/genplis/blob/main/docs/tags.md#rating)
for the scale caveat.

## Special tag names

Tag names are matched case-insensitively, so `Artist`, `artist`, and `ARTIST`
are the same. Three groups are worth knowing about:

- **Embedded tags** such as `artist`, `album`, `title`, `genre`, `year`,
  `track`, `disc`, `composer`, `comment`, and format-specific extras such as
  `original_year`. These come from the audio file.
- **Calculated audio properties** such as `filename`, `duration`, `bitrate`,
  `samplerate`, `channels`, `bitdepth`, `filesize`, `mime_type`, and
  `is_lossless`. Use them **without** the `*` that genplis prints when
  inspecting a file: write `duration >= 600`, not `*duration >= 600`.
- **`rating`**, which uses the raw `rating` tag when present and otherwise
  derives one from `fmps_rating`. See
  [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md#rating) for
  the scale caveats.

An unknown or absent tag is not an error: the rule simply does not match
(except for `!=`, which does match).

## Examples

The repository keeps working examples in
[`examples/`](https://github.com/haplo/genplis/tree/main/examples). Each one
is a complete playlist definition.

### Songs from the 1980s

```text
# songs made in the 1980s, the best decade
original_year >= 1980
original_year < 1990
```

Two rules are ANDed. `original_year` is an ID3 `TORY`-style field exposed by
the tag library; not every file has it. Use `year` instead if your files only
carry the release year. Inspect a file to see which one you have.

### Four- and five-star songs

```text
# 4-star songs or better
rating >= 4
```

And the stricter version:

```text
# 5-star songs
rating >= 5
```

Rating scales differ between players. If `rating >= 4` matches nothing or
everything, inspect your files first; see
[Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md#rating).

### Great metal songs

```text
# great metal songs (4-star or better)
genre ~= "Metal"
rating >= 4
```

Both rules must pass. Because `~=` is a substring test, this also matches
`Heavy Metal`, `Nu Metal`, and `Metalcore`; use `genre = Metal` for an exact
match.

### Musicals

```text
genre ~= "Musical"
```

### More patterns

Exact artist:

```text
artist = "DANCE WITH THE DEAD"
```

Album and album artist:

```text
album = "Some Album"
albumartist = "Some Artist"
```

Long songs, in seconds:

```text
duration >= 600
```

Lossless files (by MIME type, since booleans cannot be compared directly):

```text
mime_type ~= flac
```

Songs whose path contains a folder name:

```text
filename ~= /Live/
```

Combining several conditions:

```text
genre ~= Synthwave
year >= 2010
rating >= 4
duration < 480
```

## Testing and debugging filters

To see the tags of one file:

```bash
uv run genplis /path/to/song.mp3
```

Calculated values are printed with a `*` prefix (`*duration`, `*filename`,
`*rating`) to show that they were not embedded in the file.
Use the names **without** the `*` in filters.

To see how a `.m3ug` file is parsed without generating a playlist:

```bash
uv run genplis /path/to/Favorites.m3ug
```

The single-file form also prints the `@sort` keys when the file has them. To
see the parsed rules, the effective sort order, each matching song, and match
counts during a full run, add `--verbose`:

```bash
uv run genplis --verbose ~/Music
```

## Current limitations

- No OR, grouping, or parentheses. All rules are ANDed.
- No regex operator. `~=` is a case-sensitive substring test.
- No boolean literals, so boolean tags cannot be compared directly.
- No negative or scientific-notation numbers.
- No inline comments.
- No quote escaping.
- Exactly one space between tag and operator; no tabs or indentation.
- Numeric comparisons need a numeric rule value; quoted numbers are strings.
- One `@sort` line per file; combine all keys on that line.
- Missing sort values always go last; there is no nulls-first option.
- Text sorting is case-insensitive but not locale-aware or natural-number
  aware; numeric-looking values are compared as numbers.

Some of these are on the [roadmap](https://github.com/haplo/genplis/blob/main/docs/dev.md#roadmap).
