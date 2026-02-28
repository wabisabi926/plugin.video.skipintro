# -*- coding: utf-8 -*-
import sys
import urllib.parse
import json
import os

import xbmc
import xbmcgui
import xbmcvfs

ADDON_PATH = xbmcvfs.translatePath("special://home/addons/plugin.video.skipintro/")
ADDON_DATA_PATH = xbmcvfs.translatePath("special://profile/addon_data/plugin.video.skipintro/")
if not os.path.exists(ADDON_DATA_PATH):
    os.makedirs(ADDON_DATA_PATH)

SKIP_DATA_FILE = os.path.join(ADDON_DATA_PATH, 'skip_intro_data.json')

def log(msg): xbmc.log(f"[skipintro] {msg}", xbmc.LOGINFO)

def load_skip_data():
    if not os.path.exists(SKIP_DATA_FILE):
        return {}
    try:
        with open(SKIP_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log(f"Error loading skip data: {e}")
        return {}

def save_skip_data(data):
    try:
        with open(SKIP_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        log(f"Error saving skip data: {e}")

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
            tvshow_id = item.get('tvshowid')
            show_title = item.get('showtitle')
            season = item.get('season', -1)
            file_path = item.get('file')
            
            if tvshow_id and tvshow_id != -1 and show_title:
                return str(tvshow_id), show_title, str(season), None
            elif file_path:
                import os
                from urllib.parse import urlparse
                
                # 处理网络协议路径
                parsed = urlparse(file_path)
                if parsed.scheme:
                    # 网络协议路径 (webdav, smb, etc.)
                    path = parsed.path
                    folder_path = os.path.dirname(path)
                    # 重建完整的网络路径
                    folder_path = f"{parsed.scheme}://{parsed.netloc}{folder_path}"
                    folder_name = os.path.basename(folder_path)
                else:
                    # 本地文件路径
                    folder_path = os.path.dirname(file_path)
                    folder_name = os.path.basename(folder_path)
                return folder_path, folder_name, "1", "folder"
    except Exception as e:
        log(f"Error getting TV show info: {e}")
    return None, None, None, None

def record_skip_point():
    tvshow_id, show_title, season, folder_type = get_current_tvshow_info()
    if not tvshow_id:
        xbmc.executebuiltin(f'Notification(Skip Intro, 跳过不适用于非媒体文件, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
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
            msg = f"已记录片头: {m:02d}:{s:02d}"
        elif percentage > 80:
            outro_duration = total_time - current_time
            season_data["outro"] = outro_duration
            m, s = divmod(int(outro_duration), 60)
            msg = f"已记录片尾时长: {m:02d}:{s:02d}"
        else:
            xbmc.executebuiltin(f'Notification(Skip Intro, "请在剧集前或后20%时间段内调用", 2000, {os.path.join(ADDON_PATH, "icon.png")})')
            return

        data[tvshow_id]["seasons"][season] = season_data
        save_skip_data(data)
        
        xbmcgui.Window(10000).setProperty("MFG.Reload", "true")
        
        if folder_type == "folder":
            xbmc.executebuiltin(f'Notification(Skip Intro, {msg} (文件夹: {show_title}), 2000, {os.path.join(ADDON_PATH, "icon.png")})')
        else:
            xbmc.executebuiltin(f'Notification(Skip Intro, {msg} (第{season}季), 2000, {os.path.join(ADDON_PATH, "icon.png")})')
        log(f"Recorded skip point for {show_title} Season {season}: {season_data}")
        
    except Exception as e:
        log(f"Error recording skip point: {e}")
        xbmc.executebuiltin(f'Notification(Skip Intro, 无法记录请查阅日志, 2000, {os.path.join(ADDON_PATH, "icon.png")})')

def delete_skip_point():
    tvshow_id, show_title, season, folder_type = get_current_tvshow_info()
    if not tvshow_id:
        xbmc.executebuiltin(f'Notification(Skip Intro, 跳过不适用于非媒体文件, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
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
            xbmc.executebuiltin(f'Notification(Skip Intro, 无片头片尾标记点, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
            return

        season_data = data[tvshow_id]["seasons"][season]
        if isinstance(season_data, (int, float)):
             season_data = {"intro": season_data}

        msg = ""
        if percentage < 20:
            if "intro" in season_data:
                del season_data["intro"]
                msg = "已删除片头记录"
            else:
                msg = "当前无片头记录"
        elif percentage > 80:
            if "outro" in season_data:
                del season_data["outro"]
                msg = "已删除片尾记录"
            else:
                msg = "当前无片尾记录"
        else:
            xbmc.executebuiltin(f'Notification(Skip Intro, 删除失败 请在剧集前或后20%时间段内调用, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
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
        xbmc.executebuiltin(f'Notification(Skip Intro, 删除错误, 2000, {os.path.join(ADDON_PATH, "icon.png")})')

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
