# -*- coding: utf-8 -*-
import sys
import urllib.parse
import os

import xbmc
import xbmcgui

from common import ADDON, ADDON_PATH, load_skip_data, save_skip_data, get_current_tvshow_info, log

def record_skip_point():
    tvshow_id, show_title, season = get_current_tvshow_info()
    if not tvshow_id:
        xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32004)}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
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
        
        season_data = data[tvshow_id]["seasons"].get(season, {})
        if isinstance(season_data, (int, float)):
            season_data = {"intro": season_data}
            
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
            xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32007)}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
            return

        data[tvshow_id]["seasons"][season] = season_data
        save_skip_data(data)
        
        xbmcgui.Window(10000).setProperty("MFG.Reload", "true")
        
        full_msg = ADDON.getLocalizedString(32008) % (msg, season)
        xbmc.executebuiltin(f'Notification(Skip Intro, {full_msg}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
        log(f"Recorded skip point for {show_title} Season {season}: {season_data}")
        
    except Exception as e:
        log(f"Error recording skip point: {e}")
        xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32009)}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')

def delete_skip_point():
    tvshow_id, show_title, season = get_current_tvshow_info()
    if not tvshow_id:
        xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32004)}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
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
            xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32010)}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
            return

        season_data = data[tvshow_id]["seasons"][season]
        if isinstance(season_data, (int, float)):
             season_data = {"intro": season_data}

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
            xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32015)}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
            return

        if not season_data:
            del data[tvshow_id]["seasons"][season]
        else:
            data[tvshow_id]["seasons"][season] = season_data
            
        if not data[tvshow_id]["seasons"]:
            del data[tvshow_id]

        save_skip_data(data)
        
        xbmcgui.Window(10000).setProperty("MFG.Reload", "true")
        xbmc.executebuiltin(f'Notification(Skip Intro, {msg}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
        
    except Exception as e:
        log(f"Error deleting skip point: {e}")
        xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32016)}, 2000, {os.path.join(ADDON_PATH, "icon.png")})')

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