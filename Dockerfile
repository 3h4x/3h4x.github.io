FROM jekyll/jekyll:3.8

RUN gem install jekyll-sitemap redcarpet

CMD jekyll serve
