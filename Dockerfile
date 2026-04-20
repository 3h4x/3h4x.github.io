FROM ruby:3.3-alpine

RUN apk add --no-cache build-base git

WORKDIR /srv/jekyll

COPY Gemfile Gemfile.lock ./
RUN bundle install

EXPOSE 4001 35729

CMD ["bundle", "exec", "jekyll", "serve", "--host", "0.0.0.0", "--livereload", "--livereload-ignore", ".playwright-mcp/*", "--force_polling"]
