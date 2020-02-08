---
layout: page
title: Tags
permalink: /tags/
---

<div class="post">

  <article class="post-content">
    {% assign sorted_tags = site.tags | sort %}

    {% for tags in sorted_tags %}
      <h3>{{ tags[0] }}</h3>
      <ul>
        {% for post in tags[1] %}
          <li><a href="{{ post.url }}">{{ post.title }}</a></li>
        {% endfor %}
      </ul>
    {% endfor %}

  </article>

</div>
