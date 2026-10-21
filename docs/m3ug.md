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
- All rules in a file are combined with **AND**. Add `@OR` to a rule to join it
  to the previous rule as an alternative, and `@NOT` to negate one rule.
- A file may contain directives such as `@sort` to choose the playlist order.
  Without one, the `[output] sort` setting applies (default `filename`).
- If no song matches, no playlist file is written.
- An empty `.m3ug` file has no rules and therefore matches every song.

## File syntax

A rule is one line with three parts:

```text
tag-set operator value-set
```

For example:

```text
genre ~ "Heavy Metal"
rating >= 4
```

A file may also contain directives such as `@sort`; they control the playlist
and are not filter rules. See [Ordering](#ordering).

Rules about the file itself:

- **Encoding:** UTF-8. A byte-order mark is accepted and ignored.
- **Comments:** lines whose first non-whitespace character is `#`. There are
  no inline comments: `genre = Rock # my favorite` compares `genre` with the
  literal string `Rock # my favorite`.
- **Blank lines:** ignored.
- **Line endings:** LF or CRLF both work.
- **Whitespace:** leading and trailing whitespace is ignored. Tag, operator,
  and value may be separated by one or more spaces or tabs. The value itself
  may contain spaces (`artist = DANCE WITH THE DEAD`).
- **One rule per line.** A rule that cannot be split into
  `tag-set operator value-set` is rejected with
  `<filename:line>: Invalid filter syntax`, and the run stops.
- **Directives and modifiers:** names that start with `@` are
  case-insensitive. Unknown names are errors.

## Values and types

The value at the end of the line is interpreted as follows:

| Written as | Type | Notes |
| --- | --- | --- |
| `Metal` | string | Bare words may contain spaces. |
| `"Heavy Metal"` | string | Quotes are stripped. Either `'` or `"` works. |
| `'DANCE WITH THE DEAD'` | string | Use quotes to be explicit, or when the value has leading/trailing spaces. |
| `1980` | integer | Only digits. |
| `4.5` | float | Digits, a dot, and digits. |
| `true` / `false` | boolean | Only for `=` and `!=`. |

Details that matter when writing filters:

- Numbers are only recognized in the forms `123` and `123.45`. Negative
  numbers, `+7`, `.5`, `5.`, `1e3`, and `0x10` are treated as strings.
- Quoting always produces a string, even for digits or booleans:
  `rating = "4"` compares against the string `"4"`, and `genre = "true"`
  against the string `"true"`.
- Quotes support `\"`, `\'`, and `\\`. Other backslashes are preserved, which
  keeps regular expressions such as `\d+` readable.
- Numeric tag values stored as strings by the tag library are compared
  numerically when the rule value is a number. This is why `track = 7` matches
  a track tag of `"7"`.
- Text matching is case-insensitive by default. Tag *names* are always
  case-insensitive. Add `@CASE` to one rule to make it case-sensitive.
- For text operators (`~`, `^`, `$`, `%`), `true` and `false` are the strings
  `"true"` and `"false"`. For numeric comparisons they are errors.

## Operators

| Operator | Meaning | Rule value | Tag value |
| --- | --- | --- | --- |
| `=` | equal | string, number, or boolean | same type; numeric strings are coerced for numeric rules |
| `!=` | not equal | string, number, or boolean | inverse of `=` |
| `~` | contains | string | string, or a list of strings |
| `^` | starts with | string | string, or a list of strings |
| `$` | ends with | string | string, or a list of strings |
| `%` | regex search | string | string, or a list of strings |
| `<` | less than | number only | number or numeric string |
| `<=` | less than or equal | number only | number or numeric string |
| `>` | greater than | number only | number or numeric string |
| `>=` | greater than or equal | number only | number or numeric string |

There are no aliases. The old spellings `~`, `^=`, `$=`, `#`, and every
other operator not in this table are rejected with `Unrecognized operator`.

### Equality: `=`

- `genre = Metal` matches exactly `Metal`, not `Heavy Metal` or `Metalcore`.
  Matching is case-insensitive, so `genre = metal` also matches `Metal`.
- `rating = 5` matches a numeric rating of 5, including a tag stored as the
  string `"5"`.
- `is_lossless = true` and `is_lossless = false` compare boolean tags.
- If a tag holds several values, the rule matches when **any** value equals
  the expected value.
- A song without the tag does not match.
- Add `@CASE` when case matters:
  `@CASE artist = "DANCE WITH THE DEAD"` does not match
  `Dance With The Dead`.

### Inequality: `!=`

- `genre != Pop` matches songs where genre is `Rock`, `Metal`, and so on.
- If a tag holds several values, the rule matches only when **all** values
  differ from the expected value.
- A song **without** the tag matches, because the missing value is not equal
  to the expected value. This is often surprising; use `=` when you want to
  require a tag to exist.

### Text operators: `~`, `^`, `$`, `%`

- `~` is a substring test, `^` a prefix test, and `$` a suffix test. They are
  case-insensitive unless the rule starts with `@CASE`.
- `genre ~ Metal` matches `Metal`, `Heavy Metal`, `Metalcore`, and
  `Nu Metal`. `@CASE genre ~ metal` matches only the exact lower-case
  substring.
- `%` is a regular-expression **search**, not a full match. `genre % ^Metal`
  matches values that start with `Metal`, and `filename % \.mp3$` matches
  MP3 paths.
- `%` is compiled with `re.IGNORECASE` unless the rule has `@CASE`. Inline
  flags such as `(?-i)` still work and can override that for part of the
  pattern. Invalid patterns are parse errors with a file and line.
- A list of values matches when any element satisfies the operator.
- Non-string tag values never match. Applying a text operator to a boolean
  tag logs one warning per rule per run; use `= true` or `= false` instead.

### Numeric comparisons: `<`, `<=`, `>`, `>=`

- The expected value must be an unquoted number. `year > "1980"` is a parse
  error because the quoted value is a string; write `year > 1980`.
- `true` and `false` are not accepted. `rating > true` is a parse error.
- Numbers, numeric strings, and lists containing them are compared
  numerically. `track > 7` matches `"8"` as well as `8`.
- A list matches when any element passes the comparison.
- A missing tag, a non-numeric string, or a boolean never matches.
- `@CASE` has no meaning for comparisons and is rejected.
- Units depend on the tag: `duration` is in seconds, `bitrate` in kilobits
  per second, `samplerate` in hertz. See
  [Tags](https://github.com/haplo/genplis/blob/main/docs/tags.md).

### Multi-value rules

Square brackets make a set on either side of a rule:

```text
[genre | style] = [Metal | Rock]
[artist | albumartist] = ["DANCE WITH THE DEAD" | Perturbator]
[filename | comment] ~ [Live | Bootleg]
[artist | albumartist] % ["^A" | "^B"]
```

A bracketed token is a set only when it is unquoted, starts with `[`, ends
with `]`, and contains at least one top-level `|`. The scanner respects
quotes and escapes:

```text
title = [Untitled]         # literal string "[Untitled]"
title = [Intro | Outro]    # two-value set
title = "[Intro | Outro]"  # literal string
artist = ["AC|DC" | "A|B"] # pipes inside quotes are data
```

Tag-set elements are bare tag names: no quotes and no spaces. Value-set
elements are normal values, so numbers, quoted strings, and booleans work as
they do in a single-value rule. Empty elements and nested unquoted brackets
are errors.

Let `L` be the tag set and `R` the value set. Positive operators match when
**any** pair from a tag in `L` and a value in `R` matches. `!=` is set
non-membership: it matches only when **no** pair is equal. Missing tags
contribute no pairs, so positive operators are false and `!=` is true.

```text
[genre | style] != [Pop | Rap]
```

is false when either tag has `Pop` or `Rap`. Comparison operators accept
exactly one value on the right, but they can still use multiple tags:

```text
rating > [3 | 4]               # parse error
rating > 4                     # valid
[year | original_year] >= 1980 # valid
```

`@CASE` applies to every pair of a set rule.

### Missing values

A tag that is absent is treated as missing. Zero and false are real values,
not missing ones, so `track = 0`, `comment = ""`, and `is_lossless = false`
work as expected.

## Combining rules

Plain rules are ANDed. `@OR` joins a rule to the preceding OR group, and `@NOT`
negates the rule on its line:

```text
genre = Metal
@OR genre = Rock
rating >= 4
```

This means `(genre = Metal OR genre = Rock) AND rating >= 4`. A plain rule
starts a new AND group; consecutive `@OR` rules join the current group. `@OR`
cannot be the first rule, and `@NOT` always applies to one rule, never to a
group. There are no parentheses or nested groups.

`@OR` and `@NOT` can be combined in any order. `@CASE` can appear with either
or both:

```text
@CASE artist = "DANCE WITH THE DEAD"
@OR @NOT @CASE genre = Pop
```

Directives do not end an OR group. This is still one OR group:

```text
genre = Metal
@sort title
@OR genre = Rock
```

`@NOT rating >= 4` matches unrated songs because a missing tag makes the
comparison false. `rating < 4` does not match them.

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
genre ~ "Metal"
rating >= 4
```

Both rules must pass. Because `~` is a substring test, this also matches
`Heavy Metal`, `Nu Metal`, and `Metalcore`; use `genre = Metal` for an exact
match.

### Musicals

```text
genre ~ "Musical"
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
mime_type ~ flac
```

Songs whose path contains a folder name:

```text
filename ~ /Live/
```

Combining several conditions:

```text
genre ~ Synthwave
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

- No nested OR groups or parentheses. `@NOT` applies to one rule only.
- No negative or scientific-notation numbers.
- No inline comments.
- Numeric comparisons need a numeric rule value; quoted numbers are strings.
- One `@sort` line per file; combine all keys on that line.
- Missing sort values always go last; there is no nulls-first option.
- Text sorting is case-insensitive but not locale-aware or natural-number
  aware; numeric-looking values are compared as numbers.

Some of these are on the [roadmap](https://github.com/haplo/genplis/blob/main/docs/dev.md#roadmap).
