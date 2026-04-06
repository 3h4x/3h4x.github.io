---
layout: page
title: Archive
---

<div class="archive">
  {%- assign postsByYear = site.posts | group_by_exp: "post", "post.date | date: '%Y'" -%}
  {%- for year in postsByYear -%}
  <div class="archive-year">
    <h2 class="archive-year-title">{{ year.name }} <span class="archive-count">{{ year.items.size }}</span></h2>
    <ul class="archive-list">
      {%- for post in year.items -%}
      <li class="archive-item">
        <span class="archive-date">{{ post.date | date: "%b %-d" }}</span>
        <a href="{{ post.url | relative_url }}">{{ post.title | escape }}</a>
      </li>
      {%- endfor -%}
    </ul>
  </div>
  {%- endfor -%}
</div>
