# Juicebox Payout Keeper

**KeeperHub as the execution layer for Juicebox v4 treasuries.**

Juicebox projects don't pay anyone automatically. Funds only leave a project's treasury when
someone calls `JBMultiTerminal.sendPayoutsOf(...)`. That call is permissionless — anyone can make
it — and it has to happen *every ruleset cycle*. When nobody remembers, contributors don't get
paid and the money simply sits there.

This is a keeper for that gap. It finds projects with releasable payouts, and releases them
through KeeperHub: reviewed before signing, dry-run before broadcast, verified on-chain after.

---

## The problem is real, and measurable

The scanner reads live protocol state. At the time of writing (16 Sep 2026):

| Chain | Projects with releasable payouts | Sitting unreleased |
|---|---|---|
| Ethereum | 18 | 0.90 ETH |
| Base | 13 | 1.27 ETH |
| Sepolia | 26 | 0.18 ETH |

**2.17 ETH across 31 live mainnet projects**, releasable by anyone, right now. The largest single
one is Base project #158 holding 1.01 ETH. Re-run `python -m keeper.cli scan` for today's numbers.

These aren't estimates — each figure is `min(treasury balance, remaining cycle allowance)`,
computed the same way the protocol computes it, and confirmed by dry-running the real call:

```
sendPayoutsOf on Base #158 -> wouldRevert: false, would release 1.01 ETH
```

---

## Proof it executes

A keeper workflow, composed by an agent through KeeperHub's MCP server, released a real payout:

**[`0x2fa244e094eecae0dcfc09d3894e3d1a6e7b9261972ee2e4b4373846a74192c0`](https://sepolia.etherscan.io/tx/0x2fa244e094eecae0dcfc09d3894e3d1a6e7b9261972ee2e4b4373846a74192c0)**

- Sepolia project **#279**, treasury `0.002409 ETH` → **`0`**
- Funds went to the project's own three configured recipients (92.3% / 5.1% / 2.6%)
- `sendPayoutsOf(279, 0x…EEEe, 2409000000000000, 61166, 0)`, `reverted: false`
- Block 11717544, `receiptStatus: success`, on-chain verified by KeeperHub before the run finalised
- Gas sponsored by KeeperHub — the keeper cost nothing to operate
- Whole run: 23 seconds

Project #279 is **not ours**. We released someone else's payouts, to their recipients, and paid
nothing to do it. That is what a keeper is for.

### It also refuses correctly

Running the same workflow once the treasury was empty:

```
Check Treasury Balance -> "0"
Anything To Release    -> "0" > 0  =>  false
Release Payouts        -> never ran
transactionHashes: []
```

3 of 4 steps, no broadcast, no gas, 268ms — and the run is still recorded as a success, because
declining to act was the correct outcome. Nothing is inferred at execution time.

---

## How it works

```
  scan (this repo)          compose (agent, via MCP)        execute (KeeperHub)
  ----------------          ------------------------        -------------------
  read protocol state  -->  Schedule trigger            -->  simulate
  across 5 chains           Read treasury balance            broadcast
  rank by claimable         Condition: anything to send?     verify receipt on-chain
                            Write: sendPayoutsOf             audit trail
```

The Python side does discovery and arithmetic. KeeperHub does everything that makes on-chain
execution survivable — nonce handling, gas, retries, receipt verification, audit trail. No part of
this repo signs a transaction or holds a key.

### The money math

A project may hold more than it is allowed to pay out this cycle, and part of that cycle's
allowance may already be spent, so the releasable amount is whichever runs out first:

```python
remaining = payout_limit - used_payout_limit   # floored at 0
claimable = min(remaining, treasury_balance)
```

Payout limits are frequently denominated in a currency other than the token being paid out. The
conversion mirrors `JBTerminalStore.recordPayoutFor` exactly:

```python
amount_in_token = amount * 10**18 // price_per_unit   # JBPrices.pricePerUnitOf(..., decimals=18)
```

This matters: `sendPayoutsOf` takes its `amount` in the **limit's** currency, not in the token, so
the request has to be converted back. Skipping this was the difference between the scanner
reporting "0 ETH releasable on mainnet" and the true 2.17 ETH — most real projects don't denominate
in the raw token.

---

## Usage

```bash
pip install -r requirements.txt

python -m keeper.cli scan                     # all chains
python -m keeper.cli scan base ethereum       # specific chains
python -m keeper.cli plan base 158            # exact call args, before anything is signed
python -m unittest discover -s tests          # 12 tests, no network needed
```

Public RPCs are used by default and will rate-limit. Override per chain:

```bash
export RPC_URL_ETHEREUM=https://...
```

`plan` prints the precise arguments for review. Nothing in this repo broadcasts; execution happens
through KeeperHub, where it can be simulated and inspected first.

---

## Layout

| Path | Purpose |
|---|---|
| `keeper/juicebox.py` | Addresses, ABIs, the money math, multicall scanning |
| `keeper/cli.py` | `scan` and `plan` |
| `tests/test_math.py` | The releasable/conversion logic, incl. the underflow and missing-feed cases |

Juicebox v4 deploys every core contract at the same address on every chain, so one address book
covers mainnet, the L2s and Sepolia.

## KeeperHub surfaces used

MCP server (workflow authoring, validation, direct execution, execution logs) · agent-authored
workflows · dry-run simulation · on-chain receipt verification · gas sponsorship · audit trail.

---

## What still breaks

Honest list.

- **The scanner assumes `JBMultiTerminal`.** Projects on a custom terminal are counted and reported
  as `other-terminal`, not evaluated. 4 such projects on Base.
- **The deployed workflow hardcodes one project.** Generating a workflow per discovered project is
  mechanical but isn't wired up; today the agent composes them one at a time.
- **The workflow's condition is `balance > 0`, not the full claimable calculation.** For project
  #279 the payout limit is effectively unbounded, so the two agree. For a project whose treasury
  exceeds its cycle allowance the workflow would request too much and the call would revert — the
  dry run catches it, but the workflow should compute `min()` itself. The CLI already does.
- **Non-native payout currencies are converted at read time**, so a price move between scan and
  execution shifts the amount. `minTokensPaidOut` is set to `0`; it should be a floor derived from
  the quote.
- **No notification step.** Discord/Telegram nodes exist in KeeperHub and aren't wired in.
- **Scanning is sequential per chain** and takes ~30s on a public RPC for mainnet. Fine for a keeper
  that runs hourly; slow if you're iterating.
- **Only native-token payouts.** Projects paying out ERC-20s are out of scope.

## Notes

Juicebox's own web app was mid-migration to v6 during this build and its project-deploy flow
returned 500s, so everything here talks to the v4 contracts directly. v5 is a fork of v4 fixing a
buyback-hook bug that this keeper doesn't touch.
