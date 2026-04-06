export PATH := /opt/homebrew/opt/ruby/bin:$(PATH)

.PHONY: serve build install

serve:
	bundle exec jekyll serve

build:
	JEKYLL_ENV=production bundle exec jekyll build

install:
	bundle install
