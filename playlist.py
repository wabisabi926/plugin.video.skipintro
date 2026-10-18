# -*- coding: utf-8 -*-
"""播放列表修复与自动补全。"""
import threading
from typing import Any, Dict, List, Optional, Tuple

import xbmc

from common import (
    AUTOFILL_DELAY_SECONDS,
    MAX_DELETE_LOWER_EPISODES_BELOW,
    MAX_PLAYLIST_ITEMS_AFTER,
    MAX_PLAYLIST_ITEMS_BEFORE,
    PLAYLIST_MUTATION_DELAY_MS,
    SETTINGS,
    _autofill_event,
    log,
    log_debug,
)
from media import (
    get_active_video_playlist_state,
    get_directory_playlist_files,
    get_playlist_items,
    get_season_episodes,
    jsonrpc_call,
    normalize_media_path,
)

# 自动补全线程去重（拆出模块后需在本模块初始化）
_autofill_thread: Optional[threading.Thread] = None


class EpisodePlaylistFixer:
    def __init__(self, playlist_id: int, current_episode: int, season_info: Dict[str, Any]):
        self.playlist_id = playlist_id
        if not isinstance(season_info, dict):
            raise ValueError(f"season_info must be a dict, got: {type(season_info).__name__}")

        tvshowid = season_info.get("tvshowid")
        season_id = season_info.get("season")
        episodes = season_info.get("episodes")

        if tvshowid in (None, -1) or season_id in (None, -1):
            raise ValueError("season_info must have valid tvshowid and season")

        if not episodes or not isinstance(episodes, list):
            raise ValueError("season_info must have a non-empty episodes list")

        try:
            self.current_episode = int(current_episode)
        except (TypeError, ValueError):
            raise ValueError("current_episode must be numeric")

        self.season_info = season_info
        self.playlist_items = get_playlist_items(playlist_id)
        self.current_play = self._find_current_play()

    def _find_current_play(self) -> Optional[Dict[str, Any]]:
        tvshowid = self.season_info.get("tvshowid")
        season_id = self.season_info.get("season")
        for item in self.playlist_items:
            if (isinstance(item.get("episode"), int) and item.get("episode") == self.current_episode
                    and item.get("season") == season_id and item.get("tvshowid") == tvshowid):
                return item
        return None

    def _reindex_items(self) -> None:
        for idx, item in enumerate(self.playlist_items):
            item["position"] = idx

    def _insert(self, position: int, episode_item: Dict[str, Any]) -> bool:
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

    def _remove(self, position: int) -> bool:
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

    def _remove_incorrect_order_episodes(self) -> int:
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

    def _get_insert_position(self, target_episode: int) -> Optional[int]:
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

    def _fill_neighbors_around_current(self) -> Tuple[int, int]:
        if not self.current_play:
            return 0, 0

        season_episodes = self.season_info.get("episodes")
        if not isinstance(season_episodes, list):
            return 0, 0

        current_play_id = self.current_play.get("id")
        current_episode_idx = next((
            idx for idx, item in enumerate(season_episodes)
            if isinstance(item, dict) and item.get("id") == current_play_id
        ), -1)
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

    def fix(self) -> Dict[str, Any]:
        if not isinstance(self.current_play, dict):
            return {"removed": 0, "inserted_before": 0, "inserted_after": 0, "playlistid": self.playlist_id}

        try:
            removed_below = self._remove_incorrect_order_episodes()
            inserted_before, inserted_after = self._fill_neighbors_around_current()

            if removed_below or inserted_before or inserted_after:
                log_debug(f"Synced season playlist: removed={removed_below}, before={inserted_before}, after={inserted_after}")

            return {
                "removed": removed_below,
                "inserted_before": inserted_before,
                "inserted_after": inserted_after,
                "playlistid": self.playlist_id,
            }
        except Exception as e:
            log(f"Error fixing playlist: {e}", xbmc.LOGERROR)
            return {"removed": 0, "inserted_before": 0, "inserted_after": 0, "playlistid": self.playlist_id}


def autofill_playlist_for_current_video() -> None:
    global _autofill_thread

    if _autofill_thread and _autofill_thread.is_alive():
        # Signal existing thread to restart countdown
        _autofill_event.set()
        return

    _autofill_event.clear()

    def _autofill_thread_func() -> None:
        try:
            # Wait for delay or early signal
            if not _autofill_event.wait(AUTOFILL_DELAY_SECONDS):
                _do_autofill()
            else:
                # Re-signaled, wait again
                if not _autofill_event.wait(AUTOFILL_DELAY_SECONDS):
                    _do_autofill()
        except Exception as e:
            log(f"Autofill thread error: {e}", xbmc.LOGERROR)
        finally:
            global _autofill_thread
            _autofill_thread = None

    _autofill_thread = threading.Thread(target=_autofill_thread_func)
    _autofill_thread.daemon = True
    _autofill_thread.start()


def _do_autofill() -> None:
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
            fixer = EpisodePlaylistFixer(
                playlist_id=state.get("playlistid", 1),
                current_episode=current_episode,
                season_info=season_info
            )
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

    _sync_directory_playlist(
        state.get("playlistid", 1), state.get("position", 0),
        current_file_norm, target_norms, target_files
    )


def _sync_directory_playlist(playlist_id: int, current_position: int,
                               current_file_norm: str, target_norms: List[str],
                               target_files: List[str]) -> None:
    playlist_items = get_playlist_items(playlist_id)
    current_playlist_norms = {
        normalize_media_path(item.get("file", "")) for item in playlist_items if item.get("file")
    }
    current_playlist_norms.discard("")

    try:
        current_target_idx = target_norms.index(current_file_norm)
    except ValueError:
        return

    # Get files before current (up to MAX_PLAYLIST_ITEMS_BEFORE)
    before_slice = target_files[:current_target_idx]
    missing_before = [
        path for path, norm in zip(before_slice, target_norms[:current_target_idx])
        if norm not in current_playlist_norms
    ][-MAX_PLAYLIST_ITEMS_BEFORE:]

    # Get files after current (up to MAX_PLAYLIST_ITEMS_AFTER)
    after_slice = target_files[current_target_idx + 1:]
    missing_after = [
        path for path, norm in zip(after_slice, target_norms[current_target_idx + 1:])
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
