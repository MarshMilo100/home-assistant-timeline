import unittest

import voluptuous as vol

from custom_components.light_timeline.interpolation import EASINGS, eased_progress, plan, target_at
from custom_components.light_timeline.websocket import NODE_SCHEMA


class IndependentEasingTests(unittest.TestCase):
    def test_legacy_segments_keep_exact_progress(self):
        for name, easing in EASINGS.items():
            for progress in (0, 0.1, 0.25, 0.5, 0.75, 0.99):
                self.assertEqual(eased_progress({"ease": name}, {"ease": "ease_out"}, progress), easing(progress))

    def test_outgoing_and_incoming_settings_both_influence_segment(self):
        start = {"t": 0, "b": 0, "ease_out": "linear"}
        end = {"t": 100, "b": 100, "ease_in": "ease_in"}
        self.assertAlmostEqual(target_at([start, end], 25).brightness, 20.3125)
        self.assertAlmostEqual(target_at([start, end], 75).brightness, 60.9375)
        start["ease_out"] = "ease_out"
        self.assertAlmostEqual(target_at([start, end], 25).brightness, 34.375)

    def test_all_continuous_combinations_are_monotonic_and_bounded(self):
        for outgoing in EASINGS:
            for incoming in EASINGS:
                if "step" in (outgoing, incoming):
                    continue
                values = [eased_progress({"ease_out": outgoing}, {"ease_in": incoming}, index / 100) for index in range(101)]
                self.assertEqual(values[0], 0)
                self.assertEqual(values[-1], 1)
                self.assertTrue(all(0 <= value <= 1 for value in values), (outgoing, incoming))
                self.assertTrue(all(left <= right for left, right in zip(values, values[1:])), (outgoing, incoming))

    def test_step_on_either_side_holds_until_node(self):
        for start, end in [
            ({"t": 0, "b": 0, "ease_out": "step"}, {"t": 100, "b": 100, "ease_in": "linear"}),
            ({"t": 0, "b": 0, "ease_out": "linear"}, {"t": 100, "b": 100, "ease_in": "step"}),
        ]:
            target, transition = plan([start, end], 90, 15)
            self.assertEqual(target.brightness, 0)
            self.assertEqual(transition, 0)
            self.assertEqual(target_at([start, end], 100).brightness, 100)

    def test_schema_preserves_explicit_settings_and_legacy_fallback(self):
        node = NODE_SCHEMA({"t": 0, "b": 50, "ease_in": "sine", "ease_out": "ease_in"})
        self.assertEqual((node["ease_in"], node["ease_out"]), ("sine", "ease_in"))
        self.assertNotIn("ease_in", NODE_SCHEMA({"t": 0, "b": 50}))
        with self.assertRaises(vol.Invalid):
            NODE_SCHEMA({"t": 0, "b": 50, "ease_in": "unknown"})