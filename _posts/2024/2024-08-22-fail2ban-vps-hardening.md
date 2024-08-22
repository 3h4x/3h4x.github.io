---
layout: post
title: "Fail2ban and firewall hardening on a public-facing VPS"
categories: tech
tags: [security, devtools, deployment]
comments: True
---

The first time I ran `grep "Failed password" /var/log/auth.log | wc -l` on a new VPS, the number was embarrassing. Thousands of failed SSH attempts within 48 hours of provisioning. Bots scan the entire IPv4 space continuously — your server is being probed within minutes of getting a public IP. Let's do something about it.

<!-- readmore -->

## Starting point: UFW basics

Before `fail2ban`, you need a sane firewall. UFW (Uncomplicated Firewall) wraps `iptables` in a way that doesn't require a PhD:

```bash
apt install ufw

ufw default deny incoming
ufw default allow outgoing

ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS

ufw enable
```

That's the baseline. Deny everything inbound except what you explicitly allow. Outbound is wide open — your apps need to make requests.

One thing to be careful about: run `ufw allow 22/tcp` before `ufw enable` or you'll lock yourself out. Ask me how I know.

For apps that only need to be reached from `localhost` (PM2 apps behind nginx), don't open their ports at all. nginx talks to them on `127.0.0.1:3456` — UFW never sees that traffic. The only ports external traffic needs are `80` and `443`.

## Why fail2ban

UFW is static. It can block IPs, but it doesn't learn. Fail2ban watches log files, detects attack patterns, and dynamically bans IPs that cross a threshold. It's reactive rate limiting at the network layer.

```bash
apt install fail2ban
```

Fail2ban uses "jails" — a jail is a combination of:
- A log file to watch
- A regex pattern to match failures
- Thresholds (how many failures, over what time window)
- A ban action (what to do with the offending IP)

## SSH jail

The default SSH jail is almost good enough:

```ini
# /etc/fail2ban/jail.local
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
banaction = ufw

[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
backend = %(sshd_backend)s
maxretry = 3
bantime  = 24h
```

I tighten it: 3 failures in 10 minutes means a 24-hour ban. The default 10 minutes is too lenient for brute force attempts. And I use `banaction = ufw` to have fail2ban manage bans through UFW rather than directly via `iptables` — they play nicely together.

Restart and check status:

```bash
systemctl restart fail2ban
fail2ban-client status sshd
```

```
Status for the jail: sshd
|- Filter
|  |- Currently failed: 2
|  |- Total failed:     1847
|  `- File list:        /var/log/auth.log
`- Actions
   |- Currently banned: 12
   |- Total banned:     342
   `- Banned IP list:   45.227.255.190 198.199.64.217 ...
```

342 IPs banned in a month. All automated probing, never a legitimate user.

## Nginx jail

SSH isn't the only attack surface. HTTP gets hammered too — vulnerability scanners, WordPress login brute forces (even if you don't run WordPress), path traversal attempts. Create a custom jail:

```ini
# /etc/fail2ban/jail.local (continued)
[nginx-limit-req]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/error.log
maxretry = 10
findtime = 1m
bantime  = 10m

[nginx-botsearch]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log
filter   = nginx-botsearch
maxretry = 2
findtime = 1m
bantime  = 1h
```

The `nginx-botsearch` filter catches requests for known vulnerable paths — WordPress admin, PHPMyAdmin, `.env` files, etc. The filter definition:

```ini
# /etc/fail2ban/filter.d/nginx-botsearch.conf
[Definition]
failregex = ^<HOST> -.*"(GET|POST|HEAD).*/(wp-admin|wp-login|phpmyadmin|\.env|config\.php|xmlrpc).*" (404|403|400)
ignoreregex =
```

Any IP that probes more than twice in a minute gets banned for an hour. These aren't legitimate users — no real user requests `/wp-admin/` twice in 60 seconds.

## Custom app jail

You can jail any application that writes logs. Say you have an API with authentication and you want to ban IPs that fail auth repeatedly:

```ini
# /etc/fail2ban/jail.local
[myapp-auth]
enabled  = true
port     = http,https
logpath  = /home/deploy/.pm2/logs/api-error.log
filter   = myapp-auth
maxretry = 10
findtime = 5m
bantime  = 1h
```

```ini
# /etc/fail2ban/filter.d/myapp-auth.conf
[Definition]
failregex = ^.*"ip":"<HOST>".*"event":"auth_failed"
ignoreregex =
```

This requires your app to log auth failures in a consistent format with the IP address. Worth doing. Once you have structured logging (even just JSON to a file), you can jail against almost any pattern.

## Rate limiting in nginx

Fail2ban bans IPs reactively — after the attack has already happened. Nginx rate limiting is proactive, at the HTTP layer:

```nginx
# /etc/nginx/nginx.conf
http {
    # Define rate limit zones
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;

    # ...
}
```

```nginx
# In your server block
location /api/ {
    limit_req zone=api burst=20 nodelay;
    limit_req_status 429;
    proxy_pass http://localhost:3333;
}

location /api/auth/login {
    limit_req zone=login burst=3 nodelay;
    limit_req_status 429;
    proxy_pass http://localhost:3333;
}
```

The `api` zone allows 10 req/s with a burst of 20. The `login` zone is much tighter: 5 requests per minute, burst of 3. A human logging in isn't going to hit that limit. An automated brute force will, and they'll get `429 Too Many Requests` before fail2ban even sees a log line.

`limit_req_zone` uses `$binary_remote_addr` (4 bytes per IPv4, 16 bytes per IPv6) as the key, stored in a 10MB shared memory zone. That's enough for ~160k IPv4 addresses or ~40k IPv6 addresses tracked simultaneously.

## What the attack logs actually look like

This is from a real week of nginx access logs:

```
45.227.255.190 - - [15/Aug/2024:03:12:44] "GET /wp-login.php HTTP/1.1" 404
45.227.255.190 - - [15/Aug/2024:03:12:44] "GET /wp-admin/ HTTP/1.1" 404
45.227.255.190 - - [15/Aug/2024:03:12:45] "GET /xmlrpc.php HTTP/1.1" 404
# Banned after 2 hits

180.101.88.204 - - [15/Aug/2024:04:23:01] "GET /.env HTTP/1.1" 404
180.101.88.204 - - [15/Aug/2024:04:23:02] "GET /.git/config HTTP/1.1" 404
# Banned

134.209.82.13 - - [15/Aug/2024:11:45:23] "POST /api/auth/login HTTP/1.1" 401
134.209.82.13 - - [15/Aug/2024:11:45:24] "POST /api/auth/login HTTP/1.1" 401
# ... 47 more attempts in 30 seconds
# Banned by rate limiter first, then fail2ban
```

The WordPress probe is fully automated — no human is typing `/wp-login.php` on a Node.js API server. The `.env` and `.git/config` probes are credential harvesters. The login brute force is an obvious credential stuffing attack.

Without fail2ban these would be noise in the logs. With it, they're banned IPs that can't waste your bandwidth or server resources.

## Monitoring bans

```bash
# Current status for all jails
fail2ban-client status

# Specific jail detail
fail2ban-client status sshd

# Manually ban an IP
fail2ban-client set sshd banip 1.2.3.4

# Manually unban (for when you ban yourself)
fail2ban-client set sshd unbanip 1.2.3.4

# Watch the fail2ban log live
tail -f /var/log/fail2ban.log
```

I also have this going into Loki via Promtail so I can query it from Grafana:

```
{job="journald", unit="fail2ban.service"} |~ "Ban"
```

A quick count over time shows whether attack patterns are changing — sudden spike in bans usually means someone's running a targeted scan.

## SSH port: security theater?

Moving SSH to a non-standard port (say, `2222`) dramatically reduces log noise — bots scan port 22. But it's not real security. Port scanners will find `2222` too, just slower. If you're already running fail2ban, the bots on port 22 are banned after 3 attempts anyway.

I keep SSH on port 22. Less configuration, no risk of forgetting which port I used, and fail2ban handles the noise. But if log noise bothers you, a port change is a quick win.

## The result

After setting all this up: auth.log stays quiet. Nginx access logs still show probe attempts, but they're banned within seconds and never touch my application. The fail2ban dashboard in Grafana is almost boring — which is exactly what you want from security tooling.

None of this is exotic. UFW + fail2ban + nginx rate limits is commodity security hygiene. But it's the difference between a server that's actively defended and one that's just hoping for the best.

3h4x
