---
layout: post
title: "Ansible for a single server — overkill or exactly right?"
categories: tech
tags: [ansible, devtools, deployment, infrastructure as code]
comments: True
---

When I first set up my VPS, I configured everything by hand. SSH'd in, ran commands, tweaked config files, forgot what I did three weeks later. The second time I set up a server I wrote bash scripts. Big bash scripts. Scripts that grew organically until they were unreadable, non-idempotent, and broke in subtle ways if they'd already been partially run. The third time I used Ansible. I haven't looked back.

<!-- readmore -->

Yes — Ansible for one server. Here's why it's not overkill.

## What's wrong with bash scripts

Nothing, for simple things. But configuration management bash scripts have a failure mode: they're usually not idempotent. Run them twice and something breaks. `useradd deploy` fails if the user already exists. `mkdir /var/www` errors if the directory is there. You end up sprinkling `|| true` everywhere, or writing `if ! id deploy; then useradd deploy; fi`, which is basically reimplementing what Ansible does — just worse.

Bash scripts also don't compose well. You have a script to install nginx, a script to configure SSL, a script to set up your app. Dependencies between them are implicit and fragile. Ansible tasks are declarative: describe the desired state, and Ansible figures out what needs to change.

## The project structure

```
server/
├── inventory.ini
├── site.yml
├── group_vars/
│   └── all.yml
└── playbooks/
    ├── nginx.yml
    ├── users.yml
    ├── firewall.yml
    └── apps.yml
```

`inventory.ini` for a single server is almost comically simple:

```ini
[myserver]
203.0.113.42

[myserver:vars]
ansible_user=root
ansible_python_interpreter=/usr/bin/python3
```

One host. One group. That's it. You can use `localhost` and skip SSH entirely if the server is your local machine.

## User management

First thing I automate: creating the deploy user and locking down root access.

```yaml
# playbooks/users.yml
- name: User management
  hosts: myserver
  tasks:
    - name: Create deploy user
      user:
        name: deploy
        shell: /bin/bash
        groups: sudo
        append: yes
        state: present

    - name: Add SSH key for deploy user
      authorized_key:
        user: deploy
        key: "{{ lookup('file', '~/.ssh/id_ed25519.pub') }}"
        state: present

    - name: Disable root SSH login
      lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^PermitRootLogin'
        line: 'PermitRootLogin no'
        state: present
      notify: restart sshd

    - name: Disable password authentication
      lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^PasswordAuthentication'
        line: 'PasswordAuthentication no'
        state: present
      notify: restart sshd

  handlers:
    - name: restart sshd
      service:
        name: sshd
        state: restarted
```

Run this once and your SSH config is locked down. Run it again — nothing changes because the user already exists, the key is already there, the sshd config already has those values. Idempotent by design.

The `notify: restart sshd` + handlers pattern is clever: the restart only happens if those tasks actually changed something. If sshd_config was already correct, no unnecessary restart.

## Nginx config management

Managing nginx with Ansible means your config lives in version control. No more "which server has that custom nginx block I added by hand six months ago."

```yaml
# playbooks/nginx.yml
- name: Nginx setup
  hosts: myserver
  tasks:
    - name: Install nginx
      apt:
        name: nginx
        state: present
        update_cache: yes

    - name: Deploy nginx main config
      template:
        src: templates/nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        owner: root
        group: root
        mode: '0644'
      notify: reload nginx

    - name: Deploy site configs
      template:
        src: "templates/sites/{{ item }}.j2"
        dest: "/etc/nginx/sites-available/{{ item }}"
      loop:
        - myapp.example.com
        - api.example.com
      notify: reload nginx

    - name: Enable sites
      file:
        src: "/etc/nginx/sites-available/{{ item }}"
        dest: "/etc/nginx/sites-enabled/{{ item }}"
        state: link
      loop:
        - myapp.example.com
        - api.example.com

    - name: Remove default site
      file:
        path: /etc/nginx/sites-enabled/default
        state: absent
      notify: reload nginx

  handlers:
    - name: reload nginx
      service:
        name: nginx
        state: reloaded
```

Templates use Jinja2 so you can inject variables — domain names, backend ports, whatever varies per environment. The template for a reverse proxy config:

```nginx
# templates/sites/myapp.example.com.j2
server {
    listen 80;
    server_name {{ domain }};

    location / {
        proxy_pass http://localhost:{{ app_port }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Variables come from `group_vars/all.yml`. Consistent, version-controlled, reviewable.

## Firewall rules

UFW is simple enough, but Ansible makes it declarative:

```yaml
# playbooks/firewall.yml
- name: Firewall setup
  hosts: myserver
  tasks:
    - name: Install ufw
      apt:
        name: ufw
        state: present

    - name: Default deny incoming
      ufw:
        direction: incoming
        policy: deny

    - name: Default allow outgoing
      ufw:
        direction: outgoing
        policy: allow

    - name: Allow SSH
      ufw:
        rule: allow
        port: '22'
        proto: tcp

    - name: Allow HTTP
      ufw:
        rule: allow
        port: '80'
        proto: tcp

    - name: Allow HTTPS
      ufw:
        rule: allow
        port: '443'
        proto: tcp

    - name: Enable UFW
      ufw:
        state: enabled
```

If you ever need to open a new port, you add a task, run the playbook, done. The state is in the playbook, not in some command you ran two months ago and forgot.

## Systemd service management

For apps that aren't Node.js (or when PM2 isn't the right fit), Ansible can manage systemd units:

```yaml
- name: Deploy app service
  template:
    src: templates/myapp.service.j2
    dest: /etc/systemd/system/myapp.service
  notify:
    - reload systemd
    - restart myapp

- name: Enable and start service
  systemd:
    name: myapp
    enabled: yes
    state: started
    daemon_reload: yes
```

Ansible's `systemd` module handles `daemon-reload` automatically when you tell it to. No manual `systemctl daemon-reload` steps to forget.

## Running it

```bash
# Run everything
ansible-playbook -i inventory.ini site.yml

# Just firewall changes
ansible-playbook -i inventory.ini playbooks/firewall.yml

# Dry run — shows what would change without changing it
ansible-playbook -i inventory.ini site.yml --check --diff

# Only tasks tagged 'nginx'
ansible-playbook -i inventory.ini site.yml --tags nginx
```

The `--check --diff` combination is the killer feature. Before applying any change to production, see exactly what files would be modified and how. It's like `terraform plan` for your server config.

## When it IS overkill

Honest answer: for truly trivial things. If you have one server and you're just running `apt update && apt upgrade` — a cron job is fine. If your "infrastructure" is a single static site on nginx with one config file that never changes — Ansible won't save you much.

The break-even point for me was around the second or third non-trivial thing I needed to configure. User management + nginx + firewall + app services = Ansible pays for itself.

It also pays for itself the first time you need to rebuild the server. Full Hetzner instance replacement took about 20 minutes: provision a new server, update `inventory.ini` with the new IP, run `site.yml`. Compare that to doing it by hand while stressed because production is down.

## The thing nobody tells you

Ansible is slow. Connecting over SSH for every task adds up. A playbook with 30 tasks might take 2 minutes to run even if nothing changes. That's fine for occasional provisioning, but annoying for rapid iteration.

The fix: `--tags` to run only the relevant section, and `--limit` to target specific hosts if you have more than one.

Also: Ansible requires Python on the remote host. Usually it's there. Sometimes it's not. `raw` module lets you install it first if needed — but at that point you're writing your own bootstrapper, which is a bit turtles-all-the-way-down.

Still worth it. Having your entire server configuration in a git repo, reviewable, diffable, and replayable, changes how you think about infrastructure. It's the difference between "I think the server is configured this way" and "I know exactly how the server is configured."

3h4x
