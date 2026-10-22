---
title: Your music. Your rules. Your playlists.
description: Turn the tags in your local music collection into M3U playlists. Define a few rules, run Genplis, and let your playlists follow your collection.
home: true
hide:
  - navigation
  - toc
search:
  exclude: true
---

<div class="gp-hero" markdown="1">

<div class="gp-hero-copy" markdown="1">

<p class="gp-eyebrow">FOR THE COLLECTION YOU CALL YOUR OWN</p>

# Your music.<br>Your rules.<br><span class="gp-accent">Your playlists.</span>

<p class="gp-lead">You collected the music. Let the tags do the curating.</p>

Genplis turns your local music collection into M3U playlists with a few
readable rules. Add new music, run it again, and your playlists follow along.
No manual track lists to maintain.

[Get started](index.md){ .md-button .md-button--primary }
[Get the code](https://github.com/haplo/genplis){ .md-button }

<p class="gp-fineprint">Local files. Open source. Python 3.12+.</p>

</div>

<div class="gp-record" markdown="1">

<div class="gp-record-heading"><span class="gp-status" aria-hidden="true"></span> A MIXTAPE, WITHOUT THE MANUAL WORK</div>

<div class="gp-wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

<div class="gp-file-label">1 / DEFINE · Metal.m3ug</div>

```text
genre ~ "Metal"
@SORT random
@MAX-DURATION 1h
```

<div class="gp-file-label">2 / GENERATE</div>

```bash
genplis ~/Music
```

<div class="gp-file-label">3 / PLAY</div>

<div class="gp-result"><span>Metal.m3u</span> is ready for your next listening session.</div>

</div>

</div>

<div class="gp-section-heading" markdown="1">

<p class="gp-eyebrow">LESS PLAYLIST MAINTENANCE. MORE LISTENING.</p>

## A little text. A lot of possibility.

</div>

<div class="gp-features" markdown="1">

<div markdown="1">

### Start with your tags

Genres, artists, years, ratings, and audio properties. Use the information
already in your collection to find exactly the songs you want.

[Explore tags →](tags.md)

</div>

<div markdown="1">

### Make the mix yours

Sort or shuffle. Remove duplicates. Pick a few tracks per artist, or cap a
playlist at an hour. Small rules, useful combinations.

[Meet M3UG →](m3ug.md)

</div>

<div markdown="1">

### Run it. Run it again.

A SQLite cache remembers parsed tags. Later runs only re-read changed
files, with parallel parsing to help with larger cold scans.

[See how it works →](usage.md#what-a-run-does)

</div>

</div>

<div class="gp-start" markdown="1">

<div markdown="1">

<p class="gp-eyebrow">FROM COLLECTION TO PLAYLIST</p>

## Your first mix is a few lines away.

Install from Git with [uv](https://docs.astral.sh/uv/), put a `.m3ug` filter
in your music collection, and run Genplis. It writes an `.m3u` next to the
filter when songs match. Your audio files stay untouched.

[Walk through your first playlist →](index.md#your-first-playlist)

</div>

<div markdown="1">

```bash
uv tool install git+https://github.com/haplo/genplis.git
genplis ~/Music
```

Not on PyPI yet. Requires Python 3.12 or later.

</div>

</div>

<div class="gp-section-heading" markdown="1">

<p class="gp-eyebrow">A FEW IDEAS TO GET YOU LISTENING</p>

## What does your collection have in store?

</div>

<div class="gp-features gp-recipes" markdown="1">

<div markdown="1">

### Back to the eighties

```text
year >= 1980
year < 1990
```

Two rules. One decade.

</div>

<div markdown="1">

### A little variety

```text
@SORT random
@LIMIT 2 PER artist
@LIMIT 30
```

Keep any one artist from taking over.

</div>

<div markdown="1">

### The long way home

```text
genre ~ "Synthwave"
@SORT random
@MAX-DURATION 90m
```

A soundtrack for the journey.

</div>

</div>

[Browse all M3UG Examples →](https://github.com/haplo/genplis/tree/main/examples){ .md-button }

<div class="gp-closing" markdown="1">

## Built for people who keep their music.

Genplis grew out of a music collection curated over 30 years—and the wish
to spend less time maintaining playlists for it.

[View on GitHub](https://github.com/haplo/genplis){ .md-button }
[Help make it better](https://github.com/haplo/genplis/issues){ .md-button }

</div>
