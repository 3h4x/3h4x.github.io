---
layout: post
title:  "Jekyll upgrade to version 4.0.0 with theme change"
categories: jekyll
tags: [jekyll, github-pages]
comments: True
---

Recently I've written a [post about updating my blog](https://3h4x.github.io/jekyll/2019/08/26/blog-update.html).
As I have a lot of ideas for new posts, it's natural that I wanted to be sure `jekyll` is correct technology for me.
I did some checkups and yeah! `jekyll` is the best technology for me right now.   
Github support, development, `git push` to deploy changes without any additional configuration or component is making it 
pointless to migrate away from it.

This post will be short but for me it touches important topic of supporting and maintaing technology used to render this
blog.

<!-- readmore -->

## Changes

### Jekyll upgrade
Letest [`jekyll` 4.0.0](https://github.com/jekyll/jekyll/releases/tag/v4.0.0) has been released last year.
It has introduced many changes, fixes and improvements. Literally so many changes that it reminds me of reading 
`kubernetes` changelogs ;)  
For me if it renders fine, then it's good to go. I have already made changes to `Dockerfile` and now I'm waiting for
[`github-pages` to upgrade version](https://pages.github.com/versions/).  

So my blog is officially ready for new `jekyll` version. For me this is a part of process to support technology 
that is being used to render. 

### Using theme
When I started this blog in 2015 `jekyll` was a little bit different than today, my mindset was a little bit different.
I wanted to customize everything, I felt like it's a necessary step to stand out, be cool :D.  
Today I always prefer simplicity. Days go by and my `scss` written in 2015 got old and didn't provide functionality
that themes for `jekyll` have out of the box. I have noticed some rendering errors on mobiles, lack of _hamburger_,
alignment problems and such.  

All of this would have never happened if I would configure theme. Theme would get updated and so would my blog. By
adding customization I only added layer of troubles for me.  
That's why I decided to drop all of my custom css and go with default. 

Less technology problems more time for content writing!

## Conclusion

If you work in IT then it should be a habit for you to think about possible upgrades and dedicate time to do them. 
`github` can help a little bit with watching releases option. I love it!  
It's not like I'm upgrading `prod` cluster of `kubernetes`, with my blog I can recklessly upgrade `jekyll` version and 
easily rollback my `dev` environment if something goes wrong.  

Second conclusion is if you go with default then you will never have to "adjust" your code to newer releases. I know
that it's not possible everywhere **but** I know that my choice to customize `css` while starting this blog was a 
mistake. The bigger the project is, the bigger mistake it can be.

Simplicicty over complexity.  
[Click to see commit which changed my blog](https://github.com/3h4x/3h4x.github.io/commit/374e1b80c2e74dc47600738a674682f5b2a7ffc9) 

3h4x


