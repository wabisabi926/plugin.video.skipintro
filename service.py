# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import xbmcvfs
import json
import os
import time
import traceback
import threading

ADDON_ID = 'plugin.video.skipintro'
ADDON_PATH = xbmcvfs.translatePath(f"special://home/addons/{ADDON_ID}/")
ADDON_DATA_PATH = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")
if not os.path.exists(ADDON_DATA_PATH):
    os.makedirs(ADDON_DATA_PATH)

SKIP_DATA_FILE = os.path.join(ADDON_DATA_PATH, 'skip_intro_data.json')

def log(msg):
    xbmc.log(f"[SkipIntroService] {msg}", xbmc.LOGINFO)

def load_skip_data():
    if not os.path.exists(SKIP_DATA_FILE):
        return {}
    try:
        with open(SKIP_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log(f"Error loading skip data: {e}")
        return {}

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
            
            if tvshow_id and tvshow_id != -1:
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

class PlayerMonitor(xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)
        self.current_outro_time = None
        self.outro_triggered = False
        self.outro_countdown_start = None
        self.cancel_skip = False

    def onAVStarted(self):
        xbmc.sleep(1000)
        
        self.check_intro()
        self.update_outro_info()

    def update_outro_info(self):
        self.current_outro_time = None
        self.outro_triggered = False
        self.outro_countdown_start = None
        self.cancel_skip = False
        
        if not self.isPlayingVideo():
            return

        tvshow_id, show_title, season, folder_type = get_current_tvshow_info()
        if not tvshow_id: return

        data = load_skip_data()
        if tvshow_id not in data: return
        
        record = data[tvshow_id]
        if "seasons" in record and season in record["seasons"]:
            s_data = record["seasons"][season]
            if isinstance(s_data, dict):
                outro_duration = s_data.get("outro")
                if outro_duration:
                    try:
                        total_time = self.getTotalTime()
                        if total_time > 0:
                            self.current_outro_time = total_time - outro_duration
                            if folder_type == "folder":
                                log(f"Outro skip set for folder {show_title}. Duration: {outro_duration}, Trigger at: {self.current_outro_time}")
                            else:
                                log(f"Outro skip set for {show_title} S{season}. Duration: {outro_duration}, Trigger at: {self.current_outro_time}")
                    except Exception as e:
                        log(f"Error calculating outro trigger: {e}")

    def check_intro(self):
        if not self.isPlayingVideo():
            return

        tvshow_id, show_title, season, folder_type = get_current_tvshow_info()
        if not tvshow_id:
            return

        data = load_skip_data()
        if tvshow_id not in data:
            return

        record = data[tvshow_id]
        skip_time = 0
        
        if "seasons" in record and season in record["seasons"]:
            val = record["seasons"][season]
            if isinstance(val, dict):
                skip_time = val.get("intro", 0)
            else:
                skip_time = val
        elif "time" in record:
            skip_time = record["time"]
            
        if skip_time > 0:
            try:
                current_time = self.getTime()
                if current_time < skip_time:
                    if folder_type == "folder":
                        log(f"Auto skipping intro for folder {show_title}. Current: {current_time}, Target: {skip_time}")
                    else:
                        log(f"Auto skipping intro for {show_title} S{season}. Current: {current_time}, Target: {skip_time}")
                    self.seekTime(skip_time)
                    xbmc.executebuiltin(f'Notification(Skip Intro, 自动跳过片头 已跳转至 {int(skip_time)}秒, 2000, {os.path.join(ADDON_PATH, "icon.png")})')
            except Exception as e:
                log(f"Error during skip: {e}")

class SkipCountdownWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)
        self.cancelled = False
        self.is_ready = False
        
    def onInit(self):
        self.is_ready = True
        
    def onAction(self, action):
        action_id = action.getId()
        if action_id in [10, 92]:
            self.cancelled = True
            self.close()
        elif action_id in [1, 15]:
            xbmc.executebuiltin("PlayerControl(SmallSkipBackward)")
        elif action_id in [2, 14]:
            xbmc.executebuiltin("PlayerControl(SmallSkipForward)")
        elif action_id in [3, 20]:
            xbmc.executebuiltin("PlayerControl(BigSkipForward)")
        elif action_id in [4, 21]:
            xbmc.executebuiltin("PlayerControl(BigSkipBackward)")
        elif action_id == 7:
            xbmc.executebuiltin("ActivateWindow(VideoOSD)")
        elif action_id == 77:
            xbmc.executebuiltin("PlayerControl(Forward)")
        elif action_id == 78:
            xbmc.executebuiltin("PlayerControl(Rewind)")
        elif action_id == 12:
             xbmc.executebuiltin("PlayerControl(Play)")
            
    def update_text(self, text):
        if not self.is_ready: return
        try:
            ctrl = self.getControl(100)
            if ctrl:
                ctrl.setLabel(text)
        except:
            pass

if __name__ == '__main__':
    log("Service started")
    
    monitor = xbmc.Monitor()
    player = PlayerMonitor()
    
    countdown_window = None
    countdown_thread = None
    
    countdown_active = False
    countdown_remaining = 0.0
    last_tick_time = time.time()

    while not monitor.abortRequested():
        current_tick_time = time.time()
        dt = current_tick_time - last_tick_time
        last_tick_time = current_tick_time
        
        if xbmcgui.Window(10000).getProperty("MFG.Reload") == "true":
            xbmcgui.Window(10000).clearProperty("MFG.Reload")
            log("Reload signal received, updating info...")
            player.update_outro_info()
            countdown_active = False
            
        if player.isPlayingVideo() and player.current_outro_time:
            try:
                current_time = player.getTime()
                trigger_time = player.current_outro_time
                start_threshold = trigger_time - 6
                
                if current_time < start_threshold:
                    if player.cancel_skip: 
                        player.cancel_skip = False
                    
                    if countdown_active:
                        countdown_active = False
                        log("Playback time before outro range. Resetting countdown.")
                    
                    if countdown_window:
                        countdown_window.close()
                        if countdown_thread: countdown_thread.join()
                        countdown_window = None
                        countdown_thread = None

                elif not player.outro_triggered and not player.cancel_skip:
                    if not countdown_active:
                        countdown_active = True
                        countdown_remaining = 6.0
                        log(f"Entered outro range. Starting countdown: {countdown_remaining}s")
                    
                    if not xbmc.getCondVisibility("Player.Paused"):
                        countdown_remaining -= dt
                    
                    if not countdown_window:
                        countdown_window = SkipCountdownWindow("resources/notification_overlay.xml", ADDON_PATH)
                        countdown_thread = threading.Thread(target=countdown_window.doModal)
                        countdown_thread.start()
                    
                    display_seconds = int(countdown_remaining) + 1
                    countdown_window.update_text(f"即将跳过片尾... {display_seconds}秒 (按返回取消)")
                    
                    if countdown_window.cancelled:
                        player.cancel_skip = True
                        xbmc.executebuiltin(f'Notification(Skip Intro, 自动跳过片尾 已取消, 1000, {os.path.join(ADDON_PATH, "icon.png")})')
                        if countdown_thread and countdown_thread.is_alive():
                            countdown_thread.join()
                        countdown_window = None
                        countdown_thread = None
                        countdown_active = False
                        continue

                    if countdown_remaining <= 0:
                        player.outro_triggered = True
                        log("Countdown finished. Auto skipping outro -> Next episode")
                        
                        if countdown_window:
                            countdown_window.close()
                            if countdown_thread and countdown_thread.is_alive():
                                countdown_thread.join()
                            countdown_window = None
                            countdown_thread = None
                            
                        xbmc.executebuiltin("PlayerControl(Next)")
                        countdown_active = False

            except Exception as e:
                log(f"Error checking outro: {e}")
                log(traceback.format_exc())
                if countdown_window:
                    countdown_window.close()
                    countdown_window = None
                countdown_active = False
        else:
            if countdown_window:
                countdown_window.close()
                if countdown_thread: countdown_thread.join()
                countdown_window = None
                countdown_thread = None
            countdown_active = False
        
        if monitor.waitForAbort(0.3):
            break
