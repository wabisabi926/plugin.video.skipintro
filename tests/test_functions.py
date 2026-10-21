# -*- coding: utf-8 -*-
"""纯函数回归测试：文件名解析、自然排序、通知宽度估算。"""
import unittest

from skipintro.common import (
    _parse_season_data,
    measure_notification_text,
    notification_window_width,
)
from skipintro.media import extract_media_info_from_filename, natural_sort_key


class FilenameParsingTest(unittest.TestCase):
    def test_sxxexx(self):
        self.assertEqual(
            extract_media_info_from_filename("Show.S01E02.1080p.mkv"), (1, 2, True)
        )

    def test_lowercase(self):
        self.assertEqual(extract_media_info_from_filename("show.s1e2.mkv"), (1, 2, True))

    def test_one_x_two(self):
        self.assertEqual(extract_media_info_from_filename("Show.01x02.mkv"), (1, 2, True))

    def test_season_episode_words(self):
        self.assertEqual(
            extract_media_info_from_filename("Show Season 3 Episode 7.mkv"), (3, 7, True)
        )

    def test_chinese(self):
        self.assertEqual(
            extract_media_info_from_filename("某剧.第2季第5集.mkv"), (2, 5, True)
        )

    def test_three_digit_numbers(self):
        self.assertEqual(
            extract_media_info_from_filename("Show.S001E012.mkv"), (1, 12, True)
        )

    def test_unparsable(self):
        self.assertEqual(extract_media_info_from_filename("random.mkv"), (0, 0, False))

    def test_empty(self):
        self.assertEqual(extract_media_info_from_filename(""), (0, 0, False))


class NaturalSortTest(unittest.TestCase):
    def test_numeric_order(self):
        items = ["E10", "E2", "E1"]
        self.assertEqual(sorted(items, key=natural_sort_key), ["E1", "E2", "E10"])

    def test_case_insensitive(self):
        self.assertEqual(natural_sort_key("a1"), natural_sort_key("A1"))

    def test_empty(self):
        self.assertEqual(natural_sort_key(""), [""])


class TextWidthTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(measure_notification_text(""), 0.0)

    def test_cjk_is_one_em(self):
        self.assertAlmostEqual(measure_notification_text("片"), 32.0)

    def test_lowercase_ratio(self):
        self.assertAlmostEqual(measure_notification_text("ab"), 32.0 * 0.52 * 2)

    def test_space_ratio(self):
        self.assertAlmostEqual(measure_notification_text(" "), 32.0 * 0.26)


class WindowWidthTest(unittest.TestCase):
    def test_empty_returns_padding_only(self):
        self.assertEqual(notification_window_width(""), 16)

    def test_clamped_to_max(self):
        self.assertEqual(notification_window_width("片" * 100), 900)

    def test_grows_with_text(self):
        self.assertLess(
            notification_window_width("片"), notification_window_width("片片")
        )


class SeasonDataTest(unittest.TestCase):
    def test_number(self):
        self.assertEqual(_parse_season_data(5), {"intro": 5})

    def test_dict_is_copied(self):
        source = {"intro": 3, "outro": 10}
        result = _parse_season_data(source)
        self.assertEqual(result, source)
        self.assertIsNot(result, source)

    def test_none(self):
        self.assertEqual(_parse_season_data(None), {})


if __name__ == "__main__":
    unittest.main()
