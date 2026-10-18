# -*- coding: utf-8 -*-
"""测试包：导入时先注入 Kodi 模块替身，再让测试模块 import common。"""
from . import kodi_stub  # noqa: F401
