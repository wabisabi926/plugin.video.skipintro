# -*- coding: utf-8 -*-
import sys
import urllib.parse
import os

import xbmc
import xbmcgui

from common import ADDON, ADDON_PATH, load_skip_data, save_skip_data, get_current_tvshow_info, log, jsonrpc_call


def ensure_autoplay_next_setting(tvshow_id, source_type):
    try:
        if not tvshow_id:
            return

        item_type = ""
        result = jsonrpc_call(
            "Player.GetItem",
            {"playerid": 1},
        ) or {}
        if isinstance(result, dict):
            item = result.get("item") or {}
            item_type = str(item.get("type") or "").lower()

        if item_type in ("movie", "musicvideo") and source_type != "directory":
            return

        if source_type == "directory":
            required_values = [4]
            required_label = ADDON.getLocalizedString(32021)
        else:
            required_values = [2, 8]
            required_label = ADDON.getLocalizedString(32022)

        current_values = []
        result = jsonrpc_call(
            "Settings.GetSettingValue",
            {"setting": "videoplayer.autoplaynextitem"},
        ) or {}
        value = result.get("value") if isinstance(result, dict) else None

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
                if not item:
                    continue
                try:
                    current_values.append(int(item))
                except ValueError:
                    continue

        has_required = any(v in current_values for v in required_values)
        if has_required:
            return

        message = ADDON.getLocalizedString(32023) % (required_label,)
        confirmed = xbmcgui.Dialog().yesno(
            ADDON.getLocalizedString(32024),
            message,
            yeslabel=ADDON.getLocalizedString(32025),
            nolabel=ADDON.getLocalizedString(32026),
        )
        if not confirmed:
            return

        missing_values = [v for v in required_values if v not in current_values]
        new_values = sorted(set(current_values + missing_values))
        set_result = jsonrpc_call(
            "Settings.SetSettingValue",
            {
                "setting": "videoplayer.autoplaynextitem",
                "value": new_values,
            },
        )
        if not set_result:
            xbmc.executebuiltin(
                'Notification(%s, %s, 2000, %s)' % (
                    ADDON.getLocalizedString(32027),
                    ADDON.getLocalizedString(32020),
                    os.path.join(ADDON_PATH, "icon.png")
                )
            )
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
        xbmc.executebuiltin(
            'Notification(%s, %s, 2000, %s)' % (
                ADDON.getLocalizedString(32027),
                ADDON.getLocalizedString(32004),
                os.path.join(ADDON_PATH, "icon.png")
            )
        )
        return

    try:
        player = xbmc.Player()
        current_time = player.getTime()
        total_time = player.getTotalTime()

        if total_time <= 0:
            return

        percentage = (current_time / total_time) * 100
        data = load_skip_data()

        if tvshow_id not in data:
            data[tvshow_id] = {"title": show_title, "seasons": {}}
        elif "time" in data[tvshow_id]:
            old_time = data[tvshow_id]["time"]
            data[tvshow_id] = {"title": show_title, "seasons": {"1": {"intro": old_time}}}
            del data[tvshow_id]["time"]

        if "seasons" not in data[tvshow_id]:
            data[tvshow_id]["seasons"] = {}

        data[tvshow_id]["title"] = show_title

        raw_season = data[tvshow_id]["seasons"].get(season)
        if isinstance(raw_season, (int, float)):
            season_data = {"intro": raw_season}
        elif isinstance(raw_season, dict):
            season_data = raw_season
        else:
            season_data = {}

        msg = ""
        if percentage < 20:
            season_data["intro"] = current_time
            m, s = divmod(int(current_time), 60)
            msg = ADDON.getLocalizedString(32005) % (m, s)
        elif percentage > 80:
            outro_duration = total_time - current_time
            season_data["outro"] = outro_duration
            m, s = divmod(int(outro_duration), 60)
            msg = ADDON.getLocalizedString(32006) % (m, s)
        else:
            xbmc.executebuiltin(
                'Notification(%s, %s, 2000, %s)' % (
                    ADDON.getLocalizedString(32027),
                    ADDON.getLocalizedString(32007),
                    os.path.join(ADDON_PATH, "icon.png")
                )
            )
            return

        data[tvshow_id]["seasons"][season] = season_data
        save_skip_data(data)

        xbmcgui.Window(10000).setProperty("MFG.Reload", "true")

        full_msg = ADDON.getLocalizedString(32008) % (msg, season)
        xbmc.executebuiltin(
            'Notification(%s, %s, 2000, %s)' % (
                ADDON.getLocalizedString(32027),
                full_msg,
                os.path.join(ADDON_PATH, "icon.png")
            )
        )
        log(f"Recorded skip point for {show_title} Season {season}: {season_data}")

        ensure_autoplay_next_setting(tvshow_id, source_type)

    except Exception as e:
        log(f"Error recording skip point: {e}")
        xbmc.executebuiltin(
            'Notification(%s, %s, 2000, %s)' % (
                ADDON.getLocalizedString(32027),
                ADDON.getLocalizedString(32009),
                os.path.join(ADDON_PATH, "icon.png")
            )
        )


def delete_skip_point():
    tvshow_id, show_title, season, source_type = get_current_tvshow_info()
    if not tvshow_id:
        xbmc.executebuiltin(
            'Notification(%s, %s, 2000, %s)' % (
                ADDON.getLocalizedString(32027),
                ADDON.getLocalizedString(32004),
                os.path.join(ADDON_PATH, "icon.png")
            )
        )
        return

    try:
        player = xbmc.Player()
        current_time = player.getTime()
        total_time = player.getTotalTime()

        if total_time <= 0:
            return

        percentage = (current_time / total_time) * 100
        data = load_skip_data()

        if tvshow_id not in data or "seasons" not in data[tvshow_id] or season not in data[tvshow_id]["seasons"]:
            xbmc.executebuiltin(
                'Notification(%s, %s, 2000, %s)' % (
                    ADDON.getLocalizedString(32027),
                    ADDON.getLocalizedString(32010),
                    os.path.join(ADDON_PATH, "icon.png")
                )
            )
            return

        raw_season = data[tvshow_id]["seasons"][season]
        if isinstance(raw_season, (int, float)):
            season_data = {"intro": raw_season}
        elif isinstance(raw_season, dict):
            season_data = raw_season.copy()
        else:
            season_data = {}

        msg = ""
        if percentage < 20:
            if "intro" in season_data:
                del season_data["intro"]
                msg = ADDON.getLocalizedString(32011)
            else:
                msg = ADDON.getLocalizedString(32012)
        elif percentage > 80:
            if "outro" in season_data:
                del season_data["outro"]
                msg = ADDON.getLocalizedString(32013)
            else:
                msg = ADDON.getLocalizedString(32014)
        else:
            xbmc.executebuiltin(
                'Notification(%s, %s, 2000, %s)' % (
                    ADDON.getLocalizedString(32027),
                    ADDON.getLocalizedString(32015),
                    os.path.join(ADDON_PATH, "icon.png")
                )
            )
            return

        if not season_data:
            del data[tvshow_id]["seasons"][season]
        else:
            data[tvshow_id]["seasons"][season] = season_data

        if not data[tvshow_id]["seasons"]:
            del data[tvshow_id]

        save_skip_data(data)

        xbmcgui.Window(10000).setProperty("MFG.Reload", "true")
        xbmc.executebuiltin(
            'Notification(%s, %s, 2000, %s)' % (
                ADDON.getLocalizedString(32027),
                msg,
                os.path.join(ADDON_PATH, "icon.png")
            )
        )

    except Exception as e:
        log(f"Error deleting skip point: {e}")
        xbmc.executebuiltin(
            'Notification(%s, %s, 2000, %s)' % (
                ADDON.getLocalizedString(32027),
                ADDON.getLocalizedString(32016),
                os.path.join(ADDON_PATH, "icon.png")
            )
        )


def router(paramstring):
    log(f"Router called with: {paramstring}")
    if not paramstring:
        return

    params = dict(urllib.parse.parse_qsl(paramstring.lstrip('?')))
    mode = params.get("mode")

    if mode == "record_skip_point":
        record_skip_point()
        return

    if mode == "delete_skip_point":
        delete_skip_point()
        return


if __name__ == "__main__":
    if len(sys.argv) > 1:
        router(sys.argv[1])
    else:
        router("")
