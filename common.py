# -*- coding: utf-8 -*-
import xbmc
import xbmcvfs
import json
import os
import re
import time
import threading
import xbmcaddon
import traceback

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

_cache_lock = threading.Lock()
playlist_cache = {}
playlist_cache_expiry = 3600

_skip_data_cache = {}
_skip_data_cache_time = 0
_skip_data_cache_ttl = 2.0

_playlist_state_cache = {"data": None, "time": 0}
_PLAYLIST_STATE_CACHE_TTL = 0.5


def log(msg, prefix="[SkipIntro]"):
    xbmc.log(f"{prefix} {msg}", xbmc.LOGINFO)


def load_skip_data(force_reload=False):
    global _skip_data_cache, _skip_data_cache_time
    now = time.time()
    
    with _cache_lock:
        if not force_reload and _skip_data_cache and (now - _skip_data_cache_time) < _skip_data_cache_ttl:
            return _skip_data_cache
        if not os.path.exists(SKIP_DATA_FILE):
            _skip_data_cache = {}
            _skip_data_cache_time = now
            return {}
        try:
            with open(SKIP_DATA_FILE, 'r', encoding='utf-8') as f:
                _skip_data_cache = json.load(f)
                _skip_data_cache_time = now
                return _skip_data_cache
        except Exception as e:
            log(f"Error loading skip data: {e}")
            return {}


def save_skip_data(data):
    global _skip_data_cache, _skip_data_cache_time
    with _cache_lock:
        try:
            with open(SKIP_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            _skip_data_cache = data
            _skip_data_cache_time = time.time()
        except Exception as e:
            log(f"Error saving skip data: {e}")


def get_current_episode_id(tvshowid, season, episode):
    try:
        tvshowid = int(tvshowid) if tvshowid not in (None, -1, "") else None
        season = int(season) if season not in (None, -1, "") else None
        episode = int(episode) if episode not in (None, -1, "") else None
        
        if any(v is None for v in [tvshowid, season, episode]):
            return None
        
        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {
                "properties": ["episode", "season"],
                "tvshowid": tvshowid,
            }
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
            "VideoLibrary.GetTVShows",
            {
                "properties": ["title"]
            }
        ) or {}
        
        shows = result.get("tvshows") or []
        for show in shows:
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
        log("-"*50)
        log("get_next_episode_from_library: starting")
        
        if tvshowid in (None, -1, ""):
            log("get_next_episode_from_library: invalid tvshowid")
            return None
        
        tvshowid = int(tvshowid)
        if tvshowid == -1:
            log("get_next_episode_from_library: tvshowid is -1")
            return None
        
        log(f"get_next_episode_from_library: tvshowid={tvshowid}, current_file={current_file}")
        log(f"get_next_episode_from_library: current_episode_num={current_episode_num}, current_season_num={current_season_num}")
        
        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {
                "tvshowid": tvshowid,
                "properties": [
                    "title", "plot", "season", "episode", "playcount",
                    "showtitle", "file", "art", "runtime", "firstaired",
                    "dateadded", "lastplayed"
                ],
                "sort": {"method": "episode"},
            }
        )
        
        if not result or not result.get("episodes"):
            log("get_next_episode_from_library: no episodes found in library")
            return None
        
        episodes = result.get("episodes", [])
        log(f"get_next_episode_from_library: found {len(episodes)} episodes in library")
        
        current_index = -1
        
        if current_episode_num is not None and current_season_num is not None:
            log(f"get_next_episode_from_library: [1/3] Trying season/episode match")
            current_season_num_int = int(current_season_num)
            current_episode_num_int = int(current_episode_num)
            for idx, episode in enumerate(episodes):
                ep_season = episode.get("season")
                ep_episode = episode.get("episode")
                if ep_season == current_season_num_int and ep_episode == current_episode_num_int:
                    current_index = idx
                    log(f"get_next_episode_from_library: matched current at index {idx}")
                    break
        
        if current_index == -1 and current_file:
            log(f"get_next_episode_from_library: [2/3] Trying exact file match")
            for idx, episode in enumerate(episodes):
                if episode.get("file") == current_file:
                    current_index = idx
                    log(f"get_next_episode_from_library: matched current at index {idx}")
                    break
        
        if current_index == -1 and current_file:
            log(f"get_next_episode_from_library: [3/3] Trying partial file match")
            current_file_normalized = normalize_media_path(current_file)
            for idx, episode in enumerate(episodes):
                episode_file_normalized = normalize_media_path(episode.get("file", ""))
                if episode_file_normalized and current_file_normalized:
                    if episode_file_normalized in current_file_normalized or current_file_normalized in episode_file_normalized:
                        current_index = idx
                        log(f"get_next_episode_from_library: matched current at index {idx}")
                        break
        
        if current_index == -1:
            log("get_next_episode_from_library: could not find current episode, returning None")
            return None
        
        log(f"get_next_episode_from_library: current episode at index {current_index}")
        
        next_index = current_index + 1
        
        if next_index < len(episodes):
            next_episode = episodes[next_index]
            
            if not include_watched:
                playcount = next_episode.get("playcount", 0)
                if playcount and playcount > 0:
                    log(f"get_next_episode_from_library: next episode is watched, skipping")
                    return None
            
            log(f"get_next_episode_from_library: SUCCESS - found S{next_episode.get('season')}E{next_episode.get('episode')}")
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
        
        log("get_next_episode_from_library: no next episode (current is last)")
        return None
    except Exception as e:
        log(f"get_next_episode_from_library: ERROR - {e}")
        log(traceback.format_exc())
        return None


def get_current_episode_id_from_file(episode_file, current_file):
    try:
        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {
                "properties": ["file", "episode", "season"]
            }
        ) or {}
        
        episodes = result.get("episodes") or []
        for ep in episodes:
            if ep.get("file") == current_file:
                return ep.get("episodeid")
        
        return None
    except Exception as e:
        log(f"get_current_episode_id_from_file error: {e}")
        return None


def get_season_episodes_from_library(tvshowid, season):
    try:
        if tvshowid in (None, -1) or season in (None, -1):
            return None
        
        tvshowid = int(tvshowid)
        season = int(season)
        
        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {
                "tvshowid": tvshowid,
                "season": season,
                "properties": ["file", "episode", "season", "title", "playcount"],
                "sort": {"method": "episode", "order": "ascending"},
            }
        ) or {}
        
        episodes = result.get("episodes") or []
        if not episodes:
            return None
        
        log(f"get_season_episodes_from_library: found {len(episodes)} episodes for S{season}")
        return episodes
    except Exception as e:
        log(f"get_season_episodes_from_library error: {e}")
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


def get_next_file_in_directory(current_file):
    current_norm = normalize_media_path(current_file)
    if not current_norm:
        return None
    files = get_directory_playlist_files(current_norm)
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


class State:
    _shared_state = {}
    _state_lock = threading.Lock()
    
    def __init__(self):
        self.__dict__ = self._shared_state
        self.playing_next = False
        self.track = True
        self.pause = False
    
    def set_playing_next(self, value):
        with self._state_lock:
            self.playing_next = value
            log(f"State: playing_next set to {value}")
    
    def get_playing_next(self):
        with self._state_lock:
            return self.playing_next
    
    def reset(self):
        with self._state_lock:
            self.playing_next = False
            self.track = True
            self.pause = False
            log("State: reset to default values")


def get_current_tvshow_info():
    try:
        json_query = {
            "jsonrpc": "2.0",
            "method": "Player.GetItem",
            "params": {
                "properties": ["tvshowid", "showtitle", "season", "file"],
                "playerid": 1
            },
            "id": 1
        }
        json_response = xbmc.executeJSONRPC(json.dumps(json_query))
        response = json.loads(json_response)

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

                return f"directory:{parent_dir}", dir_name, "1", 'directory'
    except Exception as e:
        log(f"Error getting TV show info: {e}")
    return None, None, None, None


def jsonrpc_call(method, params=None, request_id=None):
    query = {
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
        log(f"JSON-RPC traceback: {traceback.format_exc()}", xbmc.LOGERROR)
        return None

    if isinstance(response, dict) and "error" in response:
        log(f"JSON-RPC error for {method}: {response.get('error')}", xbmc.LOGWARNING)
        return None
    return response.get("result") if isinstance(response, dict) else None


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
    global _playlist_state_cache
    now = time.time()
    
    with _cache_lock:
        if _playlist_state_cache["data"] and (now - _playlist_state_cache["time"]) < _PLAYLIST_STATE_CACHE_TTL:
            return _playlist_state_cache["data"]
    
    players = jsonrpc_call("Player.GetActivePlayers") or []
    video_player = next((p for p in players if p.get("type") == "video"), None)
    if not video_player:
        log("get_active_video_playlist_state: no active video player")
        return None

    player_id = video_player.get("playerid")
    log(f"get_active_video_playlist_state: player_id={player_id}")
    
    properties = jsonrpc_call(
        "Player.GetProperties",
        {
            "playerid": player_id,
            "properties": ["playlistid", "position"],
        },
    ) or {}
    log(f"get_active_video_playlist_state: properties={properties}")
    
    item = jsonrpc_call(
        "Player.GetItem",
        {
            "playerid": player_id,
            "properties": ["file", "tvshowid", "season", "episode", "showtitle", "title"],
        },
    ) or {}
    log(f"get_active_video_playlist_state: item={item}")

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
    log(f"get_active_video_playlist_state: result={result}")
    
    with _cache_lock:
        _playlist_state_cache = {"data": result, "time": now}
    
    return result


def get_playlist_items(playlist_id):
    result = jsonrpc_call(
        "Playlist.GetItems",
        {
            "playlistid": playlist_id,
            "properties": ["tvshowid", "season", "episode", "file"],
        },
    ) or {}
    items = result.get("items") or []
    for idx, itm in enumerate(items):
        itm["position"] = idx
    return items


def get_season_episodes(tvshow_id, season):
    if tvshow_id in (None, -1) or season in (None, -1):
        return None

    cache_key = f"season_{tvshow_id}_{season}"
    
    with _cache_lock:
        if cache_key in playlist_cache:
            cached = playlist_cache[cache_key]
            if time.time() - cached['time'] < playlist_cache_expiry:
                return cached['data']

    result = jsonrpc_call(
        "VideoLibrary.GetEpisodes",
        {
            "tvshowid": int(tvshow_id),
            "season": int(season),
            "properties": ["file", "episode", "season", "title"],
            "sort": {"method": "episode", "order": "ascending"},
        },
    ) or {}
    episodes = result.get("episodes") or []

    if not episodes:
        return None

    for itm in episodes:
        itm["tvshowid"] = int(tvshow_id)
        itm["season"] = int(season)
        itm["id"] = itm.get("episodeid")

    season_info = {
        "tvshowid": int(tvshow_id),
        "season": int(season),
        "episodes": episodes,
    }

    with _cache_lock:
        playlist_cache[cache_key] = {'data': season_info, 'time': time.time()}
    
    return season_info


def get_directory_playlist_files(current_file):
    parent_dir = get_parent_media_path(current_file)
    if not parent_dir:
        return []

    result = jsonrpc_call(
        "Files.GetDirectory",
        {
            "directory": parent_dir,
            "media": "video",
            "properties": ["file", "title"],
        },
    ) or {}
    files = result.get("files") or []

    playlist_items = []
    for item in files:
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
    if ADDON.getSetting('autofill_playlist_on_play') == 'false':
        log("Autofill playlist is disabled")
        return

    state = get_active_video_playlist_state()
    if not state:
        log("No active video playlist state")
        return

    current_file = state.get("file") or ""
    current_file_norm = normalize_media_path(current_file)
    if not current_file_norm:
        log("No current file")
        return

    tvshow_id = state.get("tvshowid")
    season = state.get("season")
    current_episode = state.get("episode")
    is_scraped_tvshow = tvshow_id not in (None, -1) and season not in (None, -1)

    if is_scraped_tvshow and current_episode is not None and current_episode != -1:
        season_info = get_season_episodes(tvshow_id, season)
        if not season_info:
            log("No season info found")
            return
        playlist_id = state.get("playlistid", 1)
        fixer = EpisodePlaylistFixer(
            playlist_id=playlist_id,
            current_episode=current_episode,
            season_info=season_info,
        )
        fixer.fix()
        return

    if current_file_norm.startswith("plugin://") or current_file_norm.startswith("pvr://"):
        log("Plugin or PVR stream, skipping autofill")
        return

    target_files = get_directory_playlist_files(current_file)
    target_files = [path for path in target_files if path]
    if len(target_files) <= 1:
        log("Only one or no files found, skipping autofill")
        return

    target_norms = [normalize_media_path(path) for path in target_files]
    if current_file_norm not in target_norms:
        log("Current file not in target list")
        return

    playlist_id = state.get("playlistid", 1)
    current_position = state.get("position", 0)

    _sync_directory_playlist(playlist_id, current_position, current_file_norm, target_norms, target_files)


class EpisodePlaylistFixer:
    def __init__(self, playlist_id, current_episode, season_info):
        self.playlist_id = playlist_id
        if not isinstance(season_info, dict):
            raise ValueError(f"season_info must be a dict, got: {type(season_info).__name__}")
        tvshowid = season_info.get("tvshowid")
        season_id = season_info.get("season")
        if tvshowid in (None, -1) or season_id in (None, -1):
            raise ValueError(f"season_info must have valid tvshowid and season, got: tvshowid={tvshowid}, season={season_id}")
        episodes = season_info.get("episodes")
        if not episodes or not isinstance(episodes, list):
            raise ValueError(f"season_info must have a non-empty episodes list, got: {episodes}")

        try:
            self.current_episode = int(current_episode)
        except (TypeError, ValueError):
            raise ValueError(f"current_episode must be numeric, got: {current_episode!r}")

        self.season_info = season_info
        self.playlist_items = get_playlist_items(playlist_id)
        self.current_play = self._find_current_play()

    def _find_current_play(self):
        tvshowid = self.season_info.get("tvshowid")
        season_id = self.season_info.get("season")
        for item in self.playlist_items:
            if (isinstance(item.get("episode"), int) and item.get("episode") == self.current_episode
                    and item.get("season") == season_id
                    and item.get("tvshowid") == tvshowid):
                return item
        log(f"Current playing episode {self.current_episode} not found in playlist", xbmc.LOGWARNING)
        return None

    def _reindex_items(self):
        for idx, item in enumerate(self.playlist_items):
            item["position"] = idx

    def _insert(self, position, episode_item):
        episode_id = episode_item.get("id")
        episode_no = episode_item.get("episode")
        position = int(position)
        position = max(0, min(position, len(self.playlist_items)))

        result = jsonrpc_call(
            "Playlist.Insert",
            {
                "playlistid": self.playlist_id,
                "position": position,
                "item": {"episodeid": episode_id},
            },
        )
        if result != "OK":
            log(f"Playlist.Insert failed: position={position}, episodeid={episode_id}, playlistid={self.playlist_id}")
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
            log(f"Skip removing current playing item: position={position}, playlistid={self.playlist_id}")
            return False

        result = jsonrpc_call(
            "Playlist.Remove",
            {
                "playlistid": self.playlist_id,
                "position": position,
            },
        )
        if result != "OK":
            log(f"Playlist.Remove failed: position={position}, playlistid={self.playlist_id}")
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
            is_same_tvshow = item.get("tvshowid") == current_tvshowid
            is_same_season = is_same_tvshow and item.get("season") == current_season_id
            if not is_same_season:
                continue
            episode_no = item.get("episode")
            if isinstance(episode_no, int) and episode_no < self.current_episode:
                remove_items.append(item)
                if len(remove_items) >= MAX_DELETE_LOWER_EPISODES_BELOW:
                    break

        if not remove_items:
            return 0

        log(f"Playlist remove plan: current_episode={self.current_episode}, "
            f"remove_after={[item.get('episode') for item in remove_items]}, "
            f"playlistid={self.playlist_id}")

        removed = 0
        for item in sorted(remove_items, key=lambda x: x.get("position", -1), reverse=True):
            pos = item.get("position")
            if not isinstance(pos, int):
                continue
            if self._remove(pos):
                removed += 1
                log(f"Removed incorrect order item: episode={item.get('episode')}, "
                    f"id={item.get('id')}, position={pos}, playlistid={self.playlist_id}")
        return removed

    def _get_insert_position(self, target_episode):
        if not isinstance(target_episode, int):
            return None

        current_tvshowid = self.season_info.get("tvshowid")
        current_season_id = self.season_info.get("season")
        last_same_season_position = None
        for item in self.playlist_items:
            is_same_tvshow = item.get("tvshowid") == current_tvshowid
            is_same_season = is_same_tvshow and item.get("season") == current_season_id
            if not is_same_season:
                continue
            position = item.get("position")
            last_same_season_position = position
            item_ep = item.get("episode")
            if isinstance(item_ep, int) and item_ep > target_episode:
                return position
        if isinstance(last_same_season_position, int):
            return last_same_season_position + 1
        return len(self.playlist_items)

    def _fill_neighbors_around_current(self):
        insert_before = 0
        insert_after = 0
        if not self.current_play:
            return insert_before, insert_after

        season_episodes = self.season_info.get("episodes")
        if not isinstance(season_episodes, list):
            return insert_before, insert_after

        current_play_id = self.current_play.get("id")
        current_episode_idx = -1
        for idx, item in enumerate(season_episodes):
            if isinstance(item, dict) and item.get("id") == current_play_id:
                current_episode_idx = idx
                break

        if current_episode_idx < 0:
            return insert_before, insert_after

        current_tvshowid = self.season_info.get("tvshowid")
        current_season_id = self.season_info.get("season")
        existing_ids = {
            item.get("id")
            for item in self.playlist_items
            if item.get("tvshowid") == current_tvshowid
            and item.get("season") == current_season_id
            and isinstance(item.get("id"), int)
        }

        desired_before = season_episodes[max(0, current_episode_idx - MAX_PLAYLIST_ITEMS_BEFORE):current_episode_idx]
        desired_after = season_episodes[current_episode_idx + 1:current_episode_idx + 1 + MAX_PLAYLIST_ITEMS_AFTER]
        missing_before = [item for item in desired_before if item.get("id") not in existing_ids]
        missing_after = [item for item in desired_after if item.get("id") not in existing_ids]

        if missing_before or missing_after:
            log(f"Playlist fill plan: current_episode={self.current_episode}, "
                f"missing_before={[item.get('episode') for item in missing_before]}, "
                f"missing_after={[item.get('episode') for item in missing_after]}, "
                f"playlistid={self.playlist_id}")

        for episode_item in missing_before:
            insert_pos = self._get_insert_position(episode_item.get("episode"))
            if not isinstance(insert_pos, int):
                continue
            if self._insert(insert_pos, episode_item):
                insert_before += 1
                existing_ids.add(episode_item.get("id"))
                log(f"Inserted missing before: episode={episode_item.get('episode')}, "
                    f"id={episode_item.get('id')}, position={insert_pos}, playlistid={self.playlist_id}")

        for episode_item in missing_after:
            insert_pos = self._get_insert_position(episode_item.get("episode"))
            if not isinstance(insert_pos, int):
                continue
            if self._insert(insert_pos, episode_item):
                insert_after += 1
                existing_ids.add(episode_item.get("id"))
                log(f"Inserted missing after: episode={episode_item.get('episode')}, "
                    f"id={episode_item.get('id')}, position={insert_pos}, playlistid={self.playlist_id}")

        return insert_before, insert_after

    def fix(self):
        if not isinstance(self.current_play, dict):
            return {"removed": 0, "inserted_before": 0, "inserted_after": 0, "playlistid": self.playlist_id}

        try:
            removed_below = self._remove_incorrect_order_episodes()
            inserted_before, inserted_after = self._fill_neighbors_around_current()

            if removed_below or inserted_before or inserted_after:
                log(f"Synced season playlist: removed_below={removed_below}, "
                    f"before={inserted_before}, after={inserted_after}, "
                    f"playlistid={self.playlist_id}")

            return {
                "removed": removed_below,
                "inserted_before": inserted_before,
                "inserted_after": inserted_after,
                "playlistid": self.playlist_id,
            }
        except Exception as e:
            log(f"Error fixing playlist: {e}")
            return {"removed": 0, "inserted_before": 0, "inserted_after": 0, "playlistid": self.playlist_id}


def _sync_directory_playlist(playlist_id, current_position, current_file_norm, target_norms, target_files):
    playlist_items = get_playlist_items(playlist_id)
    current_playlist_norms = {
        normalize_media_path(item.get("file", "")) for item in playlist_items if item.get("file")
    }
    current_playlist_norms.discard("")

    try:
        current_target_idx = target_norms.index(current_file_norm)
    except ValueError:
        log(f"Current file not found in target list: {current_file_norm}")
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
        log("All files already in playlist")
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

    if inserted_before or inserted_after:
        log(f"Autofilled directory playlist: before={inserted_before}, after={inserted_after}, playlistid={playlist_id}")
