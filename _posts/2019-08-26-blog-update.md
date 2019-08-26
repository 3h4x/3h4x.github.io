---
layout: post
title:  "Updating this blog"
categories: blog
tags: [jekyll, liquid, docker]
comments: True
---
Hey!

I haven't been around here for quite some time. I know that you - random internet person - don't really care so let's get to the point.
My blog was created with simplicity in mind but when I've returned after break I had to do improvements.
<!-- readmore -->

### Where is Docker?

Oh come on! So me fascinated with containers and no Dockerfile here? This was a mistake that I could quickly fix.
Bang, [`Dockerfile`](https://github.com/3h4x/3h4x.github.io/blob/master/Dockerfile) and [`docker-compose.yaml`](https://github.com/3h4x/3h4x.github.io/blob/master/docker-compose.yaml) are here.
Now running `docker-compose up` and `jekyll` is up and running.  .

Yes!

Well not quite. First let's deal with problems.

### Jekyll redcarpet problem
```
Dependency Error: Yikes! It looks like you don't have redcarpet or one of its dependencies installed. In order to use Jekyll as currently configured, you'll need to install this gem. The full error message from Ruby is: 'cannot load such file -- redcarpet' If you run into trouble, you can find helpful resources at https://jekyllrb.com/help/!
```
When I started I chose `redcarpet` (unfortunately I cannot remember exact rationale behind picking it up) **but** it seems it's not default `markdown` render and is not in `docker` image.
Default one is [`kramdown`](https://jekyllrb.com/docs/configuration/markdown/#kramdown), let's go with that as it's already present and default for `jekyll`.

### Small updates

```
Deprecation: The 'gems' configuration option has been renamed to 'plugins'. Please update your config file accordingly.
```
Right! Let's follow instruction and update [`_config.yaml`](https://github.com/3h4x/3h4x.github.io/blob/c208e4308dc92df59eaa6a74a3cb6cb5a33b4713/_config.yml#L20)

{% raw %}
```
Liquid Warning: Liquid syntax error (line 105): [:dot, "."] is not a valid expression in "{{ .NetworkSettings.IPAddress }}" in /srv/jekyll/_posts/2015-04-02-mesos-dns.md
```
{% endraw %}
Gotcha. That's annoying and I wonder how I didn't see it in the past?

Here comes [`liquid`](https://shopify.github.io/liquid/)
> Safe, customer-facing template language for flexible web apps."  .

`Liquid` use double brackets for variables and {% raw %}[`{% raw %}`](https://shopify.github.io/liquid/tags/raw/){% endraw %} tag is needed to display it properly as just text.

Next!

### Improving readability

I look at `home` with posts list and thought ["there has to be a better way!"](https://www.youtube.com/watch?v=anrOzOapJ2E) and yes there is.  .
Adding some more space and utilizing `excerpt` instead of trimming post.

In `_config.yml` I have added [`excerpt_separator`](https://github.com/3h4x/3h4x.github.io/blob/c208e4308dc92df59eaa6a74a3cb6cb5a33b4713/_config.yml#L18).
Now by putting magic `<!-- readmore -->` in post I'm signaling what should be visible in posts list. This change is giving me a lot of power and now I'm satisfied with presentation layer.

I also did some small html changes to templates. Not really worth mentioning and pointing to repo.
### Using drafts to write new posts

When writing new post in the past I just ignored it and didn't commit it to `git` repository. After reading `jekyll` documentation it became obvious that there's native way to do it - [drafts](https://jekyllrb.com/docs/posts/#drafts).

I have added `_drafts` to `.gitignore` and modified `CMD` of `docker` container with `--drafts` to actually display drafts. It's pretty clever and display post date when it was modified.
Exactly what I needed.

### Usage of tags

I used `tags` for every post that I have written in the past but it never occurred to me that they are hidden. So today I've fixed `tags` and they are displayed at bottom of my blog. There's also new menu in navigation bar `/tags` which list all posts enumerated by tags. [Code for displaying it was really simple.](https://github.com/3h4x/3h4x.github.io/blob/master/tags.md)


## That's all for today!

It's pretty simple with `jekyll`, I'm really glad that I went with it. `jekyll` is really easy to setup, modify and update while `github pages` allow me to "outsource" continous deployment.
Also starting simple and then improving is good strategy in this case. Why wasting time for features that might not be used in future?

Obviously my whole blog is in [github repository](https://github.com/3h4x/3h4x.github.io). All related changes are committed and public. You can look there any time you want!

I got new posts in plans! This blog is "not yet another blog dead" haha.


3h4x
