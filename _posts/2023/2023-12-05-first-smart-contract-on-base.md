---
layout: post
title: "First smart contract on Base — what surprised me"
categories: tech
tags: [solidity, base, web3, foundry]
comments: True
---

I've been writing Solidity for a while, but always on mainnet or testnets. Base launched in August 2023 and I figured it was time to try an L2 for real — deploy something, see how the tooling and gas economics actually differ. What follows is everything that surprised me — good and bad — about deploying on Base using the Foundry toolchain.

<!-- readmore -->

## Why Foundry over Hardhat

I'd been using Hardhat for most of my Solidity work — JavaScript-based, familiar ecosystem, lots of plugins. But I kept hearing that Foundry is faster and more ergonomic for people who actually want to write and test contracts, not glue together a JavaScript build pipeline. This seemed like the right project to switch.

Foundry's pitch: everything in Solidity. Write your tests in Solidity. Write your deployment scripts in Solidity. No context switching to JavaScript just to assert that a function reverted.

After using it for a few weeks: yes, the pitch is accurate. `forge test` runs in seconds. Tests feel natural when they're in the same language as the contracts.

## Setting up the toolchain

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

That's it. You get four tools:

- `forge` — build, test, deploy contracts
- `cast` — interact with chains from the command line
- `anvil` — local EVM node for development
- `chisel` — Solidity REPL for quick experiments

```bash
forge init my-contract
cd my-contract
```

The generated project structure:

```
my-contract/
├── src/
│   └── Counter.sol      # example contract
├── test/
│   └── Counter.t.sol    # example test
├── script/
│   └── Counter.s.sol    # example deploy script
├── lib/
│   └── forge-std/       # standard library (git submodule)
└── foundry.toml
```

Dependencies are git submodules — opinionated, but it means `forge install` is basically `git submodule add`. OpenZeppelin:

```bash
forge install OpenZeppelin/openzeppelin-contracts
```

Then in `foundry.toml`:

```toml
[profile.default]
src = "src"
out = "out"
libs = ["lib"]
remappings = ["@openzeppelin/=lib/openzeppelin-contracts/"]
```

## Writing the contract

For my first real deployment I wrote a simple registry — stores a mapping of address to a string value, emits events on updates. Nothing revolutionary. But it forced me to think through storage layout, events, and access control.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";

contract Registry is Ownable {
    mapping(address => string) private _entries;

    event EntrySet(address indexed account, string value);
    event EntryRemoved(address indexed account);

    constructor() Ownable(msg.sender) {}

    function set(string calldata value) external {
        require(bytes(value).length > 0, "empty value");
        require(bytes(value).length <= 256, "too long");
        _entries[msg.sender] = value;
        emit EntrySet(msg.sender, value);
    }

    function get(address account) external view returns (string memory) {
        return _entries[account];
    }

    function adminRemove(address account) external onlyOwner {
        delete _entries[account];
        emit EntryRemoved(account);
    }
}
```

Fairly basic. The interesting part was testing it.

## Testing with forge test

Foundry tests are Solidity contracts that inherit from `Test`:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/Registry.sol";

contract RegistryTest is Test {
    Registry public registry;
    address public user = makeAddr("user");

    function setUp() public {
        registry = new Registry();
    }

    function test_SetEntry() public {
        vm.prank(user);
        registry.set("hello world");
        assertEq(registry.get(user), "hello world");
    }

    function test_RevertOnEmpty() public {
        vm.prank(user);
        vm.expectRevert("empty value");
        registry.set("");
    }

    function test_AdminRemove() public {
        vm.prank(user);
        registry.set("to be deleted");

        registry.adminRemove(user);
        assertEq(registry.get(user), "");
    }

    function test_NonOwnerCannotRemove() public {
        vm.prank(user);
        registry.set("test");

        vm.prank(user);
        vm.expectRevert();
        registry.adminRemove(user);
    }
}
```

`vm.prank(address)` sets `msg.sender` for the next call. `vm.expectRevert()` asserts the next call reverts. `makeAddr("user")` generates a deterministic address from a label — useful for readable test output. These are all cheatcodes from `forge-std`.

```bash
forge test -vvv
```

The `-vvv` flag shows detailed traces including stack frames for failed tests. When a test fails, you see the exact execution path that led to the failure. Way better than "AssertionError" with no context.

```
Running 4 tests for test/Registry.t.sol:RegistryTest
[PASS] test_AdminRemove() (gas: 24891)
[PASS] test_NonOwnerCannotRemove() (gas: 18442)
[PASS] test_RevertOnEmpty() (gas: 10234)
[PASS] test_SetEntry() (gas: 46123)
Test result: ok. 4 passed; 0 failed; finished in 1.23ms
```

1.23ms for 4 tests. That's the speed difference vs Hardhat — no JavaScript overhead, no spinning up a JavaScript VM alongside the EVM.

## Gas costs: Base vs mainnet

This is where Base genuinely surprised me. On Ethereum mainnet, deploying even a small contract costs real money. A simple ERC-20 deploy might be $10-50 depending on gas prices. On Base at the time of writing:

| Operation | Mainnet (gwei) | Base (gwei) | Cost difference |
|-----------|---------------|-------------|-----------------|
| Contract deploy | ~600k gas | ~600k gas | Same gas units |
| Gas price | 10-50 gwei | 0.001-0.01 gwei | ~1000-5000x cheaper |
| Deploy cost | $5-25 | <$0.01 | Negligible |

The gas units are the same — the EVM is the EVM. The cost difference is entirely the gas price. Base's L2 batches transactions and posts them to Ethereum mainnet in compressed form, which amortizes the L1 data cost across many transactions.

For development and experimentation this is transformative. On mainnet, every wrong deploy is a $20 mistake. On Base, you can redeploy a dozen times while iterating and the total cost is rounding error.

## Deploying

The Foundry deploy script pattern:

```solidity
// script/Deploy.s.sol
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "../src/Registry.sol";

contract DeployScript is Script {
    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        vm.startBroadcast(deployerPrivateKey);

        Registry registry = new Registry();
        console.log("Registry deployed at:", address(registry));

        vm.stopBroadcast();
    }
}
```

```bash
forge script script/Deploy.s.sol:DeployScript \
  --rpc-url $BASE_RPC_URL \
  --broadcast \
  --verify \
  --etherscan-api-key $BASESCAN_API_KEY
```

The `--verify` flag submits the source code to Basescan for verification automatically. This was easier than I expected — one flag, no manual steps.

Get a Base RPC from Alchemy or Infura (both have free tiers). Basescan API key from basescan.org. Drop them in a `.env` and you're set.

## What was harder than expected

**ABI encoding.** When you're calling contracts from the frontend or with `cast`, you interact with the ABI — not human-readable function signatures. Tools abstract this, but when something goes wrong at the encoding layer, debugging is painful. Understanding `calldata` layout pays off.

**Event indexing.** I emitted events thinking I could efficiently query them from the frontend. You can, but "efficiently" depends on your RPC provider. Most free tier providers limit `eth_getLogs` range. If you need historical event data, you're looking at a subgraph or a database that syncs on-chain events.

**Local environment vs testnet vs mainnet.** Three different environments with different behavior. `anvil` is fast and forgiving. Testnet (Base Sepolia) has real latency and faucet headaches. Mainnet costs money. I kept forgetting which RPC I was pointing at.

**Immutability.** Once deployed, you can't fix bugs. Upgradeable proxy patterns (OpenZeppelin's UUPS or Transparent Proxy) solve this but add significant complexity. For my first contract I just accepted that bugs mean redeploy.

## What was easier than expected

`cast` is excellent for poking at deployed contracts:

```bash
# Read a value
cast call $CONTRACT_ADDRESS "get(address)(string)" $MY_ADDRESS --rpc-url $BASE_RPC_URL

# Send a transaction
cast send $CONTRACT_ADDRESS "set(string)" "hello" \
  --private-key $PRIVATE_KEY \
  --rpc-url $BASE_RPC_URL

# Decode a transaction input
cast 4byte-decode 0x4ed3885e...
```

The Foundry ecosystem is well-documented and the Discord is active. Most questions I had were answered in the docs or with a `forge --help`.

Also: `anvil --fork-url $BASE_RPC_URL` lets you fork the live Base state locally. You can test against real contract state without spending anything or waiting for transactions.

## Would I use Base again?

Yes. The gas costs make experimentation viable in a way that mainnet doesn't. The toolchain — `forge`, `cast`, `anvil` — is genuinely good. The fact that it's EVM-compatible means everything that works on Ethereum works here.

The main thing to internalize: this is still a blockchain. Immutable state, public data, eventual finality. The low gas costs tempt you into thinking it's just a database with a weird API. It's not. Design accordingly.

3h4x
