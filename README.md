# 3h4x.github.io

https://3h4x.github.io

YAB — Jekyll blog on GitHub Pages. Posts live in `_posts/YYYY/`, assets in `assets/images/`.

## Dev

```sh
docker compose up -d   # serves on http://localhost:4001 with livereload
docker compose logs -f jekyll
docker compose down
```

Bare-metal `bundle exec jekyll serve` works too but the Gemfile.lock pins `bundler 4.0.8` which system Ruby 2.6 doesn't ship — use Docker.

## New post

Create `_posts/YYYY/YYYY-MM-DD-slug.md` with front matter:

```yaml
---
layout: post
title: "…"
categories: tech
tags: [...]
comments: True
---
```

Use `<!-- readmore -->` to split intro from body. Images go under `assets/images/<slug>/`.
