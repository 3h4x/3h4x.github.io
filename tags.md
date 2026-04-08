---
layout: page
title: Tags
permalink: /tags/
sitemap: false
robots: noindex
---

<div class="tag-cloud">
  {%- assign sorted_tags = site.tags | sort -%}
  {%- assign max_count = 0 -%}
  {%- for tag in sorted_tags -%}
    {%- if tag[1].size > max_count -%}{%- assign max_count = tag[1].size -%}{%- endif -%}
  {%- endfor -%}
  {%- for count in (1..max_count) reversed -%}
    {%- for tag in sorted_tags -%}
      {%- if tag[1].size == count -%}
    <button class="tag-pill" data-tag="{{ tag[0] }}" onclick="toggleTag(this)">{{ tag[0] }} <span class="tag-count">{{ tag[1].size }}</span></button>
      {%- endif -%}
    {%- endfor -%}
  {%- endfor -%}
</div>

<div class="tag-results" id="tag-results">
  <p class="tag-hint">Click a tag to see posts</p>
</div>

{%- assign sorted_tags = site.tags | sort -%}
{%- for tag in sorted_tags -%}
<template data-tag="{{ tag[0] }}">
  {%- for post in tag[1] -%}
  <li>
    <span class="archive-date">{{ post.date | date: "%b %-d, %Y" }}</span>
    <a href="{{ post.url | relative_url }}">{{ post.title | escape }}</a>
  </li>
  {%- endfor -%}
</template>
{%- endfor -%}

<script>
function toggleTag(btn) {
  var tag = btn.getAttribute('data-tag');
  var results = document.getElementById('tag-results');
  var active = document.querySelector('.tag-pill.active');

  if (active && active !== btn) active.classList.remove('active');

  if (btn.classList.contains('active')) {
    btn.classList.remove('active');
    results.textContent = '';
    var hint = document.createElement('p');
    hint.className = 'tag-hint';
    hint.textContent = 'Click a tag to see posts';
    results.appendChild(hint);
    history.replaceState(null, '', '/tags/');
    return;
  }

  btn.classList.add('active');
  var tmpl = document.querySelector('template[data-tag="' + tag + '"]');
  results.textContent = '';
  var heading = document.createElement('h3');
  heading.textContent = tag;
  results.appendChild(heading);
  var ul = document.createElement('ul');
  ul.className = 'tag-post-list';
  ul.appendChild(tmpl.content.cloneNode(true));
  results.appendChild(ul);
  history.replaceState(null, '', '#' + tag);
}

(function() {
  var hash = location.hash.replace('#', '');
  if (hash) {
    var btn = document.querySelector('.tag-pill[data-tag="' + hash + '"]');
    if (btn) { toggleTag(btn); btn.scrollIntoView({ block: 'nearest' }); }
  }
})();
</script>
