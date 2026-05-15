# -*- coding: utf-8 -*-
import os
import xbmc
import xbmcgui
import time
import traceback
import threading

from common import (
    ADDON, ADDON_PATH, load_skip_data, get_current_tvshow_info, 
    autofill_playlist_for_current_video, log, 
    get_next_episode_from_library, play_episode_from_library,
    is_next_episode_available_in_playlist, get_active_video_playlist_state,
    get_next_file_in_directory, play_file, extract_media_info_from_filename,
    State, mark_current_episode_as_watched
)


class PlayerMonitor(xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)
        self.current_outro_time = None
        self.outro_triggered = False
        self.cancel_skip = False
        self.state = State()
        self._cached_playing_state = None
        self._state_cache_time = 0
        self._state_cache_ttl = 0.5

    def is_playing(self):
        """缓存的播放状态检查，减少API调用"""
        now = time.time()
        if now - self._state_cache_time > self._state_cache_ttl:
            try:
                self._cached_playing_state = self.isPlayingVideo()
                self._state_cache_time = now
            except Exception:
                self._cached_playing_state = False
        return self._cached_playing_state or False

    def onAVStarted(self):
        self.check_intro()
        self.retry_update_outro()
        autofill_playlist_for_current_video()

    def onPlayBackEnded(self):
        if self.state.get_playing_next():
            self.state.set_playing_next(False)
        else:
            self.state.reset()
            self.current_outro_time = None
            self.outro_triggered = False

    def onPlayBackStopped(self):
        self.state.reset()
        self.current_outro_time = None
        self.outro_triggered = False

    def onPlayBackPaused(self):
        self.state.pause = True

    def onPlayBackResumed(self):
        self.state.pause = False

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
        if not self.is_playing():
            log("update_outro_info: not playing video")
            return

        tvshow_id, show_title, season, source_type = get_current_tvshow_info()
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
        if not self.is_playing():
            return

        tvshow_id, show_title, season, source_type = get_current_tvshow_info()
        if not tvshow_id:
            return

        state = get_active_video_playlist_state()
        episode = safe_get_state_value(state, "episode")
        
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
                    
                    season_num = int(season) if season else 1
                    
                    if source_type == 'directory' and state:
                        current_file = safe_get_state_value(state, "file", "")
                        if current_file:
                            _, episode_num, parsed = extract_media_info_from_filename(current_file)
                            if not parsed or episode_num <= 0:
                                episode_num = 1
                    else:
                        episode_num = int(episode) if episode and episode != -1 else 1
                    
                    notification_text = ADDON.getLocalizedString(32000) % (season_num, episode_num)
                    show_notification(ADDON.getLocalizedString(32027), notification_text)
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
        if not self.is_ready:
            return
        try:
            ctrl = self.getControl(100)
            if ctrl:
                ctrl.setLabel(text)
        except Exception as e:
            log(f"Error updating countdown text: {e}")


def show_notification(title, message, duration=3000):
    """统一的通知显示函数"""
    try:
        xbmc.executebuiltin(
            'Notification(%s, %s, %d, %s)' % (
                title,
                message,
                duration,
                os.path.join(ADDON_PATH, "icon.png")
            )
        )
    except Exception as e:
        log(f"Error showing notification: {e}")


def cleanup_countdown(countdown_window, countdown_thread):
    """清理倒计时窗口"""
    if countdown_window:
        countdown_window.close()
        if countdown_thread and countdown_thread.is_alive():
            countdown_thread.join()
    return None, None


def handle_countdown_cancellation(countdown_state, player):
    """处理倒计时取消"""
    if countdown_state["window"] and countdown_state["window"].cancelled:
        player.cancel_skip = True
        show_notification(ADDON.getLocalizedString(32027), ADDON.getLocalizedString(32002))
        countdown_state["window"], countdown_state["thread"] = cleanup_countdown(
            countdown_state["window"], countdown_state["thread"]
        )
        countdown_state["active"] = False
        return True
    return False


def create_countdown_window():
    try:
        window = SkipCountdownWindow("notification_overlay.xml", ADDON_PATH)
        thread = threading.Thread(target=window.doModal)
        thread.start()
        return window, thread
    except Exception as e:
        log(f"Error creating countdown window: {e}")
        return None, None


def handle_outro_enter(countdown_state):
    countdown_state["active"] = True
    countdown_state["remaining"] = 6.0
    countdown_state["window"], countdown_state["thread"] = create_countdown_window()
    
    tvshow_id, show_title, season, source_type = get_current_tvshow_info()
    state = get_active_video_playlist_state()
    
    try:
        raw_string = ADDON.getLocalizedString(32001)
        
        if source_type == 'directory':
            current_file = safe_get_state_value(state, "file", "")
            if current_file:
                season_num, episode_num, parsed = extract_media_info_from_filename(current_file)
                
                if parsed:
                    if '%' in raw_string:
                        notification_text = raw_string % (season_num, episode_num)
                    else:
                        notification_text = f"S{season_num:02d}E{episode_num:02d} {raw_string}"
                else:
                    notification_text = raw_string
            else:
                notification_text = raw_string
        else:
            episode = safe_get_state_value(state, "episode")
            season_num = int(season) if season else 1
            episode_num = int(episode) if episode and episode != -1 else 1
            
            if '%' in raw_string:
                notification_text = raw_string % (season_num, episode_num)
            else:
                notification_text = f"S{season_num:02d}E{episode_num:02d} {raw_string}"
        
        show_notification(ADDON.getLocalizedString(32027), notification_text)
        log("handle_outro_enter: Notification executed")
    except Exception as e:
        log(f"Error showing outro notification: {e}")
        log(traceback.format_exc())
    
    if countdown_state["window"] and countdown_state["window"].is_ready:
        countdown_state["window"].update_text(ADDON.getLocalizedString(32003) % int(countdown_state["remaining"]))


def reset_outro_state(countdown_state, player):
    if player.cancel_skip:
        player.cancel_skip = False
    if countdown_state["active"]:
        countdown_state["active"] = False
        log("Playback time before outro range. Resetting countdown.")
    countdown_state["window"], countdown_state["thread"] = cleanup_countdown(
        countdown_state["window"], countdown_state["thread"]
    )


def stop_playback_and_wait(timeout_ms=3000, interval_ms=100):
    """安全地停止播放并等待"""
    player = xbmc.Player()
    try:
        if player.isPlayingVideo():
            player.stop()
    except Exception as e:
        log(f"stop_playback_and_wait: stop failed: {e}")
        return
    start_time = time.time()
    while True:
        try:
            if not player.isPlayingVideo():
                return
        except Exception:
            return
        elapsed_ms = (time.time() - start_time) * 1000.0
        if elapsed_ms >= timeout_ms:
            return
        xbmc.sleep(interval_ms)


def safe_get_state_value(state, key, default=None):
    """安全地获取 state 字典的值"""
    try:
        return state.get(key) if isinstance(state, dict) else default
    except Exception:
        return default


def execute_next_episode(countdown_state):
    cleanup_countdown(countdown_state["window"], countdown_state["thread"])
    countdown_state["window"], countdown_state["thread"] = None, None
    
    mark_current_episode_as_watched()
    
    shared_state = State()
    
    def try_play_next():
        shared_state.set_playing_next(True)
        xbmc.executebuiltin("PlayerControl(Next)")
    
    try:
        state = get_active_video_playlist_state()
        
        if state:
            playlist_position = safe_get_state_value(state, "position")
            playlist_id = safe_get_state_value(state, "playlistid")
            if is_next_episode_available_in_playlist(playlist_id, playlist_position):
                try_play_next()
                countdown_state["active"] = False
                return
        
        tvshow_id, show_title, season, source_type = get_current_tvshow_info()
        
        if source_type == 'library' and tvshow_id and str(tvshow_id) != '-1':
            current_file = safe_get_state_value(state, "file", "") if state else ""
            current_episode_num = safe_get_state_value(state, "episode") if state else None
            current_season_num = safe_get_state_value(state, "season") if state else None
            
            next_episode = get_next_episode_from_library(
                tvshow_id, current_file,
                include_watched=True,
                current_episode_num=current_episode_num,
                current_season_num=current_season_num
            )
            
            if next_episode and play_episode_from_library(next_episode):
                shared_state.set_playing_next(True)
                countdown_state["active"] = False
                return
        
        if source_type == "directory" and state:
            current_file = state.get("file", "")
            next_file = get_next_file_in_directory(current_file)
            if next_file:
                shared_state.set_playing_next(True)
                stop_playback_and_wait(timeout_ms=5000, interval_ms=200)
                xbmc.sleep(800)
                if play_file(next_file):
                    countdown_state["active"] = False
                    return
        
        try_play_next()
        
    except Exception:
        try:
            try_play_next()
        except Exception:
            pass
    
    countdown_state["active"] = False


def update_countdown_ui(countdown_state, player):
    if countdown_state["remaining"] <= 0:
        return
    try:
        display_seconds = int(countdown_state["remaining"]) + 1
        if countdown_state["window"] and countdown_state["window"].is_ready:
            countdown_state["window"].update_text(ADDON.getLocalizedString(32003) % display_seconds)

        if countdown_state["window"] and countdown_state["window"].cancelled:
            player.cancel_skip = True
            show_notification(ADDON.getLocalizedString(32027), ADDON.getLocalizedString(32002))
            countdown_state["window"], countdown_state["thread"] = cleanup_countdown(
                countdown_state["window"], countdown_state["thread"]
            )
            countdown_state["active"] = False
    except Exception as e:
        log(f"Error updating countdown window: {e}")


if __name__ == '__main__':
    log("Service started")

    monitor = xbmc.Monitor()
    player = PlayerMonitor()

    countdown_state = {
        "window": None,
        "thread": None,
        "active": False,
        "remaining": 0.0,
    }
    last_tick_time = time.time()

    while not monitor.abortRequested():
        current_tick_time = time.time()
        dt = current_tick_time - last_tick_time
        last_tick_time = current_tick_time

        if xbmcgui.Window(10000).getProperty("MFG.Reload") == "true":
            xbmcgui.Window(10000).clearProperty("MFG.Reload")
            player.update_outro_info()
            countdown_state["active"] = False

        if player.is_playing() and player.current_outro_time:
            try:
                current_time = player.getTime()
                trigger_time = player.current_outro_time

                if current_time < trigger_time - 6:
                    reset_outro_state(countdown_state, player)
                elif not player.outro_triggered and not player.cancel_skip:
                    if not countdown_state["active"]:
                        handle_outro_enter(countdown_state)
                    else:
                        if not xbmc.getCondVisibility("Player.Paused"):
                            countdown_state["remaining"] -= dt
                        update_countdown_ui(countdown_state, player)
                        if countdown_state["remaining"] <= 0:
                            player.outro_triggered = True
                            execute_next_episode(countdown_state)

            except Exception:
                cleanup_countdown(countdown_state["window"], countdown_state["thread"])
                countdown_state["window"], countdown_state["thread"] = None, None
                countdown_state["active"] = False
        else:
            if countdown_state["active"]:
                cleanup_countdown(countdown_state["window"], countdown_state["thread"])
                countdown_state["window"], countdown_state["thread"] = None, None
                countdown_state["active"] = False

        if monitor.waitForAbort(0.3):
            break
