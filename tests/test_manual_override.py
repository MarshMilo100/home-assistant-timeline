import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.core import Context

from custom_components.light_timeline.const import DEFAULT_RESUME_TRANSITION
from custom_components.light_timeline.engine import TimelineEngine
from custom_components.light_timeline.websocket import SCHEDULE_SCHEMA


class ManualOverrideTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        self.tasks = []
        self.hass = Mock()
        self.hass.config = SimpleNamespace(latitude=0, longitude=0, elevation=0, time_zone="UTC")
        self.hass.states.async_entity_ids.return_value = ["light.demo"]
        self.hass.services.async_call = AsyncMock()
        self.hass.async_create_task.side_effect = lambda coroutine: self.tasks.append(asyncio.create_task(coroutine))
        self.schedule = SCHEDULE_SCHEMA({"nodes": [
            {"t": 0, "b": 0, "ease": "ease_in", "curve": "square"},
            {"t": 43260, "b": 100, "ease": "linear", "mode": "ct", "k": 4000},
        ]})
        self.engine = TimelineEngine(self.hass, SimpleNamespace(options={}), None, {"schedules": {"light.demo": self.schedule}})
        self.state = self.make_state(0, "off")
        self.hass.states.get.side_effect = lambda entity_id: self.state
        self.clock = patch("custom_components.light_timeline.engine.dt_util.now", side_effect=lambda: self.now)
        self.sun = patch("custom_components.light_timeline.engine.solar_events", return_value={"sunrise": 21600, "sunset": 64800})
        self.clock.start()
        self.sun.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.sun.stop)

    def make_state(self, brightness, state="on", context=None, **attributes):
        return SimpleNamespace(state=state, context=context or Context(), attributes={
            "brightness": brightness, "supported_color_modes": ["color_temp"],
            "color_mode": "color_temp", "color_temp_kelvin": 2200,
            "min_color_temp_kelvin": 1000, "max_color_temp_kelvin": 6500, **attributes,
        })

    def change(self, old, new):
        self.state = new
        self.engine._async_state_changed(SimpleNamespace(data={"entity_id": "light.demo", "old_state": old, "new_state": new}))

    async def apply(self):
        self.engine._async_apply("light.demo", self.schedule["nodes"], 43200, 15)
        if self.tasks:
            await asyncio.gather(*self.tasks)
            self.tasks.clear()

    async def test_manual_off_holds_until_node_then_uses_incoming_easing_and_curve(self):
        self.change(self.make_state(255), self.make_state(0, "off"))
        await self.apply()
        self.hass.services.async_call.assert_not_called()
        override = self.engine._overrides["light.demo"]
        self.assertEqual(override.ease, "ease_in")
        self.assertEqual(override.curve, "square")
        self.now += timedelta(seconds=60)
        await self.apply()
        self.now += timedelta(seconds=29)
        await self.apply()
        data = self.hass.services.async_call.call_args.args[2]
        self.assertEqual(data["brightness"], 16)
        self.assertEqual(data["transition"], 1)
        self.assertAlmostEqual(data["color_temp_kelvin"], 2479, delta=1)
        self.now += timedelta(seconds=31)
        await self.apply()
        self.assertNotIn("light.demo", self.engine._overrides)
        self.assertEqual(self.hass.services.async_call.call_args.args[2]["brightness"], 255)

    async def test_on_to_on_brightness_and_temperature_changes_hold(self):
        old = self.make_state(200)
        for new in [self.make_state(50), self.make_state(200, color_temp_kelvin=3000)]:
            self.change(old, new)
            await self.apply()
            self.assertIn("light.demo", self.engine._overrides)
        self.hass.services.async_call.assert_not_called()

    async def test_own_delayed_context_and_metadata_updates_do_not_hold(self):
        await self.apply()
        context = self.hass.services.async_call.call_args.kwargs["context"]
        self.change(self.make_state(100), self.make_state(120, context=context))
        self.assertFalse(self.engine._overrides)
        self.change(self.make_state(100), self.make_state(100, extra_metadata=1))
        self.assertFalse(self.engine._overrides)
        self.change(self.make_state(100), self.make_state(120, context=Context(parent_id=context.id)))
        self.assertFalse(self.engine._overrides)

    async def test_repeated_manual_change_interrupts_recovery(self):
        self.change(self.make_state(255), self.make_state(0, "off"))
        self.now += timedelta(seconds=60)
        await self.apply()
        self.change(self.state, self.make_state(128, color_temp_kelvin=3000))
        self.assertIsNone(self.engine._overrides["light.demo"].started)
        self.hass.services.async_call.reset_mock()
        await self.apply()
        self.hass.services.async_call.assert_not_called()

    async def test_next_event_skips_inactive_days(self):
        self.schedule["days"] = [4]
        self.change(self.make_state(255), self.make_state(0, "off"))
        deadline = datetime.fromtimestamp(self.engine._overrides["light.demo"].deadline, timezone.utc)
        self.assertEqual(deadline.weekday(), 4)

    async def test_step_recovery_holds_then_jumps(self):
        self.schedule["nodes"][0]["ease"] = "step"
        self.change(self.make_state(255), self.make_state(0, "off"))
        self.now += timedelta(seconds=60)
        await self.apply()
        self.now += timedelta(seconds=30)
        await self.apply()
        self.assertEqual(self.hass.services.async_call.call_args.args[1], "turn_off")
        self.now += timedelta(seconds=DEFAULT_RESUME_TRANSITION)
        await self.apply()
        self.assertEqual(self.hass.services.async_call.call_args.args[1], "turn_on")

    async def test_tick_uses_one_second_updates_from_first_recovery_step(self):
        self.change(self.make_state(255), self.make_state(0, "off"))
        self.now += timedelta(seconds=60)
        self.engine._active = Mock(return_value={"light.demo": self.schedule["nodes"]})
        with patch("custom_components.light_timeline.engine._seconds_of_day", return_value=43260), patch("custom_components.light_timeline.engine.async_call_later") as timer:
            self.engine._async_tick()
        await asyncio.gather(*self.tasks)
        self.tasks.clear()
        self.assertEqual(timer.call_args.args[1], 1)
        self.assertIsNotNone(self.engine._overrides["light.demo"].started)

    async def test_new_scheduled_node_preempts_recovery(self):
        self.schedule["nodes"].append({"t": 43270, "b": 20, "mode": "none", "ease": "step", "curve": "linear"})
        self.change(self.make_state(255), self.make_state(0, "off"))
        self.now += timedelta(seconds=60)
        await self.apply()
        self.now += timedelta(seconds=10)
        self.engine._async_apply("light.demo", self.schedule["nodes"], 43270, 1)
        await asyncio.gather(*self.tasks)
        self.tasks.clear()
        self.assertNotIn("light.demo", self.engine._overrides)
        self.assertEqual(self.hass.services.async_call.call_args.args[2]["brightness"], 51)

    async def test_pause_and_saved_schedule_edits_clear_manual_hold(self):
        self.engine._store = SimpleNamespace(async_save=AsyncMock())
        self.engine.async_start = Mock()
        self.change(self.make_state(255), self.make_state(0, "off"))
        await self.engine.async_set_enabled(False)
        self.assertFalse(self.engine._overrides)
        self.engine.enabled = True
        self.change(self.make_state(255), self.make_state(0, "off"))
        await self.engine.async_update_schedules({"light.demo": self.schedule})
        self.assertFalse(self.engine._overrides)

    async def test_manual_rgb_color_recovers_using_incoming_easing(self):
        self.schedule["nodes"][1].update(mode="rgb", rgb=[0, 0, 255])
        old = self.make_state(128, color_mode="rgb", rgb_color=(0, 255, 0), supported_color_modes=["rgb"])
        new = self.make_state(128, color_mode="rgb", rgb_color=(255, 0, 0), supported_color_modes=["rgb"])
        self.change(old, new)
        await self.apply()
        self.hass.services.async_call.assert_not_called()
        self.now += timedelta(seconds=60)
        await self.apply()
        self.now += timedelta(seconds=29)
        await self.apply()
        data = self.hass.services.async_call.call_args.args[2]
        self.assertEqual(data["rgb_color"], (191, 0, 64))
        self.assertNotIn("color_temp_kelvin", data)

    async def test_next_solar_event_includes_offset(self):
        self.schedule["nodes"][1].update(anchor="sunset", offset=-1800)
        self.change(self.make_state(255), self.make_state(100))
        deadline = datetime.fromtimestamp(self.engine._overrides["light.demo"].deadline, timezone.utc)
        self.assertEqual((deadline.hour, deadline.minute), (17, 30))
        await self.apply()
        self.hass.services.async_call.assert_not_called()

    async def test_previous_scheduler_context_remains_recognized(self):
        await self.apply()
        previous = self.hass.services.async_call.call_args.kwargs["context"]
        self.engine._async_apply("light.demo", self.schedule["nodes"], 0, 0)
        await asyncio.gather(*self.tasks)
        self.tasks.clear()
        current = self.hass.services.async_call.call_args.kwargs["context"]
        self.assertNotEqual(previous.id, current.id)
        self.change(self.make_state(100), self.make_state(130, context=previous))
        self.assertFalse(self.engine._overrides)

    async def test_explicit_destination_ease_in_controls_manual_recovery(self):
        self.schedule["nodes"][0].update(ease_out="step", curve="linear")
        self.schedule["nodes"][1].update(ease_in="ease_in", ease_out="ease_out")
        self.change(self.make_state(255), self.make_state(0, "off"))
        override = self.engine._overrides["light.demo"]
        self.assertEqual(override.ease, "ease_in")
        await self.apply()
        self.hass.services.async_call.assert_not_called()
        self.now += timedelta(seconds=60)
        await self.apply()
        self.now += timedelta(seconds=29)
        await self.apply()
        data = self.hass.services.async_call.call_args.args[2]
        self.assertEqual(data["brightness"], 64)
        self.assertAlmostEqual(data["color_temp_kelvin"], 2479, delta=1)

    async def test_explicit_destination_step_controls_manual_recovery(self):
        self.schedule["nodes"][0]["ease_out"] = "linear"
        self.schedule["nodes"][1]["ease_in"] = "step"
        self.change(self.make_state(255), self.make_state(0, "off"))
        self.now += timedelta(seconds=60)
        await self.apply()
        self.now += timedelta(seconds=30)
        await self.apply()
        self.assertEqual(self.hass.services.async_call.call_args.args[1], "turn_off")
        self.now += timedelta(seconds=30)
        await self.apply()
        self.assertEqual(self.hass.services.async_call.call_args.args[1], "turn_on")