---
layout: post
title:  "qubitcoin — a post-quantum Bitcoin rewrite, and why silent RPC failures matter"
categories: tech
tags: [typescript, bitcoin, post-quantum, api, testing]
comments: True
---

There's a particular class of bug I hate more than crashes: the API that quietly returns nothing when you give it garbage input. No error, no `400`, just an empty result that looks exactly like a valid-but-empty result. This surfaced while working on [`qubitcoin`](https://qubitcoin.finance), a post-quantum Bitcoin rewrite I've been building — so let me introduce that first, then get to the bug.

<!-- readmore -->

## Background: post-quantum Bitcoin

Bitcoin's security rests on two cryptographic assumptions: the hardness of the elliptic curve discrete logarithm problem (ECDLP) for private key security, and SHA-256 for proof-of-work and address derivation. Quantum computers threaten the first one. Shor's algorithm, running on a sufficiently large, fault-tolerant quantum machine, can derive a private key from a public key in polynomial time. That's a well-understood consequence of how elliptic curve math works — not immediately exploitable today, but the direction of travel is clear.

`qubitcoin` is a proof-of-concept Bitcoin rewrite that replaces the vulnerable parts. The key changes:

- **CRYSTALS-Dilithium** instead of ECDSA for signatures — a lattice-based scheme standardized by NIST as a post-quantum digital signature algorithm. It's not speculative; it survived years of public cryptanalysis
- **SHA-3 (Keccak-512)** for address derivation instead of SHA-256 + RIPEMD-160
- A **58-million address snapshot** of the Bitcoin UTXO set, with balances mapped to new Dilithium-derived addresses. To be clear — you can't magically convert an ECDSA public key into a Dilithium one. The snapshot preserves economic state (which addresses hold what), not key continuity. Actual owners would need to generate new quantum-safe keys and claim their balances — think burn-and-claim: prove you control the legacy address by signing a message with the old ECDSA key, then receive the equivalent balance at your new Dilithium-derived address

Side by side, the differences look like this:

| | Bitcoin | qubitcoin |
|---|---|---|
| **Signature** | ECDSA (secp256k1) | CRYSTALS-Dilithium |
| **Hashing** | SHA-256 / RIPEMD-160 | SHA-3 (Keccak-512) |
| **Address format** | Base58Check (`1A1z...`) | 64-char hex (`a3f2...`) |

The address format reflects this. Instead of the 25–34 character Base58Check strings you're used to in Bitcoin, QBTC addresses are 64-character lowercase hex strings — the raw Keccak-512 output, no encoding layer on top. No Base58 ambiguity, no checksum to decode, and trivially easy to validate: if it's not 64 lowercase hex chars, it's wrong.

It's a PoC, not production software. But it's a PoC with a real node, a real RPC layer, and real endpoints that callers hit. Which brings us to the bug.

## The broken state

The `/api/v1/address/:address/balance` and `/api/v1/address/:address/utxos` endpoints accepted whatever you threw at them. Pass a typo, a truncated hash, a Bitcoin address (wrong format entirely), or just the string `"undefined"` (yes, it happens when you're iterating fast), and you'd get back:

```
HTTP/1.1 200 OK   ← the "liar"

{ "balance": 0, "utxos": [] }
```

Which looks totally fine! `200 OK`, so no alarms. Until you spend 20 minutes wondering why the address has no balance, only to realize you've been querying with the wrong thing the whole time. The node looked up the address, found nothing (because it doesn't exist in that format), and returned an empty result with a success status. No indication that the input was malformed. No clue that you should look at the caller, not the data.

This is a false negative — the API is implicitly saying "valid address, zero balance" when the truthful answer is "I don't know, you gave me garbage." The two outcomes are indistinguishable from the caller's side, and the `200` makes it worse. That's the problem.

## The fix

Added a small helper in `rpc.ts`:

```ts
function isValidAddress(addr: string): boolean {
  return typeof addr === 'string' && /^[0-9a-f]{64}$/.test(addr)
}
```

Sixty-four hex characters, lowercase, nothing else. The regex is intentionally strict — no normalization, no `toLowerCase()` before the check. If the caller sends uppercase hex, that's a `400`. Strictness is part of the contract, not an oversight; it forces callers to be explicit about what they're sending.

Apply it at the top of both handlers:

```ts
if (!isValidAddress(req.params.address)) {
  return res.status(400).json({ error: 'Invalid address format' })
}
```

Now garbage input gets the truth:

```
HTTP/1.1 400 Bad Request   ← the "truth-teller"

{ "error": "Invalid address format" }
```

Five or so lines of real code, but the behaviour change is meaningful — callers get a signal they can actually act on.

One thing TypeScript won't save you from here: it can give you type safety at compile time within the codebase, but the moment you're accepting input over HTTP, you're back to stringly-typed reality. Libraries like `zod` or `io-ts` exist precisely for this — they let you define schemas that validate at runtime and infer TypeScript types from the same definition. For a single hex-string check a regex is fine, but if your RPC layer grows to dozens of endpoints with complex payloads, a schema validation library pays for itself fast. The point stands either way: the runtime boundary is where compile-time guarantees end and explicit validation begins.

## Testing the edge cases

The fun part was writing the test matrix. Five new cases in `rpc.test.ts`:

- A string that's too short (32 chars)
- A string that's too long (128 chars)
- A correctly-lengthed string with non-hex characters (`g`, `z`, etc.)
- An empty string
- A valid-length string with uppercase letters — technically hex, just not lowercase

All of them should return `400` from both endpoints. The general principle that came out of this: the invalid input space is larger than the valid one, and you have to enumerate it explicitly. "It's not a valid address" is a much bigger category than it first looks, and a naive length check alone won't cover it.

## Why this matters more than it looks

Silent failures are insidious because they don't page anyone. A crash is obvious — something breaks, someone notices, the issue gets fixed. An ambiguous empty response for a malformed address can sit in a codebase for months, quietly building incorrect assumptions in every caller that integrates against it.

Explicit validation at the boundary — return `400` early, return it loudly — makes the contract clear and pushes the error as close to the source as possible. Post-quantum cryptography is the interesting part of `qubitcoin`. But a cryptographically sound node that lies about bad input is still a bad node.

3h4x
