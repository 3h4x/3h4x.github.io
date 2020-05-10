---
layout: post
title:  "Sentry 9 - fix for PagerDuty legacy integration."
categories: tech
tags: [sentry, pagerduty]
comments: True
---

Recently I've been involved in investigating why `PagerDuty` integration with `sentry` 9.1.1 doesn't work.
Same thing was happening to 9.1.2 version. The problem was not visible in UI but in logs such error message was repeating:
> 19:13:04 [INFO] sentry.plugins.pagerduty: notification-plugin.notify-failed. (plugin=u'pagerduty' error=u'Error Communicating with PagerDuty (HTTP 400): Event object is invalid')

No incoming event on PagerDuty side assured me that this problem is real.

<!-- readmore -->

## Problem investigation

It's clear that `Sentry` `PagerDuty` plugin is using APIv1 because [client.py](https://github.com/getsentry/sentry-plugins/blob/7e192d69cea047bf47adbf491c8329d9d4fb3ae2/src/sentry_plugins/pagerduty/client.py#L10-L11) 
is using [https://events.pagerduty.com/generic/2010-04-15/create_event.json](https://events.pagerduty.com/generic/2010-04-15/create_event.json) url as integration endpoint.  

Error we get in logs has 400 HTTP code:
> 19:13:04 [INFO] sentry.plugins.pagerduty: notification-plugin.notify-failed. (plugin=u'pagerduty' error=u'Error Communicating with PagerDuty (HTTP 400): Event object is invalid')

Related [documentation](https://developer.pagerduty.com/docs/events-api-v1/trigger-events/) on `PagerDuty`.
> If the event is improperly formatted, a 400 Bad Request will be returned.

Quick search on `github` revealed other people struggling with same [issue #356](https://github.com/getsentry/sentry-plugins/issues/356)  
Conversation is locked unfortunately.

## Immediate fix

TLDR: docker image `cloudposse/sentry:9.1.3`

Some more search revealed that one fix [(PR 469)](https://github.com/getsentry/sentry-plugins/pull/469) to `PagerDuty` was merged to master but never released as a version.
This problem could possibly be easily fixed by just changing two lines in PagerDuty plugin. Such change should alleviate the problem.
I created repository [cloudposse/sentry](https://github.com/cloudposse/sentry) with [Dockerfile](https://github.com/cloudposse/sentry/blob/master/Dockerfile) 
that just replace affected `PagerDuty` python file.  
After building and testing [cloudposse/sentry:9.1.3](https://hub.docker.com/layers/cloudposse/sentry/9.1.3/images/sha256-a951a05c6438a0e4e5b35a9cffbc08bcbbee3c485ea0241e4d0f3ce70905f34e?context=repo) 
it turned out that events were correctly sent to `PagerDuty` :relieved:

## Root cause
Our [request](https://github.com/getsentry/sentry-plugins/blob/7e192d69cea047bf47adbf491c8329d9d4fb3ae2/src/sentry_plugins/pagerduty/client.py#L48-L57) sent to `PagerDuty` is the culprit.
{% highlight python %}
            {
                'event_type': event_type,
                'description': description,
                'details': details,
                'incident_key': incident_key,
                'client': client or self.client,
                'client_url': client_url or absolute_uri(),
                'contexts': contexts,
            }
{% endhighlight %}
But what is exactly wrong with it?

I spinned up testing `sentry` installation with `docker-compose`. Added volume on `PagerDuty` plugin for debug and simply logged event sent to `PagerDuty` API.
{% highlight python %}
{'contexts': 
  [{'text': 'Issue Details', 'href': u'http://localhost:9000/sentry/internal/issues/1/?referrer=pagerduty_plugin', 'type': 'link'}], 
  'incident_key': 1L, 
  'description': u'This is an example Python exception', 
  'event_type': 'trigger', 
  'details': {
      'project': u'Internal',
      'release': None, 
      'url': u'http://localhost:9000/sentry/internal/issues/1/?referrer=pagerduty_plugin', 
      'culprit': u'raven.scripts.runner in main', 
      'platform': u'python', 
      'event_id': u'd9e0399f5fd041fe840dc1a5ce3d424c', 
      'tags': {'level': u'error', 'url': u'http://example.com/foo', 'sentry:user': u'id:1', 'os.name': u'Windows 8', 'browser': u'Chrome 28.0.1500', 'browser.name': u'Chrome'}, 
      'datetime': '2020-05-10T09:14:59.127000Z'
  }
}
{% endhighlight %}

What draws my attention is `'incident_key': 1L,` - it's of type `long` (`Python3` only have `int` as `long` and `int` was unified).
What `six.text_type` do is it change this variable to `str`.  
After fix `incident_key` changed to `unicode` type.   
Sending an event with that change works flawlessly.

From `PagerDuty` docs we know that `incident_key` must be string.  
The issue was happening because `sentry` was sending `json` event with integer for `incident_key`.  

Request is sent by `session` (`from sentry.http import build_session`) which is part of `sentry` and is out of scope of my investigation.  
If one want to follow then I'd [start here](https://github.com/getsentry/sentry/blob/master/src/sentry/http.py#L67)

## Conclusion

Even though the change is rather simple it might be not easy to get it. `Sentry` is big product with a lot of moving parts.  
Debugging in `docker-compose` is not the easiest thing but it helped me to understand what went wrong and what exactly this fix does.  
Root cause investigation was done only "for fun". Issue was fixed before that but this allowed me to created this post so one can follow debugging path.  

What's also worth to note is that closing `github` issues and restricting commenting does not help community. 

3h4x