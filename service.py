# -*- coding: utf-8 -*-
import os
import time
import math
import threading
from typing import Optional, Tuple

import xbmc
import xbmcgui

from common import (
    ADDON_PATH, load_skip_data, get_current_tvshow_info,
    autofill_playlist_for_current_video, log, log_debug,
    get_next_episode_from_library, play_episode_from_library,
    is_next_episode_available_in_playlist, get_active_video_playlist_state,
    get_next_file_in_directory, play_file, extract_media_info_from_filename,
    State, mark_current_episode_as_watched, get_season_episode_from_state,
    SETTINGS, PLAYBACK_STOP_TIMEOUT_MS, PLAYBACK_STOP_INTERVAL_MS,
    show_notification, close_current_notification, is_notification_showing,
    apply_notification_layout, NOTIFICATION_LABEL_ID,
    OUTRO_RESET_BUFFER, notification_max_wait,
    MAIN_LOOP_INTERVAL,
    NOTIFICATION_DURATION_LONG
)


class SkipCountdownWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)
        self.cancelled = False
        self.is_ready = False
        self._layout_applied = False

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

    def update_text(self, text: str) -> None:
        if not self.is_ready:
            return
        try:
            ctrl = self.getControl(NOTIFICATION_LABEL_ID)
            if ctrl:
                # 倒计时每秒刷新文案，窗口宽度只需在首次按文本定好
                if not self._layout_applied:
                    self._layout_applied = apply_notification_layout(self, text)
                ctrl.setLabel(text)
        except Exception as e:
            log(f"Error updating countdown text: {e}", xbmc.LOGERROR)


class CountdownState:
    def __init__(self):
        self.window: Optional[SkipCountdownWindow] = None
        self.thread: Optional[threading.Thread] = None
        self.active: bool = False
        self.remaining: float = 0.0
        self.season_num: int = 0
        self.episode_num: int = 0

    def cleanup(self) -> None:
        # 先重置状态再关窗口：close/join 抛异常时状态不会残留，
        # 否则 active 卡在 True 会导致本集之后再也不起倒计时
        window = self.window
        thread = self.thread
        self.window = None
        self.thread = None
        self.active = False
        if window:
            try:
                window.close()
            except Exception as e:
                log(f"Error closing countdown window: {e}", xbmc.LOGERROR)
        if thread and thread.is_alive():
            try:
                thread.join(timeout=1.0)
            except Exception as e:
                log(f"Error joining countdown thread: {e}", xbmc.LOGERROR)


class PlayerMonitor(xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)
        self.current_outro_time: Optional[float] = None
        self.outro_triggered: bool = False
        self.cancel_skip: bool = False
        # 等待通知播完再启动倒计时的截止时间（None 表示未在等待）
        self.pending_outro_deadline: Optional[float] = None
        # 刚记录过跳过点：等通知出现并消失后再起倒计时（带过期时间，避免状态残留）
        self.await_notification_until: Optional[float] = None
        self.state: State = State()
        self._cached_playing_state: Optional[bool] = None
        self._state_cache_time: float = 0
        self._state_cache_ttl: float = 0.5

    def is_video_playing(self) -> bool:
        now = time.time()
        if now - self._state_cache_time > self._state_cache_ttl:
            try:
                self._cached_playing_state = self.isPlayingVideo()
                self._state_cache_time = now
            except Exception as e:
                log_debug(f"isPlayingVideo check failed: {e}")
                self._cached_playing_state = False
        return self._cached_playing_state or False

    def onAVStarted(self):
        self.cancel_skip = False
        self.state.playing_next = False
        self.current_outro_time = None
        self.outro_triggered = False
        self.pending_outro_deadline = None
        self.await_notification_until = None
        self.check_intro()
        self.retry_update_outro()
        autofill_playlist_for_current_video()

    def onPlayBackEnded(self):
        if self.state.playing_next:
            self.state.playing_next = False
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

    def retry_update_outro(self, max_retries: int = 10, delay_ms: int = 1000) -> None:
        for i in range(max_retries):
            try:
                total_time = self.getTotalTime()
                if total_time > 0:
                    self.update_outro_info()
                    return
            except Exception as e:
                log(f"retry_update_outro: error getting totalTime: {e}", xbmc.LOGWARNING)
            xbmc.sleep(delay_ms)
        log("retry_update_outro: failed to get totalTime after max retries", xbmc.LOGWARNING)

    def update_outro_info(self) -> None:
        if not self.is_video_playing():
            return

        tvshow_id, show_title, season, source_type = get_current_tvshow_info()
        if not tvshow_id:
            return

        data = load_skip_data(force_reload=True)
        if tvshow_id not in data:
            return

        record = data[tvshow_id]
        if "seasons" not in record or season not in record["seasons"]:
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
                except Exception as e:
                    log(f"Error calculating outro trigger: {e}", xbmc.LOGERROR)
            elif self.current_outro_time is not None:
                self.current_outro_time = None
                self.outro_triggered = False

    def check_intro(self) -> None:
        if not self.is_video_playing():
            return

        tvshow_id, show_title, season, source_type = get_current_tvshow_info()
        if not tvshow_id:
            return

        state = get_active_video_playlist_state()
        data = load_skip_data()
        if tvshow_id not in data:
            return

        record = data[tvshow_id]
        skip_time = 0

        if "seasons" in record and season in record["seasons"]:
            val = record["seasons"][season]
            skip_time = val.get("intro", 0) if isinstance(val, dict) else val
        elif "time" in record:
            skip_time = record["time"]

        if skip_time > 0:
            try:
                current_time = self.getTime()
                if current_time < skip_time:
                    log_debug(f"Auto skipping intro for {show_title} S{season}. Current: {current_time}, Target: {skip_time}")
                    self.seekTime(skip_time)

                    season_num, episode_num = get_season_episode_from_state(source_type, state, season)
                    notification_text = SETTINGS.get_string(32000) % (season_num, episode_num)
                    show_notification(notification_text)
            except Exception as e:
                log(f"Error during skip: {e}", xbmc.LOGERROR)


def create_countdown_window() -> Tuple[Optional[SkipCountdownWindow], Optional[threading.Thread]]:
    try:
        window = SkipCountdownWindow("notification_overlay.xml", ADDON_PATH)
        # daemon：窗口若因异常没能关闭，也不会拖住 Kodi 退出
        thread = threading.Thread(target=window.doModal, daemon=True)
        thread.start()
        # 等控件就绪再返回，否则窗口会先以 XML 里的默认窄条空闪一下
        ready_deadline = time.time() + 1.0
        while time.time() < ready_deadline and not window.is_ready:
            xbmc.sleep(20)
        return window, thread
    except Exception as e:
        log(f"Error creating countdown window: {e}", xbmc.LOGERROR)
        return None, None


def stop_playback_and_wait(timeout_ms: int = PLAYBACK_STOP_TIMEOUT_MS, interval_ms: int = PLAYBACK_STOP_INTERVAL_MS) -> None:
    player = xbmc.Player()
    try:
        if player.isPlayingVideo():
            player.stop()
    except Exception as e:
        log(f"stop_playback_and_wait: stop failed: {e}", xbmc.LOGERROR)
        return

    start_time = time.time()
    while True:
        try:
            if not player.isPlayingVideo():
                return
        except Exception as e:
            log_debug(f"Error checking playback state: {e}")
            return
        elapsed_ms = (time.time() - start_time) * 1000.0
        if elapsed_ms >= timeout_ms:
            return
        xbmc.sleep(interval_ms)


def execute_next_episode(countdown_state: CountdownState) -> None:
    countdown_state.cleanup()

    mark_current_episode_as_watched()
    shared_state = State()

    def try_play_next():
        shared_state.playing_next = True
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
                shared_state.playing_next = True
                countdown_state.active = False
                return

        if source_type == "directory" and state:
            current_file = state.get("file", "")
            next_file = get_next_file_in_directory(current_file)
            if next_file:
                shared_state.playing_next = True
                stop_playback_and_wait(timeout_ms=PLAYBACK_STOP_TIMEOUT_MS, interval_ms=PLAYBACK_STOP_INTERVAL_MS)
                if play_file(next_file):
                    countdown_state.active = False
                    return

        try_play_next()
    except Exception as e:
        log(f"Error in execute_next_episode: {e}", xbmc.LOGERROR)
        try:
            try_play_next()
        except Exception as e2:
            log(f"Fallback play failed: {e2}", xbmc.LOGERROR)

    countdown_state.active = False


def has_next_episode() -> bool:
    state = get_active_video_playlist_state()
    if not state:
        return False

    playlist_position = state.get("position")
    playlist_id = state.get("playlistid")
    if is_next_episode_available_in_playlist(playlist_id, playlist_position):
        return True

    tvshow_id, show_title, season, source_type = get_current_tvshow_info()

    if source_type == 'library' and tvshow_id and str(tvshow_id) != '-1':
        current_file = state.get("file", "")
        current_episode_num = state.get("episode")
        current_season_num = state.get("season")
        next_episode = get_next_episode_from_library(
            tvshow_id, current_file, include_watched=True,
            current_episode_num=current_episode_num,
            current_season_num=current_season_num
        )
        if next_episode:
            return True

    if source_type == "directory":
        current_file = state.get("file", "")
        next_file = get_next_file_in_directory(current_file)
        if next_file:
            return True

    return False


def _countdown_display_seconds(remaining: float) -> int:
    """倒计时显示的秒数：向上取整。

    原来用 int(remaining) + 1，首帧 remaining 还是完整值时会多显示 1 秒
    （设 6 秒却显示"7 秒内"），暂停时 remaining 不减也会一直多 1。
    """
    return max(1, int(math.ceil(remaining - 1e-6)))


def _effective_countdown_seconds(player: PlayerMonitor) -> float:
    """实际倒计时秒数：不超过当前距离视频结束的剩余时间。

    倒计时是从片尾点起算的，如果用户记录的片尾比设置的倒计时还短（或者刚记录完
    片尾点时通知占用了一部分时间），倒计时会走不完——视频先播完，is_video_playing()
    变 False，倒计时停止推进，本集就再也不会自动跳转。
    这里按「当前剩余时长 - 1 秒」封顶，保证倒计时一定能在片尾内走完。
    """
    configured = float(SETTINGS.countdown_seconds)
    try:
        total_time = player.getTotalTime()
        current_time = player.getTime()
        if total_time > 0:
            left = total_time - current_time
            if left > 0:
                effective = max(1.0, min(configured, left - 1.0))
                if effective < configured:
                    log_debug(
                        f"Countdown shortened {configured:.0f}s -> {effective:.0f}s, "
                        f"only {left:.1f}s left in episode"
                    )
                return effective
    except Exception as e:
        log(f"Failed to compute effective countdown: {e}", xbmc.LOGWARNING)
    return configured


def handle_outro_enter(countdown_state: CountdownState, player: PlayerMonitor) -> None:
    countdown_state.active = True
    countdown_state.remaining = _effective_countdown_seconds(player)
    # 倒计时窗口与通知窗口位置相同，先关闭残留通知，避免视觉叠加
    close_current_notification()
    countdown_state.window, countdown_state.thread = create_countdown_window()

    tvshow_id, show_title, season, source_type = get_current_tvshow_info()
    state = get_active_video_playlist_state()

    countdown_state.season_num, countdown_state.episode_num = get_season_episode_from_state(
        source_type, state, season
    )

    if countdown_state.window and countdown_state.window.is_ready:
        countdown_state.window.update_text(
            SETTINGS.get_string(32003)
            % (countdown_state.season_num, countdown_state.episode_num,
               _countdown_display_seconds(countdown_state.remaining))
        )


def reset_outro_state(countdown_state: CountdownState, player: PlayerMonitor) -> None:
    if player.cancel_skip:
        player.cancel_skip = False
    if countdown_state.active:
        countdown_state.active = False
        log("Playback time before outro range. Resetting countdown.", xbmc.LOGDEBUG)
    countdown_state.cleanup()


def handle_countdown_cancellation(countdown_state: CountdownState, player: PlayerMonitor) -> bool:
    if countdown_state.window and countdown_state.window.cancelled:
        player.cancel_skip = True
        # 先关闭倒计时窗口，再弹通知，避免两个窗口同时处于模态
        countdown_state.cleanup()
        show_notification(SETTINGS.get_string(32002))
        return True
    return False


def update_countdown_ui(countdown_state: CountdownState, player: PlayerMonitor) -> None:
    if countdown_state.remaining <= 0:
        return

    try:
        display_seconds = _countdown_display_seconds(countdown_state.remaining)
        if countdown_state.window and countdown_state.window.is_ready:
            countdown_state.window.update_text(
                SETTINGS.get_string(32003)
                % (countdown_state.season_num, countdown_state.episode_num, display_seconds)
            )

        if handle_countdown_cancellation(countdown_state, player):
            return
    except Exception as e:
        log(f"Error updating countdown window: {e}", xbmc.LOGERROR)


if __name__ == '__main__':
    log("Service started")

    monitor = xbmc.Monitor()
    player = PlayerMonitor()
    countdown_state = CountdownState()
    last_tick_time = time.time()

    while not monitor.abortRequested():
        current_tick_time = time.time()
        dt = max(0.0, current_tick_time - last_tick_time)
        last_tick_time = current_tick_time

        if xbmcgui.Window(10000).getProperty("MFG.Reload") == "true":
            xbmcgui.Window(10000).clearProperty("MFG.Reload")
            player.update_outro_info()
            if countdown_state.active:
                countdown_state.cleanup()
            # 记录/修改跳过点后：重置等待窗口，并等 default.py 弹出的记录通知出现并消失
            # （service 与 default.py 是不同进程，通知可能晚于 MFG.Reload 出现）
            player.pending_outro_deadline = None
            player.await_notification_until = time.time() + notification_max_wait()

        if player.is_video_playing() and player.current_outro_time:
            try:
                current_time = player.getTime()
                trigger_time = player.current_outro_time

                if current_time < trigger_time - OUTRO_RESET_BUFFER:
                    player.pending_outro_deadline = None
                    reset_outro_state(countdown_state, player)
                elif not player.outro_triggered and not player.cancel_skip:
                    if not countdown_state.active:
                        now = time.time()
                        if player.pending_outro_deadline is None:
                            player.pending_outro_deadline = now + notification_max_wait()
                        showing = is_notification_showing()
                        if showing:
                            player.await_notification_until = None
                        awaiting = (player.await_notification_until is not None
                                    and now < player.await_notification_until)
                        if (showing or awaiting) and now < player.pending_outro_deadline:
                            # 通知（如"已记录片尾"）仍在显示或即将出现：等它播完再起倒计时，
                            # 避免窗口叠加；等待期间不消耗倒计时，仍是设置里的完整秒数
                            pass
                        elif not has_next_episode():
                            player.pending_outro_deadline = None
                            player.await_notification_until = None
                            show_notification(
                                SETTINGS.get_string(32032),
                                duration=NOTIFICATION_DURATION_LONG
                            )
                            mark_current_episode_as_watched()
                            player.outro_triggered = True
                        else:
                            player.pending_outro_deadline = None
                            player.await_notification_until = None
                            handle_outro_enter(countdown_state, player)
                    else:
                        if not xbmc.getCondVisibility("Player.Paused"):
                            countdown_state.remaining -= dt
                        update_countdown_ui(countdown_state, player)
                        if countdown_state.remaining <= 0:
                            player.outro_triggered = True
                            execute_next_episode(countdown_state)
            except Exception as e:
                log(f"Error in outro handling loop: {e}", xbmc.LOGERROR)
                countdown_state.cleanup()

        else:
            if countdown_state.active:
                countdown_state.cleanup()

        if monitor.waitForAbort(MAIN_LOOP_INTERVAL):
            break
