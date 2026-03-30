---
layout: post
title:  "x402 - HTTP payments that actually work"
categories: tech
tags: [web3, base, express, payments, ai-agents]
comments: True
---

HTTP `402 Payment Required`. It's been sitting in the spec since 1991 — literally the first version of HTTP that had status codes. "Reserved for future use." For decades, every web developer has scrolled past it and thought "huh, wonder when that'll be a thing."

Well, it's a thing now. `x402` is an open protocol that revives that dusty status code into actual payment infrastructure. Coinbase's Developer Platform team built the initial implementation, but this isn't just a Coinbase product — Cloudflare, Polygon, and Solana are backing it as part of a broader push for "agentic payments." The idea is that any HTTP endpoint can become a digital vending machine: request a resource, get a price, pay on-chain, receive the goods. No accounts, no API keys, no invoicing.

I wired it into one of my projects. The integration is absurdly simple.

<!-- readmore -->

## What's x402?

The idea is pure HTTP. A client hits an endpoint, the server responds with `402` and a payment payload describing what it costs. The client pays on-chain (USDC on Base), then retries the same request with a payment proof header, and the server verifies it. No API keys, no Stripe dashboard, no webhook hell — just HTTP and a blockchain.

Think about that for a second. The web has had a *payment status code* since day one.

And yet we've been building payment flows with redirect chains, OAuth tokens, webhook endpoints, and dashboard UIs. `x402` says: what if paying for an API call was as simple as sending a header?

Coinbase's [`x402-express`](https://www.coinbase.com/x402) library handles the whole flow. From the server side, it's a middleware.

## A few lines of middleware

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

That's it. Any request to `POST /api/feature-agent` without a valid payment proof gets a `402` back with a JSON body telling the client exactly what to pay. The `facilitator` from Coinbase handles on-chain verification — you never talk to an RPC yourself. I was genuinely surprised how clean this turned out.

## What happens on the client side

This is the part that clicked for me. The `402` response isn't just an error — it's a *payment instruction*. The response body contains the price, the network, the recipient address, and a facilitator URL. A real `402` response looks something like this:

```http
HTTP/1.1 402 Payment Required
Content-Type: application/json

{
  "price": "5000000",
  "asset": "USDC",
  "network": "base",
  "payTo": "0xYourTreasuryAddress...",
  "facilitator": "https://x402.org/facilitator"
}
```

A compatible client (or wallet) reads that, constructs the USDC transfer, signs it, and re-sends the original request with an `X-PAYMENT` header containing the proof. The protocol defines standardized headers — `X-PAYMENT` for the signed proof, and the `402` body for the payment terms — so any client that speaks `x402` can interact with any server. It's not a proprietary format.

From the user's perspective? They click a button, approve a transaction in their wallet, and the feature activates. No account creation, no credit card form, no "enter your billing address." Just a wallet signature.

## The handler is boring (in the best way)

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

By the time this handler runs, payment is already verified by the middleware. Your business logic doesn't know or care about payments — it just does its thing. You can stack payments too — pay again on an already-featured record and it extends from the current expiry, not from now. Seemed like the right behaviour.

## The end-to-end flow

Zooming out, here's what actually happens:

1. Client calls your endpoint
2. Server returns `402` with payment details (price, network, recipient)
3. Client sends USDC transaction on Base
4. Client retries the original request with an `X-PAYMENT` proof header
5. Middleware verifies payment via the facilitator
6. Your handler runs — payment already confirmed

That's the whole protocol. Pure request-response, no callbacks, no webhooks.

## When should you use this?

Good fit: paid API endpoints (pay-per-call, no accounts needed), one-off actions (feature unlocks, boosts, submissions), and machine-to-machine payments where bots or agents pay for services autonomously.

That last one is the angle I think people are sleeping on. The "agentic payments" framing isn't just marketing — an AI agent with a wallet can autonomously discover a `402` response, parse the payment terms, sign a transaction, and retry. No human in the loop. No OAuth dance. The agent just... pays. This is already happening: Hyperbolic Labs exposes GPU compute endpoints behind `x402`, and CoinGecko offers pay-per-use market data the same way. Bots paying for data and compute without accounts is not theoretical anymore.

Probably not a good fit: subscriptions (no recurring payment primitive yet), high-frequency microtransactions (gas + confirmation latency adds up), or anything targeting non-crypto users.

Concrete example — an AI image generation API that charges `$0.02` per call. No API keys, no account signup. Just hit the endpoint, pay, get the image. That's the kind of thing `x402` makes trivially simple.

## Why this works *now*

No user accounts needed. No payment method on file. No PCI compliance surface. A wallet, $5 USDC, and a signed transaction is the entire auth flow. The treasury address is just an EOA — every payment is verifiable on Basescan.

The `$5.00` price string gets converted to USDC units (6 decimals) automatically. Nice touch — you don't think in `5_000000`.

This pattern only became practical because cheap L2s make per-request payments viable (sub-cent gas), and stablecoins like USDC give you predictable pricing. Even a year ago, doing this on mainnet would've been absurd — $2 gas on a `$0.02` API call doesn't work. And it's not just Base — `x402` works on Polygon and Solana too, so you pick whatever chain fits your latency and cost profile.

Compared to traditional flows (Stripe + accounts + API keys) or other web3 approaches (prepaid credit systems, token-gated access), `x402` is stateless, per-request payments. No session state, no balance tracking — just HTTP.

But what really gets me is where this pattern could go. Pay-per-call APIs where every endpoint has a price tag in the middleware config. No API key management, no rate limiting by tier, no billing system — just "this costs $0.01 per call, pay or don't." Or content gates where a blog post costs $0.10 to read — no paywall subscription, no login wall. The `402` code was designed for exactly this, we just never had the rails to make it work until now.

## What I'd watch out for

It's early. The `facilitator` is a centralized Coinbase service — it verifies on-chain payments so you don't have to, but that means it's a single point of failure. If it's down, your payment flow stops. You could verify payments yourself via RPC or an indexer, but that's significantly more work. For now, you're trusting Coinbase's uptime.

UX is still crypto-native: users need a wallet, approve a transaction popup, and wait for confirmation. Even on Base with sub-second finality and tiny gas fees, this isn't Stripe-level smooth. Know your audience.

The client-side ecosystem is thin — right now you need a wallet that understands `x402` responses, or you build the client flow yourself.

But the core idea is sound. HTTP has always known it needed a payment layer. Took decades and a stablecoin on an L2, but here we are ;)

3h4x
