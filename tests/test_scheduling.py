from datetime import date, datetime, timezone
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import voluptuous as vol

from custom_components.light_timeline.scheduling import resolve_nodes, solar_events
from custom_components.light_timeline.engine import TimelineEngine
from custom_components.light_timeline.websocket import NODE_SCHEMA, SCHEDULE_SCHEMA


class SchedulingTests(unittest.TestCase):
    def test_existing_timelines_remain_daily(self):
        schedule = SCHEDULE_SCHEMA({"nodes": [{"t": 3600, "b": 50}]})
        for weekday in range(7):
            self.assertEqual(resolve_nodes(schedule, {}, weekday)[0]["t"], 3600)

    def test_events_follow_daily_times_and_offsets(self):
        schedule = SCHEDULE_SCHEMA({"nodes": [
            {"t": 0, "b": 50, "anchor": "sunrise", "offset": -1800},
            {"t": 0, "b": 80, "anchor": "sunset", "offset": 900},
        ]})
        self.assertEqual([node["t"] for node in resolve_nodes(schedule, {"sunrise": 24000, "sunset": 65000}, 0)], [22200, 65900])
        self.assertEqual([node["t"] for node in resolve_nodes(schedule, {"sunrise": 24100, "sunset": 64900}, 1)], [22300, 65800])
        self.assertEqual(schedule["nodes"][0]["t"], 0)

    def test_schedule_and_node_weekdays(self):
        schedule = SCHEDULE_SCHEMA({"days": [0, 5], "nodes": [
            {"t": 3600, "b": 50, "days": [0]},
            {"t": 7200, "b": 80, "days": [5, 6]},
        ]})
        self.assertEqual(resolve_nodes(schedule, {}, 0)[0]["t"], 3600)
        self.assertEqual(resolve_nodes(schedule, {}, 5)[0]["t"], 7200)
        self.assertEqual(resolve_nodes(schedule, {}, 6), [])

    def test_missing_solar_event_is_skipped(self):
        schedule = SCHEDULE_SCHEMA({"nodes": [
            {"t": 0, "b": 50, "anchor": "sunrise"}, {"t": 7200, "b": 80},
        ]})
        self.assertEqual([node["t"] for node in resolve_nodes(schedule, {"sunrise": None}, 0)], [7200])

    def test_collisions_and_midnight_wrap(self):
        schedule = SCHEDULE_SCHEMA({"nodes": [
            {"t": 3600, "b": 10}, {"t": 0, "b": 80, "anchor": "sunset", "offset": 7200},
        ]})
        nodes = resolve_nodes(schedule, {"sunset": 82800}, 0)
        self.assertEqual(len(nodes), 1)
        self.assertEqual((nodes[0]["t"], nodes[0]["b"]), (3600, 80))

    def test_invalid_events_days_and_offsets_are_rejected(self):
        for properties in [{"anchor": "unknown"}, {"days": [7]}, {"offset": 86400}]:
            with self.assertRaises(vol.Invalid):
                NODE_SCHEMA({"t": 0, "b": 50, **properties})

    def test_solar_helper_uses_requested_date(self):
        day = date(2026, 10, 7)
        with patch("custom_components.light_timeline.scheduling.get_astral_event_date", side_effect=[datetime(2026, 10, 7, 6, tzinfo=timezone.utc), None]) as helper:
            events = solar_events(None, day)
        self.assertIsInstance(events["sunrise"], int)
        self.assertIsNone(events["sunset"])
        self.assertEqual(helper.call_args.args[2], day)


class SchedulerCalendarTests(unittest.TestCase):
    def make_engine(self, schedule):
        hass = Mock()
        hass.config = SimpleNamespace(latitude=40, longitude=-75, elevation=0, time_zone="UTC")
        hass.states.async_entity_ids.return_value = ["light.demo"]
        return TimelineEngine(hass, SimpleNamespace(options={}), None, {"schedules": {"light.demo": schedule}})

    def test_active_nodes_follow_day_and_recompute_sun(self):
        engine = self.make_engine(SCHEDULE_SCHEMA({"days": [0, 1], "nodes": [
            {"t": 0, "b": 50, "anchor": "sunrise", "offset": 900},
        ]}))
        monday = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
        tuesday = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        sunday = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
        with patch("custom_components.light_timeline.engine.solar_events", side_effect=[{"sunrise": 24000}, {"sunrise": 24100}, {"sunrise": 24200}]) as events:
            with patch("custom_components.light_timeline.engine.dt_util.now", return_value=monday):
                self.assertEqual(engine._active()["light.demo"][0]["t"], 24900)
                engine._active()
                self.assertEqual(events.call_count, 1)
            with patch("custom_components.light_timeline.engine.dt_util.now", return_value=tuesday):
                self.assertEqual(engine._active()["light.demo"][0]["t"], 25000)
            with patch("custom_components.light_timeline.engine.dt_util.now", return_value=sunday):
                self.assertEqual(engine._active(), {})

    def test_tick_wakes_at_midnight_without_fading_into_inactive_day(self):
        schedule = SCHEDULE_SCHEMA({"nodes": [{"t": 0, "b": 50}]})
        engine = self.make_engine(schedule)
        engine._active = Mock(return_value={"light.demo": schedule["nodes"]})
        engine._async_apply = Mock()
        engine._last["light.demo"] = ("turn_on", {})
        with patch("custom_components.light_timeline.engine._seconds_of_day", return_value=86399), patch("custom_components.light_timeline.engine.async_call_later") as timer:
            engine._async_tick()
        self.assertAlmostEqual(timer.call_args.args[1], 1.05)
        self.assertLess(engine._async_apply.call_args.args[3], 1)
        self.assertEqual(engine._last, {})