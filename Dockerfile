FROM jekyll/jekyll:4.0

RUN gem install jekyll-seo jekyll-feed github-pages minima jemoji jekyll-tagging-related_posts rouge

CMD jekyll serve --drafts --trace
