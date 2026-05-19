# -*- coding: utf-8 -*-
import os
import xbmc
import xbmcgui
import time
import threading
from typing import Optional, Tuple, Any

from common import (
    ADDON_PATH, load_skip_data, get_current_tvshow_info, 
    autofill_playlist_for_current_video, log, log_exception, cleanup_expired_caches,
    get_next_episode_from_library, play_episode_from_library,
    is_next_episode_available_in_playlist, get_active_video_playlist_state,
    get_next_file_in_directory, play_file, extract_media_info_from_filename,
    State, mark_current_episode_as_watched, get_season_episode_from_state,
    SETTINGS, show_notification,
    OUTRO_COUNTDOWN_SECONDS, OUTRO_TRIGGER_THRESHOLD_SECONDS,
    RETRY_MAX_ATTEMPTS, RETRY_DELAY_MS, CACHE_CLEANUP_INTERVAL_SECONDS
)


class SkipCountdownWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs) -> None:
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)
        self.cancelled: bool = False
        self.is_ready: bool = False

    def onInit(self) -> None:
        self.is_ready = True

    def onAction(self, action: Any) -> None:
        action_id: int = action.getId()
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

    def update_text(self, text: str) -> None:
        if not self.is_ready:
            return
        try:
            ctrl = self.getControl(100)
            if ctrl:
                ctrl.setLabel(text)
        except Exception as e:
            log(f"Error updating countdown text: {e}", log_level=xbmc.LOGWARNING)


class CountdownState:
    def __init__(self) -> None:
        self.window: Optional[SkipCountdownWindow] = None
        self.thread: Optional[threading.Thread] = None
        self.active: bool = False
        self.remaining: float = 0.0

    def cleanup(self) -> None:
        if self.window:
            self.window.close()
            if self.thread and self.thread.is_alive():
                self.thread.join()
        self.window = None
        self.thread = None
        self.active = False


class PlayerMonitor(xbmc.Player):
    def __init__(self) -> None:
        xbmc.Player.__init__(self)
        self.current_outro_time: Optional[float] = None
        self.outro_triggered: bool = False
        self.cancel_skip: bool = False
        self.state = State()
        self._cached_playing_state: Optional[bool] = None
        self._state_cache_time: float = 0.0
        self._state_cache_ttl: float = 0.5

    def is_video_playing(self) -> bool:
        now: float = time.time()
        if now - self._state_cache_time > self._state_cache_ttl:
            try:
                self._cached_playing_state = self.isPlayingVideo()
                self._state_cache_time = now
            except Exception:
                self._cached_playing_state = False
        return self._cached_playing_state or False

    def onAVStarted(self) -> None:
        self.cancel_skip = False
        self.check_intro()
        self.retry_update_outro()
        autofill_playlist_for_current_video()

    def onPlayBackEnded(self) -> None:
        if self.state.get_playing_next():
            self.state.set_playing_next(False)
        else:
            self.state.reset()
            self.current_outro_time = None
            self.outro_triggered = False

    def onPlayBackStopped(self) -> None:
        self.state.reset()
        self.current_outro_time = None
        self.outro_triggered = False

    def onPlayBackPaused(self) -> None:
        self.state.pause = True

    def onPlayBackResumed(self) -> None:
        self.state.pause = False

    def retry_update_outro(self, max_retries: int = RETRY_MAX_ATTEMPTS, delay_ms: int = RETRY_DELAY_MS) -> None:
        for i in range(max_retries):
            try:
                total_time: float = self.getTotalTime()
                if total_time > 0:
                    self.update_outro_info()
                    return
            except Exception as e:
                log(f"retry_update_outro: error getting totalTime: {e}", log_level=xbmc.LOGWARNING)
            xbmc.sleep(delay_ms)
        log("retry_update_outro: failed to get totalTime after max retries", log_level=xbmc.LOGWARNING)

    def update_outro_info(self) -> None:
        tvshow_id, show_title, season, source_type = get_current_tvshow_info()
        if not tvshow_id:
            self.current_outro_time = None
            return

        data = load_skip_data()
        if tvshow_id not in data:
            self.current_outro_time = None
            return

        tvshow_data = data[tvshow_id]
        outro_duration = None

        if "seasons" in tvshow_data and season in tvshow_data["seasons"]:
            season_data = tvshow_data["seasons"][season]
            if isinstance(season_data, dict) and "outro" in season_data:
                outro_duration = float(season_data["outro"])

        if outro_duration is None and "time" in tvshow_data:
            outro_duration = float(tvshow_data["time"])

        if outro_duration is None:
            self.current_outro_time = None
            return

        try:
            total_time = self.getTotalTime()
            if total_time > 0:
                self.current_outro_time = total_time - outro_duration
                log(f"Outro trigger time set to {self.current_outro_time:.2f}s (outro duration: {outro_duration}s)")
            else:
                self.current_outro_time = None
        except Exception as e:
            log(f"Error getting total time for outro: {e}")
            self.current_outro_time = None

    def check_intro(self) -> None:
        tvshow_id, show_title, season, source_type = get_current_tvshow_info()
        if not tvshow_id:
            return

        data = load_skip_data()
        if tvshow_id not in data:
            return

        tvshow_data = data[tvshow_id]
        skip_time = None

        if "seasons" in tvshow_data and season in tvshow_data["seasons"]:
            season_data = tvshow_data["seasons"][season]
            if isinstance(season_data, dict) and "intro" in season_data:
                skip_time = float(season_data["intro"])
            elif isinstance(season_data, (int, float)):
                skip_time = float(season_data)

        if skip_time is None and "time" in tvshow_data:
            skip_time = float(tvshow_data["time"])

        if skip_time is None:
            return

        try:
            current_time = self.getTime()
            if current_time < 2:
                self.seekTime(skip_time)
                show_notification(SETTINGS.get_string(32027), SETTINGS.get_string(32001) % (show_title or ""))
                log(f"Auto-skipped intro for {show_title} at {skip_time:.2f}s")
        except Exception as e:
            log(f"Error skipping intro: {e}", log_level=xbmc.LOGWARNING)


def create_countdown_window():
    ui_file = os.path.join(ADDON_PATH, "resources", "skins", "Default", "1080i", "notification_overlay.xml")
    window = SkipCountdownWindow("notification_overlay.xml", ADDON_PATH, "Default", "1080i")
    window.show()

    def countdown_thread_func():
        while window.is_ready:
            xbmc.sleep(50)

    thread = threading.Thread(target=countdown_thread_func)
    thread.daemon = True
    thread.start()

    return window, thread


def handle_outro_enter(countdown_state):
    countdown_state.active = True
    countdown_state.remaining = OUTRO_COUNTDOWN_SECONDS
    countdown_state.window, countdown_state.thread = create_countdown_window()


def reset_outro_state(countdown_state, player):
    countdown_state.cleanup()
    player.outro_triggered = False


def update_countdown_ui(countdown_state, player):
    if not countdown_state.window:
        return

    seconds = int(countdown_state.remaining)
    if seconds > 0:
        msg = SETTINGS.get_string(32028) % seconds
        countdown_state.window.update_text(msg)
    else:
        countdown_state.window.update_text(SETTINGS.get_string(32029))


def has_next_episode():
    return is_next_episode_available_in_playlist()


def stop_playback_and_wait(timeout_ms=5000, interval_ms=100):
    try:
        player = xbmc.Player()
        if player.isPlaying():
            player.stop()

        elapsed = 0
        while elapsed < timeout_ms:
            if not player.isPlaying():
                return True
            xbmc.sleep(interval_ms)
            elapsed += interval_ms
        return False
    except Exception as e:
        log(f"Error stopping playback: {e}", log_level=xbmc.LOGWARNING)
        return False


def execute_next_episode(countdown_state):
    countdown_state.cleanup()

    mark_current_episode_as_watched()
    shared_state = State()

    def try_play_next():
        shared_state.set_playing_next(True)
        xbmc.executebuiltin("PlayerControl(Next)")

    try:
        state = get_active_video_playlist_state()

        if state:
            playlist_position = state.get("position")
            playlist_id = state.get("playlistid")
            if is_next_episode_available_in_playlist(playlist_id, playlist_position):
                try_play_next()
                countdown_state.active = False
                return

        tvshow_id, show_title, season, source_type = get_current_tvshow_info()

        if source_type == 'library' and tvshow_id and str(tvshow_id) != '-1':
            current_file = state.get("file", "") if state else ""
            current_episode_num = state.get("episode") if state else None
            current_season_num = state.get("season") if state else None

            next_episode = get_next_episode_from_library(
                tvshow_id, current_file, include_watched=True,
                current_episode_num=current_episode_num,
                current_season_num=current_season_num
            )

            if next_episode and play_episode_from_library(next_episode):
                shared_state.set_playing_next(True)
                countdown_state.active = False
                return

        if source_type == "directory" and state:
            current_file = state.get("file", "")
            next_file = get_next_file_in_directory(current_file)
            if next_file:
                shared_state.set_playing_next(True)
                stop_playback_and_wait(timeout_ms=5000, interval_ms=100)
                if play_file(next_file):
                    countdown_state.active = False
                    return

        try_play_next()
    except Exception as e:
        log_exception(e, "execute_next_episode")
        try:
            try_play_next()
        except Exception as e2:
            log_exception(e2, "execute_next_episode fallback")

    countdown_state.active = False


if __name__ == '__main__':
    log("Service started")

    monitor = xbmc.Monitor()
    player = PlayerMonitor()
    countdown_state = CountdownState()
    last_tick_time = time.time()
    last_cache_cleanup_time = time.time()

    while not monitor.abortRequested():
        current_tick_time = time.time()
        dt = current_tick_time - last_tick_time
        last_tick_time = current_tick_time

        if current_tick_time - last_cache_cleanup_time > CACHE_CLEANUP_INTERVAL_SECONDS:
            cleanup_expired_caches()
            last_cache_cleanup_time = current_tick_time

        if player.is_video_playing():
            try:
                current_time = player.getTime()
                total_time = player.getTotalTime()

                if total_time > 0:
                    percentage = (current_time / total_time) * 100
                    log(f"Playback: {current_time:.2f}/{total_time:.2f} ({percentage:.1f}%)", log_level=xbmc.LOGDEBUG)
            except Exception as e:
                log(f"Error getting playback info: {e}", log_level=xbmc.LOGWARNING)

        if player.is_video_playing() and player.current_outro_time:
            try:
                current_time = player.getTime()
                trigger_time = player.current_outro_time

                if current_time < trigger_time - OUTRO_TRIGGER_THRESHOLD_SECONDS:
                    reset_outro_state(countdown_state, player)
                elif not player.outro_triggered and not player.cancel_skip:
                    if not countdown_state.active:
                        if not has_next_episode():
                            show_notification(SETTINGS.get_string(32027), SETTINGS.get_string(32032), duration=5000)
                            mark_current_episode_as_watched()
                            player.outro_triggered = True
                        else:
                            handle_outro_enter(countdown_state)
                    else:
                        if not xbmc.getCondVisibility("Player.Paused"):
                            countdown_state.remaining -= dt
                        update_countdown_ui(countdown_state, player)
                        if countdown_state.remaining <= 0:
                            player.outro_triggered = True
                            execute_next_episode(countdown_state)
            except Exception as e:
                log_exception(e, "main loop outro handling")
                countdown_state.cleanup()

        monitor.waitForAbort(100)

    log("Service stopped")