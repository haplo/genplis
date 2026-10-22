# The M3UG filter language

M3UG is the small language *genplis* uses to describe playlists. A `.m3ug`
file contains one rule or directive per line, and the file's filter expression
must match a song for it to appear in the generated playlist.

This page is the language reference. For the tags you can use in rules, see
[Tags](tags.md). For running
genplis and the generated playlist format, see
[Usage](usage.md).

## How M3UG files work

- Put a `.m3ug` file anywhere inside your music collection. The file name
  becomes the playlist name: `Favorites.m3ug` generates `Favorites.m3u` in the
  same directory.
- One file can define one playlist. To create several playlists, use several
  `.m3ug` files. A file with `@NO-PLAYLIST` is a shared fragment and does not
  produce a playlist of its own.
- Filters are applied to every music file found under the `PATH` given on the
  command line (or configured in the config file), not just to the folder that
  contains the `.m3ug` file. Use `--filter FILE` to process one specific
  filter; a `.m3ug` file cannot be passed as `PATH`.
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

There are no aliases or alternative spellings. Any other operator is rejected
with `Unrecognized operator`.

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
  [Tags](tags.md).

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

## Duration literals

Rules whose left-hand side is only the `duration` tag accept duration
literals instead of plain seconds:

```text
duration >= 10m
duration < 1h30m
duration >= 2m15s
duration <= 1:30
```

| Form | Meaning |
| --- | --- |
| `600` | seconds |
| `10m` | minutes |
| `1h30m` | hours and minutes |
| `2m15s` | minutes and seconds |
| `30s` | seconds |
| `2d` | days |
| `1:30` | 90 seconds (`mm:ss`) |
| `1:30:00` | 90 minutes (`h:mm:ss`) |

Units are lowercase `s`, `m`, `h`, and `d`. In `mm:ss`, seconds must be 0–59
and minutes may exceed 59. In `h:mm:ss`, minutes and seconds must be 0–59.
Quoted values stay strings, so `duration = "10m"` does not become a number.
For any other tag, `10m` is an ordinary string; numeric operators reject it.
Duration literals are also accepted by `@MAX-DURATION`.

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

### Random order

`random` is a sort key that shuffles entries. It must be the last key and
cannot take `asc` or `desc`:

```text
# Shuffle every matching song
@sort random

# Reproducible shuffle with a fixed seed
@sort random 42

# Shuffle within each artist, keeping artists in order
@sort artist, random 7
```

With preceding keys, genplis sorts by those keys and then shuffles equal-key
runs. With only `random`, it shuffles everything. Without a seed the order
changes every run; a seed makes it reproducible. Each playlist gets its own
random generator.

`@sort` with no keys means directory-walk order and overrides both included
and configured defaults:

```text
@sort
```

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
handling as filters; see [Rating](tags.md#rating)
for the scale caveat.

## Playlist limits

Directives constrain how many entries are selected after ordering:

```text
@LIMIT 50
@LIMIT 3 PER artist
@MAX-DURATION 2h
```

`@LIMIT` takes a non-negative integer. `0` disables the count cap. The
playlist stops after that many entries.

`@LIMIT N PER tag` limits how many entries can share the same tag value. `PER`
is case-insensitive, and `N` is a non-negative integer; `0` disables the
per-tag cap. Tag values are normalized like sort values: multi-valued tags use
their first non-empty value, text is compared case-insensitively, and
numeric-looking strings are compared as numbers. Entries whose tag is missing
or empty are excluded while a per-tag cap is active.

A global cap and a per-tag cap can be used together:

```text
@LIMIT 100
@LIMIT 3 PER artist
```

This keeps at most 100 entries overall and at most 3 per artist. Entries
skipped by the per-tag cap do not count toward `@LIMIT` or `@MAX-DURATION`;
selection continues with the next entry.

`@MAX-DURATION` takes a duration literal or `0`. `0` disables the cap.
Entries are added in playlist order until the next one would push the total
over the limit. Unknown durations count as zero. If the first entry alone is
longer than the cap, it is still included.

```text
@LIMIT 100
@MAX-DURATION 1h30m
rating >= 4
```

All limits are selection constraints, not filters: they apply after ordering
and after `@DEDUPE`, and they do not change which songs match the rules.

## Removing duplicates

`@DEDUPE` removes entries that share the same values for the listed tags:

```text
@DEDUPE title
@DEDUPE album, title
```

Keys work like sort values: multi-valued tags use their first non-empty value,
text is compared case-insensitively, and numeric-looking strings are compared
as numbers. After ordering, the **first** entry for each key is kept and later
duplicates are dropped. Entries that are missing any key are always kept, so
`@DEDUPE title` never removes a song without a title.

Dedupe runs before `@LIMIT` and `@MAX-DURATION`, so duplicate entries do not
consume either cap. `@DEDUPE` with no tags disables dedupe; this is useful when
an included file supplies a default set of keys (see `@INCLUDE`).

## Including other files

`@INCLUDE` loads rules and default directives from another file:

```text
@INCLUDE Base.m3ug
@INCLUDE "shared/Short songs.m3ug"
```

The rest of the line is the path. Matching quotes are stripped, `~` is
expanded, and relative paths resolve from the directory of the file containing
the `@INCLUDE`. Absolute paths work too. Any readable file may be included;
the `.m3ug` extension is only a convention. If the path does not already end
in `.m3ug` and does not exist, genplis also tries the same name with `.m3ug`
appended, so `@INCLUDE Base` loads `Base.m3ug` and `@INCLUDE INC.good` loads
`INC.good.m3ug`. An existing exact path always wins. Includes may nest up to 32
levels deep.

Included rules are ANDed with the current file's rules as separate groups.
`@OR` and `@NOT` only apply within the file that writes them:

```text
# Base.m3ug
genre = Metal

# Main.m3ug
@INCLUDE Base.m3ug
rating >= 4
@OR rating = 5
```

This matches metal songs rated 4 or 5; the included `genre = Metal` is not
part of the `rating` OR group. `@INCLUDE` cannot be used under `@OR` or
`@NOT`.

### Directive merging

Included files provide defaults, and the current file's directives override
them regardless of where the `@INCLUDE` line or the directive appears:

```text
# Base.m3ug
@SORT artist
@LIMIT 10
@DEDUPE title

# Main.m3ug
@LIMIT 5
@INCLUDE Base.m3ug
```

The resulting playlist sorts by `artist`, dedupes by title, and keeps at most
5 entries. When a file includes several files, later includes win per
directive. Nested includes resolve depth-first, so each file's own directives
override its includes before the result is passed to its parent.

All include problems are fatal and name the including file, line, and path:
missing files, unreadable files, directories, cycles, excessive depth, and
invalid syntax in an included file. For example:

```text
Metal.m3ug:3: cannot include "Base.m3ug": file not found
Metal.m3ug:3: include cycle: Metal.m3ug -> Base.m3ug -> Metal.m3ug
```

## Files without a playlist

Use `@NO-PLAYLIST` for include fragments and other filter-only files:

```text
@NO-PLAYLIST
genre = Metal
rating >= 4
```

The file is still parsed and may be included by other files, but genplis does
not match songs against it directly and does not write a `.m3u` for it. Any
existing playlist with the same name is left untouched. The flag applies only
to the file that contains it and is never inherited through `@INCLUDE`.

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
  [Tags](tags.md#rating) for
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
[Tags](tags.md#rating).

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

### Show parsed rules

`--show-rules` parses the filters named with `--filter`, or every non-excluded
`.m3ug` file under a directory, without opening the cache, scanning audio, or
writing playlists:

```bash
uv run genplis --show-rules --filter Favorites.m3ug
uv run genplis --show-rules ~/Music
```

```text
Favorites.m3ug
  AND
    @INCLUDE Base.m3ug (Favorites.m3ug:1) -> /home/me/Music/Base.m3ug
      genre ~ Synthwave (line 2)
    rating >= 4 (line 2)
  directives:
    sort: artist
```

Includes are shown inline. They are always ANDed before the including file's
own rules, so the tree follows evaluation order, not source order. Nested
includes recurse in the same way. The header keeps the path exactly as written,
including quotes, and shows the resolved target so extension inference and `~`
expansion are visible.

A directive-only include does not participate in matching and has no pass/fail
status. Its directives still apply:

```text
  @INCLUDE Defaults.m3ug (Favorites.m3ug:1) -> /home/me/Music/Defaults.m3ug
    (no rules; directives only)
    directives:
      sort: artist
```

Rules keep their original literal text. Quoted numbers stay strings, so
`rating = "4"` is different from `rating = 4`; `"true"` is a string while
`true` is a boolean. Duration literals show their converted value, for example
`duration >= 10m (600s)`. `@CASE` adds `[case-sensitive]`.

### Trace one file

`--trace SONG` evaluates every selected filter for one audio file and prints
`PASS`, `FAIL`, and `SKIP` nodes. The tags consulted are listed first, and the
target is loaded through the normal tag cache path (so that one file may be
parsed or refreshed).

```bash
uv run genplis --trace song.mp3 --filter Favorites.m3ug
uv run genplis --trace song.mp3 ~/Music
```

```text
Favorites.m3ug: FAIL
  FAIL AND
    PASS artist = "Test Artist" (line 3)
      tag artist = ['Test Artist'] -> 'Test Artist'
    FAIL rating >= 4 (line 4)
      missing tag rating (no rating tag)
    SKIP genre ~ Metal (line 5) (short-circuited: an earlier AND child failed)
playlist inputs:
  sort: title
    title = 'test'
  dedupe: album
    album = <missing> (kept)
  selection: not simulated; use --trace-full
NO MATCH
```

`SKIP` means evaluation short-circuited: the rule was never applied. A missing
tag is shown explicitly. Calculated ratings report their source, multi-value
tags show the list, and `@CASE` rules are marked. Playlist inputs list the
effective sort and dedupe keys, limits, duration and `@NO-PLAYLIST`. A
deterministic exclusion, such as a missing per-tag limit key, is reported
directly. Count and duration caps need the whole collection, so `--trace`
leaves them unsimulated.

### Simulate exact selection

`--trace-full SONG` includes the same tree and playlist inputs, then performs
a dry-run scan and selection. It may read and update the tag cache like a
normal run, but it writes no playlists:

```bash
uv run genplis --trace-full song.mp3 --filter Favorites.m3ug
uv run genplis --trace-full song.mp3 ~/Music
```

```text
selection:
  /home/me/Music/Favorites.m3ug
    matches: 1
    sorted position: 1 of 1
    sort: title
      title = 'test'
    dedupe: kept: missing dedupe key
    count: no count cap
    per-tag: no per-tag cap
    duration: no duration cap
    result: IN PLAYLIST at position 1
```

The simulation reports the target's sorted position, dedupe winner, count,
per-tag and duration cap results, and the final playlist position. Failures
read `result: NOT IN PLAYLIST` with a reason. A filter that does not match is
reported as `NO MATCH`; `@NO-PLAYLIST` files are reported without simulating
them. If the target is excluded, outside the scan root, matches no filter, or
only matches `@NO-PLAYLIST` filters, the scan is skipped and the reason is
printed.

With `-q`, the requested tree or trace is still printed while progress chatter
is suppressed. `-qq` suppresses all normal output; errors still go to standard
error. None of the debugging modes writes a playlist.

### Normal runs

To process only one `.m3ug` file and regenerate its playlist:

```bash
uv run genplis ~/Music --filter ~/Music/Favorites.m3ug
```

This prints the rule tree, scans the collection (the `PATH`, or the configured
one when omitted), and writes `Favorites.m3u` next to the filter. Other `.m3ug`
files are ignored. Add `--verbose` to print each discovered filter tree, the
effective sort order, each matching song, and match counts during a full run:

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

Some of these are on the [roadmap](dev.md#roadmap).
