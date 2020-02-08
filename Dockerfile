FROM jekyll/jekyll:4.0

RUN gem install jekyll-sitemap jekyll-seo jekyll-feed github-pages minima

CMD jekyll serve --drafts --trace
