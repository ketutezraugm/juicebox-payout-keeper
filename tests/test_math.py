"""The money math, tested directly. Run: python -m unittest discover -s tests"""

import unittest

from keeper.juicebox import (
    claimable_amount,
    from_terminal_token,
    releasable,
    to_terminal_token,
)

ETH = 10**18
UNIT = 10**18
# A feed quoting 2000 units per ETH, at the 18 decimals JBTerminalStore asks for.
PRICE = 2000 * ETH


class ClaimableAmount(unittest.TestCase):
    def test_releases_full_balance_when_allowance_is_larger(self):
        self.assertEqual(claimable_amount(balance=5, payout_limit=100, used_payout_limit=0), 5)

    def test_caps_at_allowance_when_treasury_holds_more(self):
        self.assertEqual(claimable_amount(balance=100, payout_limit=30, used_payout_limit=0), 30)

    def test_subtracts_what_the_cycle_already_paid(self):
        self.assertEqual(claimable_amount(balance=100, payout_limit=30, used_payout_limit=10), 20)

    def test_nothing_once_allowance_is_spent(self):
        self.assertEqual(claimable_amount(balance=100, payout_limit=30, used_payout_limit=30), 0)

    def test_never_negative_when_limit_lowered_mid_cycle(self):
        # The owner can lower a limit below what the cycle already paid out; the
        # subtraction must not wrap into a large positive number.
        self.assertEqual(claimable_amount(balance=100, payout_limit=30, used_payout_limit=50), 0)

    def test_nothing_from_an_empty_treasury(self):
        self.assertEqual(claimable_amount(balance=0, payout_limit=100, used_payout_limit=0), 0)


class CurrencyConversion(unittest.TestCase):
    def test_converts_into_eth_at_the_quoted_price(self):
        self.assertEqual(to_terminal_token(2000 * UNIT, PRICE), 1 * ETH)

    def test_converts_eth_back_into_the_amount_to_request(self):
        self.assertEqual(from_terminal_token(1 * ETH, PRICE), 2000 * UNIT)

    def test_missing_feed_converts_to_nothing_not_a_wrong_number(self):
        self.assertEqual(to_terminal_token(2000 * UNIT, 0), 0)


class Releasable(unittest.TestCase):
    def test_priced_limit_requests_units_and_expects_eth(self):
        self.assertEqual(
            releasable(balance=10 * ETH, payout_limit=2000 * UNIT, used_payout_limit=0, price_per_unit=PRICE),
            (2000 * UNIT, 1 * ETH),
        )

    def test_thin_treasury_caps_the_request(self):
        # Allowance is 2000 units (1 ETH) but only 0.5 ETH is held, so ask for 1000.
        self.assertEqual(
            releasable(balance=ETH // 2, payout_limit=2000 * UNIT, used_payout_limit=0, price_per_unit=PRICE),
            (1000 * UNIT, ETH // 2),
        )

    def test_same_currency_needs_no_conversion(self):
        self.assertEqual(
            releasable(balance=5 * ETH, payout_limit=3 * ETH, used_payout_limit=1 * ETH, price_per_unit=0),
            (2 * ETH, 2 * ETH),
        )


if __name__ == "__main__":
    unittest.main()
