# -*- coding: utf-8 -*-
"""从 Emby for Kodi Next Gen 的本地库读取片头/片尾记录点。

Emby 插件把记录点写在 `Database/emby_<ServerId>.db` 的 `MediaSources` 表：
`EmbyId / MediaSourceId / Path / Name / Size / IntroStart / IntroEnd / CreditsStart`，
三个时间值都是秒，与 `xbmc.Player().getTime()` 同单位。本模块只读打开，不写库、不联网。

匹配顺序（从最可靠到兜底）：
  1. 播放路径里带 `item=<EmbyId>`（Emby 插件播放 URL）；
  2. Kodi 剧集 id → `Episode.KodiId` → EmbyId；
  3. 播放路径与 `MediaSources.Path` 完全一致；
  4. 文件名（`MediaSources.Name` / Path 的 basename）匹配。

手动记录与 Emby 的优先级：手动记录优先，缺失时再用 Emby。
"""

import glob
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

ITEM_RE = re.compile(r"[?&]item=(\d+)")
TICKS_PER_SECOND = 10000000


def _profile_db_dir(profile: Optional[str] = None) -> str:
    if profile:
        return os.path.join(profile, "Database")
    try:
        import xbmcvfs

        return xbmcvfs.translatePath("special://profile/Database")
    except Exception:
        return ""


def database_paths(profile: Optional[str] = None) -> List[str]:
    """所有 Emby 服务器库文件，按文件名排序；没有则返回空列表。"""
    db_dir = _profile_db_dir(profile)
    if not db_dir:
        return []
    return sorted(glob.glob(os.path.join(db_dir, "emby_*.db")))


def server_id_from_db(db_path: str) -> str:
    name = os.path.basename(db_path or "")
    if name.startswith("emby_") and name.endswith(".db"):
        return name[5:-3]
    return ""


def _connect(db_path: str) -> sqlite3.Connection:
    # mode=ro：Kodi 正在写这个库，只读连接不参与锁竞争，也不会改动任何数据
    uri = "file:%s?mode=ro" % (db_path or "").replace("\\", "/")
    return sqlite3.connect(uri, uri=True, timeout=1)


def _base_name(path: str) -> str:
    path = (path or "").split("?", 1)[0].split("#", 1)[0].replace("\\", "/")
    return path.rsplit("/", 1)[-1]


def _seconds(value: Any) -> int:
    """记录点统一成秒；兼容误存成 100ns ticks 的库。"""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    if number > TICKS_PER_SECOND:  # 大于 115 天只可能是 ticks
        number //= TICKS_PER_SECOND
    return max(0, number)


def _row_markers(row: Any) -> Optional[Dict[str, Any]]:
    emby_id, media_id, name, path = row[0], row[1], row[2], row[3]
    intro_start = _seconds(row[4])
    intro_end = _seconds(row[5])
    credits_start = _seconds(row[6])
    if not (intro_end or credits_start):
        return None
    return {
        "emby_id": str(emby_id or ""),
        "media_source_id": str(media_id or ""),
        "name": name or "",
        "path": path or "",
        "intro_start": intro_start,
        "intro_end": intro_end,
        "credits_start": credits_start,
    }


def _query_markers(con: sqlite3.Connection, emby_id: str) -> Optional[Dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        "SELECT EmbyId, MediaSourceId, Name, Path, IntroStart, IntroEnd, CreditsStart "
        "FROM MediaSources WHERE EmbyId = ? ORDER BY Size DESC LIMIT 1",
        (str(emby_id),),
    )
    row = cur.fetchone()
    return _row_markers(row) if row else None


def _query_markers_by_path(con: sqlite3.Connection, playing_file: str) -> Optional[Dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        "SELECT EmbyId, MediaSourceId, Name, Path, IntroStart, IntroEnd, CreditsStart "
        "FROM MediaSources WHERE Path = ? LIMIT 1",
        (playing_file or "",),
    )
    row = cur.fetchone()
    if row:
        return _row_markers(row)

    base = _base_name(playing_file)
    if not base:
        return None
    cur.execute(
        "SELECT EmbyId, MediaSourceId, Name, Path, IntroStart, IntroEnd, CreditsStart "
        "FROM MediaSources WHERE Name = ? OR Path LIKE ? LIMIT 1",
        (base, "%" + base + "%"),
    )
    row = cur.fetchone()
    return _row_markers(row) if row else None


def find_markers(playing_file: str = "", kodi_id: int = 0,
                 db_paths: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """返回第一个命中的记录点 dict；没有记录点返回 None。"""
    paths = db_paths if db_paths is not None else database_paths()
    parsed_id = ITEM_RE.search(playing_file or "")
    emby_id = parsed_id.group(1) if parsed_id else ""

    for db_path in paths:
        try:
            con = _connect(db_path)
        except Exception:
            continue
        try:
            markers = _query_markers(con, emby_id) if emby_id else None
            if markers is None and kodi_id:
                cur = con.cursor()
                cur.execute("SELECT EmbyId FROM Episode WHERE KodiId = ? LIMIT 1", (int(kodi_id),))
                row = cur.fetchone()
                if row:
                    markers = _query_markers(con, row[0])
            if markers is None and playing_file:
                markers = _query_markers_by_path(con, playing_file)
            if markers:
                markers["server_id"] = server_id_from_db(db_path)
                markers["db_path"] = os.path.basename(db_path)
                return markers
        except Exception:
            continue
        finally:
            con.close()
    return None


def intro_skip_target(manual_seconds: Any, markers: Optional[Dict[str, Any]]) -> int:
    """片头跳到哪里：手动记录优先，没有手动记录时用 Emby 的 IntroEnd。"""
    try:
        manual = int(float(manual_seconds or 0))
    except (TypeError, ValueError):
        manual = 0
    if manual > 0:
        return manual
    try:
        return max(0, int((markers or {}).get("intro_end") or 0))
    except (TypeError, ValueError):
        return 0


def outro_trigger_time(manual_outro_seconds: Any, total_seconds: Any,
                       markers: Optional[Dict[str, Any]]) -> float:
    """片尾倒计时从哪开始：手动记录（从结尾倒推）优先，否则用 Emby 的 CreditsStart。

    返回 0 表示没有可用的片尾点。
    """
    try:
        manual = float(manual_outro_seconds or 0)
        total = float(total_seconds or 0)
    except (TypeError, ValueError):
        manual = total = 0.0
    if manual > 0 and total > manual:
        return total - manual
    try:
        credits = float((markers or {}).get("credits_start") or 0)
    except (TypeError, ValueError):
        credits = 0.0
    return max(0.0, credits)
