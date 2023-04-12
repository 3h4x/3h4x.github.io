---
layout: post
title: "Deploying with PM2 — why I stopped using Docker for Node.js apps"
categories: tech
tags: [pm2, docker, devtools, deployment]
comments: True
---

Hot take: Docker is overkill for deploying Node.js apps on a single server. I know, I know. Containers are great. Isolation, reproducibility, all that. But when you're running 4 Express apps on one VPS and your "deployment" is `rsync` + restart, Docker adds a layer of complexity that earns you almost nothing.

<!-- readmore -->

## The Docker setup I had

Each app had a `Dockerfile`, a `docker-compose.yml`, and a deploy script that would:

1. Build the image on the server (or pull from a registry)
2. Stop the old container
3. Start the new one
4. Pray the health check passes before the load balancer notices

This worked. But every deployment involved downloading base images, rebuilding layers, and the inevitable "why is `node_modules` 800MB in the container." My deploy times were 2-3 minutes for apps that take 10 seconds to start natively.

And then there's the networking. Docker's bridge network, port mapping, container DNS — all problems that don't exist when your app just binds to `localhost:3456`.

The one that really got me was logs. `docker logs -f myapp` is fine until you have 4 containers and need to correlate events across them. You end up either setting up a centralized log driver (another moving part) or doing the `ssh` + `docker exec` dance. Compare that to `pm2 logs` which shows everything in one stream.

## What PM2 actually gives you

```bash
npm install -g pm2
pm2 start app.js --name my-app
```

That's the deployment. But PM2 is more than a process runner:

**Crash recovery.** App throws an unhandled exception at 3am? PM2 restarts it. Automatically. With exponential backoff so a boot loop doesn't eat your CPU. You can tune `max_restarts` and `restart_delay` if you need tighter control.

**Zero-downtime restarts.** `pm2 reload my-app` starts a new instance, waits for it to be ready, then kills the old one. No dropped requests. This uses the cluster module under the hood — same technique NGINX uses. For anything serving real traffic, this is the feature that matters.

**Log management.** `pm2 logs my-app` streams stdout/stderr. `pm2 logrotate` keeps them from eating your disk. Logs go to `~/.pm2/logs/` by default, which makes Promtail scraping trivial.

**Cluster mode.** `pm2 start app.js -i max` forks across all CPU cores. Free horizontal scaling on a single box. Useful if your app is CPU-bound and the server has headroom.

**Ecosystem file.** One config for all your apps:

```javascript
module.exports = {
  apps: [
    {
      name: 'api',
      script: './dist/server.js',
      instances: 2,
      exec_mode: 'cluster',
      max_memory_restart: '512M',
      env: {
        NODE_ENV: 'production',
        PORT: 3333
      }
    },
    {
      name: 'worker',
      script: './dist/worker.js',
      instances: 1,
      cron_restart: '0 */6 * * *',
      env: {
        NODE_ENV: 'production'
      }
    }
  ]
}
```

`pm2 start ecosystem.config.js` and you're done. All apps, all config, one command. The `max_memory_restart` is particularly useful — if something starts leaking memory, PM2 kills and restarts it before your VPS starts swapping.

## My deploy script

```bash
#!/bin/bash
set -e

APP_DIR=/home/deploy/app
rsync -avz --delete \
  --exclude node_modules \
  --exclude .env \
  dist/ package.json package-lock.json \
  deploy@server:$APP_DIR/

ssh deploy@server "cd $APP_DIR && npm ci --production && pm2 reload ecosystem.config.js"
```

Total deploy time: ~8 seconds. Most of that is `npm ci`. The `--delete` flag on `rsync` ensures stale files don't linger after refactors. And because we're syncing `dist/` (already built locally), the server never needs to run a build.

One refinement I added later — after `pm2 reload` completes, check that the app is actually up:

```bash
ssh deploy@server "pm2 show api | grep -q 'online' || (pm2 logs api --lines 50; exit 1)"
```

If the reload succeeded but the app immediately crashed, this surfaces the last 50 lines of logs and fails the deploy. Saved me from silent failures more than once.

## Startup persistence

The thing people always miss: `pm2 start` doesn't survive reboots by default.

```bash
pm2 startup
# Run the command it prints, something like:
# sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u deploy --hp /home/deploy

pm2 save
```

`pm2 startup` generates a systemd unit that restarts PM2 on boot. `pm2 save` dumps the current process list to disk so PM2 knows what to start. After a kernel update and reboot, everything comes back. No intervention needed.

## Monitoring

`pm2 monit` gives you a live dashboard — CPU, memory, restart count per process. Good for a quick sanity check. For anything more serious I have Prometheus + Grafana, and Promtail shipping PM2 logs to Loki.

```bash
# Quick status
pm2 list

# Live dashboard
pm2 monit

# Memory/CPU for a specific app
pm2 show api
```

The `pm2 show` output also tells you uptime, restart count, and the path to log files. Useful for debugging without having to remember where everything lives.

## When Docker still wins

I'm not saying Docker is bad. It's the right tool when:

- You're deploying to multiple machines or Kubernetes
- You need strict dependency isolation (different Node versions per app)
- Your CI/CD pipeline is built around container images
- You're working in a team and "works on my machine" is a real problem
- Your app has system dependencies beyond Node (ImageMagick, FFmpeg, etc.)

That last one is real. If your app shells out to `ffmpeg`, Docker makes the dependency explicit and reproducible. With PM2, you're just hoping `ffmpeg` is installed on the server.

But for solo dev, single server, Node.js apps? PM2 is less complexity for the same reliability. The app runs as a regular process, logs go to regular files, networking is just ports. Nothing to debug that you wouldn't debug anyway.

## One year later

I've been running 5 apps with PM2 for a year now. Zero issues that were PM2's fault. The `pm2 save` + `pm2 startup` combo means everything comes back after a reboot. `pm2 monit` gives me a live dashboard. And I haven't written a `Dockerfile` in months.

One thing I didn't expect: debugging is faster. When an app misbehaves, I can `ssh` in, `pm2 logs myapp --lines 100`, and see what happened. No container runtime to navigate. The process is just there, on the filesystem, behaving like a normal program.

Sometimes the boring tool is the right tool.

3h4x
