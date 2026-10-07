import asyncio
import math
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from custom_components.light_timeline.engine import TimelineEngine
from custom_components.light_timeline.interpolation import plan, target_at
from custom_components.light_timeline.websocket import NODE_SCHEMA, SCHEDULE_SCHEMA
from homeassistant.util.color import color_temperature_to_rgb


class FadeToWarmTests(unittest.TestCase):
    def test_brightness_endpoints_and_midpoint(self):
        for brightness, kelvin in [(0, 1200), (50, 1950), (100, 2700)]:
            with self.subTest(brightness=brightness):
                nodes = [NODE_SCHEMA({"t": 0, "b": brightness})]
                target = target_at(nodes, 0, True)
                self.assertAlmostEqual(target.brightness, brightness)
                self.assertEqual(target.kelvin, kelvin)
                self.assertIsNone(target.rgb)

    def test_uses_eased_curved_brightness(self):
        nodes = [
            NODE_SCHEMA({"t": 0, "b": 0, "ease": "ease_in", "curve": "square"}),
            NODE_SCHEMA({"t": 3600, "b": 100}),
        ]
        target = target_at(nodes, 1800, True)
        self.assertAlmostEqual(target.brightness, 6.25)
        self.assertEqual(target.kelvin, math.floor(1200 + 15 * 6.25 + 0.5))

    def test_overrides_color_without_modifying_nodes(self):
        nodes = [NODE_SCHEMA({"t": 0, "b": 50, "mode": "rgb", "rgb": [0, 0, 255]})]
        self.assertEqual(target_at(nodes, 0).rgb, (0, 0, 255))
        self.assertEqual(target_at(nodes, 0, True).kelvin, 1950)
        self.assertEqual(target_at(nodes, 0).rgb, (0, 0, 255))
        self.assertEqual(nodes[0]["rgb"], [0, 0, 255])

    def test_transition_lookahead_and_midnight(self):
        nodes = [NODE_SCHEMA({"t": 0, "b": 0}), NODE_SCHEMA({"t": 43200, "b": 100})]
        target, transition = plan(nodes, 86390, 20, True)
        self.assertEqual(target, target_at(nodes, 10, True))
        self.assertEqual(transition, 20)

    def test_step_keeps_current_brightness_and_temperature(self):
        nodes = [
            NODE_SCHEMA({"t": 0, "b": 50, "ease": "step"}),
            NODE_SCHEMA({"t": 60, "b": 100}),
        ]
        target, transition = plan(nodes, 30, 15, True)
        self.assertEqual(target.kelvin, 1950)
        self.assertEqual(transition, 0)

    def test_schedule_default_and_persistence_field(self):
        self.assertFalse(SCHEDULE_SCHEMA({"nodes": []})["fade_to_warm"])
        self.assertTrue(SCHEDULE_SCHEMA({"nodes": [], "fade_to_warm": True})["fade_to_warm"])


class FadeToWarmServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_capabilities_and_off(self):
        for modes, brightness, maximum, expected in [
            (["color_temp"], 50, 6500, {"color_temp_kelvin": 2000}),
            (["color_temp"], 100, 6500, {"color_temp_kelvin": 2700}),
            (["color_temp"], 100, 2400, {"color_temp_kelvin": 2400}),
            (["rgb"], 50, 6500, {"rgb_color": tuple(round(channel) for channel in color_temperature_to_rgb(1950))}),
            (["rgb", "color_temp"], 50, 6500, {"color_temp_kelvin": 2000}),
            (["brightness"], 50, 6500, {}),
            (["color_temp"], 0, 6500, {}),
        ]:
            with self.subTest(modes=modes, brightness=brightness):
                tasks = []
                hass = Mock()
                hass.services.async_call = AsyncMock()
                hass.async_create_task.side_effect = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
                hass.states.get.return_value = SimpleNamespace(state="on", attributes={
                    "supported_color_modes": modes,
                    "min_color_temp_kelvin": 2000,
                    "max_color_temp_kelvin": maximum,
                })
                nodes = [NODE_SCHEMA({"t": 0, "b": brightness})]
                engine = TimelineEngine(hass, SimpleNamespace(options={}), None, {
                    "schedules": {"light.demo": {"nodes": nodes, "fade_to_warm": True}},
                })
                engine._async_apply("light.demo", nodes, 0, 0)
                await asyncio.gather(*tasks)
                args = hass.services.async_call.call_args.args
                self.assertEqual(args[1], "turn_off" if brightness == 0 else "turn_on")
                color_data = {key: value for key, value in args[2].items() if key in ("rgb_color", "color_temp_kelvin")}
                self.assertEqual(color_data, expected)