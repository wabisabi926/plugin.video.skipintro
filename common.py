# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import xbmcvfs
import json
import os
import re
import time
import math
import threading
import xbmcaddon
import shutil
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union
from functools import wraps

T = TypeVar('T')

ADDON_ID = 'plugin.video.skipintro'
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_PATH = xbmcvfs.translatePath(f"special://home/addons/{ADDON_ID}/")
ADDON_DATA_PATH = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")

if not os.path.exists(ADDON_DATA_PATH):
    os.makedirs(ADDON_DATA_PATH)

# File paths
SKIP_DATA_FILE = os.path.join(ADDON_DATA_PATH, 'skip_intro_data.json')

# Playlist configuration
MAX_PLAYLIST_ITEMS_BEFORE = 10
MAX_PLAYLIST_ITEMS_AFTER = 50
MAX_DELETE_LOWER_EPISODES_BELOW = 10
PLAYLIST_MUTATION_DELAY_MS = 300

# Playback control
PLAYBACK_STOP_TIMEOUT_MS = 5000
PLAYBACK_STOP_INTERVAL_MS = 100
DEFAULT_NOTIFICATION_DURATION = 3000   # 普通通知兜底停留时长（毫秒），实际以设置项 3-10 秒为准
NOTIFICATION_DURATION_LONG = 5000

# Skip thresholds (percentage)
SKIP_THRESHOLD_INTRO = 20
SKIP_THRESHOLD_OUTRO = 80

# Countdown configuration
COUNTDOWN_SECONDS = 6
OUTRO_RESET_BUFFER = 6
# 片尾区内记录/修改片尾点后，先等通知播完再启动倒计时（上限秒数）
OUTRO_NOTIFICATION_WAIT = 3.0
MAIN_LOOP_INTERVAL = 0.3

# Auto-fill configuration
AUTOFILL_DELAY_SECONDS = 2
SAVE_DEBOUNCE_MS = 500

# Cache configuration
CACHE_TTL_SKIP_DATA = 2.0
CACHE_TTL_PLAYLIST_STATE = 0.4
CACHE_TTL_SEASON_EPISODES = 3600
MAX_SEASON_CACHE_ENTRIES = 100

# Thread safety
_cache_lock = threading.Lock()
_state_lock = threading.Lock()
_save_lock = threading.Lock()

_caches: Dict[str, Any] = {
    'skip_data': {'data': None, 'time': 0.0, 'ttl': CACHE_TTL_SKIP_DATA},
    'playlist_state': {'data': None, 'time': 0.0, 'ttl': CACHE_TTL_PLAYLIST_STATE},
    'season_episodes': OrderedDict()
}

# Auto-fill thread dedup
_autofill_thread: Optional[threading.Thread] = None
_autofill_event = threading.Event()

# Save debounce
_save_timer: Optional[threading.Timer] = None
_save_pending_data: Optional[Dict[str, Any]] = None
_save_pending_lock = threading.Lock()


def log(msg: str, prefix: str = "[SkipIntro]", log_level: int = xbmc.LOGINFO) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    xbmc.log(f"{timestamp} {prefix} {msg}", log_level)


def log_error(msg: str, prefix: str = "[SkipIntro]") -> None:
    log(msg, prefix, xbmc.LOGERROR)


def log_warning(msg: str, prefix: str = "[SkipIntro]") -> None:
    log(msg, prefix, xbmc.LOGWARNING)


def log_debug(msg: str, prefix: str = "[SkipIntro]") -> None:
    if SETTINGS.debug_mode:
        log(msg, prefix, xbmc.LOGDEBUG)


# 通知窗口：单个皮肤窗口，运行时按文本宽度调整控件尺寸，
# 等价于 Kodi 原生 Notification 的自适应宽度（见 apply_notification_layout）
NOTIFICATION_WINDOW_XML = "notification_overlay.xml"
NOTIFICATION_LABEL_ID = 100
NOTIFICATION_IMAGE_ID = 101
NOTIFICATION_MAX_WIDTH = 900        # XML 里 group 的固定宽度，窗口不会超过它
NOTIFICATION_SIDE_PADDING = 8       # 文字左右内边距
NOTIFICATION_MIN_WIDTH = 0          # 窗口宽度下限，0 表示完全贴合文本
NOTIFICATION_FONT_EM = 32.0         # font14 在 720p 基准下的 em 尺寸（导火线 32 / Estuary 33）
NOTIFICATION_WIDTH_SAFETY = 1.02    # 宽度估算余量，吸收字体渲染的 kerning/hinting 差异
NOTIFICATION_BASE_COLOR = "262626"  # 通知条底色（RGB），透明度由设置项控制
NOTIFICATION_OPACITY_DEFAULT = 80   # 默认不透明度（%）
NOTIFICATION_TOP_DEFAULT = 10       # 通知条垂直位置（占屏幕高度的百分比）
NOTIFICATION_TOP_MIN = 0
NOTIFICATION_TOP_MAX = 90

_notification_lock = threading.Lock()
_active_notification_threads: List[threading.Thread] = []
_current_notification: Optional["NotificationWindow"] = None
_notification_showing: bool = False

# 跨进程通知状态标记：default.py（记录跳过点）与 service.py 是两个独立进程，
# 模块级变量不共享，必须借助 Window(10000) 属性通信
NOTIFICATION_PROP = "SkipIntro.NotificationShowing"


def _notification_token(window: "NotificationWindow") -> str:
    """通知窗口唯一标识（含进程号，跨进程唯一）。"""
    return f"{os.getpid()}-{id(window)}"


def _mark_notification_showing(window: "NotificationWindow", duration: int) -> None:
    try:
        xbmcgui.Window(10000).setProperty(
            NOTIFICATION_PROP,
            f"{_notification_token(window)}|{time.time() + duration / 1000.0 + 1.0:.3f}",
        )
    except Exception as e:
        log(f"Failed to mark notification property: {e}", xbmc.LOGWARNING)


def _clear_notification_prop(window: "NotificationWindow") -> None:
    try:
        win = xbmcgui.Window(10000)
        raw = win.getProperty(NOTIFICATION_PROP) or ""
        if raw.split("|", 1)[0] == _notification_token(window):
            win.clearProperty(NOTIFICATION_PROP)
    except Exception as e:
        log(f"Failed to clear notification property: {e}", xbmc.LOGWARNING)


def _char_width_ratio(ch: str) -> float:
    """单个字符相对 em 的宽度系数（按 NotoSans 实测近似值）。"""
    code = ord(ch)
    if code > 0x2E80:      # CJK 汉字与全角标点
        return 1.0
    if ch == " ":
        return 0.26
    if "0" <= ch <= "9":
        return 0.57
    if "A" <= ch <= "Z":
        return 0.65
    if "a" <= ch <= "z":
        return 0.52
    return 0.33


def measure_notification_text(text: str) -> float:
    """估算文本在 font25_title 下的渲染宽度（1080i 皮肤坐标）。"""
    return sum(_char_width_ratio(ch) for ch in text) * NOTIFICATION_FONT_EM


def notification_window_width(text: str) -> int:
    """按文本宽度算出窗口宽度（含两侧内边距），并限制在配置区间内。"""
    text_width = measure_notification_text(text) * NOTIFICATION_WIDTH_SAFETY
    width = int(math.ceil(text_width)) + NOTIFICATION_SIDE_PADDING * 2
    return max(NOTIFICATION_MIN_WIDTH, min(width, NOTIFICATION_MAX_WIDTH))


def notification_background_color() -> str:
    """按设置里的不透明度生成通知条背景色（AARRGGBB）。"""
    opacity = SETTINGS.notification_opacity
    alpha = max(0, min(255, int(opacity * 255 / 100.0 + 0.5)))
    return f"{alpha:02X}{NOTIFICATION_BASE_COLOR}"


def notification_max_wait() -> float:
    """等待通知消失的最长时间。

    不低于 OUTRO_NOTIFICATION_WAIT，并且要覆盖一条通知的完整停留时长，
    否则通知比等待窗口还长时，倒计时会叠在通知上。
    """
    return max(OUTRO_NOTIFICATION_WAIT, SETTINGS.notification_seconds + 1.0)


def apply_notification_layout(window: Any, text: str) -> bool:
    """按文本宽度调整背景与文本控件：右边缘锚定，左边缘随文字伸缩。

    XML 里 group 固定为 NOTIFICATION_MAX_WIDTH 宽并靠右，这里把背景和文本
    重新定位到 group 的右侧，宽度贴合文本，等价于原生通知的自适应效果。
    """
    try:
        width = notification_window_width(text)
        left = NOTIFICATION_MAX_WIDTH - width
        # 百分比换算成当前皮肤坐标（1080i 皮肤下 10% = 108，720p 皮肤下 = 72，比例一致）
        screen_height = window.getHeight() or 1080
        top_pct = SETTINGS.notification_top_pct
        top = int(screen_height * top_pct / 100)

        image = window.getControl(NOTIFICATION_IMAGE_ID)
        if image:
            image.setPosition(left, top)
            image.setWidth(width)
            try:
                color = notification_background_color()
                image.setColorDiffuse(color)
                log_debug(
                    f"Notification layout: width={width}, top={top}({top_pct}%), color={color}"
                )
            except Exception as e:
                log(f"Failed to apply notification opacity: {e}", xbmc.LOGWARNING)

        label = window.getControl(NOTIFICATION_LABEL_ID)
        if label:
            label_width = width - NOTIFICATION_SIDE_PADDING * 2
            label.setPosition(left + NOTIFICATION_SIDE_PADDING, top)
            label.setWidth(label_width)
            actual = label.getWidth()
            if actual != label_width:
                log_warning(
                    f"Notification label width not applied: got {actual}, expected {label_width}"
                )

        # 诊断输出：确认 setPosition / setWidth 是否真的生效
        log_debug(
            f"Layout: text={measure_notification_text(text):.0f}px, window={width}, "
            f"left={left}, top={top}({top_pct}%), screen_h={screen_height}"
        )
        if image:
            log_debug(f"  image: pos={image.getPosition()}, size={image.getWidth()}x{image.getHeight()}")
        if label:
            log_debug(f"  label: pos={label.getPosition()}, size={label.getWidth()}x{label.getHeight()}")

        return True
    except Exception as e:
        log(f"Failed to apply notification layout: {e}", xbmc.LOGERROR)
        return False


class NotificationWindow(xbmcgui.WindowXMLDialog):
    """使用插件自带皮肤绘制的通知窗口，替代 Kodi 原生 Notification。"""

    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)
        self.is_ready = False
        self._closed = False
        self._layout_applied = False

    def onInit(self):
        self.is_ready = True

    def set_message(self, message: str) -> bool:
        """写入文本；控件尚未就绪时返回 False，便于调用方轮询重试。"""
        try:
            ctrl = self.getControl(NOTIFICATION_LABEL_ID)
            if ctrl:
                # 首次写入时按文本宽度定好窗口尺寸，之后只更新文字
                if not self._layout_applied:
                    self._layout_applied = apply_notification_layout(self, message)
                ctrl.setLabel(message)
                return True
        except Exception as e:
            log(f"Failed to set notification label: {e}", xbmc.LOGERROR)
        return False

    def request_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.close()
        except Exception as e:
            log(f"Failed to close notification window: {e}", xbmc.LOGERROR)

    def onAction(self, action):
        action_id = action.getId()
        if action_id in [10, 92]:
            self.request_close()
            return
        # 通知窗口会抢占焦点，这里把播放类按键转发给播放器，避免打断视频操作
        if action_id in [1, 15]:
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


def _run_notification_window(window: "NotificationWindow") -> None:
    global _notification_showing
    try:
        window.doModal()
    except Exception as e:
        log(f"Notification window error: {e}", xbmc.LOGERROR)
    finally:
        _clear_notification_prop(window)
        with _notification_lock:
            current = threading.current_thread()
            if current in _active_notification_threads:
                _active_notification_threads.remove(current)
            # doModal 返回即窗口已关闭，是最可靠的"不再显示"信号
            if _current_notification is window:
                _notification_showing = False


def _present_notification(window: "NotificationWindow", message: str, duration: int) -> None:
    """控件一旦可用就立即写入文本，停留指定时长后关闭。

    这里不依赖 onInit 回调（该回调在脚本进程的某些时序下不会触发），
    改为直接轮询控件，避免文本延迟数秒才出现。
    """
    global _notification_showing
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not window.set_message(message):
            xbmc.sleep(20)
        # 窗口初始化可能重置文本，稍后再补写一次确保最终显示
        xbmc.sleep(150)
        window.set_message(message)
        time.sleep(duration / 1000.0)
    except Exception as e:
        log(f"Notification present error: {e}", xbmc.LOGERROR)
    finally:
        window.request_close()
        _clear_notification_prop(window)
        with _notification_lock:
            current = threading.current_thread()
            if current in _active_notification_threads:
                _active_notification_threads.remove(current)
            if _current_notification is window:
                _notification_showing = False


def show_notification(message: str, duration: Optional[int] = None) -> None:
    """通过插件自带 XML 窗口显示通知（非阻塞，窗口到时间自动关闭）。

    duration 不传时按设置项「通知停留时长」取值（默认 3 秒）。
    """
    global _current_notification, _notification_showing
    if duration is None:
        duration = SETTINGS.notification_seconds * 1000
    try:
        window = NotificationWindow(NOTIFICATION_WINDOW_XML, ADDON_PATH)

        with _notification_lock:
            previous = _current_notification
            _current_notification = window
            _notification_showing = True

        # 新通知到来时先关掉上一条，避免多窗口叠加
        if previous is not None:
            previous.request_close()

        _mark_notification_showing(window, duration)

        modal_thread = threading.Thread(target=_run_notification_window, args=(window,), daemon=True)
        present_thread = threading.Thread(
            target=_present_notification, args=(window, message, duration), daemon=True
        )
        with _notification_lock:
            _active_notification_threads.append(modal_thread)
            _active_notification_threads.append(present_thread)
        modal_thread.start()
        present_thread.start()
    except Exception as e:
        log(f"Failed to show notification: {e}", xbmc.LOGERROR)


def is_notification_showing() -> bool:
    """当前是否有通知窗口正在显示（跨进程）。

    通知可能由 default.py 或 service.py 弹出，两者是不同进程，
    因此以 Window(10000) 属性为准；属性里带截止时间，进程异常退出也不会残留。
    """
    try:
        raw = xbmcgui.Window(10000).getProperty(NOTIFICATION_PROP) or ""
    except Exception:
        raw = ""
    if raw:
        try:
            return time.time() < float(raw.rpartition("|")[2])
        except ValueError:
            return False
    with _notification_lock:
        return _notification_showing


def close_current_notification() -> None:
    """立即关闭当前显示中的通知窗口（供倒计时窗口等需要互斥的场景调用）。"""
    global _current_notification, _notification_showing
    with _notification_lock:
        window = _current_notification
        _current_notification = None
        _notification_showing = False
    if window is not None:
        try:
            window.request_close()
        except Exception as e:
            log(f"Failed to close current notification: {e}", xbmc.LOGERROR)
        _clear_notification_prop(window)


def wait_for_notifications(timeout_ms: Optional[int] = None) -> None:
    """等待进行中的通知窗口结束。

    短生命周期的脚本进程（如 default.py 的 RunScript）退出前调用，
    否则守护线程会随进程一起被销毁，窗口来不及显示。
    不传 timeout 时按「通知停留时长 + 3 秒」算，保证能覆盖最长 10 秒的通知。
    """
    if timeout_ms is None:
        timeout_ms = SETTINGS.notification_seconds * 1000 + 3000
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        with _notification_lock:
            alive = [t for t in _active_notification_threads if t.is_alive()]
        if not alive:
            return
        alive[0].join(timeout=0.1)


def _parse_season_data(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, (int, float)):
        return {"intro": raw}
    if isinstance(raw, dict):
        return raw.copy()
    return {}


def catch_exceptions(default_return: Any = None, log_prefix: str = "[SkipIntro]") -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log(f"[{func.__name__}] Error: {e}", log_prefix, xbmc.LOGERROR)
                return default_return
        return wrapper
    return decorator


class SettingsManager:
    def __init__(self) -> None:
        self._addon = ADDON
        self._settings_cache: Dict[str, str] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_ttl: float = 5.0

    def _get_setting(self, setting_id: str, default: Optional[str] = None) -> Optional[str]:
        now: float = time.time()
        if setting_id in self._settings_cache:
            cache_time: float = self._cache_time.get(setting_id, 0.0)
            if now - cache_time < self._cache_ttl:
                return self._settings_cache[setting_id]

        try:
            value: str = self._addon.getSetting(setting_id)
            self._settings_cache[setting_id] = value
            self._cache_time[setting_id] = now
            return value
        except Exception as e:
            log(f"Failed to get setting '{setting_id}': {e}", xbmc.LOGERROR)
            return default

    @property
    def autofill_playlist_on_play(self) -> bool:
        value: Optional[str] = self._get_setting('autofill_playlist_on_play')
        return value == 'true'

    @property
    def debug_mode(self) -> bool:
        value: Optional[str] = self._get_setting('debug_mode')
        return value == 'true'

    def _get_int_setting(self, setting_id: str, default: int, minimum: int, maximum: int) -> int:
        """读取数值型设置并限制在 [minimum, maximum]。

        Kodi 的数字输入框不做范围校验（输入超范围也会原样保存，settings.xml 里的
        <constraints> 不拦），所以越界时把修正后的值写回设置，避免设置页显示的
        数字和实际生效的值不一致。
        """
        raw = self._get_setting(setting_id)
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            # 空串是 Kodi 尚未初始化的正常状态，静默用默认值；
            # 非空却解析不了（比如手改配置文件写成 abc）则写回默认值，别让设置页一直显示脏值
            if raw and str(raw).strip():
                log(f"Setting '{setting_id}'='{raw}' is not a number, reset to {default}", xbmc.LOGWARNING)
                self.set_setting(setting_id, default)
            return default
        clamped = max(minimum, min(value, maximum))
        if clamped != value:
            log(
                f"Setting '{setting_id}'={value} out of range [{minimum}, {maximum}], "
                f"corrected to {clamped}",
                xbmc.LOGWARNING,
            )
            self.set_setting(setting_id, clamped)
        return clamped

    @property
    def countdown_seconds(self) -> int:
        """片尾倒计时秒数，设置项可调（3-10）。"""
        return self._get_int_setting('countdown_seconds', COUNTDOWN_SECONDS, 3, 10)

    @property
    def notification_seconds(self) -> int:
        """普通通知停留秒数，设置项可调（3-10）。"""
        return self._get_int_setting(
            'notification_seconds', DEFAULT_NOTIFICATION_DURATION // 1000, 3, 10
        )

    @property
    def notification_opacity(self) -> int:
        """通知条不透明度百分比，设置项可调（30-100）。"""
        return self._get_int_setting(
            'notification_opacity', NOTIFICATION_OPACITY_DEFAULT, 30, 100
        )

    @property
    def notification_top_pct(self) -> int:
        """通知条垂直位置（占屏幕高度的百分比），设置项可调（0-90）。"""
        return self._get_int_setting(
            'notification_top_pct', NOTIFICATION_TOP_DEFAULT,
            NOTIFICATION_TOP_MIN, NOTIFICATION_TOP_MAX
        )

    def get_string(self, string_id: int) -> str:
        try:
            return self._addon.getLocalizedString(string_id)
        except Exception as e:
            log(f"Failed to get string {string_id}: {e}", xbmc.LOGERROR)
            return f"[String {string_id}]"

    def invalidate_cache(self) -> None:
        self._settings_cache.clear()
        self._cache_time.clear()

    def set_setting(self, setting_id: str, value: Union[bool, int, float, str]) -> bool:
        try:
            if isinstance(value, bool):
                str_value = 'true' if value else 'false'
            elif isinstance(value, (int, float)):
                str_value = str(value)
            else:
                str_value = str(value)
            self._addon.setSetting(setting_id, str_value)
            self.invalidate_cache()
            return True
        except Exception as e:
            log(f"Failed to set '{setting_id}': {e}", xbmc.LOGERROR)
            return False


SETTINGS: SettingsManager = SettingsManager()


def _get_cached_data(cache_name: str, force_reload: bool = False) -> Tuple[Any, bool]:
    with _cache_lock:
        cache: Optional[Dict[str, Any]] = _caches.get(cache_name)
        if not cache:
            return None, False

        now: float = time.time()
        if not force_reload and cache.get('data') is not None and (now - cache.get('time', 0)) < cache.get('ttl', 3600.0):
            return cache['data'], True

        return None, False


def _set_cached_data(cache_name: str, data: Any) -> None:
    with _cache_lock:
        cache: Optional[Dict[str, Any]] = _caches.get(cache_name)
        if cache:
            cache['data'] = data
            cache['time'] = time.time()


def _evict_season_cache() -> None:
    season_cache: OrderedDict = _caches.get('season_episodes', OrderedDict())
    while len(season_cache) > MAX_SEASON_CACHE_ENTRIES:
        season_cache.popitem(last=False)


def load_skip_data(force_reload: bool = False) -> Dict[str, Any]:
    cached, hit = _get_cached_data('skip_data', force_reload)
    if hit:
        return cached

    if not os.path.exists(SKIP_DATA_FILE):
        _set_cached_data('skip_data', {})
        return {}

    try:
        with open(SKIP_DATA_FILE, 'r', encoding='utf-8') as f:
            data: Dict[str, Any] = json.load(f)
            _set_cached_data('skip_data', data)
            return data
    except (json.JSONDecodeError, IOError) as e:
        log(f"Failed to load skip data: {e}", xbmc.LOGERROR)
        return {}


def _do_save_skip_data(data: Dict[str, Any]) -> None:
    temp_file: str = SKIP_DATA_FILE + ".tmp"
    backup_file: str = SKIP_DATA_FILE + ".bak"

    try:
        if os.path.exists(SKIP_DATA_FILE):
            shutil.copy2(SKIP_DATA_FILE, backup_file)

        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        with open(temp_file, 'r', encoding='utf-8') as f:
            json.load(f)

        os.replace(temp_file, SKIP_DATA_FILE)

        if os.path.exists(backup_file):
            os.remove(backup_file)

        _set_cached_data('skip_data', data)
    except Exception as e:
        log(f"Failed to save skip data: {e}", xbmc.LOGERROR)
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError as cleanup_err:
                log(f"Failed to remove temp file: {cleanup_err}", xbmc.LOGWARNING)
        if os.path.exists(backup_file):
            try:
                if os.path.exists(SKIP_DATA_FILE):
                    os.remove(SKIP_DATA_FILE)
                if os.path.exists(backup_file):
                    os.rename(backup_file, SKIP_DATA_FILE)
                    log("Restored backup file successfully", xbmc.LOGDEBUG)
            except OSError as restore_err:
                log(f"Failed to restore backup: {restore_err}", xbmc.LOGERROR)


def save_skip_data(data: Dict[str, Any], immediate: bool = False) -> None:
    with _save_pending_lock:
        global _save_pending_data, _save_timer
        _save_pending_data = data

        if _save_timer is not None:
            _save_timer.cancel()

        if immediate:
            _save_timer = None
            _save_pending_data = None
            with _save_lock:
                _do_save_skip_data(data)
            return

        _save_timer = threading.Timer(SAVE_DEBOUNCE_MS / 1000.0, _flush_save_data)
        _save_timer.daemon = True
        _save_timer.start()


def _flush_save_data() -> None:
    global _save_pending_data, _save_timer
    with _save_pending_lock:
        data = _save_pending_data
        _save_timer = None
        _save_pending_data = None

    if data is not None:
        with _save_lock:
            _do_save_skip_data(data)


def delete_all_skip_points() -> None:
    with _save_pending_lock:
        global _save_pending_data, _save_timer
        _save_pending_data = None
        if _save_timer is not None:
            _save_timer.cancel()
            _save_timer = None

    if os.path.exists(SKIP_DATA_FILE):
        os.remove(SKIP_DATA_FILE)
    _set_cached_data('skip_data', {})


def jsonrpc_call(method: str, params: Optional[Dict[str, Any]] = None, request_id: Optional[Union[int, str]] = None) -> Optional[Dict[str, Any]]:
    query: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "id": request_id or method,
    }
    if params is not None:
        query["params"] = params

    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
    except (ValueError, RuntimeError) as e:
        log(f"JSON-RPC call failed [{method}]: {e}", xbmc.LOGERROR)
        return None

    if isinstance(response, dict) and "error" in response:
        error = response.get('error', {})
        log(f"JSON-RPC error [{method}]: {error}", xbmc.LOGWARNING)
        return None

    return response.get("result") if isinstance(response, dict) else None


def get_current_episode_id(tvshowid: Any, season: Any, episode: Any, current_file: Optional[str] = None) -> Optional[int]:
    try:
        tvshowid = int(tvshowid) if tvshowid not in (None, -1, "") else None
        season = int(season) if season not in (None, -1, "") else None
        episode = int(episode) if episode not in (None, -1, "") else None

        if current_file:
            result = jsonrpc_call(
                "VideoLibrary.GetEpisodes",
                {"properties": ["file", "episode", "season"]}
            ) or {}
            episodes = result.get("episodes") or []
            for ep in episodes:
                if ep.get("file") == current_file:
                    return ep.get("episodeid")

        if any(v is None for v in [tvshowid, season, episode]):
            return None

        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {"properties": ["episode", "season"], "tvshowid": tvshowid}
        ) or {}

        episodes = result.get("episodes") or []
        for ep in episodes:
            if ep.get("season") == season and ep.get("episode") == episode:
                episodeid = ep.get("episodeid")
                if episodeid and episodeid != -1:
                    log_debug(f"Found episodeid={episodeid} for S{season}E{episode}")
                    return episodeid

        log_debug(f"No episodeid found for S{season}E{episode}")
        return None
    except (ValueError, TypeError) as e:
        log(f"get_current_episode_id error: {e}", xbmc.LOGERROR)
        return None


def get_tvshowid_from_title(show_title: str) -> Optional[int]:
    try:
        result = jsonrpc_call(
            "VideoLibrary.GetTVShows", {"properties": ["title"]}
        ) or {}

        for show in result.get("tvshows", []):
            if show.get("label") == show_title:
                tvshowid = show.get("tvshowid")
                log_debug(f"Found tvshowid={tvshowid} for '{show_title}'")
                return tvshowid

        log_debug(f"No tvshowid found for '{show_title}'")
        return None
    except Exception as e:
        log(f"get_tvshowid_from_title error: {e}", xbmc.LOGERROR)
        return None


def get_next_episode_from_library(tvshowid: Any, current_file: Optional[str] = None,
                                    include_watched: bool = True,
                                    current_episode_num: Optional[int] = None,
                                    current_season_num: Optional[int] = None) -> Optional[Dict[str, Any]]:
    try:
        if tvshowid in (None, -1, ""):
            return None

        tvshowid = int(tvshowid)
        if tvshowid <= 0:
            return None

        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {
                "tvshowid": tvshowid,
                "properties": ["title", "plot", "season", "episode", "playcount",
                               "showtitle", "file", "art", "runtime", "firstaired",
                               "dateadded", "lastplayed"],
                "sort": {"method": "episode"},
            }
        )

        if not result or not result.get("episodes"):
            return None

        episodes: List[Dict[str, Any]] = result.get("episodes", [])
        # Kodi 的 "episode" 排序只按集号，跨季时顺序可能交错；
        # 本地按 (season, episode) 重排，确保 next_index 取到的是真正的下一集
        episodes.sort(key=lambda ep: (ep.get("season") or 0, ep.get("episode") or 0))
        current_index = -1

        if current_episode_num is not None and current_season_num is not None:
            current_season_int = int(current_season_num)
            current_episode_int = int(current_episode_num)
            for idx, episode in enumerate(episodes):
                if episode.get("season") == current_season_int and episode.get("episode") == current_episode_int:
                    current_index = idx
                    break

        if current_index == -1 and current_file:
            for idx, episode in enumerate(episodes):
                if episode.get("file") == current_file:
                    current_index = idx
                    break

        if current_index == -1 and current_file:
            current_file_norm = normalize_media_path(current_file)
            for idx, episode in enumerate(episodes):
                ep_file_norm = normalize_media_path(episode.get("file", ""))
                if ep_file_norm and current_file_norm:
                    if ep_file_norm in current_file_norm or current_file_norm in ep_file_norm:
                        current_index = idx
                        break

        if current_index == -1:
            return None

        next_index = current_index + 1
        if next_index >= len(episodes):
            return None

        next_episode = episodes[next_index]

        if not include_watched:
            playcount = next_episode.get("playcount", 0)
            if playcount and playcount > 0:
                return None

        return {
            "episodeid": next_episode.get("episodeid"),
            "tvshowid": next_episode.get("tvshowid"),
            "season": next_episode.get("season"),
            "episode": next_episode.get("episode"),
            "title": next_episode.get("title"),
            "showtitle": next_episode.get("showtitle"),
            "file": next_episode.get("file"),
            "plot": next_episode.get("plot"),
            "playcount": next_episode.get("playcount", 0),
            "art": next_episode.get("art"),
            "runtime": next_episode.get("runtime"),
            "firstaired": next_episode.get("firstaired"),
        }
    except Exception as e:
        log(f"get_next_episode_from_library error: {e}", xbmc.LOGERROR)
        return None


def get_season_episodes(tvshowid: Any, season: Any) -> Optional[Dict[str, Any]]:
    try:
        if tvshowid in (None, -1, "") or season in (None, -1, ""):
            return None

        tvshowid_int = int(tvshowid)
        season_int = int(season)

        if tvshowid_int <= 0 or season_int <= 0:
            return None

        cache_key = f"{tvshowid_int}_{season_int}"
        with _cache_lock:
            season_cache = _caches['season_episodes']
            if cache_key in season_cache:
                cached = season_cache[cache_key]
                if time.time() - cached['time'] < CACHE_TTL_SEASON_EPISODES:
                    season_cache.move_to_end(cache_key)
                    return cached['data']

        result = jsonrpc_call(
            "VideoLibrary.GetEpisodes",
            {
                "tvshowid": tvshowid_int,
                "season": season_int,
                "properties": ["file", "episode", "season", "title"],
                "sort": {"method": "episode", "order": "ascending"},
            },
        ) or {}

        episodes = result.get("episodes") or []
        if not episodes:
            return None

        for itm in episodes:
            itm["tvshowid"] = tvshowid_int
            itm["season"] = season_int
            itm["id"] = itm.get("episodeid")

        season_info = {
            "tvshowid": tvshowid_int,
            "season": season_int,
            "episodes": episodes,
        }

        with _cache_lock:
            season_cache = _caches['season_episodes']
            season_cache[cache_key] = {'data': season_info, 'time': time.time()}
            _evict_season_cache()

        return season_info
    except Exception as e:
        log(f"get_season_episodes error: {e}", xbmc.LOGERROR)
        return None


def play_episode_from_library(episode_info: Dict[str, Any]) -> bool:
    episodeid = episode_info.get("episodeid")
    if not episodeid or episodeid == -1:
        return False
    result = jsonrpc_call("Player.Open", {"item": {"episodeid": episodeid}})
    return result == "OK"


def is_next_episode_available_in_playlist(playlist_id: Optional[int] = None,
                                            playlist_position: Optional[int] = None) -> bool:
    if playlist_id is None or playlist_position is None:
        state = get_active_video_playlist_state()
        if not state:
            return False
        playlist_id = state.get("playlistid", 1)
        playlist_position = state.get("position", 0)

    result = jsonrpc_call(
        "Playlist.GetItems",
        {"playlistid": int(playlist_id or 1), "properties": [],
         "limits": {"start": int(playlist_position or 0) + 1, "end": int(playlist_position or 0) + 2}}
    ) or {}
    return len(result.get("items") or []) > 0


def play_file(file_path: str) -> bool:
    file_path = str(file_path or "")
    if not file_path:
        return False
    result = jsonrpc_call("Player.Open", {"item": {"file": file_path}})
    return result == "OK"


def mark_current_episode_as_watched() -> bool:
    state = get_active_video_playlist_state()
    if not state:
        return False

    episode_id = state.get("episodeid")
    if not episode_id or episode_id == -1:
        # 兜底：按 tvshowid + 季集回查媒体库（目录模式无库记录，直接跳过）
        tvshow_id = state.get("tvshowid")
        season_no = state.get("season")
        episode_no = state.get("episode")
        if tvshow_id in (None, -1) or season_no is None or episode_no is None:
            return False
        episode_id = get_current_episode_id(tvshow_id, season_no, episode_no)
    if not episode_id or episode_id == -1:
        return False

    result = jsonrpc_call(
        "VideoLibrary.SetEpisodeDetails",
        {"episodeid": episode_id, "playcount": 1}
    )
    return result == "OK"


def normalize_media_path(path: str) -> str:
    if not path:
        return ""
    normalized = str(path).split('?', 1)[0].split('#', 1)[0]
    return normalized.replace('\\', '/').rstrip('/')


# Patterns for extracting season/episode info from filenames
# Ordered by priority: most specific patterns first
_FILENAME_PATTERNS: List[re.Pattern] = [
    # S01E01 or S01.E01 or S01_E01 or S01-E01 (most common)
    re.compile(r'[sS](?P<season>\d{1,4})[.\-_]?[eE](?P<episode>\d{1,4})'),
    # 01x01 or 01X01
    re.compile(r'(?P<season>\d{1,4})[xX](?P<episode>\d{1,4})'),
    # S01 EP01
    re.compile(r'S(?P<season>\d{1,4})[ ._-]?EP(?P<episode>\d{1,4})'),
    # Season 1 Episode 1
    re.compile(r'Season[\s._-]?(?P<season>\d{1,4})[\s._-]*Episode[\s._-]?(?P<episode>\d{1,4})'),
    # S1 E1
    re.compile(r'S(?P<season>\d{1,4})[\s._-]*E(?P<episode>\d{1,4})'),
    # 第1季第1集 (Chinese)
    re.compile(r'第(?P<season>\d{1,4})季第(?P<episode>\d{1,4})集'),
    # 01-01 or 01.01 or 01_01 (number-number)
    re.compile(r'(?P<season>\d{1,4})[.\-_](?P<episode>\d{1,4})'),
    # 第1集 (Chinese, episode only)
    re.compile(r'第(?P<episode>\d{1,4})集'),
    # E01 or EP01 (episode only, least specific)
    re.compile(r'[eE][pP]?(?P<episode>\d{1,4})'),
]


def extract_media_info_from_filename(filename: str) -> Tuple[int, int, bool]:
    if not filename:
        return 0, 0, False

    basename = os.path.basename(normalize_media_path(filename))
    basename = os.path.splitext(basename)[0]

    for pattern in _FILENAME_PATTERNS:
        match = pattern.search(basename)
        if match:
            groups = match.groupdict()
            season = int(groups.get("season", 1) or 1)
            episode = int(groups.get("episode", 1) or 1)
            if season > 0 and episode > 0:
                return season, episode, True

    return 0, 0, False


def natural_sort_key(value: str) -> List[Any]:
    text = str(value or "")
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', text)]


def get_parent_media_path(path: str) -> Optional[str]:
    normalized = normalize_media_path(path)
    if not normalized:
        return None
    last_sep = normalized.rfind('/')
    if last_sep <= 0:
        return None
    return normalized[:last_sep]


def _extract_episode_id(item_data: Dict[str, Any]) -> Optional[int]:
    """从 Player.GetItem 返回的 item 中取 episodeid。

    Player.GetItem 的 properties 不支持 "episodeid"（不在 List.Fields.All 中，
    请求会导致 InvalidParams），但 List.Item.Base 的 "id" 对剧集条目就是 episodeid。
    """
    if item_data.get("type") != "episode":
        return None
    item_id = item_data.get("id")
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return None
    return item_id if item_id > 0 else None


def get_active_video_playlist_state() -> Optional[Dict[str, Any]]:
    cached, hit = _get_cached_data('playlist_state')
    if hit:
        return cached

    player_id = _get_video_player_id()
    if player_id is None:
        return None

    # Get item info (only valid item properties)
    item_response = jsonrpc_call(
        "Player.GetItem",
        {
            "playerid": player_id,
            "properties": ["file", "tvshowid", "season", "episode", "showtitle", "title"]
        },
    ) or {}

    item_data = item_response.get("item") or {}

    # Get player properties (playlistid, position are player properties)
    props_response = jsonrpc_call(
        "Player.GetProperties",
        {
            "properties": ["playlistid", "position"],
            "playerid": player_id
        },
    ) or {}

    playlist_id = int(props_response.get("playlistid") or 1)
    current_position = int(props_response.get("position") or 0)

    if playlist_id < 0 or current_position < 0:
        return None

    episode_no = item_data.get("episode")
    try:
        episode_no = int(episode_no) if episode_no is not None else None
    except (TypeError, ValueError):
        episode_no = None

    season_no = item_data.get("season")
    try:
        season_no = int(season_no) if season_no is not None else None
    except (TypeError, ValueError):
        season_no = None

    result = {
        "playerid": player_id,
        "playlistid": playlist_id,
        "position": current_position,
        "file": item_data.get("file") or "",
        "tvshowid": item_data.get("tvshowid"),
        # List.Item.Base 的 id 对剧集条目即 episodeid（无需请求，随响应返回）
        "episodeid": _extract_episode_id(item_data),
        "season": season_no,
        "episode": episode_no,
        "showtitle": item_data.get("showtitle") or "",
        "title": item_data.get("title") or "",
    }

    _set_cached_data('playlist_state', result)
    return result


def get_playlist_items(playlist_id: int) -> List[Dict[str, Any]]:
    result = jsonrpc_call(
        "Playlist.GetItems",
        {"playlistid": playlist_id, "properties": ["tvshowid", "season", "episode", "file"]},
    ) or {}
    items = result.get("items") or []
    for idx, itm in enumerate(items):
        itm["position"] = idx
    return items


def get_season_episode_from_state(source_type: str, state: Any, season: Any) -> Tuple[int, int]:
    try:
        if source_type == 'directory' and isinstance(state, dict):
            current_file = state.get("file", "")
            if current_file:
                season_num, episode_num, parsed = extract_media_info_from_filename(current_file)
                if parsed and season_num > 0 and episode_num > 0:
                    return season_num, episode_num

        season_num = int(season) if (season and int(season) > 0) else 1

        if isinstance(state, dict):
            episode = state.get("episode")
            episode_num = int(episode) if (episode is not None and episode != -1 and int(episode) > 0) else 1
        else:
            episode_num = 1

        return season_num, episode_num
    except (ValueError, TypeError):
        return 1, 1


def get_directory_playlist_files(current_file: str) -> List[str]:
    try:
        if not current_file:
            return []

        parent_dir = get_parent_media_path(current_file)
        if not parent_dir:
            return []

        result = jsonrpc_call(
            "Files.GetDirectory",
            {"directory": parent_dir, "media": "video", "properties": ["file", "title"]},
        ) or {}

        if not isinstance(result, dict):
            return []

        files = result.get("files") or []
        if not isinstance(files, list):
            return []

        playlist_items = []
        for item in files:
            if not isinstance(item, dict):
                continue

            file_path = item.get("file")
            if not file_path:
                continue

            file_type = item.get("filetype")
            if file_type and file_type != "file":
                continue

            sort_title = item.get("title") or item.get("label") or os.path.basename(normalize_media_path(file_path))
            playlist_items.append((sort_title, file_path))

        playlist_items.sort(key=lambda value: (natural_sort_key(value[0]), normalize_media_path(value[1]).casefold()))
        return [file_path for _, file_path in playlist_items]
    except Exception as e:
        log(f"get_directory_playlist_files error: {e}", xbmc.LOGERROR)
        return []


def get_next_file_in_directory(current_file: str) -> Optional[str]:
    try:
        if not current_file:
            return None

        current_norm = normalize_media_path(current_file)
        if not current_norm:
            return None

        files = get_directory_playlist_files(current_file)
        if not files:
            return None

        norms = [normalize_media_path(path) for path in files]
        try:
            idx = norms.index(current_norm)
        except ValueError:
            return None

        next_idx = idx + 1
        if next_idx >= len(files):
            return None

        return files[next_idx]
    except Exception as e:
        log(f"get_next_file_in_directory error: {e}", xbmc.LOGERROR)
        return None


def _get_video_player_id() -> Optional[int]:
    players = jsonrpc_call("Player.GetActivePlayers") or []
    video_player = next((p for p in players if p.get("type") == "video"), None)
    if not video_player:
        return None
    return video_player.get("playerid")


def get_current_tvshow_info() -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    try:
        player_id = _get_video_player_id()
        if player_id is None:
            return None, None, None, None

        # Get item info (only valid item properties)
        result = jsonrpc_call(
            "Player.GetItem",
            {"properties": ["tvshowid", "showtitle", "season", "file"], "playerid": player_id}
        ) or {}

        item = result.get("item") or {}
        tvshow_id = item.get('tvshowid')
        show_title = item.get('showtitle')
        season = item.get('season', -1)
        file_path = item.get('file')

        # Check type via Player.GetProperties
        props = jsonrpc_call(
            "Player.GetProperties",
            {"properties": ["type"], "playerid": player_id}
        ) or {}
        item_type = props.get('type', '')

        if item_type == 'movie' or item_type == 'musicvideo':
            return None, None, None, None

        if tvshow_id and tvshow_id != -1 and show_title:
            return str(tvshow_id), show_title, str(season), 'library'

        if file_path:
            if file_path.startswith("plugin://") or file_path.startswith("pvr://"):
                return None, None, None, None

            basename = os.path.basename(file_path)
            has_episode_pattern = bool(re.search(
                r'[sS]\d{1,4}[._-]?[eE]\d{1,4}|\d{1,4}[xX]\d{1,4}|第\d{1,4}集', basename
            ))

            if not has_episode_pattern:
                return None, None, None, None

            parent_dir = os.path.dirname(file_path)
            dir_name = os.path.basename(parent_dir)

            season_num, episode_num, parsed = extract_media_info_from_filename(file_path)
            if not parsed or season_num <= 0:
                season_num = 1

            return f"directory:{parent_dir}", dir_name, str(season_num), 'directory'
    except Exception as e:
        log(f"get_current_tvshow_info error: {e}", xbmc.LOGERROR)
    return None, None, None, None


class State:
    """Thread-safe shared state using Borg pattern."""
    _shared_data: Dict[str, Any] = {
        'playing_next': False,
        'track': True,
        'pause': False,
    }

    def __init__(self) -> None:
        pass  # Use class-level shared data directly

    @property
    def playing_next(self) -> bool:
        with _state_lock:
            return self._shared_data['playing_next']

    @playing_next.setter
    def playing_next(self, value: bool) -> None:
        with _state_lock:
            self._shared_data['playing_next'] = value
            log_debug(f"playing_next set to {value}")

    @property
    def track(self) -> bool:
        with _state_lock:
            return self._shared_data['track']

    @track.setter
    def track(self, value: bool) -> None:
        with _state_lock:
            self._shared_data['track'] = value

    @property
    def pause(self) -> bool:
        with _state_lock:
            return self._shared_data['pause']

    @pause.setter
    def pause(self, value: bool) -> None:
        with _state_lock:
            self._shared_data['pause'] = value

    def reset(self) -> None:
        with _state_lock:
            self._shared_data.update({
                'playing_next': False,
                'track': True,
                'pause': False
            })


class EpisodePlaylistFixer:
    def __init__(self, playlist_id: int, current_episode: int, season_info: Dict[str, Any]):
        self.playlist_id = playlist_id
        if not isinstance(season_info, dict):
            raise ValueError(f"season_info must be a dict, got: {type(season_info).__name__}")

        tvshowid = season_info.get("tvshowid")
        season_id = season_info.get("season")
        episodes = season_info.get("episodes")

        if tvshowid in (None, -1) or season_id in (None, -1):
            raise ValueError("season_info must have valid tvshowid and season")

        if not episodes or not isinstance(episodes, list):
            raise ValueError("season_info must have a non-empty episodes list")

        try:
            self.current_episode = int(current_episode)
        except (TypeError, ValueError):
            raise ValueError("current_episode must be numeric")

        self.season_info = season_info
        self.playlist_items = get_playlist_items(playlist_id)
        self.current_play = self._find_current_play()

    def _find_current_play(self) -> Optional[Dict[str, Any]]:
        tvshowid = self.season_info.get("tvshowid")
        season_id = self.season_info.get("season")
        for item in self.playlist_items:
            if (isinstance(item.get("episode"), int) and item.get("episode") == self.current_episode
                    and item.get("season") == season_id and item.get("tvshowid") == tvshowid):
                return item
        return None

    def _reindex_items(self) -> None:
        for idx, item in enumerate(self.playlist_items):
            item["position"] = idx

    def _insert(self, position: int, episode_item: Dict[str, Any]) -> bool:
        episode_id = episode_item.get("id")
        episode_no = episode_item.get("episode")
        position = max(0, min(int(position), len(self.playlist_items)))

        result = jsonrpc_call(
            "Playlist.Insert",
            {"playlistid": self.playlist_id, "position": position, "item": {"episodeid": episode_id}},
        )
        if result != "OK":
            return False

        self.playlist_items.insert(position, {
            "position": position,
            "type": "episode",
            "episode": episode_no,
            "id": episode_id,
            "season": episode_item.get("season"),
            "tvshowid": episode_item.get("tvshowid"),
        })
        self._reindex_items()
        xbmc.sleep(PLAYLIST_MUTATION_DELAY_MS)
        return True

    def _remove(self, position: int) -> bool:
        try:
            position = int(position)
        except (TypeError, ValueError):
            return False

        current_pos = self.current_play.get("position") if isinstance(self.current_play, dict) else None
        if isinstance(current_pos, int) and position == current_pos:
            return False

        result = jsonrpc_call("Playlist.Remove", {"playlistid": self.playlist_id, "position": position})
        if result != "OK":
            return False

        if 0 <= position < len(self.playlist_items):
            self.playlist_items.pop(position)
        self._reindex_items()
        xbmc.sleep(PLAYLIST_MUTATION_DELAY_MS)
        return True

    def _remove_incorrect_order_episodes(self) -> int:
        if not self.current_play:
            return 0

        current_tvshowid = self.season_info.get("tvshowid")
        current_season_id = self.season_info.get("season")

        remove_items = []
        for item in self.playlist_items[self.current_play["position"] + 1:]:
            is_same_season = item.get("tvshowid") == current_tvshowid and item.get("season") == current_season_id
            if not is_same_season:
                continue
            episode_no = item.get("episode")
            if isinstance(episode_no, int) and episode_no < self.current_episode:
                remove_items.append(item)
                if len(remove_items) >= MAX_DELETE_LOWER_EPISODES_BELOW:
                    break

        removed = 0
        for item in sorted(remove_items, key=lambda x: x.get("position", -1), reverse=True):
            pos = item.get("position")
            if isinstance(pos, int) and self._remove(pos):
                removed += 1
        return removed

    def _get_insert_position(self, target_episode: int) -> Optional[int]:
        if not isinstance(target_episode, int):
            return None

        current_tvshowid = self.season_info.get("tvshowid")
        current_season_id = self.season_info.get("season")
        last_same_season_position = None

        for item in self.playlist_items:
            is_same_season = item.get("tvshowid") == current_tvshowid and item.get("season") == current_season_id
            if not is_same_season:
                continue
            position = item.get("position")
            last_same_season_position = position
            item_ep = item.get("episode")
            if isinstance(item_ep, int) and item_ep > target_episode:
                return position

        return last_same_season_position + 1 if isinstance(last_same_season_position, int) else len(self.playlist_items)

    def _fill_neighbors_around_current(self) -> Tuple[int, int]:
        if not self.current_play:
            return 0, 0

        season_episodes = self.season_info.get("episodes")
        if not isinstance(season_episodes, list):
            return 0, 0

        current_play_id = self.current_play.get("id")
        current_episode_idx = next((
            idx for idx, item in enumerate(season_episodes)
            if isinstance(item, dict) and item.get("id") == current_play_id
        ), -1)
        if current_episode_idx < 0:
            return 0, 0

        current_tvshowid = self.season_info.get("tvshowid")
        current_season_id = self.season_info.get("season")
        existing_ids = {
            item.get("id") for item in self.playlist_items
            if item.get("tvshowid") == current_tvshowid and item.get("season") == current_season_id
        }

        desired_before = season_episodes[max(0, current_episode_idx - MAX_PLAYLIST_ITEMS_BEFORE):current_episode_idx]
        desired_after = season_episodes[current_episode_idx + 1:current_episode_idx + 1 + MAX_PLAYLIST_ITEMS_AFTER]
        missing_before = [item for item in desired_before if item.get("id") not in existing_ids]
        missing_after = [item for item in desired_after if item.get("id") not in existing_ids]

        insert_before = insert_after = 0
        for episode_item in missing_before:
            insert_pos = self._get_insert_position(episode_item.get("episode"))
            if isinstance(insert_pos, int) and self._insert(insert_pos, episode_item):
                insert_before += 1
                existing_ids.add(episode_item.get("id"))

        for episode_item in missing_after:
            insert_pos = self._get_insert_position(episode_item.get("episode"))
            if isinstance(insert_pos, int) and self._insert(insert_pos, episode_item):
                insert_after += 1
                existing_ids.add(episode_item.get("id"))

        return insert_before, insert_after

    def fix(self) -> Dict[str, Any]:
        if not isinstance(self.current_play, dict):
            return {"removed": 0, "inserted_before": 0, "inserted_after": 0, "playlistid": self.playlist_id}

        try:
            removed_below = self._remove_incorrect_order_episodes()
            inserted_before, inserted_after = self._fill_neighbors_around_current()

            if removed_below or inserted_before or inserted_after:
                log_debug(f"Synced season playlist: removed={removed_below}, before={inserted_before}, after={inserted_after}")

            return {
                "removed": removed_below,
                "inserted_before": inserted_before,
                "inserted_after": inserted_after,
                "playlistid": self.playlist_id,
            }
        except Exception as e:
            log(f"Error fixing playlist: {e}", xbmc.LOGERROR)
            return {"removed": 0, "inserted_before": 0, "inserted_after": 0, "playlistid": self.playlist_id}


def autofill_playlist_for_current_video() -> None:
    global _autofill_thread

    if _autofill_thread and _autofill_thread.is_alive():
        # Signal existing thread to restart countdown
        _autofill_event.set()
        return

    _autofill_event.clear()

    def _autofill_thread_func() -> None:
        try:
            # Wait for delay or early signal
            if not _autofill_event.wait(AUTOFILL_DELAY_SECONDS):
                _do_autofill()
            else:
                # Re-signaled, wait again
                if not _autofill_event.wait(AUTOFILL_DELAY_SECONDS):
                    _do_autofill()
        except Exception as e:
            log(f"Autofill thread error: {e}", xbmc.LOGERROR)
        finally:
            global _autofill_thread
            _autofill_thread = None

    _autofill_thread = threading.Thread(target=_autofill_thread_func)
    _autofill_thread.daemon = True
    _autofill_thread.start()


def _do_autofill() -> None:
    if not SETTINGS.autofill_playlist_on_play:
        return

    state = get_active_video_playlist_state()
    if not state:
        return

    current_file = state.get("file") or ""
    current_file_norm = normalize_media_path(current_file)
    if not current_file_norm:
        return

    tvshow_id = state.get("tvshowid")
    season = state.get("season")
    current_episode = state.get("episode")
    is_scraped_tvshow = tvshow_id not in (None, -1) and season not in (None, -1)

    if is_scraped_tvshow and current_episode is not None and current_episode != -1:
        season_info = get_season_episodes(tvshow_id, season)
        if season_info:
            fixer = EpisodePlaylistFixer(
                playlist_id=state.get("playlistid", 1),
                current_episode=current_episode,
                season_info=season_info
            )
            fixer.fix()
        return

    if current_file_norm.startswith("plugin://") or current_file_norm.startswith("pvr://"):
        return

    target_files = get_directory_playlist_files(current_file)
    target_files = [path for path in target_files if path]
    if len(target_files) <= 1:
        return

    target_norms = [normalize_media_path(path) for path in target_files]
    if current_file_norm not in target_norms:
        return

    _sync_directory_playlist(
        state.get("playlistid", 1), state.get("position", 0),
        current_file_norm, target_norms, target_files
    )


def _sync_directory_playlist(playlist_id: int, current_position: int,
                               current_file_norm: str, target_norms: List[str],
                               target_files: List[str]) -> None:
    playlist_items = get_playlist_items(playlist_id)
    current_playlist_norms = {
        normalize_media_path(item.get("file", "")) for item in playlist_items if item.get("file")
    }
    current_playlist_norms.discard("")

    try:
        current_target_idx = target_norms.index(current_file_norm)
    except ValueError:
        return

    # Get files before current (up to MAX_PLAYLIST_ITEMS_BEFORE)
    before_slice = target_files[:current_target_idx]
    missing_before = [
        path for path, norm in zip(before_slice, target_norms[:current_target_idx])
        if norm not in current_playlist_norms
    ][-MAX_PLAYLIST_ITEMS_BEFORE:]

    # Get files after current (up to MAX_PLAYLIST_ITEMS_AFTER)
    after_slice = target_files[current_target_idx + 1:]
    missing_after = [
        path for path, norm in zip(after_slice, target_norms[current_target_idx + 1:])
        if norm not in current_playlist_norms
    ][:MAX_PLAYLIST_ITEMS_AFTER]

    if not missing_before and not missing_after:
        return

    inserted_before = 0
    for path in missing_before:
        result = jsonrpc_call(
            "Playlist.Insert",
            {"playlistid": playlist_id, "position": current_position + inserted_before, "item": {"file": path}},
        )
        if result == "OK":
            inserted_before += 1
            xbmc.sleep(PLAYLIST_MUTATION_DELAY_MS)

    insert_pos = current_position + inserted_before + 1
    inserted_after = 0
    for path in missing_after:
        result = jsonrpc_call(
            "Playlist.Insert",
            {"playlistid": playlist_id, "position": insert_pos, "item": {"file": path}},
        )
        if result == "OK":
            inserted_after += 1
            insert_pos += 1
            xbmc.sleep(PLAYLIST_MUTATION_DELAY_MS)
