# 3h4x.github.io

Personal blog "YAB", Jekyll on GitHub Pages. **This repository is public and every push to `master` publishes.** How to
write and preview a post (front matter, `<!-- readmore -->`, `docker compose up -d`): `README.md`.

## Workflow: the owner reads first

- Write a new post or a change to one as a local file only. **No commit, no push, no PR** until the owner has read it
  and said to publish. A pushed branch or a PR in this repo is already public, even unmerged.
- When handing a draft over, list every number, name and technical detail you are unsure about, so the owner decides.
- Posts are in English, whatever language the request is in.
- Credit honestly: agents write most of the code, the owner designs the systems, decides how they work and what is
  allowed. Never frame a project as one that "builds itself" or has no author.

## What never goes into a post

Everything here is public and indexed. Do not publish, in a post, its front matter, an image, alt text, a commit message
or a PR body:

1. **Live operational state.** Subscription or quota usage (percentages, margins, "runs out before reset"), pacing or
   admission decisions, current queue, backlog or board counts, firing alerts, ongoing incidents,
   anything phrased "right now" / "as I write this" about the running system.
2. **Infrastructure identifiers.** Server or node names, IP addresses, hostnames other than the public sites named
   below, Kubernetes namespace names, internal service or Secret names, token or credential names, ports, registry
   hosts, image names, cloud account or bucket names.
3. **Security detail that maps the attack surface.** General principles are fine (the model holds no credentials,
   egress only through an allow-list proxy, trusted and untrusted phases are separate Pods). Not fine: where a specific
   credential lives, allow-list contents, policy or rule names, and **any known weakness or gap that is not fixed yet**.
4. **Private repositories and their artefacts.** Names of private repos, issue/PR/run numbers or links into them
   (`some-repo#123`), internal ticket text, chat quotes, file paths from private code. Describe the idea, not
   the reference. Anecdotes about specific PRs stay generic ("a change of a few dozen lines"), never a number.
5. **Projects on other domains.** Never name or link an app or project that is not on `*.datacrash.io` (or
   agentclub.trade) in connection with DataCrash: that discloses who owns it. Only name what the owner explicitly named.
6. **Business numbers beyond rounded aggregates.** Per-repository or per-project costs, token use, revenue, user or
   customer counts, subscription plans or accounts. Allowed: rounded totals over a stated period across the whole system
   ("~12,800 agent runs since mid-October", "~$16 median for a medium PR"), clearly labelled as estimates where they are.
7. **People.** No names, emails or accounts except the public contact `3h4x@datacrash.io`.

If a draft needs one of these to make its point, rewrite the point in general terms, or ask the owner.
