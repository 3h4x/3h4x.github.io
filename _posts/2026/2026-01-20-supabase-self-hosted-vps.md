---
layout: post
title: "Self-hosting Supabase on a VPS — what you actually need"
categories: tech
tags: [supabase, docker, database, devtools]
comments: True
---

Supabase Cloud is genuinely good. Managed Postgres, row-level security, Auth with social providers, Realtime subscriptions, Storage — all wired up, all maintained by someone else. The free tier is generous. So why would anyone self-host it? Cost, mostly. And control. And the fact that your data isn't sitting on someone else's hardware if that matters to you. Here's what actually running Supabase on a VPS looks like, past the "just run docker-compose" step.

<!-- readmore -->

## Why self-host at all

The Supabase free tier gives you 500MB database, 1GB file storage, and 50,000 MAU for Auth. Fine for side projects, not fine when you scale. Their Pro plan is $25/month per project, and most usage-based pricing kicks in fast if you have real traffic.

On a VPS you're already paying for (say, a Hetzner AX41 at €34/month or a Contabo box), running Supabase costs essentially nothing extra. You get unlimited database size (within disk), unlimited Auth users, and full control over Postgres extensions, RLS policies, and backup schedules.

The trade-off: you own maintenance. Postgres version upgrades, security patches, monitoring, backups — that's you now. If you're already running a VPS with other services, the operational overhead is minimal. If you've never run Postgres in production, think twice.

## The Docker Compose setup

Supabase publishes an official self-hosted Docker Compose config. Clone it:

```bash
git clone --depth 1 https://github.com/supabase/supabase
cd supabase/docker
cp .env.example .env
```

Edit `.env` — the required changes:

```bash
# Generate these properly, don't use examples
POSTGRES_PASSWORD=<strong-password>
JWT_SECRET=<at-least-32-char-random-string>
ANON_KEY=<generated-jwt-using-JWT_SECRET>
SERVICE_ROLE_KEY=<generated-jwt-using-JWT_SECRET>

# Your VPS public IP or domain
SITE_URL=https://your-domain.com
API_EXTERNAL_URL=https://your-domain.com
```

The `ANON_KEY` and `SERVICE_ROLE_KEY` are JWTs signed with your `JWT_SECRET`. Supabase provides a script to generate them, or you can use any JWT library. Don't skip this — using the example keys is a security hole.

Then:

```bash
docker compose up -d
```

That's the happy path. In practice you'll tweak things.

## What's easy

**Postgres** just works. It's Postgres 15 with `pg_graphql`, `pgvector`, `uuid-ossp`, and a bunch of other extensions pre-installed. You connect with any standard Postgres client:

```bash
psql -h localhost -p 5432 -U postgres -d postgres
```

The Supabase Studio UI runs on port 3000 by default — your SQL editor, table browser, RLS policy editor. It's legitimately good.

**Auth** also works out of the box. Email/password, magic links, and OAuth social providers are all configuration — you drop in your Google/GitHub OAuth credentials in Studio and it works. JWT issuance, refresh tokens, user management — all handled. No code to write.

**Postgres Row Level Security** is just Postgres. You write SQL policies, they apply. The Studio UI even has a visual policy editor if you don't want to write raw SQL.

## What's harder

**Realtime subscriptions** work, but they require websocket connections to stay open. On a VPS with nginx in front, you need to configure websocket proxying properly:

```nginx
location /realtime/ {
    proxy_pass http://localhost:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;  # Keep websockets alive
}
```

Without `proxy_read_timeout` being long enough, nginx will kill idle websocket connections after 60 seconds. Your clients will see random disconnects. Annoying to debug.

**Edge Functions** — these are Supabase's serverless functions, running Deno under the hood. Self-hosted Edge Functions work, but the DX is rougher than Cloud. You need the Supabase CLI to deploy functions locally:

```bash
supabase functions deploy my-function --project-ref local
```

Debugging is also more involved — you're tailing Docker logs instead of having a nice log viewer. For anything complex, Edge Functions on self-hosted are more trouble than they're worth. I use a regular Express/Node process for that work instead.

**Storage** works for basic file uploads. The S3-compatible API layer (via `imgproxy` and the storage service) does its job. But if you need image transformations at scale, the self-hosted storage service is slower than Cloud's CDN-backed equivalent. For serving images to end users, consider putting Cloudflare in front.

**Email delivery** — Supabase uses an internal SMTP service for auth emails (confirmations, password resets). You need to point it at a real SMTP provider. Supabase Cloud handles this for you; self-hosted means configuring this yourself:

```bash
# In .env
SMTP_HOST=smtp.postmarkapp.com
SMTP_PORT=587
SMTP_USER=<your-postmark-token>
SMTP_PASS=<your-postmark-token>
SMTP_SENDER_NAME=Your App
```

Don't skip email setup. Without it, user signups silently fail when confirmation emails don't send.

## Backup strategy

This is on you now. Postgres backups are straightforward with `pg_dump` or `pg_basebackup`.

A simple cron-based approach:

```bash
# /etc/cron.d/supabase-backup
0 * * * * root /usr/local/bin/backup-supabase.sh

# backup-supabase.sh
#!/bin/bash
BACKUP_DIR=/var/backups/supabase
DATE=$(date +%Y%m%d_%H%M%S)
docker exec supabase-db pg_dump -U postgres postgres \
  | gzip > $BACKUP_DIR/postgres_$DATE.sql.gz

# Retain last 100 backups
ls -t $BACKUP_DIR/*.sql.gz | tail -n +101 | xargs rm -f
```

For anything serious, also consider `pg_basebackup` for binary backups (faster restore) and shipping backups offsite — S3, Backblaze B2, wherever. A backup that only lives on the same disk as the database isn't really a backup.

Test your restore path before you need it:

```bash
gunzip -c postgres_20260120_120000.sql.gz | docker exec -i supabase-db psql -U postgres
```

## Nginx config sketch

The full Supabase stack exposes several services. A minimal nginx config routing everything through one domain:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    # SSL certs (Let's Encrypt via certbot)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Studio (web UI)
    location / {
        proxy_pass http://localhost:3000;
    }

    # REST API + Auth + Storage
    location /rest/ { proxy_pass http://localhost:8000; }
    location /auth/ { proxy_pass http://localhost:8000; }
    location /storage/ { proxy_pass http://localhost:8000; }

    # Realtime (websockets)
    location /realtime/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

The Kong API gateway (port 8000 in the default compose setup) routes to the appropriate internal service. You can expose Kong directly or put nginx in front — I use nginx because the VPS runs other services too.

## When to just use Supabase Cloud

Self-hosting makes sense when:
- You're already running a VPS with spare capacity
- Your data has residency or compliance requirements
- You need features locked behind higher Cloud tiers (more connections, bigger database)
- You want full Postgres access (custom extensions, direct `pg_hba.conf` edits)

Use Supabase Cloud when:
- You want zero maintenance overhead
- You're building a side project and $25/month is fine
- You need the managed Edge Functions DX
- You don't want to think about backups

The Cloud product is excellent. Self-hosting is an operational trade-off, not a technical superiority flex. Know what you're signing up for.

3h4x
