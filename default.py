# -*- coding: utf-8 -*-
import sys
import urllib.parse
import os
from typing import Tuple

import xbmc
import xbmcgui

from common import (
    load_skip_data, save_skip_data, get_current_tvshow_info,
    log, SETTINGS, delete_all_skip_points,
    show_notification, _parse_season_data,
    SKIP_THRESHOLD_INTRO, SKIP_THRESHOLD_OUTRO
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
        show_notification(SETTINGS.get_string(32027), SETTINGS.get_string(32004))
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
        data[tvshow_id] = {"title": show_title, "seasons": {season: {"intro": old_time}}}

    if "seasons" not in data[tvshow_id]:
        data[tvshow_id]["seasons"] = {}

    data[tvshow_id]["title"] = show_title

    raw_season = data[tvshow_id]["seasons"].get(season)
    season_data = _parse_season_data(raw_season)

    if percentage < SKIP_THRESHOLD_INTRO:
        season_data["intro"] = current_time
        m, s = divmod(int(current_time), 60)
        msg = SETTINGS.get_string(32005) % (m, s)
    elif percentage > SKIP_THRESHOLD_OUTRO:
        outro_duration = total_time - current_time
        season_data["outro"] = outro_duration
        m, s = divmod(int(outro_duration), 60)
        msg = SETTINGS.get_string(32006) % (m, s)
    else:
        show_notification(SETTINGS.get_string(32027), SETTINGS.get_string(32007))
        return

    data[tvshow_id]["seasons"][season] = season_data
    save_skip_data(data)

    xbmcgui.Window(10000).setProperty("MFG.Reload", "true")

    full_msg = SETTINGS.get_string(32008) % (msg, season)
    show_notification(SETTINGS.get_string(32027), full_msg)
    log(f"Recorded skip point for {show_title} Season {season}: {season_data}")


def delete_skip_point() -> None:
    tvshow_id, show_title, season, source_type = get_current_tvshow_info()
    if not tvshow_id:
        show_notification(SETTINGS.get_string(32027), SETTINGS.get_string(32004))
        return

    current_time, total_time = get_current_playback_time()
    if total_time <= 0:
        return

    percentage = (current_time / total_time) * 100
    data = load_skip_data()

    if tvshow_id not in data or "seasons" not in data[tvshow_id] or season not in data[tvshow_id]["seasons"]:
        show_notification(SETTINGS.get_string(32027), SETTINGS.get_string(32010))
        return

    raw_season = data[tvshow_id]["seasons"][season]
    season_data = _parse_season_data(raw_season)

    if percentage < SKIP_THRESHOLD_INTRO:
        if "intro" in season_data:
            del season_data["intro"]
            msg = SETTINGS.get_string(32011)
        else:
            msg = SETTINGS.get_string(32012)
    elif percentage > SKIP_THRESHOLD_OUTRO:
        if "outro" in season_data:
            del season_data["outro"]
            msg = SETTINGS.get_string(32013)
        else:
            msg = SETTINGS.get_string(32014)
    else:
        show_notification(SETTINGS.get_string(32027), SETTINGS.get_string(32015))
        return

    if not season_data:
        del data[tvshow_id]["seasons"][season]
    else:
        data[tvshow_id]["seasons"][season] = season_data

    if not data[tvshow_id]["seasons"]:
        del data[tvshow_id]

    save_skip_data(data)

    xbmcgui.Window(10000).setProperty("MFG.Reload", "true")
    show_notification(SETTINGS.get_string(32027), msg)


def router(paramstring: str) -> None:
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
            SETTINGS.get_string(32034),
            yeslabel=SETTINGS.get_string(32025),
            nolabel=SETTINGS.get_string(32026),
        )
        if confirmed:
            delete_all_skip_points()
            show_notification(SETTINGS.get_string(32027), SETTINGS.get_string(32035))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        router(sys.argv[1])
