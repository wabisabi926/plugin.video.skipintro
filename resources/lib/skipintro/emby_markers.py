# -*- coding: utf-8 -*-
"""从 Emby for Kodi Next Gen 的本地库读取片头/片尾记录点。

Emby 插件把记录点写在 `Database/emby_<ServerId>.db` 的 `MediaSources` 表：
`EmbyId / MediaSourceId / Path / Name / Size / IntroStart / IntroEnd / CreditsStart`，
三个时间值都是秒，与 `xbmc.Player().getTime()` 同单位。本模块只读打开，不写库、不联网。

匹配顺序（从最可靠到兜底）：
  1. 播放路径里带 `item=<EmbyId>`（Emby 插件播放 URL）；
  2. Kodi 剧集 id → `Episode.KodiId` → EmbyId；
  3. 播放路径与 `MediaSources.Path` 完全一致（允许 Kodi 的 `|` 播放选项）；
  4. 文件名严格匹配：完整文件名或去媒体扩展名后一致，且标记结果唯一。
     通用文件名（video.mkv / unknown.mkv 等）不参与兜底，歧义结果直接放弃，
     避免把别的剧集记录点套到当前播放上。

本模块只负责「取出 Emby 侧的原始记录点」，与本地手动记录、季基准的优先级
统一由 `common.get_skip_point()` / `common.get_outro_trigger()` 决定。
"""

import glob
import os
import re
import sqlite3
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Tuple

ITEM_RE = re.compile(r"[?&]item=(\d+)")
TICKS_PER_SECOND = 10000000
# 这些文件名过于通用，按名字兜底会匹配到大量无关剧集
GENERIC_STEMS = {"video", "index", "playlist", "stream", "unknown", "download", "movie"}
MEDIA_EXTENSIONS = {
    ".3gp", ".avi", ".flv", ".iso", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4",
    ".mpeg", ".mpg", ".rmvb", ".strm", ".ts", ".vob", ".webm", ".wmv",
}
_SELECT_COLUMNS = "EmbyId, MediaSourceId, Name, Path, IntroStart, IntroEnd, CreditsStart"


def _log_warning(message: str) -> None:
    try:
        import xbmc

        xbmc.log(f"[SkipIntro] Emby markers: {message}", xbmc.LOGWARNING)
    except Exception:
        pass


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


def _strip_kodi_options(path: str) -> str:
    """去掉 Kodi 的 `|` 播放选项（如 |redirect-limit=1000），保留查询串。"""
    return (path or "").split("|", 1)[0].replace("\\", "/")


def _base_name(path: str) -> str:
    path = _strip_kodi_options(path)
    path = path.split("?", 1)[0].split("#", 1)[0]
    return path.rsplit("/", 1)[-1]


def _name_keys(value: str) -> Tuple[str, str]:
    """返回 (完整文件名, 去媒体扩展名后的 stem)，均做 URL 解码和 casefold。

    只去掉已知媒体扩展名：发行名本身可能带很多点（如 ...H.265-BlackTV），
    不能把最后一段误当成扩展名。
    """
    base = urllib.parse.unquote(_base_name(value or "")).strip()
    ext = os.path.splitext(base)[1].casefold()
    stem = base[:-len(ext)] if ext in MEDIA_EXTENSIONS else base
    return base.casefold(), stem.casefold()


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


def _marker_signature(markers: Dict[str, Any]) -> Tuple[int, int, int]:
    return (markers["intro_start"], markers["intro_end"], markers["credits_start"])


def _pick_markers(rows: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """从多行候选中取标记；多个不同结果视为歧义，放弃而不是瞎猜。"""
    found = [markers for markers in (_row_markers(row) for row in rows) if markers]
    if not found:
        return None
    if len({_marker_signature(markers) for markers in found}) > 1:
        _log_warning(f"ambiguous marker rows ({len(found)}), ignored")
        return None
    return found[0]


def _query_markers(con: sqlite3.Connection, emby_id: Any) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """按 EmbyId 查。返回 (是否找到该条目的行, 标记或 None)。"""
    cur = con.cursor()
    cur.execute(
        f"SELECT {_SELECT_COLUMNS} FROM MediaSources WHERE EmbyId = ? ORDER BY Size DESC",
        (str(emby_id),),
    )
    rows = cur.fetchall()
    if not rows:
        return False, None
    return True, _pick_markers(rows)


def _emby_id_from_kodi(con: sqlite3.Connection, kodi_id: Any) -> Optional[Any]:
    cur = con.cursor()
    cur.execute("SELECT EmbyId FROM Episode WHERE KodiId = ? LIMIT 1", (int(kodi_id),))
    row = cur.fetchone()
    return row[0] if row else None


def _query_markers_by_exact_path(con: sqlite3.Connection,
                                 playing_file: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """按完整路径查。查询串不裁剪，避免把通用的 video.mkv 全匹配到一起。"""
    raw = (playing_file or "").replace("\\", "/")
    decoded = urllib.parse.unquote(raw)
    candidates = []
    for candidate in (raw, _strip_kodi_options(raw),
                      decoded, _strip_kodi_options(decoded)):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    cur = con.cursor()
    for candidate in candidates:
        if not candidate:
            continue
        cur.execute(
            f"SELECT {_SELECT_COLUMNS} FROM MediaSources WHERE Path = ?",
            (candidate,),
        )
        rows = cur.fetchall()
        if rows:
            return True, _pick_markers(rows)
    return False, None


def _query_markers_by_name(con: sqlite3.Connection, playing_file: str) -> Optional[Dict[str, Any]]:
    """严格文件名兜底：完整名或去媒体扩展名一致；通用名直接放弃。"""
    base, stem = _name_keys(playing_file)
    if not stem or stem in GENERIC_STEMS:
        return None

    cur = con.cursor()
    cur.execute(
        f"SELECT {_SELECT_COLUMNS} FROM MediaSources "
        "WHERE IntroEnd > 0 OR CreditsStart > 0"
    )
    matches = []
    for row in cur.fetchall():
        name_base, name_stem = _name_keys(row[2])
        path_base, path_stem = _name_keys(row[3])
        if base in (name_base, path_base) or stem in (name_stem, path_stem):
            matches.append(row)
    if not matches:
        return None

    markers = _pick_markers(matches)
    if markers is None:
        _log_warning(f"ambiguous filename match for {base!r}, ignored")
    return markers


def _with_source(markers: Optional[Dict[str, Any]], db_path: str) -> Optional[Dict[str, Any]]:
    if not markers:
        return None
    markers = dict(markers)
    markers["server_id"] = server_id_from_db(db_path)
    markers["db_path"] = os.path.basename(db_path)
    return markers


def find_markers(playing_file: str = "", kodi_id: int = 0,
                 db_paths: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """返回第一个命中的记录点 dict；没有记录点返回 None。

    强身份（item / kodi_id / 精确路径）一旦命中就停止，即使该行没有标记，
    也不会再用弱兜底去拿别的剧集标记。
    """
    paths = db_paths if db_paths is not None else database_paths()
    parsed_id = ITEM_RE.search(playing_file or "")
    emby_id = parsed_id.group(1) if parsed_id else ""

    connections: List[Tuple[str, sqlite3.Connection]] = []
    try:
        for db_path in paths:
            try:
                connections.append((db_path, _connect(db_path)))
            except Exception as e:
                _log_warning(f"cannot open {os.path.basename(db_path)}: {e}")

        for db_path, con in connections:
            try:
                if emby_id:
                    found, markers = _query_markers(con, emby_id)
                    if found:
                        return _with_source(markers, db_path)
                if kodi_id:
                    mapped_id = _emby_id_from_kodi(con, kodi_id)
                    if mapped_id:
                        found, markers = _query_markers(con, mapped_id)
                        if found:
                            return _with_source(markers, db_path)
            except Exception as e:
                _log_warning(f"marker lookup failed: {e}")
                continue

        if playing_file:
            for db_path, con in connections:
                try:
                    found, markers = _query_markers_by_exact_path(con, playing_file)
                    if found:
                        return _with_source(markers, db_path)
                except Exception as e:
                    _log_warning(f"path lookup failed: {e}")
                    continue

        if playing_file:
            for db_path, con in connections:
                try:
                    markers = _query_markers_by_name(con, playing_file)
                    if markers:
                        return _with_source(markers, db_path)
                except Exception as e:
                    _log_warning(f"name lookup failed: {e}")
                    continue
    finally:
        for _, con in connections:
            try:
                con.close()
            except Exception:
                pass
    return None
