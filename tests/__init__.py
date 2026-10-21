# -*- coding: utf-8 -*-
"""测试包：注入 Kodi 模块替身与插件模块路径。"""
import os
import sys

from . import kodi_stub  # noqa: F401

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "resources",
        "lib",
    ),
)
