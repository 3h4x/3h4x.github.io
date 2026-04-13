FROM ruby:3.3-alpine

RUN apk add --no-cache build-base git

WORKDIR /srv/jekyll

COPY Gemfile Gemfile.lock ./
RUN bundle install

CMD bundle exec jekyll serve --drafts --trace --host 0.0.0.0
