# -*- coding: utf-8 -*-
"""为 common.py 提供最小化的 Kodi 模块替身，让纯函数可以在本地单测。"""
import os
import sys
import tempfile
import types

_TMP_DIR = tempfile.mkdtemp(prefix="skipintro_test_")


class _FakeAddon:
    def __init__(self, *args, **kwargs):
        self._settings = {}

    def getSetting(self, key):
        return self._settings.get(key, "")

    def setSetting(self, key, value):
        self._settings[key] = value

    def getLocalizedString(self, string_id):
        return "[String %s]" % string_id


class _FakePlayer:
    def __init__(self, *args, **kwargs):
        pass


class _FakeMonitor:
    def __init__(self, *args, **kwargs):
        pass

    def waitForAbort(self, timeout=0):
        return True


def _install(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


_install(
    "xbmc",
    LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3,
    log=lambda *a, **k: None,
    sleep=lambda ms: None,
    executebuiltin=lambda *a, **k: None,
    getCondVisibility=lambda *a, **k: False,
    getInfoLabel=lambda *a, **k: "",
    Player=_FakePlayer,
    Monitor=_FakeMonitor,
    translatePath=lambda p: _TMP_DIR,
)
_install(
    "xbmcgui",
    WindowXMLDialog=object,
    Window=object,
    Dialog=object,
    ControlImage=object,
    ControlLabel=object,
)
_install("xbmcaddon", Addon=_FakeAddon)
_install("xbmcvfs", translatePath=lambda p: _TMP_DIR, exists=lambda p: os.path.exists(p))
