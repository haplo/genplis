# The M3UG filter language

M3UG describes which songs belong in a playlist and how to order them. This
is the language reference; start with the [Quickstart](index.md#quickstart)
to make your first playlist. For tag names and units, see [Tags](tags.md);
for running genplis, see [Usage](usage.md).

## How M3UG files work

A `.m3ug` file defines one playlist. `Favorites.m3ug` produces `Favorites.m3u`
in the same directory when songs match. Each filter applies to the whole
collection you scan, not just the folder containing the filter.

The file contains two kinds of lines:

- **Rules** select songs by their tags. Ordinary rules must all match;
  `@OR` and `@NOT` express alternatives and exclusions.
- **Directives** control the result: `@SORT`, `@DEDUPE`, `@LIMIT`, and
  `@MAX-DURATION` order and narrow the selection. `@INCLUDE` reuses another
  file, and `@NO-PLAYLIST` marks a shared fragment.

An empty file has no rules and matches every song. See
[Generated playlists](usage.md#generated-playlists) for output behavior.

## File syntax

A rule has three parts, separated by spaces or tabs:

```text
tag operator value
```

For example:

```text
genre ~ "Heavy Metal"
*rating >= 4
```

- Use **one rule or directive per line** in a UTF-8 text file. A byte-order
  mark and either LF or CRLF line endings are accepted.
- Blank lines and leading/trailing whitespace are ignored. Values can
  contain spaces, as in `artist = DANCE WITH THE DEAD`.
- Put **comments on their own lines**, starting with `#` after any indentation.
  There are no inline comments: `genre = Rock # favorite` searches for the
  literal value `Rock # favorite`.
- Names beginning with `@` are case-insensitive. Unknown names, malformed
  rules, and invalid directive arguments stop the run with a file and line
  number. Rule modifiers cannot be applied to directives.

## Special tag names

Use tag names as shown by [file inspection](tags.md#inspect-your-tags).
Names always ignore case: `Artist` and `artist` are the same.

A leading `*` explicitly selects a **calculated value**:

| Name | Meaning |
| --- | --- |
| `artist`, `genre`, `year`, etc. | Embedded metadata |
| `*duration`, `*filename`, `*is_lossless`, etc. | Calculated audio properties |
| `*rating` | Normalized 0–5 rating, currently calculated from `fmps_rating` |

Unprefixed audio-property names such as `duration` remain supported, but an
embedded tag with the same name takes precedence. Unprefixed `rating` uses
the raw tag when present and otherwise falls back to the calculated rating.
Use `*rating` when you want the normalized scale, even if a raw rating also
exists. Files with only a raw rating have no calculated rating; see
[Rating](tags.md#rating).

The prefix works in rules, tag sets, sort keys, dedupe keys, and per-tag
limits. It is **not a wildcard**: `*artist` is missing because artist is not
a calculated property. See [Calculated audio properties](tags.md#calculated-audio-properties)
for the available names and units.

## Values and types

| Written as | Interpreted as |
| --- | --- |
| `Metal` or `Heavy Metal` | Text; bare values may contain spaces |
| `"Heavy Metal"` or `'Heavy Metal'` | Text with the surrounding quotes removed |
| `1980` | Integer |
| `4.5` | Decimal number |
| `true` or `false` | Boolean for `=` and `!=` |

**Quote text, not numbers**, when the distinction matters. `track = 7`
matches a numeric value or the string `"7"`; `track = "7"` requires text.
Quotes always make a string, even for `"true"` or a duration such as `"10m"`.
They also preserve spaces inside the quotes.

Numbers must use digits, optionally followed by a dot and more digits.
Forms such as `-1`, `+7`, `.5`, `5.`, `1e3`, and `0x10` are text, not
numbers. Numeric comparisons reject them.

Quoted strings support `\"`, `\'`, and `\\`. Other backslashes are preserved,
so regexes such as `\d+` stay readable. Text operators (`~`, `^`, `$`, `%`)
treat their value as text, including bare `true`, `false`, or digits.

## Operators

| Operator | Meaning | Example |
| --- | --- | --- |
| `=` | Equals | `genre = Metal` |
| `!=` | Does not equal | `genre != Pop` |
| `~` | Contains | `genre ~ Metal` |
| `^` | Starts with | `title ^ Live` |
| `$` | Ends with | `title $ Remix` |
| `%` | Regular-expression search | `*filename % \.mp3$` |
| `<`, `<=` | Less than / at most | `duration < 5m` |
| `>`, `>=` | Greater than / at least | `year >= 1980` |

These are the only operator spellings. Equality accepts text, numbers, or
booleans; text operators need string tag values; numeric comparisons accept
numbers and numeric strings, but not booleans.

### Text and case

Text matching ignores case unless the rule starts with `@CASE`:

```text
@CASE artist = "DANCE WITH THE DEAD"
```

`genre = Metal` matches exactly `Metal`, ignoring case. `genre ~ Metal`
also matches `Heavy Metal` and `Metalcore`. Use `is_lossless = true` for a
boolean property; text operators don't match numbers or booleans.

`%` searches anywhere in a value rather than requiring the whole value to
match. Use regex anchors when needed: `genre % ^Metal` matches a prefix.
Regexes are case-insensitive unless `@CASE` is used; inline regex flags can
override that. Invalid patterns are reported with a file and line number.

### Numeric comparisons

Write an unquoted number, as in `year > 1980`, not `year > "1980"`.
Numeric strings in tags are converted, so `track > 7` matches `"8"` as
well as `8`. Missing or non-numeric values never pass a numeric comparison.
`@CASE` is not allowed on numeric comparisons.

### Multi-value rules

Use brackets and `|` to list alternative tags or values:

```text
[genre | style] = [Metal | Rock]
[artist | albumartist] = ["DANCE WITH THE DEAD" | Perturbator]
[*filename | comment] ~ [Live | Bootleg]
```

A positive test passes if **any tag/value pair** matches. `!=` passes only
when **no pair** is equal: `[genre | style] != [Pop | Rap]` rejects a song
if either tag has either exact value. The same any/all behavior applies when
a song's tag itself has several values; see [Multi-valued tags](tags.md#multi-valued-tags).

Numeric comparisons allow several tags but only one value:
`[year | original_year] >= 1980` is valid; `rating > [3 | 4]` is not.
`@CASE` applies to the whole rule.

Set syntax has a few boundaries:

- A set must be unquoted and contain at least one `|`. `[Untitled]` alone
  is literal text, not a one-item set.
- Quote literal brackets or pipes when needed: `title = "[Intro | Outro]"`
  is one string, and `artist = ["AC|DC" | "A|B"]` is a two-value set.
- Tag names within a set are unquoted and contain no spaces. Values use
  the normal types above. Empty elements and nested unquoted sets are errors.

### Missing values

An absent or unknown tag does not match positive tests such as `=`, `~`, or
`>=`. **It does match `!=`**: `genre != Pop` includes songs without a genre.
With tag sets, missing tags contribute no values to compare.

Zero, `false`, and an empty string are real values: `track = 0`,
`is_lossless = false`, and `comment = ""` can match. Ignored or oversized
tags behave as missing; see [Missing or discarded tags](tags.md#missing-or-discarded-tags).

## Duration literals

Rules using only `duration` or `*duration` accept readable durations as well
as plain seconds. `@MAX-DURATION` accepts the same forms.

| Form | Meaning |
| --- | --- |
| `600` | 600 seconds |
| `30s`, `10m`, `2h`, `2d` | Seconds, minutes, hours, days |
| `2m15s`, `1h30m` | Combined units |
| `1:30` | 90 seconds (`mm:ss`) |
| `1:30:00` | 90 minutes (`h:mm:ss`) |

For example, `*duration >= 10m` selects songs at least ten minutes long.
Units must be lowercase. In colon forms, seconds must be 0–59; minutes must
also be 0–59 in `h:mm:ss`, but may exceed 59 in `mm:ss`.

Quotes prevent conversion: `duration = "10m"` compares text. For other tags,
`10m` is ordinary text, so a numeric test such as `bitrate > 10m` is invalid.

## Combining rules

Ordinary rules are joined with **AND**. `@OR` joins its rule to the previous
rule as an alternative; consecutive `@OR` lines extend that group:

```text
genre = Metal
@OR genre = Rock
*rating >= 4
```

This means `(genre = Metal OR genre = Rock) AND *rating >= 4`. A new ordinary
rule starts a new AND group. `@OR` cannot be the first rule, and there are no
parentheses or nested OR groups.

`@NOT` negates only the rule on its line, not a group:

```text
genre ~ Metal
@NOT title ~ Live
```

You can combine `@OR`, `@NOT`, and `@CASE` in any order before a rule.
Directives don't end an OR group: placing `@SORT title` between
`genre = Metal` and `@OR genre = Rock` would not change their grouping.

Be careful with missing values: `@NOT *rating >= 4` includes songs with no
calculated rating, because their comparison fails and is then negated.
`*rating < 4` excludes those songs.

## Ordering

Use one `@SORT` line with comma-separated keys, highest priority first:

```text
@SORT *rating desc, artist, album, disc, track, title
```

Each key optionally takes `asc` (the default) or `desc`. Later keys break
ties on earlier ones. Some useful choices:

| Directive | Order |
| --- | --- |
| `@SORT title` | Title, A–Z |
| `@SORT year desc` | Newest first |
| `@SORT artist, album, disc, track, title` | Album order |
| `@SORT duration` | Shortest first |
| `@SORT filename` | Absolute file path |
| `@SORT` | Directory-walk order, overriding included and configured defaults |

Without `@SORT`, the [configured sort](config.md#sort) applies; its default
is `filename`. `filename` and `*filename` sort by absolute path, not the
relative path written into the playlist. Calculated names such as `*rating`
work as keys just as they do in rules.

Numeric-looking values sort numerically (`2` before `10`); other text sorts
case-insensitively. Multi-valued tags use their first non-empty value. Text
sorting is not locale-aware, and digits within text are not sorted as numbers.

### Missing sort values

Missing or empty values sort last **for that key**, in either direction.
Equal or jointly missing values move the comparison to the next key; a
missing lower-priority key never overrides a higher-priority difference.
For example, with `@SORT artist, album, track`, a song without a track number
still stays with its album. Complete ties keep directory-walk order.

### Random order

| Directive | Effect |
| --- | --- |
| `@SORT random` | Shuffle all matching songs |
| `@SORT random 42` | Shuffle reproducibly with a fixed seed |
| `@SORT artist, random 7` | Sort artists, then shuffle within each artist |

`random` must be the last key and cannot take `asc` or `desc`. Its optional
seed is a non-negative integer. Without a seed, the shuffle changes each run;
with preceding keys, only equal-key groups are shuffled.

## Removing duplicates

`@DEDUPE` keeps the **first entry after sorting** for each combination of
listed tag values:

```text
@DEDUPE artist, title
```

This removes repeated artist/title pairs. Choose your sort order to decide
which copy wins. Keys use the [same normalization as sorting](#ordering),
including the first non-empty value for multi-valued tags; calculated keys
such as `*duration` are allowed too.

Entries missing any key are always kept. Dedupe happens before playlist
limits, so removed duplicates don't consume a cap. Use `@DEDUPE` with no
keys to disable a default inherited through `@INCLUDE`.

## Playlist limits

After matching, genplis **sorts → removes duplicates → applies limits**.
Limits narrow the final playlist; they don't change which rules a song
matches.

| Directive | Effect |
| --- | --- |
| `@LIMIT 100` | Keep at most 100 songs |
| `@LIMIT 3 PER artist` | Keep at most three songs per artist |
| `@MAX-DURATION 1h30m` | Stop when the next song would exceed 90 minutes |

The three limits can be combined. Counts must be non-negative integers;
`0` disables the corresponding cap. Use at most one of each form in a file,
just as `@SORT` and `@DEDUPE` each take one line.

For **per-tag limits**, `PER` ignores case and the key uses the same
normalization as sorting. A calculated key is allowed, for example
`@LIMIT 3 PER *rating`. Songs missing that key, or with an empty value, are
excluded while the cap is active. Songs skipped by this cap don't consume
the total count or duration budget; selection continues with the next song.

For **duration limits**, unknown durations count as zero. If the first
selected song alone exceeds the cap, it is still included. Otherwise,
selection stops rather than looking for a shorter song that might fit.

## Including other files

`@INCLUDE` reuses another file's rules and default directives:

```text
@INCLUDE Base.m3ug
*rating >= 4
```

The included rules and this file's rules must **all** match. Their OR groups
remain separate: an `@OR` here cannot join a rule inside `Base.m3ug`.
Rule modifiers cannot be applied to `@INCLUDE`.

Paths follow these rules:

- Relative paths start at the directory of the file containing `@INCLUDE`,
  not the current working directory. Absolute paths and `~` work too.
- Quote paths with spaces: `@INCLUDE "shared/Short songs.m3ug"`.
- An existing exact path wins. Otherwise, if the path doesn't end in
  `.m3ug`, genplis tries appending it: `@INCLUDE Base` can load `Base.m3ug`.
  Any readable filter file can be included; the extension is a convention.
- Includes may nest up to 32 levels. Missing or unreadable files,
  directories, cycles, excessive depth, and syntax errors stop the run.
  Errors identify the including file, line, and path.

### Directive merging

Included directives are **defaults**. The including file's own directive
always wins, regardless of line position. For example, if `Base.m3ug` sets
`@SORT artist` and `@LIMIT 10`, this file inherits the sort but limits the
playlist to five entries:

```text
@LIMIT 5
@INCLUDE Base.m3ug
```

When including several files, later includes win **per directive**. Nested
includes resolve their own defaults before passing them to the parent. A
local `@SORT` with no keys, `@DEDUPE` with no keys, or a limit of `0` can
explicitly disable the corresponding inherited setting.

## Files without a playlist

Mark a reusable fragment with `@NO-PLAYLIST`:

```text
@NO-PLAYLIST
genre ~ Metal
```

The file is parsed for includes but doesn't match songs directly or generate
its own playlist. An existing `.m3u` is left untouched. This flag takes no
arguments, applies only to its own file, and is never inherited by files
that include it.

## Examples

The [example gallery](https://github.com/haplo/genplis/tree/main/examples)
contains complete filters you can copy. For a more tailored playlist,
combine rules and directives:

```text
# An hour of highly rated metal, with some artist variety
genre ~ Metal
*rating >= 4
@SORT random
@DEDUPE artist, title
@LIMIT 3 PER artist
@MAX-DURATION 1h
```

Both rules must match. The results are shuffled, duplicate artist/title pairs
are removed, and selection then respects the per-artist and duration caps.
For other common patterns, use `year >= 1980` with `year < 1990` for 1980s
releases, or `*is_lossless = true` for lossless files. See
[Common tags](tags.md#common-tags) and [Rating](tags.md#rating) before choosing
fields for your collection.

## Testing and debugging filters

First [inspect a song's tags](tags.md#inspect-your-tags) to check its names
and values. Then choose the tool for your question:

| Option | Answers | Work performed |
| --- | --- | --- |
| `--show-rules` | How was the filter parsed? | Rules only; no audio or cache access |
| `--trace SONG` | Does this song match? | Evaluate one song; no full selection simulation |
| `--trace-full SONG` | Will this song reach the playlist? | Simulate ordering, dedupe, and limits across the collection when needed |

All three modes **leave playlists untouched**. `--filter` selects a specific
filter; without it, genplis discovers filters under the collection path.

### Show parsed rules

```bash
genplis --show-rules --filter ~/Music/Favorites.m3ug
```

The tree shows included files inline, resolved include paths, original rule
values, and effective directives. Includes appear before local rules because
the tree follows evaluation order. A directive-only include has no match
test, but its defaults still apply.

### Trace one file

```bash
genplis ~/Music --trace ~/Music/song.mp3 --filter ~/Music/Favorites.m3ug
```

A trace might contain this excerpt:

```text
    PASS artist = "Test Artist" (line 3)
      tag artist = ['Test Artist'] -> 'Test Artist'
    FAIL rating >= 4 (line 4)
      missing tag rating (no rating tag)
    SKIP genre ~ Metal (line 5) (short-circuited: an earlier AND child failed)
```

`PASS` and `FAIL` show evaluated rules; `SKIP` means the result was already
decided, so that rule wasn't tested. Traces identify missing values,
calculated rating sources, and case-sensitive rules. They also show the
effective playlist inputs, but don't simulate the full selection.

### Simulate exact selection

```bash
genplis ~/Music --trace-full ~/Music/song.mp3 --filter ~/Music/Favorites.m3ug
```

This adds the song's sorted position, any dedupe winner or cap failure, and
the final result: `IN PLAYLIST` with a position, or `NOT IN PLAYLIST` with a
reason. A song that fails the rules is reported as `NO MATCH`. Excluded songs,
songs outside the collection, and `@NO-PLAYLIST` filters aren't simulated.

Both trace modes may update the tag cache: `--trace` loads only the target;
`--trace-full` may scan the collection. Add `-q` to keep the requested tree
or trace without progress chatter; `-qq` suppresses all normal output.

For normal playlist generation, see [Usage](usage.md).
