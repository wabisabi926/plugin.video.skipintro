import os
import xbmc
import xbmcgui
import xbmcvfs

ADDON_ID = 'plugin.video.skipintro'
ADDON_PATH = xbmcvfs.translatePath(f"special://home/addons/{ADDON_ID}/")
ADDON_DATA_PATH = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")

def get_icon_path():
    return os.path.join(ADDON_PATH, "icon.png")

def notification(message, title="Skip Intro", duration=1000, sound=False):
    xbmcgui.Dialog().notification(title, message, get_icon_path(), duration, sound)
    
def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{ADDON_ID}] {msg}", level)