# -*- coding: utf-8 -*-
"""Emby 本地记录点查询与手动/自动优先级测试：只依赖临时 SQLite。"""

import os
import sqlite3
import tempfile
import unittest

from skipintro.emby_markers import (
    find_markers,
    intro_skip_target,
    outro_trigger_time,
    server_id_from_db,
)


def make_db(rows, episodes=()):
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    con = sqlite3.connect(handle.name)
    cur = con.cursor()
    cur.execute("CREATE TABLE Episode (EmbyId TEXT, KodiId INTEGER)")
    cur.execute(
        "CREATE TABLE MediaSources ("
        "EmbyId TEXT, MediaSourceId TEXT, Name TEXT, Path TEXT, Size INTEGER, "
        "IntroStart INTEGER, IntroEnd INTEGER, CreditsStart INTEGER)"
    )
    cur.executemany("INSERT INTO Episode VALUES (?, ?)", episodes)
    cur.executemany("INSERT INTO MediaSources VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()
    return handle.name


class EmbyMarkersTest(unittest.TestCase):

    def setUp(self):
        self.db = make_db(
            rows=[
                ("100", "ms1", "The.Message.S01E01.mp4", "smb://nas/The.Message.S01E01.mp4",
                 1000, 0, 100, 2380),
                ("101", "ms2", "Other.mp4", "smb://nas/Other.mp4", 900, 1234567890, 1234568890, 0),
            ],
            episodes=[("100", 6011)],
        )

    def tearDown(self):
        os.unlink(self.db)

    def test_lookup_by_kodi_id(self):
        result = find_markers("", 6011, db_paths=[self.db])
        self.assertIsNotNone(result)
        self.assertEqual(result["emby_id"], "100")
        self.assertEqual(result["intro_end"], 100)
        self.assertEqual(result["credits_start"], 2380)

    def test_lookup_by_plugin_item_url(self):
        result = find_markers(
            "plugin://plugin.service.emby-next-gen/?mode=play&item=100&server=x",
            0, db_paths=[self.db],
        )
        self.assertEqual(result["emby_id"], "100")

    def test_lookup_by_exact_path(self):
        result = find_markers("smb://nas/Other.mp4", 0, db_paths=[self.db])
        self.assertEqual(result["emby_id"], "101")
        self.assertEqual(result["intro_end"], 123)
        self.assertEqual(result["credits_start"], 0)

    def test_no_markers_returns_none(self):
        self.assertIsNone(find_markers("smb://nas/missing.mp4", 999, db_paths=[self.db]))

    def test_server_id_from_db_name(self):
        self.assertEqual(server_id_from_db("emby_abc123.db"), "abc123")


class ResolveTest(unittest.TestCase):

    markers = {"intro_end": 100, "credits_start": 2380}

    def test_manual_intro_wins(self):
        self.assertEqual(intro_skip_target(95, self.markers), 95)

    def test_emby_intro_fallback(self):
        self.assertEqual(intro_skip_target(0, self.markers), 100)
        self.assertEqual(intro_skip_target(None, None), 0)

    def test_manual_outro_wins(self):
        self.assertEqual(outro_trigger_time(30, 2400, self.markers), 2370)

    def test_emby_credits_fallback(self):
        self.assertEqual(outro_trigger_time(0, 2400, self.markers), 2380)
        self.assertEqual(outro_trigger_time(None, 0, None), 0)

    def test_invalid_manual_outro_falls_back(self):
        self.assertEqual(outro_trigger_time(9999, 2400, self.markers), 2380)


if __name__ == "__main__":
    unittest.main()
