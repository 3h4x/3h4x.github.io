---
layout: post
title: "The price of one verified change: seven principles for autonomous delivery that gets cheaper over time"
categories: tech
tags: [ai, agents, autonomous-agents, unit-economics, code-review, ci-cd, kubernetes, kueue, automation, datacrash]
comments: True
---

In [the previous post](/tech/2026/11/18/claude-code-agents-k3s-sandbox.html) I described how datacrash.io turns an issue into a verified deploy with agents doing the work, and named the real constraint: not what the models can do, but what each verified change costs. This post is about how a platform like that should be measured and run, so that the cost per change goes down over time instead of up.

No deep internals this time. These are the seven principles datacrash.io is built on, seen from the side that matters: the one writing the issues.

<!-- readmore -->

## 1. Price the outcome, not the activity

Nobody wants "agent runs" or "CI minutes". What a team wants is a change that does what the issue asked for, merged, deployed and checked in production. So that is the unit: **one verified change, one pull request, one price.**

That price has to be complete:

- the agent work behind it: planning, writing the code, every review, every fix after a review or a red check,
- the CI time spent on every version of it,
- its share of the deploy build that took it live,
- and, shown separately, the check after the deploy that the change actually does what it promised.

The work behind one change is naturally spread over many attempts: a plan, a first version, a fix, a second review, a retry after a conflict. A platform that reports per attempt hides the real cost of a change; one that traces every attempt back to the change it served shows it. And what can't be measured is reported as *unknown*, never as free. A cost that looks like zero because data is missing is worse than no number at all.

Every change now shows this price on its own page, next to the code.

## 2. Separate the useful from the wasted

A total alone doesn't say what to fix. So every change's price is also split into the part that moved it forward and the part that didn't:

- an attempt that failed or stopped on a usage limit,
- a review that couldn't finish, or a review of a version that was already replaced and found nothing,
- a CI job run again on exactly the same code, where only the last run carried the result.

Each wasted attempt is counted once, with every reason that applies. The waste share is the number to drive down; the total is just the bill. And the same rule as above holds: if one wasted attempt can't be priced, the share is unknown, not rounded down.

## 3. Fixed overhead is a property of how work is cut

Every change, however small, pays for a plan, an isolated sandbox, a review and a CI run. For a large change that is noise; for a one-line fix it is most of the bill. That is not a flaw to hide, it's the physics of doing work safely.

So the platform treats it as guidance, not as waste to absorb silently. datacrash.io watches what small changes cost relative to their size, per repository, and says so when work is arriving in slices too thin to be economical. The remedy is not technical: related work belongs in one card, and one card becomes one change.

## 4. Review must converge

An automated reviewer that reads every new version from scratch never runs out of opinions. Each new opinion means another fix, another full CI run and another full review. A review process that can't end isn't rigor, it's a cost with no ceiling. So review is designed to converge:

- **A finding has to earn its block.** To stop a merge, a finding must describe a concrete, likely way things break. Style preferences and "what if" speculation are recorded as notes, not blockers.
- **Later rounds are incremental.** A follow-up review checks the new version against the earlier findings instead of starting over, and it can't reverse its own earlier asks.
- **Medium findings stop blocking after a few rounds.** If something is still only a medium concern after several versions, it's recorded and the change moves on.
- **There is a cap.** A change gets a bounded number of automatic review rounds across all its versions. After that it goes to a person, with the open findings listed, as one decision.
- **Interrupted work resumes.** A long review that is cut short continues from what it already checked; a part that was reviewed once is never paid for again.

From the outside the contract is simple: a change either converges and merges, or it reaches a human with one clear question. It never circles.

## 5. CI should never pay twice

The same rule for CI, which runs inside datacrash.io's own cluster:

- **Every test runs in exactly one place.** The suite is split into parallel parts, dependencies come from a shared cache instead of being installed for every job, and a job that only checks lint, types and the build never re-runs a suite another job already runs. A duplicated suite is the most expensive kind of waste, because it repeats on every version of every change.
- **Queued, not contended.** Jobs wait for capacity instead of fighting over it, so a burst of changes slows down gracefully instead of failing.
- **Tested together before they land.** A merge queue checks the next changes on top of the current main branch, so a broken combination is caught before it reaches main, not after. A change whose status hasn't moved for too long steps aside instead of holding up the ones behind it.
- **Main stays green, and the time it isn't is measured.** A change is never sent to fix a failure that belongs to main. How long main stays red is tracked, and a long red stretch is an alert, because every change in the queue is paying for it.

## 6. Order work by cost of delay, not by arrival

What is cheapest is not always what should go first. A platform that takes cards in arrival order spends its budget on whatever was written first, not on what matters. So cards are ordered by **cost of delay divided by size**, a rule borrowed from lean product development:

- a fix to the delivery pipeline itself weighs the most, because every other change pays for its delay; a bug weighs more than a chore, and a chore more than a feature;
- among equals, the smaller card goes first, because it delivers its value sooner;
- an explicitly urgent card jumps the line, and a card waiting on another wakes up as soon as that dependency changes.

The ordering uses fixed weights and stored facts, no model, and every decision is saved with its reason, so "why is my card not moving" always has an answer. Plans don't go stale in the queue either: a plan older than a week is written again against the current code before any work starts on it.

## 7. Optimization is a loop, not a project

Cost doesn't stay low because of one cleanup. It stays low because the platform keeps measuring itself:

1. Every merged change is measured: its price, its waste, its time to production.
2. When a number crosses a threshold, such as the weekly median price of a change rising, too much overhead on small changes or main staying red, it raises an alert and the fix becomes a card on the board like any other.
3. An agent picks it up, changes the platform, and the next changes are measured again.

The platform improves itself through the same pipeline it offers to everyone else. To be clear about who does what: the measurements and the agents find and fix the waste, but which numbers matter, where the thresholds are and what an agent may change are my decisions. The system doesn't optimize toward a goal it chose for itself; it optimizes toward the one I wrote down, and it shows its work while doing it.

## What this means if you're writing the issues

- **You pay for verified changes, not for activity.** Retries, review rounds and red builds are part of the price of a change, visible per change, with the wasted part called out, not hidden in a monthly total.
- **The price goes down over time.** Every improvement to the platform applies to every repository at once.
- **What matters most moves first,** and you can always see why a card is where it is.
- **You get told how to work with it.** If your tasks are too small to be economical, you hear it as a recommendation, not discover it on an invoice.
- **Done is checked, not declared.** If what the issue promised can't be observed after the deploy, the change goes back to work by itself instead of waiting in someone's inbox.
- **When it needs you, it asks once.** A change that can't converge on its own reaches you as one decision with the reasons attached, not as an endless thread.

If you're investing in or building in this space, or want to see how this would work on your own repositories, write to me at [3h4x@datacrash.io](mailto:3h4x@datacrash.io).
