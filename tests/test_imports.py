# -*- coding: utf-8 -*-
"""导入链路冒烟测试：包模块与根目录入口脚本。"""
import importlib.util
import os
import unittest

import skipintro.common
import skipintro.media
import skipintro.playlist

_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_entry(name):
    path = os.path.join(_ADDON_ROOT, name + ".py")
    spec = importlib.util.spec_from_file_location("_entry_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImportChainTest(unittest.TestCase):
    def test_relative_imports_resolve_to_package(self):
        self.assertEqual(skipintro.media.log.__module__, "skipintro.common")
        self.assertEqual(skipintro.playlist.log.__module__, "skipintro.common")

    def test_public_functions_available(self):
        self.assertTrue(callable(skipintro.media.get_next_episode_from_library))
        self.assertTrue(callable(skipintro.playlist.autofill_playlist_for_current_video))

    def test_entry_scripts_load(self):
        for entry in ("default", "service"):
            with self.subTest(entry=entry):
                self.assertIsNotNone(_load_entry(entry))


if __name__ == "__main__":
    unittest.main()
