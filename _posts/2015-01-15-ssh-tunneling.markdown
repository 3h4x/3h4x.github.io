---
layout: post
title:  "SSH tunneling classics"
date:   2015-01-15 17:17:12
categories: ssh tricks
comments: True
---
## Far, far away, behind NAT and firewall

Well you might heard this story or be in my shoes in the past.

Basically, you got ssh connection to a server but there is no internet and every service that you would like to connect
to is blocked. But if you got ssh then you good, no worries!

<!-- readmore -->
## Reverse

You need to install some packages on that poor and sad outdated server.
Well you might spend a month just doing aptitude download or yum download and then sending it over,
thinking about scripts that will automate downloading, sending and installing.
_STOP_! Let's do ssh tunnel!

### ssh -R

Example:

We want from remote host connect locally to TCP port :3142.
That traffic will be routed to apt.cacher.io to port 3142 via your computer.

`ssh $remote_host -R 3142:apt.cacher.io:3142`

Well if you did that you just logged to the remote server.
Now you can `netstat -ntlp` and check if you really have 127.0.0.1:3142 listening.
If so, then just tell apt where is the proxy:

`echo 'Acquire::http::Proxy "http://localhost:3142";' > /etc/apt/apt.conf.d/99proxy`

This is just an example but you can do same thing for any service out there.

## Straight

There is a service on that remote machine and you really want to sink your teeth in it.
But it listens only on localhost so there is no way to do your job comfortably or even there is no way to do anything at all.
But of course there is ssh to the rescue.

### ssh -L

Example:

We want to use 0xDBE, TOAD or any other IDE for DBA to connect to the remote database which is listening only on
localhost.

To achieve that we need to create a proxy that will route traffic from our machine to the remote machine DB port.
To be specific let's use 5432.

`ssh $remote_host -L 5432:localhost:5432`

This will open new port on your computer `netstat -ntlp` to check it of course. It's done.
You can treat remote database as if it were local.

## Socks

This one is pretty cool if you want to check quickly without much hassle if service is available from the internet.
There is one catch tho, you need shell access somewhere.

### ssh -D

Example:

So we got this web service, it's behind a proxy and someone in different city/country/universe says it does not work.

Okay, so let's prove that it really works!
`ssh $remote_host_in_djibouti -D 14141`
and then configure socks proxy in your favourite browser.

Now every website will be obtained from $remote_host_in_djibouti.

If it doesn't work... well it could be anything ;)
But if it works you can tell 'if it works from Djibouti than it works from everywhere' :D

## Useful flags

* -C - compress all data
* -f - ssh will go to background
* -i - pick file with private key
* -A - forward your authentication via ssh
* -X - forward X

and don't forget `man ssh`


> Bye bye, see you real soon!

3hx
