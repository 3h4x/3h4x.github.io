---
layout: post
title: "Building with viem instead of ethers.js — the migration"
categories: tech
tags: [web3, typescript, devtools, viem]
comments: True
---

I spent a good chunk of last year migrating from `ethers.js` v5 to `viem`. Not because I had to — `ethers` was working fine. But I kept seeing `viem` pop up in every modern web3 project, and after reading the docs I understood why. It's a fundamentally better approach to the same problem.

<!-- readmore -->

## Why viem exists

`ethers.js` is battle-tested and comprehensive. It's also a kitchen-sink library — you import the whole thing or nothing. v6 improved tree-shaking but the API surface is still enormous. `viem` was built from the start with TypeScript and tree-shaking as first-class concerns.

The pitch: fully typed, tree-shakeable, modular. Every function is importable independently. Your bundle only includes what you use.

That's the theory. In practice, the difference in bundle size matters most for frontends. For Node.js scripts and backend services, it matters less. But the TypeScript experience is genuinely better with `viem` regardless of context — and that alone justified the migration for me.

## The basic setup

With `ethers.js` v5:

```typescript
import { ethers } from 'ethers';

const provider = new ethers.providers.JsonRpcProvider('https://mainnet.base.org');
const signer = new ethers.Wallet(privateKey, provider);
```

With `viem`:

```typescript
import { createPublicClient, createWalletClient, http } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { base } from 'viem/chains';

const publicClient = createPublicClient({
  chain: base,
  transport: http('https://mainnet.base.org'),
});

const account = privateKeyToAccount(`0x${privateKey}`);

const walletClient = createWalletClient({
  account,
  chain: base,
  transport: http('https://mainnet.base.org'),
});
```

More verbose upfront, but the split between `publicClient` (reads) and `walletClient` (writes) is actually cleaner. You know exactly what capabilities each client has.

## Reading contract state

`ethers` v5:

```typescript
const contract = new ethers.Contract(address, abi, provider);
const balance = await contract.balanceOf(userAddress);
// balance is a BigNumber, not a bigint
console.log(balance.toString());
```

`viem`:

```typescript
const balance = await publicClient.readContract({
  address,
  abi,
  functionName: 'balanceOf',
  args: [userAddress],
});
// balance is a bigint — native JS primitive
console.log(balance.toString());
```

The `readContract` style is more verbose but it's explicit. You can also batch reads with `multicall`:

```typescript
const results = await publicClient.multicall({
  contracts: [
    { address, abi, functionName: 'balanceOf', args: [addr1] },
    { address, abi, functionName: 'balanceOf', args: [addr2] },
    { address, abi, functionName: 'totalSupply' },
  ],
});
// results is typed based on the ABI — TypeScript knows the return types
```

This is where the TypeScript advantage really shows. If your ABI is typed (which `viem` encourages with `as const`), `multicall` results are fully typed. No casting, no guessing.

## Writing transactions

`ethers` v5:

```typescript
const contract = new ethers.Contract(address, abi, signer);
const tx = await contract.transfer(recipient, amount);
await tx.wait();
```

`viem`:

```typescript
const hash = await walletClient.writeContract({
  address,
  abi,
  functionName: 'transfer',
  args: [recipient, amount],
});

const receipt = await publicClient.waitForTransactionReceipt({ hash });
```

The pattern of `writeContract` returning a hash, then separately waiting for the receipt, feels more honest about what's happening on-chain. The separation of concerns between `walletClient` (signs and sends) and `publicClient` (queries and waits) becomes second nature quickly.

## ABI encoding and type safety

This is where `viem` earns its reputation. Define your ABI with `as const`:

```typescript
const abi = [
  {
    name: 'transfer',
    type: 'function',
    inputs: [
      { name: 'to', type: 'address' },
      { name: 'amount', type: 'uint256' },
    ],
    outputs: [{ name: '', type: 'bool' }],
  },
] as const;
```

Now TypeScript knows that `transfer` takes `[Address, bigint]` and returns `boolean`. If you pass the wrong types, the compiler tells you before you hit the network. With `ethers`, you'd find out at runtime.

In practice, I generate ABIs from Foundry's build output and they come pre-typed. The `as const` assertion is the key — it tells TypeScript to treat the array as a literal type, not just `Array<object>`.

## Event listeners

`ethers` v5:

```typescript
contract.on('Transfer', (from, to, amount, event) => {
  console.log(from, to, amount.toString());
});
```

`viem`:

```typescript
const unwatch = publicClient.watchContractEvent({
  address,
  abi,
  eventName: 'Transfer',
  onLogs: (logs) => {
    for (const log of logs) {
      console.log(log.args.from, log.args.to, log.args.amount);
    }
  },
});

// Later:
unwatch();
```

The `unwatch()` pattern is cleaner than `contract.removeAllListeners()`. The `onLogs` receives a typed array — `log.args` is fully typed if you use the ABI correctly. That said, `viem`'s polling-based approach (default) vs `ethers`'s WebSocket subscriptions is a trade-off. For WebSocket, `viem` supports it via the `webSocket` transport.

## Wallet connections in the browser

`ethers` v5 with MetaMask:

```typescript
const provider = new ethers.providers.Web3Provider(window.ethereum);
const signer = provider.getSigner();
```

`viem` with `wagmi` (which is built on `viem`):

```typescript
import { useWalletClient, usePublicClient } from 'wagmi';

const { data: walletClient } = useWalletClient();
const publicClient = usePublicClient();
```

If you're in a React app, `wagmi` is the answer. It wraps `viem` and handles connection state, chain switching, account changes. The `ethers` equivalent was `web3-react` or `wagmi` v1 (which used ethers). `wagmi` v2+ is viem-native and the difference shows — fewer footguns, better TypeScript, first-class React hooks.

## What's worse

Honestly? Mostly verbosity. Simple scripts that took 5 lines with `ethers` take 12 with `viem`. The `createPublicClient`/`createWalletClient` setup is more ceremony.

ENS resolution is also less convenient — `ethers` has it baked in, `viem` requires explicit calls to the ENS contracts.

Error messages can be cryptic. `viem` throws typed errors (good!) but the error objects can be deeply nested. You'll write a few `instanceof` checks.

## What's better

The TypeScript experience is genuinely superior. Less casting, fewer `any` escapes, actual compile-time guarantees. `bigint` everywhere instead of `BigNumber` (which was always a wrapper). Tree-shaking actually works. The `simulateContract` function for dry-running writes before submitting is excellent:

```typescript
// Simulate first — throws if the transaction would revert
const { request } = await publicClient.simulateContract({
  address,
  abi,
  functionName: 'transfer',
  args: [recipient, amount],
  account,
});

// If simulate didn't throw, send it
const hash = await walletClient.writeContract(request);
```

This pattern catches reverts before spending gas. `ethers` had `callStatic` for this but it wasn't as integrated into the API.

## What's just different

Unit conversion. `ethers` had `ethers.utils.parseEther` and `ethers.utils.formatEther`. `viem` has `parseEther` and `formatEther` as standalone imports. Same thing, different import path.

Signing. `ethers.utils.solidityKeccak256` becomes `keccak256(encodePacked(...))` in `viem`. More explicit about what encoding you're using, which is actually less error-prone.

Address checksumming. `viem` is strict about `Address` type (checksummed) vs plain `string`. You'll add a few `getAddress()` calls during migration.

## Migration approach

I did it incrementally. Started by replacing provider and read calls in one module, kept `ethers` for write operations until I understood the `walletClient` API. Took about a week of evenings for a medium-sized codebase.

The rough order that worked: providers first, then reads, then events, then writes. Test each step before moving on. The TypeScript errors will guide you — `viem`'s types are strict and the compiler will complain until things are right.

Worth it? Yeah. I wouldn't start a new web3 project with `ethers.js` v5 today.

3h4x