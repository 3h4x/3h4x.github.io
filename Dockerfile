FROM jekyll/jekyll:3.8

RUN gem install jekyll-sitemap

CMD jekyll serve --drafts
