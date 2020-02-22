FROM jekyll/jekyll:4.0

RUN gem install jekyll-seo jekyll-feed github-pages minima jemoji

CMD jekyll serve --drafts --trace
