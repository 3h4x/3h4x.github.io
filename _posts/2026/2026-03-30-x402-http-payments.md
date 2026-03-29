---
layout: post
title:  "x402 - HTTP payments that actually work"
categories: tech
tags: [web3, base, express, payments]
comments: True
---

HTTP `402 Payment Required` has been in the spec since 1991. Listed in every HTTP reference as "reserved for future use." Thirty-five years later, Coinbase shipped `x402` and suddenly that status code is doing real work. I just wired it into one of my projects to gate an endpoint behind on-chain payment — and the integration is absurdly simple.

<!-- readmore -->

## What's x402?

The idea: a server responds with `402` and a payment payload, the client pays on-chain (USDC on Base), retries with a payment proof header, and the server verifies it. No API keys, no Stripe webhooks, no dashboard — just HTTP and a blockchain.

Coinbase's `x402-express` library handles all of this. From the server side, it's a middleware.

## Three lines of middleware

```js
const { paymentMiddleware } = require('x402-express');
const { facilitator } = require('@coinbase/x402');

app.use(paymentMiddleware(
  TREASURY_ADDRESS,
  {
    'POST /api/feature-agent': {
      price: '$5.00',
      network: 'base',
      config: { description: 'Feature your agent for 30 days' }
    }
  },
  facilitator
));
```

That's it. Any request to `POST /api/feature-agent` that doesn't carry a valid payment proof gets a `402` back. The `facilitator` from Coinbase handles verifying the on-chain payment — you don't talk to an RPC yourself. Genuinely surprised how clean this is.

## What happens on the other side

The handler itself is boring — in the best way:

```js
app.post('/api/feature-agent', (req, res) => {
  const nowSec = Math.floor(Date.now() / 1000);
  const currentExpiry = (agent.featured_until && agent.featured_until > nowSec)
    ? agent.featured_until : nowSec;
  const newExpiry = currentExpiry + (30 * 24 * 3600); // 30 days

  db.prepare('UPDATE agents SET featured_until = ? WHERE id = ?')
    .run(newExpiry, agent.id);

  res.json({ featured_until_iso: new Date(newExpiry * 1000).toISOString() });
});
```

By the time this handler runs, payment is already verified by the middleware. You can stack it too — pay again on an already-featured record and it extends from the current expiry, not from now. Seemed like the right behaviour.

## Why I like this

No user accounts needed. No payment method on file. No PCI compliance surface. A wallet, $5 USDC, and a signed transaction is the entire auth flow. The treasury address is just an EOA — every payment is verifiable on Basescan.

The `$5.00` price string gets converted to USDC units (6 decimals) automatically. That was a nice touch — you don't think in `5_000000`.

## Other stuff today

Busy day across projects. `bonker.wtf` got proper OpenGraph and JSON-LD schema tags — structured data for the token factory. `clawdit.xyz` had duplicate security headers in the nginx config that I cleaned up. `clanker.chat` got a 762-line socket connection limit test suite covering rate limiting and connection handling edge cases. And `volumino` shipped a live trade settings panel — keeper parameters tweakable without a redeploy.

But the x402 thing is the one that has me excited. It's one of those integrations where you look at the final diff and think "this is too small for what it actually does." If you want HTTP-native monetization without a payment processor in the middle, `x402` is worth a look.

Know what you are doing and have fun!

3h4x
