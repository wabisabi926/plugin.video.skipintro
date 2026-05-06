# -*- coding: utf-8 -*-
import xbmc
import xbmcvfs
import json
import os
import xbmcaddon

ADDON_ID = 'plugin.video.skipintro'
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_PATH = xbmcvfs.translatePath(f"special://home/addons/{ADDON_ID}/")
ADDON_DATA_PATH = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")

if not os.path.exists(ADDON_DATA_PATH):
    os.makedirs(ADDON_DATA_PATH)

SKIP_DATA_FILE = os.path.join(ADDON_DATA_PATH, 'skip_intro_data.json')

def log(msg, prefix="[SkipIntro]"):
    xbmc.log(f"{prefix} {msg}", xbmc.LOGINFO)

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
                "properties": ["tvshowid", "showtitle", "season"],
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
            
            if tvshow_id and tvshow_id != -1 and show_title:
                return str(tvshow_id), show_title, str(season)
    except Exception as e:
        log(f"Error getting TV show info: {e}")
    return None, None, None