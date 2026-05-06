# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import time
import traceback
import threading

from common import ADDON, ADDON_PATH, load_skip_data, get_current_tvshow_info, log

class PlayerMonitor(xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)
        self.current_outro_time = None
        self.outro_triggered = False
        self.outro_countdown_start = None
        self.cancel_skip = False
        self._playback_started = False

    def _handle_playback_start(self):
        log("Playback started")
        self._playback_started = True
        if not self.isPlayingVideo():
            return
        self.check_intro()
        self.retry_update_outro()

    def onAVStarted(self):
        self._handle_playback_start()

    def onPlayBackStarted(self):
        self._handle_playback_start()

    def onPlayBackEnded(self):
        log("onPlayBackEnded triggered")
        self._playback_started = False
        self.current_outro_time = None
        self.outro_triggered = False

    def onPlayBackStopped(self):
        log("onPlayBackStopped triggered")
        self._playback_started = False
        self.current_outro_time = None
        self.outro_triggered = False

    def retry_update_outro(self, max_retries=10, delay_ms=1000):
        for i in range(max_retries):
            try:
                total_time = self.getTotalTime()
                if total_time > 0:
                    self.update_outro_info()
                    return
            except Exception as e:
                log(f"retry_update_outro: error getting totalTime: {e}")
            xbmc.sleep(delay_ms)
        log("retry_update_outro: failed to get totalTime after max retries")

    def update_outro_info(self):
        if not self.isPlayingVideo():
            log("update_outro_info: not playing video")
            return

        tvshow_id, show_title, season = get_current_tvshow_info()
        if not tvshow_id:
            log("update_outro_info: no tvshow_id")
            return

        data = load_skip_data()
        if tvshow_id not in data:
            log(f"update_outro_info: no data for tvshow_id {tvshow_id}")
            return

        record = data[tvshow_id]
        if "seasons" not in record or season not in record["seasons"]:
            log(f"update_outro_info: no season data for S{season}")
            return

        s_data = record["seasons"][season]
        if isinstance(s_data, dict):
            outro_duration = s_data.get("outro")
            if outro_duration:
                try:
                    total_time = self.getTotalTime()
                    if total_time > 0:
                        new_outro_time = total_time - outro_duration
                        if self.current_outro_time != new_outro_time:
                            self.current_outro_time = new_outro_time
                            self.outro_triggered = False
                            self.outro_countdown_start = None
                            self.cancel_skip = False
                        log(f"update_outro_info: outro skip set for {show_title} S{season}. Duration: {outro_duration}, Trigger at: {self.current_outro_time}")
                    else:
                        log(f"update_outro_info: total_time is {total_time}, retrying later")
                except Exception as e:
                    log(f"Error calculating outro trigger: {e}")
            else:
                if self.current_outro_time is not None:
                    self.current_outro_time = None
                    self.outro_triggered = False
        else:
            log(f"update_outro_info: s_data is not dict: {s_data}")

    def check_intro(self):
        if not self.isPlayingVideo():
            return

        tvshow_id, show_title, season = get_current_tvshow_info()
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
                    log(f"Auto skipping intro for {show_title} S{season}. Current: {current_time}, Target: {skip_time}")
                    self.seekTime(skip_time)
                    xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32000) % int(skip_time)}, 3000, {os.path.join(ADDON_PATH, "icon.png")})')
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

def cleanup_countdown(countdown_window, countdown_thread):
    if countdown_window:
        countdown_window.close()
        if countdown_thread and countdown_thread.is_alive():
            countdown_thread.join()
        countdown_window = None
        countdown_thread = None
    return countdown_window, countdown_thread

if __name__ == '__main__':
    import os
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

                log(f"Main loop: current={current_time:.1f}, trigger={trigger_time:.1f}, threshold={start_threshold:.1f}")

                if current_time < start_threshold:
                    if player.cancel_skip: 
                        player.cancel_skip = False
                    
                    if countdown_active:
                        countdown_active = False
                        log("Playback time before outro range. Resetting countdown.")
                    
                    countdown_window, countdown_thread = cleanup_countdown(countdown_window, countdown_thread)

                elif not player.outro_triggered and not player.cancel_skip:
                    if not countdown_active:
                        countdown_active = True
                        countdown_remaining = 6.0
                        log(f"Entered outro range. Starting countdown: {countdown_remaining}s")
                        xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32001)}, 3000, {os.path.join(ADDON_PATH, "icon.png")})')
                    
                    if not xbmc.getCondVisibility("Player.Paused"):
                        countdown_remaining -= dt
                    
                    if not countdown_window:
                        try:
                            countdown_window = SkipCountdownWindow("notification_overlay.xml", ADDON_PATH)
                            countdown_thread = threading.Thread(target=countdown_window.doModal)
                            countdown_thread.start()
                        except Exception as e:
                            log(f"Error creating countdown window: {e}")
                            countdown_window = None
                            countdown_thread = None
                    
                    if countdown_window:
                        try:
                            display_seconds = int(countdown_remaining) + 1
                            countdown_window.update_text(ADDON.getLocalizedString(32003) % display_seconds)
                            
                            if countdown_window.cancelled:
                                player.cancel_skip = True
                                xbmc.executebuiltin(f'Notification(Skip Intro, {ADDON.getLocalizedString(32002)}, 3000, {os.path.join(ADDON_PATH, "icon.png")})')
                                countdown_window, countdown_thread = cleanup_countdown(countdown_window, countdown_thread)
                                countdown_active = False
                                continue
                        except Exception as e:
                            log(f"Error updating countdown window: {e}")

                    if countdown_remaining <= 0:
                        player.outro_triggered = True
                        log("Countdown finished. Auto skipping outro -> Next episode")
                        log(f"Executing PlayerControl(Next) - current time: {current_time:.1f}, trigger time: {trigger_time:.1f}")
                        
                        countdown_window, countdown_thread = cleanup_countdown(countdown_window, countdown_thread)
                        
                        try:
                            xbmc.executebuiltin("PlayerControl(Next)")
                            log("PlayerControl(Next) executed successfully")
                        except Exception as e:
                            log(f"Error executing PlayerControl(Next): {e}")
                        countdown_active = False

            except Exception as e:
                log(f"Error checking outro: {e}")
                log(traceback.format_exc())
                countdown_window, countdown_thread = cleanup_countdown(countdown_window, countdown_thread)
                countdown_active = False
        else:
            countdown_window, countdown_thread = cleanup_countdown(countdown_window, countdown_thread)
            countdown_active = False
        
        if monitor.waitForAbort(0.3):
            break