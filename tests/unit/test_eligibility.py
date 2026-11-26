import unittest

from mcp_history_security.data.histor.eligibility import (
    Transition,
    eligible_window,
    select_window,
)


class WindowTests(unittest.TestCase):
    def test_preserves_immediate_predecessor(self) -> None:
        transitions = (
            Transition("a", "b", True),
            Transition("b", "c", False),
            Transition("c", "d", True),
        )
        self.assertTrue(eligible_window(transitions, 2))
        self.assertTrue(eligible_window(transitions, 3))
        self.assertEqual(select_window(transitions, 4), ("a", "b", "c", "d"))
        self.assertEqual(select_window(transitions, 3), ("b", "c", "d"))

    def test_gap_outside_window(self) -> None:
        transitions = (
            Transition(None, "a", True, False),
            Transition("a", "b", True),
            Transition("b", "c", True),
        )
        self.assertTrue(eligible_window(transitions, 3))
        self.assertFalse(eligible_window(transitions, 4))

    def test_incomplete_latest_target_is_not_replaced(self) -> None:
        transitions = (Transition("a", "b", True), Transition("b", None, True))
        self.assertFalse(eligible_window(transitions, 2))

    def test_reversion(self) -> None:
        transitions = (Transition("a", "b", True), Transition("b", "a", True))
        self.assertTrue(eligible_window(transitions, 3))

    def test_prior_reversion_retains_chronological_state(self) -> None:
        transitions = (
            Transition("a", "b", True),
            Transition("b", "a", True),
            Transition("a", "c", True),
        )
        self.assertTrue(eligible_window(transitions, 4))


if __name__ == "__main__":
    unittest.main()
