# -*- coding: utf-8 -*-
"""媒体库查询：JSON-RPC、剧集定位、文件名解析、播放列表状态。"""
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import xbmc

from .common import (
    CACHE_TTL_SEASON_EPISODES,
    _cache_lock,
    _caches,
    _evict_season_cache,
    _get_cached_data,
    _set_cached_data,
    log,
    log_debug,
)


def jsonrpc_call(method: str, params: Optional[Dict[str, Any]] = None, request_id: Optional[Union[int, str]] = None) -> Optional[Dict[str, Any]]:
    query: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "id": request_id or method,
    }
    if params is not None:
        query["params"] = params

    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
    except (ValueError, RuntimeError) as e:
        log(f"JSON-RPC call failed [{method}]: {e}", xbmc.LOGERROR)
        return None

    if isinstance(response, dict) and "error" in response:
        error = response.get('error', {})
        log(f"JSON-RPC error [{method}]: {error}", xbmc.LOGWARNING)
        return None

    return response.get("result") if isinstance(response, dict) else None


def get_current_episode_id(tvshowid: Any, season: Any, episode: Any, current_file: Optional[str] = None) -> Optional[int]:
    try:
        tvshowid = int(tvshowid) if tvshowid not in (None, -1, "") else None
        season = int(season) if season not in (None, -1, "") else None
        episode = int(episode) if episode not in (None, -1, "") else None

        if current_file:
            result = jsonrpc_call(
                "VideoLibrary.GetEpisodes",
                {"properties": ["file", "episode", "season"]}
            ) or {}
            episodes = result.get("episodes") or []
            for ep in episodes:
                if ep.get("file") == current_file:
                    return ep.get("episodeid")

        if any(v is None for v in [tvshowid, season, episode]):
            return None

        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {"properties": ["episode", "season"], "tvshowid": tvshowid}
        ) or {}

        episodes = result.get("episodes") or []
        for ep in episodes:
            if ep.get("season") == season and ep.get("episode") == episode:
                episodeid = ep.get("episodeid")
                if episodeid and episodeid != -1:
                    log_debug(f"Found episodeid={episodeid} for S{season}E{episode}")
                    return episodeid

        log_debug(f"No episodeid found for S{season}E{episode}")
        return None
    except (ValueError, TypeError) as e:
        log(f"get_current_episode_id error: {e}", xbmc.LOGERROR)
        return None


def get_tvshowid_from_title(show_title: str) -> Optional[int]:
    try:
        result = jsonrpc_call(
            "VideoLibrary.GetTVShows", {"properties": ["title"]}
        ) or {}

        for show in result.get("tvshows", []):
            if show.get("label") == show_title:
                tvshowid = show.get("tvshowid")
                log_debug(f"Found tvshowid={tvshowid} for '{show_title}'")
                return tvshowid

        log_debug(f"No tvshowid found for '{show_title}'")
        return None
    except Exception as e:
        log(f"get_tvshowid_from_title error: {e}", xbmc.LOGERROR)
        return None


def get_next_episode_from_library(tvshowid: Any, current_file: Optional[str] = None,
                                    include_watched: bool = True,
                                    current_episode_num: Optional[int] = None,
                                    current_season_num: Optional[int] = None) -> Optional[Dict[str, Any]]:
    try:
        if tvshowid in (None, -1, ""):
            return None

        tvshowid = int(tvshowid)
        if tvshowid <= 0:
            return None

        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {
                "tvshowid": tvshowid,
                "properties": ["title", "plot", "season", "episode", "playcount",
                               "showtitle", "file", "art", "runtime", "firstaired",
                               "dateadded", "lastplayed"],
                "sort": {"method": "episode"},
            }
        )

        if not result or not result.get("episodes"):
            return None

        episodes: List[Dict[str, Any]] = result.get("episodes", [])
        # Kodi 的 "episode" 排序只按集号，跨季时顺序可能交错；
        # 本地按 (season, episode) 重排，确保 next_index 取到的是真正的下一集
        episodes.sort(key=lambda ep: (ep.get("season") or 0, ep.get("episode") or 0))
        current_index = -1

        if current_episode_num is not None and current_season_num is not None:
            current_season_int = int(current_season_num)
            current_episode_int = int(current_episode_num)
            for idx, episode in enumerate(episodes):
                if episode.get("season") == current_season_int and episode.get("episode") == current_episode_int:
                    current_index = idx
                    break

        if current_index == -1 and current_file:
            for idx, episode in enumerate(episodes):
                if episode.get("file") == current_file:
                    current_index = idx
                    break

        if current_index == -1 and current_file:
            current_file_norm = normalize_media_path(current_file)
            for idx, episode in enumerate(episodes):
                ep_file_norm = normalize_media_path(episode.get("file", ""))
                if ep_file_norm and current_file_norm:
                    if ep_file_norm in current_file_norm or current_file_norm in ep_file_norm:
                        current_index = idx
                        break

        if current_index == -1:
            return None

        next_index = current_index + 1
        if next_index >= len(episodes):
            return None

        next_episode = episodes[next_index]

        if not include_watched:
            playcount = next_episode.get("playcount", 0)
            if playcount and playcount > 0:
                return None

        return {
            "episodeid": next_episode.get("episodeid"),
            "tvshowid": next_episode.get("tvshowid"),
            "season": next_episode.get("season"),
            "episode": next_episode.get("episode"),
            "title": next_episode.get("title"),
            "showtitle": next_episode.get("showtitle"),
            "file": next_episode.get("file"),
            "plot": next_episode.get("plot"),
            "playcount": next_episode.get("playcount", 0),
            "art": next_episode.get("art"),
            "runtime": next_episode.get("runtime"),
            "firstaired": next_episode.get("firstaired"),
        }
    except Exception as e:
        log(f"get_next_episode_from_library error: {e}", xbmc.LOGERROR)
        return None


def get_season_episodes(tvshowid: Any, season: Any) -> Optional[Dict[str, Any]]:
    try:
        if tvshowid in (None, -1, "") or season in (None, -1, ""):
            return None

        tvshowid_int = int(tvshowid)
        season_int = int(season)

        if tvshowid_int <= 0 or season_int <= 0:
            return None

        cache_key = f"{tvshowid_int}_{season_int}"
        with _cache_lock:
            season_cache = _caches['season_episodes']
            if cache_key in season_cache:
                cached = season_cache[cache_key]
                if time.time() - cached['time'] < CACHE_TTL_SEASON_EPISODES:
                    season_cache.move_to_end(cache_key)
                    return cached['data']

        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {
                "tvshowid": tvshowid_int,
                "season": season_int,
                "properties": ["file", "episode", "season", "title"],
                "sort": {"method": "episode", "order": "ascending"},
            },
        ) or {}

        episodes = result.get("episodes") or []
        if not episodes:
            return None

        for itm in episodes:
            itm["tvshowid"] = tvshowid_int
            itm["season"] = season_int
            itm["id"] = itm.get("episodeid")

        season_info = {
            "tvshowid": tvshowid_int,
            "season": season_int,
            "episodes": episodes,
        }

        with _cache_lock:
            season_cache = _caches['season_episodes']
            season_cache[cache_key] = {'data': season_info, 'time': time.time()}
            _evict_season_cache()

        return season_info
    except Exception as e:
        log(f"get_season_episodes error: {e}", xbmc.LOGERROR)
        return None


def play_episode_from_library(episode_info: Dict[str, Any]) -> bool:
    episodeid = episode_info.get("episodeid")
    if not episodeid or episodeid == -1:
        return False
    result = jsonrpc_call("Player.Open", {"item": {"episodeid": episodeid}})
    return result == "OK"


def is_next_episode_available_in_playlist(playlist_id: Optional[int] = None,
                                            playlist_position: Optional[int] = None) -> bool:
    if playlist_id is None or playlist_position is None:
        state = get_active_video_playlist_state()
        if not state:
            return False
        playlist_id = state.get("playlistid", 1)
        playlist_position = state.get("position", 0)

    result = jsonrpc_call(
        "Playlist.GetItems",
        {"playlistid": int(playlist_id or 1), "properties": [],
         "limits": {"start": int(playlist_position or 0) + 1, "end": int(playlist_position or 0) + 2}}
    ) or {}
    return len(result.get("items") or []) > 0


def play_file(file_path: str) -> bool:
    file_path = str(file_path or "")
    if not file_path:
        return False
    result = jsonrpc_call("Player.Open", {"item": {"file": file_path}})
    return result == "OK"


def mark_current_episode_as_watched() -> bool:
    state = get_active_video_playlist_state()
    if not state:
        return False

    episode_id = state.get("episodeid")
    if not episode_id or episode_id == -1:
        # 兜底：按 tvshowid + 季集回查媒体库（目录模式无库记录，直接跳过）
        tvshow_id = state.get("tvshowid")
        season_no = state.get("season")
        episode_no = state.get("episode")
        if tvshow_id in (None, -1) or season_no is None or episode_no is None:
            return False
        episode_id = get_current_episode_id(tvshow_id, season_no, episode_no)
    if not episode_id or episode_id == -1:
        return False

    result = jsonrpc_call(
        "VideoLibrary.SetEpisodeDetails",
        {"episodeid": episode_id, "playcount": 1}
    )
    return result == "OK"


def normalize_media_path(path: str) -> str:
    if not path:
        return ""
    normalized = str(path).split('?', 1)[0].split('#', 1)[0]
    return normalized.replace('\\', '/').rstrip('/')


# Patterns for extracting season/episode info from filenames
# Ordered by priority: most specific patterns first
_FILENAME_PATTERNS: List[re.Pattern] = [
    # S01E01 or S01.E01 or S01_E01 or S01-E01 (most common)
    re.compile(r'[sS](?P<season>\d{1,4})[.\-_]?[eE](?P<episode>\d{1,4})'),
    # 01x01 or 01X01
    re.compile(r'(?P<season>\d{1,4})[xX](?P<episode>\d{1,4})'),
    # S01 EP01
    re.compile(r'S(?P<season>\d{1,4})[ ._-]?EP(?P<episode>\d{1,4})'),
    # Season 1 Episode 1
    re.compile(r'Season[\s._-]?(?P<season>\d{1,4})[\s._-]*Episode[\s._-]?(?P<episode>\d{1,4})'),
    # S1 E1
    re.compile(r'S(?P<season>\d{1,4})[\s._-]*E(?P<episode>\d{1,4})'),
    # 第1季第1集 (Chinese)
    re.compile(r'第(?P<season>\d{1,4})季第(?P<episode>\d{1,4})集'),
    # 01-01 or 01.01 or 01_01 (number-number)
    re.compile(r'(?P<season>\d{1,4})[.\-_](?P<episode>\d{1,4})'),
    # 第1集 (Chinese, episode only)
    re.compile(r'第(?P<episode>\d{1,4})集'),
    # E01 or EP01 (episode only, least specific)
    re.compile(r'[eE][pP]?(?P<episode>\d{1,4})'),
]


def extract_media_info_from_filename(filename: str) -> Tuple[int, int, bool]:
    if not filename:
        return 0, 0, False

    basename = os.path.basename(normalize_media_path(filename))
    basename = os.path.splitext(basename)[0]

    for pattern in _FILENAME_PATTERNS:
        match = pattern.search(basename)
        if match:
            groups = match.groupdict()
            season = int(groups.get("season", 1) or 1)
            episode = int(groups.get("episode", 1) or 1)
            if season > 0 and episode > 0:
                return season, episode, True

    return 0, 0, False


def natural_sort_key(value: str) -> List[Any]:
    text = str(value or "")
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', text)]


def get_parent_media_path(path: str) -> Optional[str]:
    normalized = normalize_media_path(path)
    if not normalized:
        return None
    last_sep = normalized.rfind('/')
    if last_sep <= 0:
        return None
    return normalized[:last_sep]


def _extract_episode_id(item_data: Dict[str, Any]) -> Optional[int]:
    """从 Player.GetItem 返回的 item 中取 episodeid。

    Player.GetItem 的 properties 不支持 "episodeid"（不在 List.Fields.All 中，
    请求会导致 InvalidParams），但 List.Item.Base 的 "id" 对剧集条目就是 episodeid。
    """
    if item_data.get("type") != "episode":
        return None
    item_id = item_data.get("id")
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return None
    return item_id if item_id > 0 else None


def get_active_video_playlist_state() -> Optional[Dict[str, Any]]:
    cached, hit = _get_cached_data('playlist_state')
    if hit:
        return cached

    player_id = _get_video_player_id()
    if player_id is None:
        return None

    # Get item info (only valid item properties)
    item_response = jsonrpc_call(
        "Player.GetItem",
        {
            "playerid": player_id,
            "properties": ["file", "tvshowid", "season", "episode", "showtitle", "title"]
        },
    ) or {}

    item_data = item_response.get("item") or {}

    # Get player properties (playlistid, position are player properties)
    props_response = jsonrpc_call(
        "Player.GetProperties",
        {
            "properties": ["playlistid", "position"],
            "playerid": player_id
        },
    ) or {}

    playlist_id = int(props_response.get("playlistid") or 1)
    current_position = int(props_response.get("position") or 0)

    if playlist_id < 0 or current_position < 0:
        return None

    episode_no = item_data.get("episode")
    try:
        episode_no = int(episode_no) if episode_no is not None else None
    except (TypeError, ValueError):
        episode_no = None

    season_no = item_data.get("season")
    try:
        season_no = int(season_no) if season_no is not None else None
    except (TypeError, ValueError):
        season_no = None

    result = {
        "playerid": player_id,
        "playlistid": playlist_id,
        "position": current_position,
        "file": item_data.get("file") or "",
        "tvshowid": item_data.get("tvshowid"),
        # List.Item.Base 的 id 对剧集条目即 episodeid（无需请求，随响应返回）
        "episodeid": _extract_episode_id(item_data),
        "season": season_no,
        "episode": episode_no,
        "showtitle": item_data.get("showtitle") or "",
        "title": item_data.get("title") or "",
    }

    _set_cached_data('playlist_state', result)
    return result


def get_playlist_items(playlist_id: int) -> List[Dict[str, Any]]:
    result = jsonrpc_call(
        "Playlist.GetItems",
        {"playlistid": playlist_id, "properties": ["tvshowid", "season", "episode", "file"]},
    ) or {}
    items = result.get("items") or []
    for idx, itm in enumerate(items):
        itm["position"] = idx
    return items


def get_season_episode_from_state(source_type: str, state: Any, season: Any) -> Tuple[int, int]:
    try:
        if source_type == 'directory' and isinstance(state, dict):
            current_file = state.get("file", "")
            if current_file:
                season_num, episode_num, parsed = extract_media_info_from_filename(current_file)
                if parsed and season_num > 0 and episode_num > 0:
                    return season_num, episode_num

        season_num = int(season) if (season and int(season) > 0) else 1

        if isinstance(state, dict):
            episode = state.get("episode")
            episode_num = int(episode) if (episode is not None and episode != -1 and int(episode) > 0) else 1
        else:
            episode_num = 1

        return season_num, episode_num
    except (ValueError, TypeError):
        return 1, 1


def get_directory_playlist_files(current_file: str) -> List[str]:
    try:
        if not current_file:
            return []

        parent_dir = get_parent_media_path(current_file)
        if not parent_dir:
            return []

        result = jsonrpc_call(
            "Files.GetDirectory",
            {"directory": parent_dir, "media": "video", "properties": ["file", "title"]},
        ) or {}

        if not isinstance(result, dict):
            return []

        files = result.get("files") or []
        if not isinstance(files, list):
            return []

        playlist_items = []
        for item in files:
            if not isinstance(item, dict):
                continue

            file_path = item.get("file")
            if not file_path:
                continue

            file_type = item.get("filetype")
            if file_type and file_type != "file":
                continue

            sort_title = item.get("title") or item.get("label") or os.path.basename(normalize_media_path(file_path))
            playlist_items.append((sort_title, file_path))

        playlist_items.sort(key=lambda value: (natural_sort_key(value[0]), normalize_media_path(value[1]).casefold()))
        return [file_path for _, file_path in playlist_items]
    except Exception as e:
        log(f"get_directory_playlist_files error: {e}", xbmc.LOGERROR)
        return []


def get_next_file_in_directory(current_file: str) -> Optional[str]:
    try:
        if not current_file:
            return None

        current_norm = normalize_media_path(current_file)
        if not current_norm:
            return None

        files = get_directory_playlist_files(current_file)
        if not files:
            return None

        norms = [normalize_media_path(path) for path in files]
        try:
            idx = norms.index(current_norm)
        except ValueError:
            return None

        next_idx = idx + 1
        if next_idx >= len(files):
            return None

        return files[next_idx]
    except Exception as e:
        log(f"get_next_file_in_directory error: {e}", xbmc.LOGERROR)
        return None


def _get_video_player_id() -> Optional[int]:
    players = jsonrpc_call("Player.GetActivePlayers") or []
    video_player = next((p for p in players if p.get("type") == "video"), None)
    if not video_player:
        return None
    return video_player.get("playerid")


def get_current_tvshow_info() -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    try:
        player_id = _get_video_player_id()
        if player_id is None:
            return None, None, None, None

        # Get item info (only valid item properties)
        result = jsonrpc_call(
            "Player.GetItem",
            {"properties": ["tvshowid", "showtitle", "season", "file"], "playerid": player_id}
        ) or {}

        item = result.get("item") or {}
        tvshow_id = item.get('tvshowid')
        show_title = item.get('showtitle')
        season = item.get('season', -1)
        file_path = item.get('file')

        # Check type via Player.GetProperties
        props = jsonrpc_call(
            "Player.GetProperties",
            {"properties": ["type"], "playerid": player_id}
        ) or {}
        item_type = props.get('type', '')

        if item_type == 'movie' or item_type == 'musicvideo':
            return None, None, None, None

        if tvshow_id and tvshow_id != -1 and show_title:
            return str(tvshow_id), show_title, str(season), 'library'

        if file_path:
            if file_path.startswith("plugin://") or file_path.startswith("pvr://"):
                return None, None, None, None

            basename = os.path.basename(file_path)
            has_episode_pattern = bool(re.search(
                r'[sS]\d{1,4}[._-]?[eE]\d{1,4}|\d{1,4}[xX]\d{1,4}|第\d{1,4}集', basename
            ))

            if not has_episode_pattern:
                return None, None, None, None

            parent_dir = os.path.dirname(file_path)
            dir_name = os.path.basename(parent_dir)

            season_num, episode_num, parsed = extract_media_info_from_filename(file_path)
            if not parsed or season_num <= 0:
                season_num = 1

            return f"directory:{parent_dir}", dir_name, str(season_num), 'directory'
    except Exception as e:
        log(f"get_current_tvshow_info error: {e}", xbmc.LOGERROR)
    return None, None, None, None
