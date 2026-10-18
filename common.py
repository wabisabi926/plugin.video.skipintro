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
