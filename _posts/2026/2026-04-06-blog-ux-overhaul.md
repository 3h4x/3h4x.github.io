---
layout: post
title:  "Overhauling a Jekyll blog — dark mode, code blocks, and all the small things"
categories: tech
tags: [jekyll, css, liquid, github-pages, devtools]
comments: True
---

This blog has been running on Jekyll since 2015. The content changed, the stack around it changed, but the blog itself? Same minima theme, same default code blocks, same flat archive page. It was time to fix that.

<!-- readmore -->

## What was wrong

Nothing was *broken*, but the UX had accumulated a lot of friction:

- Code blocks had a pale lavender background (`#eef`) that made syntax hard to read
- No dark mode — in 2026!
- The archive page was a flat bullet list with no grouping
- The tags page was a wall of headings, one per tag, most with a single post
- No reading time indicator
- No previous/next navigation between posts
- The site description still said "Container orchestration, observability tools..." — which hadn't been accurate for years

None of these individually are dealbreakers. But stacked together, they make the difference between a blog that feels maintained and one that feels abandoned.

## Dark mode with a toggle

The approach: CSS custom properties for all colors, a `data-theme` attribute on `<html>`, and a small script that reads from `localStorage` with a fallback to `prefers-color-scheme`.

```css
:root,
[data-theme="light"] {
  --bg-color: #fdfdfd;
  --text-color: #111;
  --code-block-bg: #1e1e2e;
}

[data-theme="dark"] {
  --bg-color: #1a1b26;
  --text-color: #c9d1d9;
  --code-block-bg: #13141c;
}
```

The critical piece is avoiding FOUC (flash of unstyled content). The theme detection script goes in `<head>`, before any rendering:

```html
<script>
  (function() {
    var saved = localStorage.getItem('theme');
    var preferred = saved ||
      (window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', preferred);
  })();
</script>
```

The toggle itself is a button in the header nav — moon for "switch to dark", sun for "switch to light". Persists across pages and sessions.

## Code blocks

Swapped the default minima code styling for a Catppuccin Mocha-inspired dark theme. Code blocks are always dark regardless of the site theme — dark-on-dark reads well in both modes, and switching syntax themes on toggle felt jarring in testing.

```scss
pre {
  background-color: var(--code-block-bg);
  color: var(--code-block-text);
  border-radius: 8px;
  padding: 1em 1.25em;
  line-height: 1.6;
}
```

Inline code got a distinct treatment: pink text on a subtle gray background. Makes `code` references pop without being distracting.

On wider screens, code blocks extend slightly beyond the content column with negative margins. Small detail, but it gives them visual weight and separates them from the prose.

## Archive grouped by year

Before: a flat list of 22 posts sorted by date. After: posts grouped under year headings with post counts.

{% raw %}
```
assign postsByYear = site.posts
    | group_by_exp: "post", "post.date | date: '%Y'"

for year in postsByYear
  <h2>{{ year.name }} <span class="count">{{ year.items.size }}</span></h2>
  ...
endfor
```
{% endraw %}

Jekyll's `group_by_exp` filter does the heavy lifting. Each year section shows the month and day alongside the title — tabular-nums in the CSS keeps the dates aligned.

## Interactive tag cloud

The old tags page listed every tag as its own `<h3>` with a bullet list of posts underneath. With 47 tags (most used only once), that's a lot of scrolling for very little discovery.

The new version has a tag cloud at the top — pill-shaped buttons with post counts. Click one, it highlights and shows the posts inline below. Click again to collapse. The URL updates to `#tagname` so links from post headers still work.

No JavaScript framework, no build step. Just `<template>` elements pre-rendered by Jekyll and cloned into the DOM on click. The entire interaction is ~25 lines of vanilla JS.

## The smaller things

**Reading time** — word count divided by 200, shown next to the date on both the homepage and post headers. Jekyll's `number_of_words` filter handles it in Liquid.

**Previous/Next navigation** — `page.previous` and `page.next` are built-in Jekyll variables. Two-column layout at the bottom of each post, after the related posts section.

**Skip-to-content link** — hidden until you Tab into it. One of those accessibility basics that's easy to forget on a personal blog.

**Footer cleanup** — replaced the old multi-column minima footer with a single-row layout: site title, tagline, and social icons.

**Pagination** — was showing just the current page number. Now shows all pages with `<<` / `>>` arrows, generated from `paginator.total_pages`.

**Related posts ranked by tag overlap** — the `jekyll-tagging-related_posts` plugin scores related posts by tag rarity, which is fine until all your tags appear the same number of times. I wrote a custom plugin that prioritizes posts sharing the *most* tags first, then falls back to rarity weighting, then date. A post sharing 3 tags with yours will always rank above one sharing 1, which is what you'd expect.

## GitHub Actions instead of built-in Pages

One gotcha: GitHub Pages runs Jekyll in safe mode — custom plugins in `_plugins/` are ignored. So the related posts plugin, which is the whole point, wouldn't work on the live site.

The fix: switch from GitHub's built-in Jekyll builder to a GitHub Actions workflow that builds the site ourselves. The workflow is straightforward:

```yaml
- name: Setup Ruby
  uses: ruby/setup-ruby@v1
  with:
    ruby-version: '3.3'
    bundler-cache: true

- name: Build site
  run: bundle exec jekyll build
  env:
    JEKYLL_ENV: production
```

Then deploy with `actions/deploy-pages`. In **Settings → Pages → Source**, pick "GitHub Actions" instead of "Deploy from a branch". That's it — full plugin support, same auto-deploy on push.

## The Ruby detour

Running Jekyll locally in 2026 on macOS required updating the Gemfile from Jekyll 4.2 to 4.4 — the system Ruby (2.6) is ancient, and Homebrew ships Ruby 4.0 which broke the old `bundler` lockfile. Once past that, `jemoji` was missing from the Gemfile despite being in `_config.yml`. Standard Jekyll dependency archaeology.

Added `livereload: true` and `port: 4001` to `_config.yml` so `bundle exec jekyll serve` just works without flags.

## What's next

The blog is still Jekyll and I'm keeping it that way. The content is what matters, and Jekyll stays out of the way. But the reading experience should match the effort that goes into the posts — and now it does.

3h4x
