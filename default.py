# -*- coding: utf-8 -*-
import sys
import urllib.parse
import os

import xbmc
import xbmcgui

from common import (
    ADDON_PATH, load_skip_data, save_skip_data, get_current_tvshow_info, log, 
    jsonrpc_call, SETTINGS, delete_all_skip_points,
    DEFAULT_NOTIFICATION_DURATION
)


def show_notification(message, duration=DEFAULT_NOTIFICATION_DURATION):
    xbmc.executebuiltin(
        'Notification(%s, %s, %d, %s)' % (
            SETTINGS.get_string(32027),
            message,
            duration,
            os.path.join(ADDON_PATH, "icon.png")
        )
    )


def get_current_playback_time():
    try:
        player = xbmc.Player()
        if not player.isPlayingVideo():
            log("get_current_playback_time: No video is playing")
            return 0, 0
        
        current_time = player.getTime()
        total_time = player.getTotalTime()
        
        if current_time < 0 or total_time <= 0:
            log(f"get_current_playback_time: Invalid time values - current: {current_time}, total: {total_time}")
            return 0, 0
        
        return current_time, total_time
    except Exception as e:
        log(f"get_current_playback_time error: {e}")
        return 0, 0


def get_autoplay_settings():
    result = jsonrpc_call("Settings.GetSettingValue", {"setting": "videoplayer.autoplaynextitem"}) or {}
    value = result.get("value") if isinstance(result, dict) else None

    current_values = []
    if isinstance(value, list):
        for item in value:
            try:
                current_values.append(int(item))
            except (TypeError, ValueError):
                continue
    elif isinstance(value, (int, float)):
        current_values.append(int(value))
    elif isinstance(value, str):
        for item in value.split(','):
            item = item.strip()
            if item:
                try:
                    current_values.append(int(item))
                except ValueError:
                    continue
    return current_values


def set_autoplay_settings(values):
    result = jsonrpc_call(
        "Settings.SetSettingValue",
        {"setting": "videoplayer.autoplaynextitem", "value": sorted(set(values))}
    )
    return result == "OK"


def ensure_autoplay_next_setting(tvshow_id, source_type):
    try:
        if not tvshow_id:
            return

        result = jsonrpc_call("Player.GetItem", {"playerid": 1}) or {}
        item = result.get("item") or {}
        item_type = str(item.get("type") or "").lower()

        if item_type in ("movie", "musicvideo") and source_type != "directory":
            return

        if source_type == "directory":
            required_values = [4]
            required_label = SETTINGS.get_string(32021)
        else:
            required_values = [2, 8]
            required_label = SETTINGS.get_string(32022)

        current_values = get_autoplay_settings()
        has_required = any(v in current_values for v in required_values)

        if has_required:
            return

        message = SETTINGS.get_string(32023) % (required_label,)
        confirmed = xbmcgui.Dialog().yesno(
            SETTINGS.get_string(32024),
            message,
            yeslabel=SETTINGS.get_string(32025),
            nolabel=SETTINGS.get_string(32026),
        )
        if not confirmed:
            return

        missing_values = [v for v in required_values if v not in current_values]
        new_values = current_values + missing_values

        if not set_autoplay_settings(new_values):
            show_notification(SETTINGS.get_string(32020))
            return

        try:
            player = xbmc.Player()
            if player.isPlayingVideo():
                player.stop()
        except Exception as e:
            log(f"Error stopping playback after setting autoplay next: {e}")
    except Exception as e:
        log(f"Error in ensure_autoplay_next_setting: {e}")


def record_skip_point():
    tvshow_id, show_title, season, source_type = get_current_tvshow_info()
    if not tvshow_id:
        show_notification(SETTINGS.get_string(32004))
        return

    current_time, total_time = get_current_playback_time()
    if total_time <= 0:
        return

    percentage = (current_time / total_time) * 100
    data = load_skip_data()

    if tvshow_id not in data:
        data[tvshow_id] = {"title": show_title, "seasons": {}}
    elif "time" in data[tvshow_id]:
        old_time = data[tvshow_id]["time"]
        data[tvshow_id] = {"title": show_title, "seasons": {"1": {"intro": old_time}}}

    if "seasons" not in data[tvshow_id]:
        data[tvshow_id]["seasons"] = {}

    data[tvshow_id]["title"] = show_title

    raw_season = data[tvshow_id]["seasons"].get(season)
    season_data = {"intro": raw_season} if isinstance(raw_season, (int, float)) else (raw_season.copy() if isinstance(raw_season, dict) else {})

    if percentage < 20:
        season_data["intro"] = current_time
        m, s = divmod(int(current_time), 60)
        msg = SETTINGS.get_string(32005) % (m, s)
    elif percentage > 80:
        outro_duration = total_time - current_time
        season_data["outro"] = outro_duration
        m, s = divmod(int(outro_duration), 60)
        msg = SETTINGS.get_string(32006) % (m, s)
    else:
        show_notification(SETTINGS.get_string(32007))
        return

    data[tvshow_id]["seasons"][season] = season_data
    save_skip_data(data)

    xbmcgui.Window(10000).setProperty("MFG.Reload", "true")

    full_msg = SETTINGS.get_string(32008) % (msg, season)
    show_notification(full_msg)
    log(f"Recorded skip point for {show_title} Season {season}: {season_data}")

    ensure_autoplay_next_setting(tvshow_id, source_type)


def delete_skip_point():
    tvshow_id, show_title, season, source_type = get_current_tvshow_info()
    if not tvshow_id:
        show_notification(SETTINGS.get_string(32004))
        return

    current_time, total_time = get_current_playback_time()
    if total_time <= 0:
        return

    percentage = (current_time / total_time) * 100
    data = load_skip_data()

    if tvshow_id not in data or "seasons" not in data[tvshow_id] or season not in data[tvshow_id]["seasons"]:
        show_notification(SETTINGS.get_string(32010))
        return

    raw_season = data[tvshow_id]["seasons"][season]
    season_data = {"intro": raw_season} if isinstance(raw_season, (int, float)) else (raw_season.copy() if isinstance(raw_season, dict) else {})

    if percentage < 20:
        if "intro" in season_data:
            del season_data["intro"]
            msg = SETTINGS.get_string(32011)
        else:
            msg = SETTINGS.get_string(32012)
    elif percentage > 80:
        if "outro" in season_data:
            del season_data["outro"]
            msg = SETTINGS.get_string(32013)
        else:
            msg = SETTINGS.get_string(32014)
    else:
        show_notification(SETTINGS.get_string(32015))
        return

    if not season_data:
        del data[tvshow_id]["seasons"][season]
    else:
        data[tvshow_id]["seasons"][season] = season_data

    if not data[tvshow_id]["seasons"]:
        del data[tvshow_id]

    save_skip_data(data)

    xbmcgui.Window(10000).setProperty("MFG.Reload", "true")
    show_notification(msg)


def router(paramstring):
    log(f"Router called with: {paramstring}")
    if not paramstring:
        return

    params = dict(urllib.parse.parse_qsl(paramstring.lstrip('?')))
    mode = params.get("mode")
    action = params.get("action")

    if mode == "record_skip_point":
        record_skip_point()
    elif mode == "delete_skip_point":
        delete_skip_point()
    elif action == "delete_all_skip_points":
        confirmed = xbmcgui.Dialog().yesno(
            SETTINGS.get_string(32027),
            "确定要删除所有记录点吗？此操作不可撤销。",
            yeslabel=SETTINGS.get_string(32025),
            nolabel=SETTINGS.get_string(32026),
        )
        if confirmed:
            delete_all_skip_points()
            show_notification("已删除所有记录点")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        router(sys.argv[1])