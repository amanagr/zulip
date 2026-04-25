import sys
import unittest
from unittest.mock import patch

try:
    from tools.lib.run_dev_helpers import (
        DEFAULT_BASE_PORT,
        FALLBACK_BASE_PORTS,
        PORTS_PER_INSTANCE,
        is_port_range_available,
        pick_base_port,
    )
except ImportError:
    print("ERROR!!! You need to run this via tools/test-tools.")
    sys.exit(1)


class PickBasePortTest(unittest.TestCase):
    def test_explicit_request_returned_unchanged(self) -> None:
        # An explicit --base-port wins, even if the requested port is
        # outside the fallback list and even if it's busy: the user
        # gets a clear bind error at listener startup, not silent
        # rerouting to a different port.
        with patch(
            "tools.lib.run_dev_helpers.is_port_range_available", return_value=False
        ) as mocked:
            self.assertEqual(pick_base_port(8080, None), 8080)
            mocked.assert_not_called()

    def test_picks_default_when_free(self) -> None:
        with patch("tools.lib.run_dev_helpers.is_port_range_available", return_value=True):
            self.assertEqual(pick_base_port(None, None), DEFAULT_BASE_PORT)

    def test_falls_back_to_next_free_range(self) -> None:
        # 9991 busy, 9971 free; pick 9971.
        with patch(
            "tools.lib.run_dev_helpers.is_port_range_available",
            side_effect=[False, True, True, True],
        ):
            self.assertEqual(pick_base_port(None, None), 9971)

    def test_falls_back_through_to_last_candidate(self) -> None:
        # First three busy, fourth free.
        with patch(
            "tools.lib.run_dev_helpers.is_port_range_available",
            side_effect=[False, False, False, True],
        ):
            self.assertEqual(pick_base_port(None, None), FALLBACK_BASE_PORTS[-1])

    def test_returns_none_when_every_range_busy(self) -> None:
        # All four candidates busy: caller must surface an error and exit.
        with patch("tools.lib.run_dev_helpers.is_port_range_available", return_value=False):
            self.assertIsNone(pick_base_port(None, None))


class IsPortRangeAvailableTest(unittest.TestCase):
    def test_probes_full_six_port_range(self) -> None:
        # The probe must check all six ports starting at base, not
        # just the proxy port.  Otherwise a stray Tornado on +2 would
        # let run-dev start with a doomed base.
        with patch("tools.lib.run_dev_helpers.is_port_available", return_value=True) as mocked:
            self.assertTrue(is_port_range_available(9991, None))
            calls = [call.args for call in mocked.call_args_list]
            self.assertEqual(
                calls,
                [(9991 + offset, None) for offset in range(PORTS_PER_INSTANCE)],
            )

    def test_short_circuits_on_first_busy_port(self) -> None:
        # If +0 is busy, we don't bother probing +1..+5.
        with patch(
            "tools.lib.run_dev_helpers.is_port_available",
            side_effect=[False, True, True, True, True, True],
        ) as mocked:
            self.assertFalse(is_port_range_available(9991, None))
            self.assertEqual(mocked.call_count, 1)

    def test_detects_collision_in_middle_of_range(self) -> None:
        # +0..+1 free, +2 busy: range is unusable.
        with patch(
            "tools.lib.run_dev_helpers.is_port_available",
            side_effect=[True, True, False, True, True, True],
        ):
            self.assertFalse(is_port_range_available(9991, None))


class FallbackPortsTest(unittest.TestCase):
    def test_fallback_ranges_do_not_overlap_test_base(self) -> None:
        # The test base port (9981) and its derived ports (9981..9986)
        # must not collide with any fallback proxy base or its derived
        # +1..+5 ports.  The 20-port stride makes this work, but a
        # future change to the constants could regress it silently.
        from tools.lib.run_dev_helpers import TEST_BASE_PORT

        test_range = set(range(TEST_BASE_PORT, TEST_BASE_PORT + PORTS_PER_INSTANCE))
        for base in FALLBACK_BASE_PORTS:
            fallback_range = set(range(base, base + PORTS_PER_INSTANCE))
            self.assertEqual(
                fallback_range & test_range,
                set(),
                f"Fallback {base}..{base + PORTS_PER_INSTANCE - 1} overlaps test range "
                f"{TEST_BASE_PORT}..{TEST_BASE_PORT + PORTS_PER_INSTANCE - 1}",
            )

    def test_fallback_ranges_do_not_overlap_each_other(self) -> None:
        # Each fallback claims 6 ports; with a 20-port stride between
        # bases, no two ranges should overlap.
        seen: set[int] = set()
        for base in FALLBACK_BASE_PORTS:
            range_ports = set(range(base, base + PORTS_PER_INSTANCE))
            self.assertEqual(
                seen & range_ports, set(), f"Fallback {base} overlaps an earlier fallback"
            )
            seen |= range_ports
