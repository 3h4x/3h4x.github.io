BUNDLE := /opt/homebrew/opt/ruby/bin/bundle

.PHONY: serve build install

serve:
	$(BUNDLE) exec jekyll serve --livereload

build:
	JEKYLL_ENV=production $(BUNDLE) exec jekyll build

install:
	$(BUNDLE) install
