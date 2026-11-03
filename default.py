# -*- coding: utf-8 -*-
import sys
import urllib.parse
import os
from typing import Tuple

import xbmc
import xbmcgui

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "lib"))

from skipintro.common import (
    ADDON, load_skip_data, save_skip_data,
    log, SETTINGS, delete_all_skip_points,
    show_notification, wait_for_notifications,
    set_skip_point, clear_skip_point, get_skip_point, prune_skip_record,
    SKIP_THRESHOLD_INTRO, SKIP_THRESHOLD_OUTRO
)
from skipintro.media import (
    get_current_tvshow_info, get_active_video_playlist_state,
    get_season_episode_from_state, get_current_episode_number,
)


def get_current_playback_time() -> Tuple[float, float]:
    try:
        player = xbmc.Player()
        if not player.isPlayingVideo():
            log("No video is playing", xbmc.LOGDEBUG)
            return 0, 0

        current_time = player.getTime()
        total_time = player.getTotalTime()

        if current_time < 0 or total_time <= 0:
            log(f"Invalid time values - current: {current_time}, total: {total_time}", xbmc.LOGWARNING)
            return 0, 0

        return current_time, total_time
    except Exception as e:
        log(f"get_current_playback_time error: {e}", xbmc.LOGERROR)
        return 0, 0


def record_skip_point() -> None:
    tvshow_id, show_title, season, source_type = get_current_tvshow_info()
    if not tvshow_id:
        show_notification(SETTINGS.get_string(32004))
        return

    current_time, total_time = get_current_playback_time()
    if total_time <= 0:
        return

    percentage = (current_time / total_time) * 100
    state = get_active_video_playlist_state()
    season_num, episode_num = get_season_episode_from_state(source_type, state, season)
    # 集号不可靠时退回季级记录，避免把某一集的记录点错写到第 1 集
    episode = get_current_episode_number(source_type, season, state)

    data = load_skip_data()

    record = data.get(tvshow_id)
    if not isinstance(record, dict) or not isinstance(record.get("seasons"), dict):
        # 兼容旧格式：整剧只有一个 time 值
        legacy_time = record.get("time") if isinstance(record, dict) else None
        record = {"title": show_title, "seasons": {}}
        if legacy_time:
            record["seasons"][season] = {"intro": legacy_time}
        data[tvshow_id] = record
    record["title"] = show_title

    if percentage < SKIP_THRESHOLD_INTRO:
        layer = set_skip_point(record, season, episode, "intro", current_time)
        m, s = divmod(int(current_time), 60)
        msg = SETTINGS.get_string(32005) % (m, s)
    elif percentage > SKIP_THRESHOLD_OUTRO:
        outro_duration = total_time - current_time
        layer = set_skip_point(record, season, episode, "outro", outro_duration)
        m, s = divmod(int(outro_duration), 60)
        msg = SETTINGS.get_string(32006) % (m, s)
    else:
        show_notification(SETTINGS.get_string(32007))
        return

    if layer == "unknown":
        # 集号识别不出来又已有整季标记：宁可不写，也不静默改掉整季
        show_notification(SETTINGS.get_string(32058))
        return

    save_skip_data(data, immediate=True)

    xbmcgui.Window(10000).setProperty("MFG.Reload", "true")

    full_msg = SETTINGS.get_string(32008) % (msg, season_num, episode_num)
    show_notification(full_msg)
    log(
        f"Recorded skip point for {show_title} S{season_num}E{episode_num}: "
        f"season={season} episode_key={episode} layer={layer}"
    )


def delete_skip_point() -> None:
    tvshow_id, show_title, season, source_type = get_current_tvshow_info()
    if not tvshow_id:
        show_notification(SETTINGS.get_string(32004))
        return

    current_time, total_time = get_current_playback_time()
    if total_time <= 0:
        return

    percentage = (current_time / total_time) * 100
    if percentage < SKIP_THRESHOLD_INTRO:
        key, deleted_msg, missing_msg = "intro", 32011, 32012
    elif percentage > SKIP_THRESHOLD_OUTRO:
        key, deleted_msg, missing_msg = "outro", 32013, 32014
    else:
        show_notification(SETTINGS.get_string(32015))
        return

    state = get_active_video_playlist_state()
    episode = get_current_episode_number(source_type, season, state)

    data = load_skip_data()
    record = data.get(tvshow_id)
    if not isinstance(record, dict):
        show_notification(SETTINGS.get_string(32010))
        return

    # 只删本集覆盖，季基准不在这里动，避免一个快捷键静默清掉全季
    if clear_skip_point(record, season, episode, key) == "episode":
        prune_skip_record(data, tvshow_id)
        save_skip_data(data, immediate=True)
        xbmcgui.Window(10000).setProperty("MFG.Reload", "true")
        show_notification(SETTINGS.get_string(deleted_msg))
        log(f"Cleared {key} override for {show_title} season={season} episode_key={episode}")
        return

    season_value, _ = get_skip_point(record, season, 0, key, 0)
    show_notification(SETTINGS.get_string(32054 if season_value > 0 else missing_msg))


def show_help() -> None:
    xbmcgui.Dialog().textviewer(
        SETTINGS.get_string(32056),
        SETTINGS.get_string(32057),
    )


def confirm_delete_all() -> None:
    confirmed = xbmcgui.Dialog().yesno(
        "",
        SETTINGS.get_string(32034),
        yeslabel=SETTINGS.get_string(32025),
        nolabel=SETTINGS.get_string(32026),
    )
    if confirmed:
        delete_all_skip_points()
        show_notification(SETTINGS.get_string(32035))


def main_menu() -> None:
    """插件主界面：从「程序插件」点进来时显示。"""
    options = [
        SETTINGS.get_string(32055),
        SETTINGS.get_string(32033),
        SETTINGS.get_string(32059),
    ]
    try:
        index = xbmcgui.Dialog().select(SETTINGS.get_string(32027), options)
    except Exception as e:
        log(f"main_menu failed: {e}", xbmc.LOGERROR)
        index = -1

    if index == 0:
        show_help()
    elif index == 1:
        confirm_delete_all()
    elif index == 2:
        ADDON.openSettings()


def router(paramstring: str) -> None:
    log(f"Router called with: {paramstring}")
    # plugin:// 调用会带上 "/?mode=..." 形式的路径，RunScript 则直接是 "mode=..."
    cleaned = (paramstring or "").lstrip("/").lstrip("?")
    if not cleaned:
        main_menu()
        return

    params = dict(urllib.parse.parse_qsl(cleaned))
    mode = params.get("mode")
    action = params.get("action")

    if mode == "record_skip_point":
        record_skip_point()
    elif mode == "delete_skip_point":
        delete_skip_point()
    elif mode == "show_help":
        show_help()
    elif mode == "menu":
        main_menu()
    elif action == "delete_all_skip_points":
        confirm_delete_all()


if __name__ == "__main__":
    router(sys.argv[1] if len(sys.argv) > 1 else "")
    # 等待自定义通知窗口显示完毕，避免脚本进程退出时窗口被销毁
    wait_for_notifications()
