"""Command line entry point: find and plan Juicebox payouts."""

from __future__ import annotations

import sys
from collections import defaultdict
from decimal import Decimal

from .juicebox import (
    CHAINS,
    JB,
    NATIVE_TOKEN,
    ScanResult,
    scan_chain,
)


def format_eth(wei: int) -> str:
    """Wei as a plain decimal string, without exponent notation or trailing zeros."""
    value = Decimal(wei) / Decimal(10**18)
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def report(result: ScanResult) -> int:
    total = sum(c.claimable for c in result.candidates)
    # Plain ASCII: the Windows console default code page mangles anything fancier.
    print(f"\n=== {result.chain} - {result.project_count} projects ===")

    if not result.candidates:
        print("no releasable payouts found")
    else:
        print(
            f"{len(result.candidates)} project(s) holding "
            f"{format_eth(total)} ETH that anyone can release now\n"
        )
        print("  project    claimable ETH    balance ETH      priced in")
        for c in result.candidates[:20]:
            priced = "ETH" if c.price_per_unit == 0 else f"currency {c.currency}"
            print(
                f"  #{str(c.project_id):<8} {format_eth(c.claimable):<16} "
                f"{format_eth(c.balance):<16} {priced}"
            )
        if len(result.candidates) > 20:
            print(f"  ... and {len(result.candidates) - 20} more")

    grouped: dict[str, list[int]] = defaultdict(list)
    for s in result.skipped:
        grouped[s.reason].append(s.balance)
    if grouped:
        print("\n  skipped:")
        for reason, balances in grouped.items():
            print(
                f"    {len(balances):>3} {reason:<22} holding {format_eth(sum(balances))} ETH"
            )
    return total


def scan(args: list[str]) -> None:
    names = args or list(CHAINS)
    unknown = [n for n in names if n not in CHAINS]
    if unknown:
        print(f"unknown chain: {unknown[0]} (known: {', '.join(CHAINS)})", file=sys.stderr)
        raise SystemExit(1)

    grand_total = 0
    for name in names:
        try:
            grand_total += report(scan_chain(name))
        except Exception as err:  # a dead RPC should not abort the other chains
            print(f"\n=== {name} - scan failed ===")
            print(f"  {str(err).splitlines()[0]}")
    print(f"\nTotal releasable across scanned chains: {format_eth(grand_total)} ETH\n")


def plan(args: list[str]) -> None:
    """Print the exact sendPayoutsOf call so it can be reviewed before anything is signed."""
    if len(args) != 2 or args[0] not in CHAINS:
        print("usage: plan <chain> <projectId>", file=sys.stderr)
        raise SystemExit(1)
    chain, project_id = args[0], int(args[1])

    result = scan_chain(chain)
    match = next((c for c in result.candidates if c.project_id == project_id), None)
    if match is None:
        print(f"project #{project_id} on {chain} has nothing releasable right now")
        return

    print(f"\nsendPayoutsOf on {chain} - project #{match.project_id}")
    print(f"  terminal         {JB['multi_terminal']}")
    print(f"  projectId        {match.project_id}")
    print(f"  token            {NATIVE_TOKEN}")
    print(f"  amount           {match.amount_to_request}   (denominated in currency {match.currency})")
    print(f"  currency         {match.currency}")
    print("  minTokensPaidOut 0")
    print(f"\n  expected payout  {format_eth(match.claimable)} ETH")
    print(f"  treasury holds   {format_eth(match.balance)} ETH")
    if match.price_per_unit:
        print(f"  price used       {format_eth(match.price_per_unit)} per ETH (JBPrices)")
    print()


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    command, args = (argv[0], argv[1:]) if argv else ("", [])
    if command == "scan":
        scan(args)
    elif command == "plan":
        plan(args)
    else:
        print("usage: scan [chain...] | plan <chain> <projectId>", file=sys.stderr)
        print(f"chains: {', '.join(CHAINS)}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
