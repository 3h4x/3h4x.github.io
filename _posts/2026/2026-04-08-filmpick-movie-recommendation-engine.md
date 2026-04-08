---
layout: post
title:  "filmpick — a local movie recommendation engine, renamed"
categories: tech
tags: [nextjs, python, sqlite, tmdb, movies, recommendation-engine]
comments: True
---

I've been running a project called `movies-organizer` for a while. Bad name. It sounds like a tool for renaming files. Today I renamed it to `filmpick` — because what it actually does is help you pick your next film.

<!-- readmore -->

## What it is

`filmpick` is a personal movie discovery engine that runs entirely on your machine. No cloud, no account, no tracking. You rate films, it builds a model of your taste, and gives you better recommendations than any streaming platform will — because unlike them, it has no incentive to push you toward specific content.

Seven recommendation engines, all powered by your own ratings:

- **By Genre** — weighs genres by how you *actually* rate them, not just what you click on
- **By Actor** — tracks which actors keep showing up in your highest-rated movies
- **By Director** — loved 3 Villeneuve films? Here's everything else he directed
- **Similar** — seeds from your top-rated films via [TMDb](https://www.themoviedb.org/)'s recommendation API
- **Hidden Gems** — high TMDb score, low vote count; stuff you'd never find browsing
- **Star-Studded** — popular, well-rated films you somehow missed
- **Surprise Me** — random discovery when you genuinely don't know what you're in the mood for

All engines automatically exclude movies you've already seen, dismissed, or queued. No repeats, no noise.

![filmpick top rated movies](/assets/filmpick-top-rated.png)
*My 10/10 Action films — The Shining, Leon, Scarface, Ghost in the Shell, Ninja Scroll. Sorted by personal rating, filtered by genre. The engines seed from these to find what's next.*

## Why the rename

The original name `movies-organizer` described a side feature — the app can scan a folder of video files, parse titles and years from filenames, and fetch metadata automatically. That part exists, but it's not the point.

The point is: you sit down on Friday evening not knowing what to watch, and the app tells you. The name should reflect that. `filmpick` does it in one word.

There's also the boring practical reason: "organizer" as a suffix is completely overloaded. Everything from a few years ago was called `<noun>-organizer`. The GitHub repo is renamed too — it's [film-pick](https://github.com/3h4x/film-pick) all the way down now.

## The stack evolution

It started as a Python CLI. You'd run a script, it would call [TMDb](https://www.themoviedb.org/), and spit out recommendations in the terminal. Useful for me, basically unusable for anyone else.

Then it became a `Next.js` monorepo (Next.js 16 + React 19 + TypeScript, `SQLite` under the hood). Same data model, but now there's a proper UI, a REST API, filtering, sorting, and a TMDb key config panel — so you don't have to touch any config files to get started.

```bash
pnpm install
pnpm dev    # http://localhost:4000
```

The Python CLI still lives in the repo for the media organization side — renaming files, moving them into folders — but all the recommendation logic is in `Next.js` now.

![filmpick recommendations by director](/assets/filmpick-recommendations.png)
*Recommendations filtered by director — "More from director Robert Rodriguez". Each engine gets its own filter tab.*

## Your library, your ratings

The library view is where the data lives. 1786 films tracked, sortable by your rating, global TMDb score, year, title, or date added. Filter by genre, source, year range — or toggle unrated films to find things you watched but never scored.

Sort by "My Rating" and your 10/10s float to the top. It's surprisingly satisfying to see your all-time favorites laid out like that — and it's exactly the data the recommendation engines use to find your next one.

![filmpick discover view](/assets/filmpick-discover.png)
*The Discover tab — "Because you love Crime" with The Usual Suspects, Memories of Murder, Better Days... good taste is rewarded with better recommendations.*

## The watchlist

When you find something interesting in Discover but aren't ready to watch it tonight, add it to your Watchlist. It's a simple queue — no algorithms, no sorting, just your curated "watch next" pile.

![filmpick watchlist](/assets/filmpick-watchlist.png)
*9 films queued — The Black Phone, Traffic, The Place Beyond the Pines, I Saw the Devil, Parasite... Friday evening sorted.*

## Person intelligence

One feature I keep coming back to: the app tracks not just movies but the people behind them.

Rate a Coen Brothers film highly, and `filmpick` builds a profile — how many of their films you've seen, your average rating across them, their full filmography sorted by what you haven't watched yet. Same for actors. If Tilda Swinton keeps appearing in your 9s and 10s, she gets a high person score and her unseen work floats to the top.

Streaming platforms could technically do this. They don't, because their recommendation goal is engagement and licensing cost management — not finding you the best Tilda Swinton film you haven't seen yet.

## Tuning the engines

The Config tab lets you control which engines run, exclude genres you never watch, set a minimum year cutoff, and filter by minimum TMDb rating. All preferences are stored locally in `SQLite` — no config files to maintain.

![filmpick config panel](/assets/filmpick-config.png)
*The Config panel — toggle recommendation engines, exclude genres, set year and rating floors. TMDb API key loaded from environment via `bioenv`.*

Toggle off "Surprise Me" if you don't want random picks. Exclude Horror if that's not your thing. Set the minimum year to 2000 if you only care about modern cinema. Every filter immediately affects what the Discover tab shows.

## Credentials — don't store them in plaintext

The app needs a [TMDb API key](https://developer.themoviedb.org/docs/getting-started). Option A is pasting it into the Config tab — it gets stored in the local `SQLite` database, which is fine for a local tool.

Option B, which I prefer: [bioenv](https://github.com/3h4x/bioenv) — biometric-protected env vars via macOS Touch ID + Keychain. The key never touches disk in plaintext.

```bash
bioenv set TMDB_API_KEY <your-tmdb-read-access-token>
eval "$(bioenv load)"   # Touch ID prompt, then:
pnpm dev
```

Environment variable takes priority over the database config. Small thing, but it matters.

The repo is at [github.com/3h4x/film-pick](https://github.com/3h4x/film-pick).

3h4x
