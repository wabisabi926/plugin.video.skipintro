# -*- coding: utf-8 -*-
"""分层记录点测试：季基准 + 本集覆盖，以及 Emby 自动记录点的优先级。"""

import unittest

from skipintro.common import (
    _parse_season_data,
    clear_skip_point,
    get_outro_trigger,
    get_skip_point,
    prune_skip_record,
    set_skip_point,
)


def make_record(season="1"):
    return {"title": "Show", "seasons": {season: {}}}


class SetPointTest(unittest.TestCase):

    def test_first_record_becomes_season_default(self):
        record = make_record()
        layer = set_skip_point(record, "1", 5, "intro", 100)
        self.assertEqual(layer, "season")
        self.assertEqual(record["seasons"]["1"]["intro"], 100)
        self.assertNotIn("episodes", record["seasons"]["1"])

    def test_later_record_only_overrides_that_episode(self):
        record = make_record()
        set_skip_point(record, "1", 1, "intro", 100)
        layer = set_skip_point(record, "1", 5, "intro", 130)
        self.assertEqual(layer, "episode")
        self.assertEqual(record["seasons"]["1"]["intro"], 100)
        self.assertEqual(record["seasons"]["1"]["episodes"]["5"]["intro"], 130)

    def test_episode_override_does_not_touch_other_episodes(self):
        record = make_record()
        set_skip_point(record, "1", 1, "intro", 100)
        set_skip_point(record, "1", 5, "intro", 130)
        set_skip_point(record, "1", 1, "intro", 110)
        # 第 1 集更正后只影响自己，第 5 集保持 130，季基准仍是 100
        self.assertEqual(record["seasons"]["1"]["intro"], 100)
        self.assertEqual(record["seasons"]["1"]["episodes"]["1"]["intro"], 110)
        self.assertEqual(record["seasons"]["1"]["episodes"]["5"]["intro"], 130)

    def test_intro_and_outro_tracked_separately(self):
        record = make_record()
        self.assertEqual(set_skip_point(record, "1", 3, "intro", 100), "season")
        self.assertEqual(set_skip_point(record, "1", 3, "outro", 60), "season")
        self.assertEqual(record["seasons"]["1"]["intro"], 100)
        self.assertEqual(record["seasons"]["1"]["outro"], 60)

    def test_unknown_episode_does_not_overwrite_season_marker(self):
        record = make_record()
        set_skip_point(record, "1", 1, "intro", 100)
        layer = set_skip_point(record, "1", 0, "intro", 120)
        self.assertEqual(layer, "unknown")
        self.assertEqual(record["seasons"]["1"]["intro"], 100)
        self.assertNotIn("episodes", record["seasons"]["1"])

    def test_unknown_episode_creates_season_marker_when_empty(self):
        record = make_record()
        self.assertEqual(set_skip_point(record, "1", 0, "intro", 120), "season")
        self.assertEqual(record["seasons"]["1"]["intro"], 120)


class ResolveIntroTest(unittest.TestCase):

    def test_priority_episode_over_emby_over_season(self):
        record = make_record()
        set_skip_point(record, "1", 1, "intro", 100)
        set_skip_point(record, "1", 2, "intro", 130)
        self.assertEqual(get_skip_point(record, "1", 2, "intro", 200)[0], 130)
        self.assertEqual(get_skip_point(record, "1", 3, "intro", 200)[0], 200)
        self.assertEqual(get_skip_point(record, "1", 3, "intro", 0)[0], 100)

    def test_sources_reported(self):
        record = make_record()
        set_skip_point(record, "1", 1, "intro", 100)
        set_skip_point(record, "1", 2, "intro", 130)
        self.assertEqual(get_skip_point(record, "1", 2, "intro", 200)[1], "episode")
        self.assertEqual(get_skip_point(record, "1", 3, "intro", 200)[1], "auto")
        self.assertEqual(get_skip_point(record, "1", 3, "intro", 0)[1], "season")
        self.assertEqual(get_skip_point({}, "1", 3, "intro", 0)[1], "none")

    def test_explicit_zero_disables_episode(self):
        record = make_record()
        set_skip_point(record, "1", 1, "intro", 100)
        set_skip_point(record, "1", 2, "intro", 0)
        self.assertEqual(get_skip_point(record, "1", 2, "intro", 200)[0], 0)

    def test_legacy_number_and_single_time(self):
        self.assertEqual(get_skip_point({"seasons": {"1": 95}}, "1", 1, "intro", 0)[0], 95)
        self.assertEqual(get_skip_point({"time": 80}, "1", 1, "intro", 0)[0], 80)

    def test_missing_season_uses_emby(self):
        self.assertEqual(get_skip_point({}, "3", 7, "intro", 90)[0], 90)


class ResolveOutroTest(unittest.TestCase):

    def test_relative_length_adapts_to_episode_duration(self):
        record = make_record()
        set_skip_point(record, "1", 1, "outro", 60)
        self.assertEqual(get_outro_trigger(record, "1", 2, 2700)[0], 2640)
        self.assertEqual(get_outro_trigger(record, "1", 2, 3000)[0], 2940)

    def test_emby_credits_used_as_absolute(self):
        self.assertEqual(get_outro_trigger({}, "1", 2, 2700, 2500)[0], 2500)

    def test_episode_override_wins(self):
        record = make_record()
        set_skip_point(record, "1", 1, "outro", 60)
        set_skip_point(record, "1", 5, "outro", 120)
        self.assertEqual(get_outro_trigger(record, "1", 5, 2700, 2500)[0], 2580)

    def test_duration_shorter_than_outro_is_ignored(self):
        record = make_record()
        set_skip_point(record, "1", 1, "outro", 600)
        self.assertEqual(get_outro_trigger(record, "1", 2, 300)[0], 0)


class ClearPointTest(unittest.TestCase):

    def test_clear_only_removes_episode_override(self):
        record = make_record()
        set_skip_point(record, "1", 1, "intro", 100)
        set_skip_point(record, "1", 2, "intro", 130)
        self.assertEqual(clear_skip_point(record, "1", 2, "intro"), "episode")
        self.assertEqual(record["seasons"]["1"]["intro"], 100)
        self.assertNotIn("episodes", record["seasons"]["1"])

    def test_clear_without_override_keeps_season_default(self):
        record = make_record()
        set_skip_point(record, "1", 1, "intro", 100)
        self.assertEqual(clear_skip_point(record, "1", 2, "intro"), "none")
        self.assertEqual(record["seasons"]["1"]["intro"], 100)

    def test_prune_removes_empty_entries(self):
        data = {"280": {"title": "Show", "seasons": {"1": {"episodes": {}}}}}
        prune_skip_record(data, "280")
        self.assertNotIn("280", data)


class CopySafetyTest(unittest.TestCase):

    def test_parse_season_data_deep_copies_episodes(self):
        raw = {"intro": 100, "episodes": {"2": {"intro": 130}}}
        copy = _parse_season_data(raw)
        copy["episodes"]["2"]["intro"] = 999
        self.assertEqual(raw["episodes"]["2"]["intro"], 130)


if __name__ == "__main__":
    unittest.main()
