---
layout: post
title:  "Migration to Google Cloud Dns from different provider."
categories: tech
tags: [dns, gcp, python]
comments: True
---
Decision to pick DNS provider should be, in my opinion, based on currently used cloud environment. 
If you use AWS then `Route53`, GCP then `Cloud Dns`, etc. It's easier to manage it and audit then. 
Not the case for multicloud usage but most of the companies I worked for were using single cloud.

If DNS domain was registered before cloud adoption then your task might be to migrate DNS. Such migration is not 
uncommon and in this blog post I will write about changing `NS` records from `godaddy` to google `Cloud Dns`.

<!-- readmore -->

## DNS NS records

NS record delegates a DNS zone to use the given authoritative name servers. It usually have long TTL as changing it is 
not frequent and it's preventing frequent queries from clients.  
[More information in related RFC](https://tools.ietf.org/html/rfc1035#page-12)

You can check your current NS servers with `dig` command:
{% highlight yaml %}
dig +short NS cheezburger.com
{% endhighlight %}

## Migration plan

There is a [documentation](https://cloud.google.com/dns/docs/migrating) about migration.

Here is my plan: 
1. Replicate records from `goddady` to `Cloud Dns`
1. Lower TTL on `goddady` NS records 
1. Wait for `Cloud Dns` to have new records available
1. Check if all records are the same for those two providers
1. Change `goddady` NS records to point `Cloud Dns` ones
1. Wait for propagation

## Migration execution

- Unfortunately our provider didn't provide way to export records so it was manual job to 
create them in terraform.  
{% highlight terraform %}
resource "google_dns_managed_zone" "prod" {
  name     = "prod"
  project  = google_project.prod.project_id
  dns_name = "cheesburger.com."
}

#
# A
#
resource "google_dns_record_set" "a_cheesburger" {
  managed_zone = google_dns_managed_zone.prod.name
  project      = google_project.prod.project_id

  type = "A"
  ttl  = 300

  name    = google_dns_managed_zone.prod.dns_name
  rrdatas = ["5.5.5.5"]
}
{% endhighlight %}
- Unfortunately it's not possible to change TTL of NS record in `goddady`
- To check if records have propagated correctly and to avoid any human error I made a `python` script checking
if DNS records are matching for different resolvers.

To be able to use it you need to install additional `python` libraries:
{% highlight shell %}
pip install dnspython
pip install click
{% endhighlight %}
    
Here is a script:  
{% highlight python %}
#!/usr/bin/env python3
import socket

import dns.resolver
import click

# Dictionary with records to be checked
dns_records = {
    'A': [
        'cheezburger.com',
    ],
    'CNAME': [
        'icanhas.cheezburger.com',
    ],
    'TXT': [
        'cheezburger.com',
    ],
    'MX': [
        'cheezburger.com',
    ]
}

# DNS resolvers used to resolve records in dns_records dictionary 
resolver_cfl = dns.resolver.Resolver()
resolver_cfl.nameservers = ['1.1.1.1']
resolver_ggl = dns.resolver.Resolver()
resolver_ggl.nameservers = ['8.8.8.8']
# nameserver can be also DNS address like socket.gethostbyname('ns-cloud-a1.googledomains.com.')

resolvers = {
    'cfl': resolver_cfl,
    'ggl': resolver_ggl,
}

for record_type in dns_records:
    for record in dns_records[record_type]:
        click.secho(f'Checking {record} {record_type}', bold=True)
        record_result = {
            'cfl': [],
            'ggl': [],
        }

        for name, resolver in resolvers.items():
            for rdata in resolver.query(record, record_type):
                if record_type == 'A':
                    record_result[name].append(rdata.address)
                if record_type == 'CNAME':
                    record_result[name].append(rdata.target)
                if record_type == 'TXT':
                    record_result[name].append(rdata.strings)
                if record_type == 'MX':
                    record_result[name].append((rdata.exchange, rdata.preference))

        click.secho(f'CFL: {sorted(record_result["cfl"])}')
        click.secho(f'GGL: {sorted(record_result["ggl"])}')
        if sorted(record_result['cfl']) == sorted(record_result['ggl']):
            click.secho(u'All good. Records match!', bg='green')
        else:
            click.secho('Ups, records dont match', bg='red')
            raise Exception

        print()
{% endhighlight %}

When all records match we are ready for migration.
- Change NS records in `godaddy` to match your zone in GCP  
{% highlight yaml -%}
gcloud dns managed-zones describe prod --project prod-270011 --format json | jq .nameServers
{% endhighlight %}
- Wait for propagation periodically checking if NS record have changed:  
{% highlight yaml %}
watch dig +short NS cheezburger.com
{% endhighlight %}  
Worst case scenario: it will take longer than TTL set on current NS records. Be prepared for that. 
- Enjoy DNS in GCP!  

## Thoughts

Migrating DNS is not rocket science but needs to be executed with caution, especially for already used domains that 
are serving production traffic.  
Migrating DNSSEC is more complicated but is also out of the scope of this post.

I hope someone will find my execution plan and `python` snippet useful.

**Note:** I'm not affiliated in any way with [icanhas.cheezburger.com](https://icanhas.cheezburger.com) :hamburger:

3h4x