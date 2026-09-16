"""Juicebox v4 on-chain reads.

Every core contract sits at the same address on every chain (deterministic deployment),
so one address book covers mainnet, the L2s and Sepolia alike.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from eth_abi import decode as abi_decode
from web3 import Web3

# EIP-55 checksummed. Strict validators (KeeperHub's included) reject a wrong-cased
# address outright, so tests/test_math.py asserts every entry here round-trips.
JB = {
    "projects": "0x0b538A02610d7d3Cc91Ce2870F423e0a34D646AD",
    "directory": "0x0bC9F153DEe4d3D474ce0903775b9b2AAae9AA41",
    "multi_terminal": "0xDB9644369c79C3633cDE70D2Df50d827D7dC7Dbc",
    "terminal_store": "0x6F6740ddA12033ca9fBAA56693194E38cfD36827",
    "fund_access_limits": "0xf1e1dF5bba779e977A27ccC273847Ab1346fCEb8",
    "rulesets": "0xDA86EeDb67C6C9FB3E58FE83Efa28674D7C89826",
    "splits": "0x9e834f2ae0970f8746E25Fba6D42FD90BB96630C",
    "prices": "0xE712D14b04F1a1Fe464Be930e3ea72B9B0a141D7",
}

MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"

# Juicebox represents native ETH with this sentinel address.
NATIVE_TOKEN = "0x000000000000000000000000000000000000EEEe"
# ...and the terminal's accounting currency id for it is 0xEEEE.
NATIVE_CURRENCY = 61166
# JBTerminalStore converts currencies at 18 decimals of fidelity.
PRICE_DECIMALS = 18
# Splits are parts of 1e9, not basis points.
SPLITS_TOTAL_PERCENT = 1_000_000_000

CHAINS: dict[str, dict[str, Any]] = {
    "ethereum": {"chain_id": 1, "rpc": "https://ethereum-rpc.publicnode.com"},
    "base": {"chain_id": 8453, "rpc": "https://base-rpc.publicnode.com"},
    "arbitrum": {"chain_id": 42161, "rpc": "https://arbitrum-one-rpc.publicnode.com"},
    "optimism": {"chain_id": 10, "rpc": "https://optimism-rpc.publicnode.com"},
    "sepolia": {"chain_id": 11155111, "rpc": "https://ethereum-sepolia-rpc.publicnode.com"},
}

RULESET_TUPLE = "(uint48,uint48,uint48,uint48,uint32,uint112,uint32,address,uint256)"
CURRENCY_AMOUNT_TUPLE = "(uint224,uint32)"
SPLIT_TUPLE = "(uint32,uint64,address,bool,uint48,address)"

ABI: dict[str, list[dict[str, Any]]] = {
    "projects": [
        {
            "name": "count",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "uint256"}],
        }
    ],
    "directory": [
        {
            "name": "primaryTerminalOf",
            "type": "function",
            "stateMutability": "view",
            "inputs": [
                {"name": "projectId", "type": "uint256"},
                {"name": "token", "type": "address"},
            ],
            "outputs": [{"type": "address"}],
        }
    ],
    "terminal_store": [
        {
            "name": "balanceOf",
            "type": "function",
            "stateMutability": "view",
            "inputs": [
                {"name": "terminal", "type": "address"},
                {"name": "projectId", "type": "uint256"},
                {"name": "token", "type": "address"},
            ],
            "outputs": [{"type": "uint256"}],
        },
        {
            "name": "usedPayoutLimitOf",
            "type": "function",
            "stateMutability": "view",
            "inputs": [
                {"name": "terminal", "type": "address"},
                {"name": "projectId", "type": "uint256"},
                {"name": "token", "type": "address"},
                {"name": "rulesetCycleNumber", "type": "uint256"},
                {"name": "currency", "type": "uint256"},
            ],
            "outputs": [{"type": "uint256"}],
        },
    ],
    "rulesets": [
        {
            "name": "currentOf",
            "type": "function",
            "stateMutability": "view",
            "inputs": [{"name": "projectId", "type": "uint256"}],
            "outputs": [
                {
                    "type": "tuple",
                    "components": [
                        {"name": "cycleNumber", "type": "uint48"},
                        {"name": "id", "type": "uint48"},
                        {"name": "basedOnId", "type": "uint48"},
                        {"name": "start", "type": "uint48"},
                        {"name": "duration", "type": "uint32"},
                        {"name": "weight", "type": "uint112"},
                        {"name": "weightCutPercent", "type": "uint32"},
                        {"name": "approvalHook", "type": "address"},
                        {"name": "metadata", "type": "uint256"},
                    ],
                }
            ],
        }
    ],
    "fund_access_limits": [
        {
            "name": "payoutLimitsOf",
            "type": "function",
            "stateMutability": "view",
            "inputs": [
                {"name": "projectId", "type": "uint256"},
                {"name": "rulesetId", "type": "uint256"},
                {"name": "terminal", "type": "address"},
                {"name": "token", "type": "address"},
            ],
            "outputs": [
                {
                    "type": "tuple[]",
                    "components": [
                        {"name": "amount", "type": "uint224"},
                        {"name": "currency", "type": "uint32"},
                    ],
                }
            ],
        }
    ],
    "prices": [
        {
            "name": "pricePerUnitOf",
            "type": "function",
            "stateMutability": "view",
            "inputs": [
                {"name": "projectId", "type": "uint256"},
                {"name": "pricingCurrency", "type": "uint256"},
                {"name": "unitCurrency", "type": "uint256"},
                {"name": "decimals", "type": "uint256"},
            ],
            "outputs": [{"type": "uint256"}],
        }
    ],
    "splits": [
        {
            "name": "splitsOf",
            "type": "function",
            "stateMutability": "view",
            "inputs": [
                {"name": "projectId", "type": "uint256"},
                {"name": "rulesetId", "type": "uint256"},
                {"name": "groupId", "type": "uint256"},
            ],
            "outputs": [
                {
                    "type": "tuple[]",
                    "components": [
                        {"name": "percent", "type": "uint32"},
                        {"name": "projectId", "type": "uint64"},
                        {"name": "beneficiary", "type": "address"},
                        {"name": "preferAddToBalance", "type": "bool"},
                        {"name": "lockedUntil", "type": "uint48"},
                        {"name": "hook", "type": "address"},
                    ],
                }
            ],
        }
    ],
    "multi_terminal": [
        {
            "name": "sendPayoutsOf",
            "type": "function",
            "stateMutability": "nonpayable",
            "inputs": [
                {"name": "projectId", "type": "uint256"},
                {"name": "token", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "currency", "type": "uint256"},
                {"name": "minTokensPaidOut", "type": "uint256"},
            ],
            "outputs": [{"type": "uint256"}],
        }
    ],
}

MULTICALL3_ABI = [
    {
        "name": "aggregate3",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "calls",
                "type": "tuple[]",
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "allowFailure", "type": "bool"},
                    {"name": "callData", "type": "bytes"},
                ],
            }
        ],
        "outputs": [
            {
                "name": "returnData",
                "type": "tuple[]",
                "components": [
                    {"name": "success", "type": "bool"},
                    {"name": "returnData", "type": "bytes"},
                ],
            }
        ],
    }
]


# --- pure money math (no chain access, so it can be tested directly) -------------------


def to_terminal_token(amount: int, price_per_unit: int) -> int:
    """Convert out of a pricing currency into the terminal's token.

    Mirrors JBTerminalStore.recordPayoutFor: mulDiv(amount, 1e18, pricePerUnit).
    """
    if price_per_unit == 0:
        return 0
    return (amount * 10**PRICE_DECIMALS) // price_per_unit


def from_terminal_token(token_amount: int, price_per_unit: int) -> int:
    """Inverse of :func:`to_terminal_token`, priced in the limit's currency."""
    return (token_amount * price_per_unit) // 10**PRICE_DECIMALS


def claimable_amount(balance: int, payout_limit: int, used_payout_limit: int) -> int:
    """Releasable amount when limit and treasury share a currency.

    A project can hold more than it may pay out this cycle, and part of the cycle's
    allowance may already be spent, so whichever runs out first is the cap.
    """
    remaining = payout_limit - used_payout_limit if payout_limit > used_payout_limit else 0
    return min(remaining, balance)


def releasable(
    balance: int, payout_limit: int, used_payout_limit: int, price_per_unit: int
) -> tuple[int, int]:
    """Return ``(amount_to_request, expected_payout)``.

    sendPayoutsOf takes its amount in the *limit's* currency, so a project whose limit is
    denominated elsewhere needs the request in that currency even though ETH is what
    leaves the treasury. Pass ``price_per_unit=0`` when no conversion is needed.
    """
    same_currency = price_per_unit == 0
    remaining = payout_limit - used_payout_limit if payout_limit > used_payout_limit else 0
    remaining_in_token = remaining if same_currency else to_terminal_token(remaining, price_per_unit)

    if remaining_in_token <= balance:
        return remaining, remaining_in_token

    # The treasury, not the allowance, is the binding constraint: ask only for what it can
    # cover. Integer division floors, so this rounds down and never over-requests.
    amount_to_request = balance if same_currency else from_terminal_token(balance, price_per_unit)
    expected = balance if same_currency else to_terminal_token(amount_to_request, price_per_unit)
    return amount_to_request, expected


# --- chain access ---------------------------------------------------------------------


@dataclass
class Candidate:
    project_id: int
    balance: int
    payout_limit: int
    used_payout_limit: int
    amount_to_request: int  # denominated in `currency`
    claimable: int  # what should actually leave the treasury
    currency: int
    price_per_unit: int
    ruleset_id: int
    cycle_number: int


@dataclass
class Skipped:
    project_id: int
    balance: int
    reason: str


@dataclass
class ScanResult:
    chain: str
    project_count: int
    candidates: list[Candidate]
    skipped: list[Skipped]


def web3_for(chain: str) -> Web3:
    if chain not in CHAINS:
        raise ValueError(f"unknown chain {chain!r}; known: {', '.join(CHAINS)}")
    # RPC_URL_<CHAIN> lets an operator swap in a private endpoint; public nodes rate-limit.
    url = os.environ.get(f"RPC_URL_{chain.upper()}") or CHAINS[chain]["rpc"]
    return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 60}))


def _chunks(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def multicall(
    w3: Web3, calls: list[tuple[str, str, list[Any]]], output_types: list[str], batch: int = 60
) -> list[Any | None]:
    """Batch view calls through Multicall3.

    `calls` are ``(contract_key, function_name, args)``. Returns a list positionally
    matching `calls`, with ``None`` where an individual call reverted.
    """
    if not calls:
        return []

    mc = w3.eth.contract(address=Web3.to_checksum_address(MULTICALL3), abi=MULTICALL3_ABI)
    encoded = []
    for key, fn, args in calls:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(JB[key]), abi=ABI[key]
        )
        encoded.append(
            (Web3.to_checksum_address(JB[key]), True, contract.encode_abi(fn, args=args))
        )

    out: list[Any | None] = []
    for group_calls, group_types in zip(
        _chunks(encoded, batch), _chunks(output_types, batch), strict=True
    ):
        results = mc.functions.aggregate3(list(group_calls)).call()
        for (ok, data), types in zip(results, group_types, strict=True):
            if not ok or not data:
                out.append(None)
                continue
            try:
                decoded = abi_decode([types], data)[0]
            except Exception:
                out.append(None)
                continue
            out.append(decoded)
    return out


def scan_chain(chain: str) -> ScanResult:
    w3 = web3_for(chain)
    projects = w3.eth.contract(
        address=Web3.to_checksum_address(JB["projects"]), abi=ABI["projects"]
    )
    project_count = projects.functions.count().call()
    ids = list(range(1, project_count + 1))

    skipped: list[Skipped] = []

    # A project can route funds through a terminal we do not know how to drive, so read
    # each project's own terminal rather than assuming JBMultiTerminal.
    terminals = multicall(
        w3,
        [("directory", "primaryTerminalOf", [pid, NATIVE_TOKEN]) for pid in ids],
        ["address"] * len(ids),
    )
    known = JB["multi_terminal"].lower()
    on_known_terminal = []
    for pid, terminal in zip(ids, terminals, strict=True):
        if terminal is None:
            continue
        addr = str(terminal).lower()
        if addr == "0x" + "0" * 40:
            continue
        if addr == known:
            on_known_terminal.append(pid)
        else:
            skipped.append(Skipped(pid, 0, "other-terminal"))

    balances = multicall(
        w3,
        [
            ("terminal_store", "balanceOf", [JB["multi_terminal"], pid, NATIVE_TOKEN])
            for pid in on_known_terminal
        ],
        ["uint256"] * len(on_known_terminal),
    )
    balance_of = {
        pid: bal
        for pid, bal in zip(on_known_terminal, balances, strict=True)
        if bal is not None
    }
    funded = [pid for pid in on_known_terminal if balance_of.get(pid, 0) > 0]
    if not funded:
        return ScanResult(chain, project_count, [], skipped)

    rulesets = multicall(
        w3,
        [("rulesets", "currentOf", [pid]) for pid in funded],
        [RULESET_TUPLE] * len(funded),
    )
    with_ruleset = []
    for pid, ruleset in zip(funded, rulesets, strict=True):
        if ruleset is None:
            continue
        cycle_number, ruleset_id = ruleset[0], ruleset[1]
        if ruleset_id == 0:
            continue
        with_ruleset.append((pid, ruleset_id, cycle_number))

    limits = multicall(
        w3,
        [
            ("fund_access_limits", "payoutLimitsOf", [pid, rid, JB["multi_terminal"], NATIVE_TOKEN])
            for pid, rid, _ in with_ruleset
        ],
        [f"{CURRENCY_AMOUNT_TUPLE}[]"] * len(with_ruleset),
    )

    # A project can carry several payout limits, one per currency; evaluate every row and
    # keep whichever releases the most.
    rows = []
    for (pid, rid, cycle), limit_rows in zip(with_ruleset, limits, strict=True):
        balance = balance_of.get(pid, 0)
        if limit_rows is None:
            continue
        if len(limit_rows) == 0:
            skipped.append(Skipped(pid, balance, "no-payout-limit"))
            continue
        for amount, currency in limit_rows:
            rows.append((pid, rid, cycle, balance, amount, currency))

    needs_price = [row for row in rows if row[5] != NATIVE_CURRENCY]
    prices = multicall(
        w3,
        [
            ("prices", "pricePerUnitOf", [pid, currency, NATIVE_CURRENCY, PRICE_DECIMALS])
            for pid, _, _, _, _, currency in needs_price
        ],
        ["uint256"] * len(needs_price),
    )
    price_of = {
        (row[0], row[5]): price
        for row, price in zip(needs_price, prices, strict=True)
        if price is not None
    }

    used_limits = multicall(
        w3,
        [
            (
                "terminal_store",
                "usedPayoutLimitOf",
                [JB["multi_terminal"], pid, NATIVE_TOKEN, cycle, currency],
            )
            for pid, _, cycle, _, _, currency in rows
        ],
        ["uint256"] * len(rows),
    )

    best: dict[int, Candidate] = {}
    for (pid, rid, cycle, balance, limit, currency), used in zip(
        rows, used_limits, strict=True
    ):
        is_native = currency == NATIVE_CURRENCY
        price = 0 if is_native else price_of.get((pid, currency))
        if not is_native and not price:
            skipped.append(Skipped(pid, balance, "no-price-feed"))
            continue
        used = used or 0
        amount_to_request, expected = releasable(balance, limit, used, price or 0)
        if expected == 0:
            continue
        candidate = Candidate(
            project_id=pid,
            balance=balance,
            payout_limit=limit,
            used_payout_limit=used,
            amount_to_request=amount_to_request,
            claimable=expected,
            currency=currency,
            price_per_unit=price or 0,
            ruleset_id=rid,
            cycle_number=cycle,
        )
        current = best.get(pid)
        if current is None or candidate.claimable > current.claimable:
            best[pid] = candidate

    candidates = sorted(best.values(), key=lambda c: c.claimable, reverse=True)
    return ScanResult(chain, project_count, candidates, skipped)
