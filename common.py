# -*- coding: utf-8 -*-
import xbmc
import xbmcvfs
import json
import os
import re
import time
import threading
import xbmcaddon
import shutil
from typing import Any, Dict, List, Optional, Tuple, Union, Callable, TypeVar
from functools import wraps

T = TypeVar('T')

ADDON_ID = 'plugin.video.skipintro'
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_PATH = xbmcvfs.translatePath(f"special://home/addons/{ADDON_ID}/")
ADDON_DATA_PATH = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")

if not os.path.exists(ADDON_DATA_PATH):
    os.makedirs(ADDON_DATA_PATH)

SKIP_DATA_FILE = os.path.join(ADDON_DATA_PATH, 'skip_intro_data.json')
MAX_PLAYLIST_ITEMS_BEFORE = 10
MAX_PLAYLIST_ITEMS_AFTER = 50
MAX_DELETE_LOWER_EPISODES_BELOW = 10
PLAYLIST_MUTATION_DELAY_MS = 300

PLAYBACK_STOP_TIMEOUT_MS = 5000
PLAYBACK_STOP_INTERVAL_MS = 100
DEFAULT_NOTIFICATION_DURATION = 2000

_cache_lock = threading.Lock()
_caches = {
    'skip_data': {'data': None, 'time': 0, 'ttl': 2.0},
    'playlist_state': {'data': None, 'time': 0, 'ttl': 0.5},
    'season_episodes': {}
}
playlist_cache_expiry = 3600


def log(msg: str, prefix: str = "[SkipIntro]", log_level: int = xbmc.LOGINFO) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    xbmc.log(f"{timestamp} {prefix} {msg}", log_level)


def log_error(msg: str, prefix: str = "[SkipIntro]") -> None:
    log(msg, prefix, xbmc.LOGERROR)


def log_warning(msg: str, prefix: str = "[SkipIntro]") -> None:
    log(msg, prefix, xbmc.LOGWARNING)


def log_debug(msg: str, prefix: str = "[SkipIntro]") -> None:
    if SETTINGS.debug_mode:
        log(msg, prefix, xbmc.LOGDEBUG)


def catch_exceptions(default_return: Any = None, log_prefix: str = "[SkipIntro]") -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log(f"Error in {func.__name__}: {e}", log_prefix, xbmc.LOGERROR)
                return default_return
        return wrapper
    return decorator


class SettingsManager:
    def __init__(self) -> None:
        self._addon = ADDON
        self._settings_cache: Dict[str, str] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_ttl: float = 5.0

    def _get_setting(self, setting_id: str, default: Optional[str] = None) -> Optional[str]:
        now: float = time.time()
        if setting_id in self._settings_cache:
            cache_time: float = self._cache_time.get(setting_id, 0.0)
            if now - cache_time < self._cache_ttl:
                return self._settings_cache[setting_id]

        try:
            value: str = self._addon.getSetting(setting_id)
            self._settings_cache[setting_id] = value
            self._cache_time[setting_id] = now
            return value
        except Exception as e:
            log(f"Error getting setting '{setting_id}': {e}")
            return default

    @property
    def autofill_playlist_on_play(self) -> bool:
        value: Optional[str] = self._get_setting('autofill_playlist_on_play')
        return value == 'true'

    @property
    def debug_mode(self) -> bool:
        value: Optional[str] = self._get_setting('debug_mode')
        return value == 'true'

    def get_string(self, string_id: int) -> str:
        try:
            return self._addon.getLocalizedString(string_id)
        except Exception as e:
            log(f"Error getting string {string_id}: {e}")
            return f"[String {string_id}]"

    def invalidate_cache(self) -> None:
        self._settings_cache.clear()
        self._cache_time.clear()

    def set_setting(self, setting_id: str, value: Union[bool, int, float, str]) -> bool:
        try:
            str_value: str
            if isinstance(value, bool):
                str_value = 'true' if value else 'false'
            elif isinstance(value, (int, float)):
                str_value = str(value)
            else:
                str_value = str(value)
            self._addon.setSetting(setting_id, str_value)
            self.invalidate_cache()
            return True
        except Exception as e:
            log(f"Error setting '{setting_id}': {e}")
            return False


SETTINGS: SettingsManager = SettingsManager()


def _get_cached_data(cache_name: str, force_reload: bool = False) -> Tuple[Any, bool]:
    with _cache_lock:
        cache: Optional[Dict[str, Any]] = _caches.get(cache_name)
        if not cache:
            return None, False

        now: float = time.time()
        if not force_reload and cache['data'] is not None and (now - cache['time']) < cache.get('ttl', 3600.0):
            return cache['data'], True

        return None, False


def _set_cached_data(cache_name: str, data: Any) -> None:
    with _cache_lock:
        cache: Optional[Dict[str, Any]] = _caches.get(cache_name)
        if cache:
            cache['data'] = data
            cache['time'] = time.time()


def load_skip_data(force_reload: bool = False) -> Dict[str, Any]:
    cached, hit = _get_cached_data('skip_data', force_reload)
    if hit:
        return cached

    if not os.path.exists(SKIP_DATA_FILE):
        _set_cached_data('skip_data', {})
        return {}

    try:
        with open(SKIP_DATA_FILE, 'r', encoding='utf-8') as f:
            data: Dict[str, Any] = json.load(f)
            _set_cached_data('skip_data', data)
            return data
    except Exception as e:
        log(f"Error loading skip data: {e}")
        return {}


def save_skip_data(data: Dict[str, Any]) -> None:
    temp_file: str = SKIP_DATA_FILE + ".tmp"
    backup_file: str = SKIP_DATA_FILE + ".bak"

    try:
        if os.path.exists(SKIP_DATA_FILE):
            shutil.copy2(SKIP_DATA_FILE, backup_file)

        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        with open(temp_file, 'r', encoding='utf-8') as f:
            json.load(f)

        os.replace(temp_file, SKIP_DATA_FILE)

        if os.path.exists(backup_file):
            os.remove(backup_file)

        _set_cached_data('skip_data', data)
    except Exception as e:
        log(f"Error saving skip data: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        if os.path.exists(backup_file):
            try:
                if os.path.exists(SKIP_DATA_FILE):
                    os.remove(SKIP_DATA_FILE)
                os.rename(backup_file, SKIP_DATA_FILE)
            except Exception as backup_e:
                log(f"Failed to restore backup: {backup_e}")


def delete_all_skip_points() -> None:
    if os.path.exists(SKIP_DATA_FILE):
        os.remove(SKIP_DATA_FILE)
    _set_cached_data('skip_data', {})


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
    except Exception as e:
        log(f"JSON-RPC call failed for {method}: {e}", xbmc.LOGERROR)
        return None

    if isinstance(response, dict) and "error" in response:
        log(f"JSON-RPC error for {method}: {response.get('error')}", xbmc.LOGWARNING)
        return None

    return response.get("result") if isinstance(response, dict) else None


def get_current_episode_id(tvshowid, season, episode, current_file=None):
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
                    log(f"get_current_episode_id: found episodeid={episodeid} for S{season}E{episode}")
                    return episodeid

        log(f"get_current_episode_id: no episodeid found for S{season}E{episode}")
        return None
    except Exception as e:
        log(f"get_current_episode_id error: {e}")
        return None


def get_tvshowid_from_title(show_title):
    try:
        result = jsonrpc_call(
            "VideoLibrary.GetTVShows", {"properties": ["title"]}
        ) or {}

        for show in result.get("tvshows", []):
            if show.get("label") == show_title:
                tvshowid = show.get("tvshowid")
                log(f"get_tvshowid_from_title: found tvshowid={tvshowid} for '{show_title}'")
                return tvshowid

        log(f"get_tvshowid_from_title: no tvshowid found for '{show_title}'")
        return None
    except Exception as e:
        log(f"get_tvshowid_from_title error: {e}")
        return None


def get_next_episode_from_library(tvshowid, current_file, include_watched=True, current_episode_num=None, current_season_num=None):
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

        episodes = result.get("episodes", [])
        current_index = -1

        if current_episode_num is not None and current_season_num is not None:
            current_season_num_int = int(current_season_num)
            current_episode_num_int = int(current_episode_num)
            for idx, episode in enumerate(episodes):
                if episode.get("season") == current_season_num_int and episode.get("episode") == current_episode_num_int:
                    current_index = idx
                    break

        if current_index == -1 and current_file:
            for idx, episode in enumerate(episodes):
                if episode.get("file") == current_file:
                    current_index = idx
                    break

        if current_index == -1 and current_file:
            current_file_normalized = normalize_media_path(current_file)
            for idx, episode in enumerate(episodes):
                episode_file_normalized = normalize_media_path(episode.get("file", ""))
                if episode_file_normalized and current_file_normalized:
                    if episode_file_normalized in current_file_normalized or current_file_normalized in episode_file_normalized:
                        current_index = idx
                        break

        if current_index == -1:
            return None

        next_index = current_index + 1
        if next_index < len(episodes):
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

        return None
    except Exception as e:
        log(f"get_next_episode_from_library: ERROR - {e}")
        return None


def get_season_episodes(tvshowid, season):
    try:
        if tvshowid in (None, -1, "") or season in (None, -1, ""):
            return None

        tvshowid_int = int(tvshowid)
        season_int = int(season)

        if tvshowid_int <= 0 or season_int <= 0:
            return None

        cache_key = f"{tvshowid_int}_{season_int}"
        with _cache_lock:
            cached = _caches['season_episodes'].get(cache_key)
            if cached and time.time() - cached['time'] < playlist_cache_expiry:
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
            _caches['season_episodes'][cache_key] = {'data': season_info, 'time': time.time()}

        return season_info
    except Exception as e:
        log(f"get_season_episodes: ERROR - {e}")
        return None


def play_episode_from_library(episode_info):
    episodeid = episode_info.get("episodeid")
    if not episodeid or episodeid == -1:
        return False
    result = jsonrpc_call("Player.Open", {"item": {"episodeid": episodeid}})
    return result == "OK"


def is_next_episode_available_in_playlist(playlist_id=None, playlist_position=None):
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


def play_file(file_path):
    file_path = str(file_path or "")
    if not file_path:
        return False
    result = jsonrpc_call("Player.Open", {"item": {"file": file_path}})
    return result == "OK"


def mark_current_episode_as_watched():
    state = get_active_video_playlist_state()
    if not state:
        return False

    episode_id = state.get("episodeid")
    if not episode_id or episode_id == -1:
        return False

    result = jsonrpc_call(
        "VideoLibrary.SetEpisodeDetails",
        {"episodeid": episode_id, "playcount": 1}
    )
    return result == "OK"


def normalize_media_path(path):
    if not path:
        return ""
    normalized = str(path).split('?', 1)[0].split('#', 1)[0]
    return normalized.replace('\\', '/').rstrip('/')


def extract_media_info_from_filename(filename):
    if not filename:
        return 0, 0, False

    basename = os.path.basename(normalize_media_path(filename))
    basename = os.path.splitext(basename)[0]

    patterns = [
        r'[sS](?P<season>\d{1,4})[.\-_]?[eE](?P<episode>\d{1,4})',
        r'(?P<season>\d{1,4})[xX](?P<episode>\d{1,4})',
        r'[eE][pP]?(?P<episode>\d{1,4})',
        r'第(?P<episode>\d{1,4})集',
        r'(?P<season>\d{1,4})[.\-](?P<episode>\d{1,4})',
        r'Season[\s._-]?(?P<season>\d{1,4})[\s._-]*Episode[\s._-]?(?P<episode>\d{1,4})',
        r'Season[\s._-]?(?P<season>\d{1,4})[\s._-]*E[\s._-]?(?P<episode>\d{1,4})',
        r'S(?P<season>\d{1,4})[\s._-]*E(?P<episode>\d{1,4})',
        r'(?P<season>\d{1,2})[xX](?P<episode>\d{2,3})',
        r'Episode[\s._-]?(?P<episode>\d{1,4})',
        r'Ep[\s._-]?(?P<episode>\d{1,4})',
        r'第(?P<season>\d{1,4})季第(?P<episode>\d{1,4})集',
        r'S(?P<season>\d{1,4})[ ._-]?EP(?P<episode>\d{1,4})',
        r'(\d{4})[._-](?P<episode>\d{1,4})',
        r'[sS](?P<season>\d{1,4})[ ._-]?(?P<episode>\d{1,4})',
    ]

    for pattern in patterns:
        match = re.search(pattern, basename)
        if match:
            groups = match.groupdict()
            season = int(groups.get("season", 1) or 1)
            episode = int(groups.get("episode", 1) or 1)
            if season > 0 and episode > 0:
                return season, episode, True

    return 0, 0, False


def natural_sort_key(value):
    text = str(value or "")
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', text)]


def get_parent_media_path(path):
    normalized = normalize_media_path(path)
    if not normalized:
        return None
    last_sep = normalized.rfind('/')
    if last_sep <= 0:
        return None
    return normalized[:last_sep]


def get_active_video_playlist_state():
    cached, hit = _get_cached_data('playlist_state')
    if hit:
        return cached

    players = jsonrpc_call("Player.GetActivePlayers") or []
    video_player = next((p for p in players if p.get("type") == "video"), None)
    if not video_player:
        return None

    player_id = video_player.get("playerid")
    properties = jsonrpc_call(
        "Player.GetProperties",
        {"playerid": player_id, "properties": ["playlistid", "position"]},
    ) or {}

    item = jsonrpc_call(
        "Player.GetItem",
        {"playerid": player_id, "properties": ["file", "tvshowid", "season", "episode", "showtitle", "title"]},
    ) or {}

    current_item = item.get("item") or {}
    playlist_id = int(properties.get("playlistid") or 1)
    current_position = int(properties.get("position") or 0)

    if playlist_id < 0 or current_position < 0:
        return None

    episode_no = current_item.get("episode")
    try:
        episode_no = int(episode_no) if episode_no is not None else None
    except (TypeError, ValueError):
        episode_no = None

    season_no = current_item.get("season")
    try:
        season_no = int(season_no) if season_no is not None else None
    except (TypeError, ValueError):
        season_no = None

    result = {
        "playerid": player_id,
        "playlistid": playlist_id,
        "position": current_position,
        "file": current_item.get("file") or "",
        "tvshowid": current_item.get("tvshowid"),
        "season": season_no,
        "episode": episode_no,
        "showtitle": current_item.get("showtitle") or "",
        "title": current_item.get("title") or "",
    }

    _set_cached_data('playlist_state', result)
    return result


def get_playlist_items(playlist_id):
    result = jsonrpc_call(
        "Playlist.GetItems",
        {"playlistid": playlist_id, "properties": ["tvshowid", "season", "episode", "file"]},
    ) or {}
    items = result.get("items") or []
    for idx, itm in enumerate(items):
        itm["position"] = idx
    return items


def get_season_episode_from_state(source_type, state, season):
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
    except Exception:
        return 1, 1


def get_directory_playlist_files(current_file):
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
        log(f"get_directory_playlist_files: ERROR - {e}")
        return []


def get_next_file_in_directory(current_file):
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
        idx = norms.index(current_norm)

        next_idx = idx + 1
        if next_idx >= len(files):
            return None

        return files[next_idx]
    except (ValueError, Exception):
        return None


def get_current_tvshow_info():
    try:
        json_query = {
            "jsonrpc": "2.0",
            "method": "Player.GetItem",
            "params": {"properties": ["tvshowid", "showtitle", "season", "file"], "playerid": 1},
            "id": 1
        }
        response = json.loads(xbmc.executeJSONRPC(json.dumps(json_query)))

        if 'result' in response and 'item' in response['result']:
            item = response['result']['item']
            item_type = item.get('type', '')
            tvshow_id = item.get('tvshowid')
            show_title = item.get('showtitle')
            season = item.get('season', -1)
            file_path = item.get('file')

            if item_type == 'movie' or item_type == 'musicvideo':
                return None, None, None, None

            if tvshow_id and tvshow_id != -1 and show_title:
                return str(tvshow_id), show_title, str(season), 'library'

            if file_path:
                if file_path.startswith("plugin://") or file_path.startswith("pvr://"):
                    return None, None, None, None

                basename = os.path.basename(file_path)
                has_episode_pattern = bool(re.search(r'[sS]\d{1,4}[._-]?[eE]\d{1,4}|\d{1,4}[xX]\d{1,4}|第\d{1,4}集', basename))

                if not has_episode_pattern:
                    return None, None, None, None

                parent_dir = os.path.dirname(file_path)
                dir_name = os.path.basename(parent_dir)

                season_num, episode_num, parsed = extract_media_info_from_filename(file_path)
                if not parsed or season_num <= 0:
                    season_num = 1

                return f"directory:{parent_dir}", dir_name, str(season_num), 'directory'
    except Exception as e:
        log(f"Error getting TV show info: {e}")
    return None, None, None, None


class State:
    _shared_state: Dict[str, bool] = {}
    _state_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self.__dict__ = self._shared_state
        if 'playing_next' not in self._shared_state:
            self.playing_next = False
            self.track = True
            self.pause = False

    @property
    def playing_next(self) -> bool:
        with self._state_lock:
            return self._shared_state.get('playing_next', False)

    @playing_next.setter
    def playing_next(self, value: bool) -> None:
        with self._state_lock:
            self._shared_state['playing_next'] = value
            log(f"State: playing_next set to {value}")

    def reset(self) -> None:
        with self._state_lock:
            self._shared_state.update({
                'playing_next': False,
                'track': True,
                'pause': False
            })


class EpisodePlaylistFixer:
    def __init__(self, playlist_id, current_episode, season_info):
        self.playlist_id = playlist_id
        if not isinstance(season_info, dict):
            raise ValueError(f"season_info must be a dict, got: {type(season_info).__name__}")

        tvshowid = season_info.get("tvshowid")
        season_id = season_info.get("season")
        episodes = season_info.get("episodes")

        if tvshowid in (None, -1) or season_id in (None, -1):
            raise ValueError(f"season_info must have valid tvshowid and season")

        if not episodes or not isinstance(episodes, list):
            raise ValueError(f"season_info must have a non-empty episodes list")

        try:
            self.current_episode = int(current_episode)
        except (TypeError, ValueError):
            raise ValueError(f"current_episode must be numeric")

        self.season_info = season_info
        self.playlist_items = get_playlist_items(playlist_id)
        self.current_play = self._find_current_play()

    def _find_current_play(self):
        tvshowid = self.season_info.get("tvshowid")
        season_id = self.season_info.get("season")
        for item in self.playlist_items:
            if (isinstance(item.get("episode"), int) and item.get("episode") == self.current_episode
                    and item.get("season") == season_id and item.get("tvshowid") == tvshowid):
                return item
        return None

    def _reindex_items(self):
        for idx, item in enumerate(self.playlist_items):
            item["position"] = idx

    def _insert(self, position, episode_item):
        episode_id = episode_item.get("id")
        episode_no = episode_item.get("episode")
        position = max(0, min(int(position), len(self.playlist_items)))

        result = jsonrpc_call(
            "Playlist.Insert",
            {"playlistid": self.playlist_id, "position": position, "item": {"episodeid": episode_id}},
        )
        if result != "OK":
            return False

        self.playlist_items.insert(position, {
            "position": position,
            "type": "episode",
            "episode": episode_no,
            "id": episode_id,
            "season": episode_item.get("season"),
            "tvshowid": episode_item.get("tvshowid"),
        })
        self._reindex_items()
        xbmc.sleep(PLAYLIST_MUTATION_DELAY_MS)
        return True

    def _remove(self, position):
        try:
            position = int(position)
        except (TypeError, ValueError):
            return False

        current_pos = self.current_play.get("position") if isinstance(self.current_play, dict) else None
        if isinstance(current_pos, int) and position == current_pos:
            return False

        result = jsonrpc_call("Playlist.Remove", {"playlistid": self.playlist_id, "position": position})
        if result != "OK":
            return False

        if 0 <= position < len(self.playlist_items):
            self.playlist_items.pop(position)
        self._reindex_items()
        xbmc.sleep(PLAYLIST_MUTATION_DELAY_MS)
        return True

    def _remove_incorrect_order_episodes(self):
        if not self.current_play:
            return 0

        current_tvshowid = self.season_info.get("tvshowid")
        current_season_id = self.season_info.get("season")

        remove_items = []
        for item in self.playlist_items[self.current_play["position"] + 1:]:
            is_same_season = item.get("tvshowid") == current_tvshowid and item.get("season") == current_season_id
            if not is_same_season:
                continue
            episode_no = item.get("episode")
            if isinstance(episode_no, int) and episode_no < self.current_episode:
                remove_items.append(item)
                if len(remove_items) >= MAX_DELETE_LOWER_EPISODES_BELOW:
                    break

        removed = 0
        for item in sorted(remove_items, key=lambda x: x.get("position", -1), reverse=True):
            pos = item.get("position")
            if isinstance(pos, int) and self._remove(pos):
                removed += 1
        return removed

    def _get_insert_position(self, target_episode):
        if not isinstance(target_episode, int):
            return None

        current_tvshowid = self.season_info.get("tvshowid")
        current_season_id = self.season_info.get("season")
        last_same_season_position = None

        for item in self.playlist_items:
            is_same_season = item.get("tvshowid") == current_tvshowid and item.get("season") == current_season_id
            if not is_same_season:
                continue
            position = item.get("position")
            last_same_season_position = position
            item_ep = item.get("episode")
            if isinstance(item_ep, int) and item_ep > target_episode:
                return position

        return last_same_season_position + 1 if isinstance(last_same_season_position, int) else len(self.playlist_items)

    def _fill_neighbors_around_current(self):
        if not self.current_play:
            return 0, 0

        season_episodes = self.season_info.get("episodes")
        if not isinstance(season_episodes, list):
            return 0, 0

        current_play_id = self.current_play.get("id")
        current_episode_idx = next((idx for idx, item in enumerate(season_episodes)
                                    if isinstance(item, dict) and item.get("id") == current_play_id), -1)
        if current_episode_idx < 0:
            return 0, 0

        current_tvshowid = self.season_info.get("tvshowid")
        current_season_id = self.season_info.get("season")
        existing_ids = {
            item.get("id") for item in self.playlist_items
            if item.get("tvshowid") == current_tvshowid and item.get("season") == current_season_id
        }

        desired_before = season_episodes[max(0, current_episode_idx - MAX_PLAYLIST_ITEMS_BEFORE):current_episode_idx]
        desired_after = season_episodes[current_episode_idx + 1:current_episode_idx + 1 + MAX_PLAYLIST_ITEMS_AFTER]
        missing_before = [item for item in desired_before if item.get("id") not in existing_ids]
        missing_after = [item for item in desired_after if item.get("id") not in existing_ids]

        insert_before = insert_after = 0
        for episode_item in missing_before:
            insert_pos = self._get_insert_position(episode_item.get("episode"))
            if isinstance(insert_pos, int) and self._insert(insert_pos, episode_item):
                insert_before += 1
                existing_ids.add(episode_item.get("id"))

        for episode_item in missing_after:
            insert_pos = self._get_insert_position(episode_item.get("episode"))
            if isinstance(insert_pos, int) and self._insert(insert_pos, episode_item):
                insert_after += 1
                existing_ids.add(episode_item.get("id"))

        return insert_before, insert_after

    def fix(self):
        if not isinstance(self.current_play, dict):
            return {"removed": 0, "inserted_before": 0, "inserted_after": 0, "playlistid": self.playlist_id}

        try:
            removed_below = self._remove_incorrect_order_episodes()
            inserted_before, inserted_after = self._fill_neighbors_around_current()

            if removed_below or inserted_before or inserted_after:
                log(f"Synced season playlist: removed_below={removed_below}, before={inserted_before}, after={inserted_after}")

            return {
                "removed": removed_below,
                "inserted_before": inserted_before,
                "inserted_after": inserted_after,
                "playlistid": self.playlist_id,
            }
        except Exception as e:
            log(f"Error fixing playlist: {e}")
            return {"removed": 0, "inserted_before": 0, "inserted_after": 0, "playlistid": self.playlist_id}


def autofill_playlist_for_current_video():
    def _autofill_thread():
        try:
            time.sleep(2)
            _do_autofill()
        except Exception as e:
            log(f"Autofill thread error: {e}")

    thread = threading.Thread(target=_autofill_thread)
    thread.daemon = True
    thread.start()


def _do_autofill():
    if not SETTINGS.autofill_playlist_on_play:
        return

    state = get_active_video_playlist_state()
    if not state:
        return

    current_file = state.get("file") or ""
    current_file_norm = normalize_media_path(current_file)
    if not current_file_norm:
        return

    tvshow_id = state.get("tvshowid")
    season = state.get("season")
    current_episode = state.get("episode")
    is_scraped_tvshow = tvshow_id not in (None, -1) and season not in (None, -1)

    if is_scraped_tvshow and current_episode is not None and current_episode != -1:
        season_info = get_season_episodes(tvshow_id, season)
        if season_info:
            fixer = EpisodePlaylistFixer(playlist_id=state.get("playlistid", 1),
                                         current_episode=current_episode,
                                         season_info=season_info)
            fixer.fix()
        return

    if current_file_norm.startswith("plugin://") or current_file_norm.startswith("pvr://"):
        return

    target_files = get_directory_playlist_files(current_file)
    target_files = [path for path in target_files if path]
    if len(target_files) <= 1:
        return

    target_norms = [normalize_media_path(path) for path in target_files]
    if current_file_norm not in target_norms:
        return

    _sync_directory_playlist(state.get("playlistid", 1), state.get("position", 0),
                             current_file_norm, target_norms, target_files)


def _sync_directory_playlist(playlist_id, current_position, current_file_norm, target_norms, target_files):
    playlist_items = get_playlist_items(playlist_id)
    current_playlist_norms = {
        normalize_media_path(item.get("file", "")) for item in playlist_items if item.get("file")
    }
    current_playlist_norms.discard("")

    try:
        current_target_idx = target_norms.index(current_file_norm)
    except ValueError:
        return

    missing_before = [
        path for path, norm in zip(target_files[:current_target_idx], target_norms[:current_target_idx])
        if norm not in current_playlist_norms
    ][-MAX_PLAYLIST_ITEMS_BEFORE:]
    missing_after = [
        path for path, norm in zip(target_files[current_target_idx + 1:], target_norms[current_target_idx + 1:])
        if norm not in current_playlist_norms
    ][:MAX_PLAYLIST_ITEMS_AFTER]

    if not missing_before and not missing_after:
        return

    inserted_before = 0
    for path in missing_before:
        result = jsonrpc_call(
            "Playlist.Insert",
            {"playlistid": playlist_id, "position": current_position + inserted_before, "item": {"file": path}},
        )
        if result == "OK":
            inserted_before += 1
            xbmc.sleep(PLAYLIST_MUTATION_DELAY_MS)

    insert_pos = current_position + inserted_before + 1
    inserted_after = 0
    for path in missing_after:
        result = jsonrpc_call(
            "Playlist.Insert",
            {"playlistid": playlist_id, "position": insert_pos, "item": {"file": path}},
        )
        if result == "OK":
            inserted_after += 1
            insert_pos += 1
            xbmc.sleep(PLAYLIST_MUTATION_DELAY_MS)
