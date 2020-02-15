---
layout: post
title:  "Fighting Google Analytics bounce rate"
categories: jekyll
tags: [jekyll, google-analytics, liquid]
comments: True
---

More and more updates on my blog made me look into another aspect of internet blog which is monitoring web traffic.
I have `google analytics` enabled since the beginning but recently I have also added `bing` and `yandex`. `Duckduckgo` 
which is my main search engine don't have webmaster tools. To be fair probably just `google` cover over 90% of search traffic 
so any additionals have small impact.

When I looked into `google analytics` I saw bounce rate 100% on some acquisition types and time spent 0 seconds.  
After some investigation I have both answer and way to improve that.

<!-- readmore -->

## Bounce rate

> A bounce is a single-page session on your site. In Analytics, a bounce is calculated specifically as a session that triggers only a single request to the Analytics server, such as when a user opens a single page on your site and then exits without triggering any other requests to the Analytics server during that session.  
> Bounce rate is single-page sessions divided by all sessions, or the percentage of all sessions on your site in which users viewed only a single page and triggered only a single request to the Analytics server.  
> These single-page sessions have a session duration of 0 seconds since there are no subsequent hits after the first one that would let Analytics calculate the length of the session. 

[More documentation from google docs](https://support.google.com/analytics/answer/1009409?hl=en) 

Let me put it in other words. A bounce is when a user navigate to a page like [https://3h4x.github.io/](https://3h4x.github.io/), look at it and 
close the tab. It doesn't matter if page was opened for 1 second or 10 hours, it still counts as 0 seconds as `google analytics`
can't calculate session duration without another click.

I think now it's clear what a bounce is. 

### Tag usage
This website is content focused and I don't mind people looking at one specific post and end journey there. 
But, in my opinion, every blog is specific and content provided is somewhat similar. In `jekyll` similar content can be
explored with tag usage.

Starting this blog I have used tags and created [tags page](/tags/). Even though every post have tags I never paid 
much attention to it.  
For example currently I see bounce rate 100% on direct entries. I guess that someone bookmarked specific 
post and is comming back to it. I believe that adding tag links on bottom of the post can somewhat help high bounce 
rate. This post have tag [`jekyll`](/tags/#jekyll) and if you are interested in it, then nothing should stop you
from exploring related content.

The more content with same tag I will have, the better the outcome of this approach will be.

[This commit](https://github.com/3h4x/3h4x.github.io/commit/eb657b044e57b9bc57dbe7cfa51888ee81aa89f8) contains all 
changes that I had to do to display tags on the bottom. It ain't much but it's honest work.

### Event tracking
Another thing related to bounce rates are events. 

> Events are user interactions with content that can be measured independently from a web-page or screen load. Downloads, link clicks, form submissions, and video plays are all examples of actions you might want to analyze as Events.

Some people incorporate practices like "read more" buttons that executes `js` in middle of a post to see if a 
person was engaged with the content. I'm not big a fan of that because it changes what bounce actually is. For me it's 
more worth to see whole blog post in one go. This brings better user expierience and uninterrupted reading.

In the future I might incorporate some event tracking but for now I want to see how change in tags display will change
current statistics. 

There are also some considerations for event tracking that one should be aware of:
> In general, a "bounce" is described as a single-page session to your site. In Analytics, a bounce is calculated specifically as a session that triggers only a single GIF request, such as when a user comes to a single page on your website and then exits without causing any other request to the Analytics server for that session. However, if you implement Event measurement for your site, you might notice a change in bounce rate metrics for those pages where Event measurement is present. This is because Event measurement, like page measurement is classified as an interaction request.  
> **It's important to keep in mind that any implementation of Event measurement that automatically executes on page load will result in a zero bounce rate for the page.**

[Read more docs about event tracking](https://support.google.com/analytics/answer/1033068?hl=en#Implementation)

## Conclusion

High bounce rate is something that might be automatically considered as bad but it shouldn't be. It's just a metric
and one has to know how it's calculated. My blog is not seeling anything. I don't need to force engagment, my content should.  
I think I'm fighting it in the right way, without changing what bounce rate actually is. Eventually more content will 
decrease bounce rate for some acquisition types but I also understand some cases where it will never go down. 

3h4x