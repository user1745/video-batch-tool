import os
import sys
import subprocess
import threading
import queue
import tempfile
import time
import shutil
import re
import math
import struct
import calendar
import unicodedata
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, colorchooser, font as tkfont

# Enable High DPI Awareness on Windows
if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.m4v', '.ts', '.webm', '.mpg', '.mpeg'}

# Timestamp display formats.
# Each entry: (下拉框显示名, FFmpeg drawtext strftime 格式(冒号已按三重反斜杠转义),
#              起始时间 strptime 格式, 起始时间 strftime 格式)
# 说明: 添加新格式时, 需同时提供 FFmpeg 渲染格式与起始时间的解析/显示格式。
TIMESTAMP_FORMATS = [
    ("YYYY-MM-DD HH:MM:SS",        "%Y-%m-%d %H\\\\\\:%M\\\\\\:%S",     "%Y-%m-%d %H:%M:%S",     "%Y-%m-%d %H:%M:%S"),
    ("YYYY/MM/DD HH:MM:SS",        "%Y/%m/%d %H\\\\\\:%M\\\\\\:%S",     "%Y/%m/%d %H:%M:%S",     "%Y/%m/%d %H:%M:%S"),
    ("DD-MM-YYYY HH:MM:SS",        "%d-%m-%Y %H\\\\\\:%M\\\\\\:%S",     "%d-%m-%Y %H:%M:%S",     "%d-%m-%Y %H:%M:%S"),
    ("YYYY年MM月DD日 HH:MM:SS",     "%Y年%m月%d日 %H\\\\\\:%M\\\\\\:%S", "%Y年%m月%d日 %H:%M:%S", "%Y年%m月%d日 %H:%M:%S"),
    ("YYYY-MM-DD HH:MM",           "%Y-%m-%d %H\\\\\\:%M",              "%Y-%m-%d %H:%M",        "%Y-%m-%d %H:%M"),
    ("HH:MM",                      "%H\\\\\\:%M",                       "%H:%M",                 "%H:%M"),
]

APP_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__
))
DEFAULT_FONT_NAME = "凤凰点阵体VonwaonBitmap16px.ttf"


# ---------------------------------------------------------------------------
# 资源定位: 让"单文件 exe"与"exe + 同目录资源"两种分发方式都能自愈。
#
# 打包成单文件(onefile)时, PyInstaller 把随包资源(ffmpeg/ffprobe/字体)解压到
# sys._MEIPASS 指向的临时目录, 该目录每次启动都不同且启动后可能被清理, 所以只能
# 运行时通过该属性定位; 源码运行/onedir 时它不存在。
# 查找顺序: exe 同目录(便于用户外挂覆盖) > 内置资源目录 > 旧版 ffmpeg/bin 布局。
# ---------------------------------------------------------------------------
def resource_dirs():
    """返回候选资源目录(按优先级排序, 已去重)。"""
    dirs = [APP_DIR]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(meipass)
    for d in list(dirs):
        dirs.append(os.path.join(d, "ffmpeg", "bin"))

    out = []
    seen = set()
    for d in dirs:
        key = os.path.normcase(os.path.normpath(d))
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find_ffmpeg_exe():
    """定位 ffmpeg.exe: 资源目录 > 系统 PATH; 找不到返回空串。"""
    for d in resource_dirs():
        p = os.path.join(d, "ffmpeg.exe")
        if os.path.isfile(p):
            return os.path.normpath(p)
    sys_ffmpeg = shutil.which("ffmpeg")
    return os.path.normpath(sys_ffmpeg) if sys_ffmpeg else ""


def find_ffprobe_exe(ffmpeg_exe=""):
    """定位 ffprobe.exe: 先看 ffmpeg 同目录, 再看资源目录, 最后系统 PATH。"""
    cands = []
    if ffmpeg_exe:
        cands.append(os.path.join(os.path.dirname(ffmpeg_exe), "ffprobe.exe"))
    for d in resource_dirs():
        cands.append(os.path.join(d, "ffprobe.exe"))
    for p in cands:
        if os.path.isfile(p):
            return os.path.normpath(p)
    sys_ffprobe = shutil.which("ffprobe")
    return os.path.normpath(sys_ffprobe) if sys_ffprobe else ""


def find_font_file():
    """定位默认字体: 资源目录下字母序最前的 .ttf > 系统字体; 都没有返回空串。"""
    for d in resource_dirs():
        try:
            ttfs = sorted(
                f for f in os.listdir(d)
                if f.lower().endswith(".ttf") and os.path.isfile(os.path.join(d, f))
            )
        except OSError:
            ttfs = []
        if ttfs:
            return os.path.normpath(os.path.join(d, ttfs[0]))
    for f in [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]:
        if os.path.exists(f):
            return os.path.normpath(f)
    return ""


def describe_source(path):
    """给一个资源路径贴上"它来自哪里"的标签。

    用于日志/自检, 让"到底用的是内置资源还是本机安装"一眼可见:
      内置(随 exe 打包)   → sys._MEIPASS, 即单文件 exe 启动时解压出来的临时目录
      exe 同目录(外挂)    → 用户放在 exe 旁边的文件, 刻意优先覆盖内置版本
      系统字体(兜底)      → C:\\Windows\\Fonts 下的兜底字体
      系统 PATH(本机安装) → 本机自己装的 ffmpeg/ffprobe, 只在前两者都缺失时才用
    """
    if not path:
        return "未找到"

    def norm(p):
        return os.path.normcase(os.path.normpath(p))

    d = norm(os.path.dirname(path))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and d == norm(meipass):
        return "内置(随 exe 打包)"
    if d in (norm(APP_DIR), norm(os.path.join(APP_DIR, "ffmpeg", "bin"))):
        return "exe 同目录(外挂)"
    win_fonts = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")
    if d == norm(win_fonts):
        return "系统字体(兜底)"
    return "系统 PATH(本机安装)"

# "裁剪拉伸"的目标输出分辨率。面板里的字体大小/X偏移/Y偏移都按"源视频像素"
# 定义, 开启裁剪拉伸后要按输出比例换算, 见 _scale_factors()。
CROP_OUT_W = 1920
CROP_OUT_H = 1080

# 四个总开关之间每个间隔的最小宽度(等间隔布局时作为保底)
TOGGLE_GAP_MIN = 24

# 预览刷新限流参数(单位: 毫秒)
#   PREVIEW_THROTTLE_MS —— 两次"启动渲染"之间的最小间隔。拖动/连按箭头时用它
#     限流, 避免连发事件把 CPU 跑满。取"距上次起帧满这么久就允许再起帧"的
#     精确时刻等待(见 _schedule_preview_refresh_internal), 不额外叠加固定延迟,
#     所以只要上一帧渲完了, 这一帧就是立刻起的。
#   PREVIEW_QUEUE_POLL_MS —— UI 线程轮询渲染结果队列的间隔。这个值直接决定
#     "渲完之后多久显示出来"的延迟, 太大(默认 100ms)会在快渲染时明显卡顿。
# 二者组合 = 限流 + 立即补帧: 拖动过程中每一帧都是"上一帧结束就立刻起下一帧",
# 不再等固定防抖窗口, 视觉上就是实时的。
PREVIEW_THROTTLE_MS = 140
PREVIEW_QUEUE_POLL_MS = 16

# 预览图的 PNG 压缩等级: 1 = 最快。预览图每个参数改动都要重编码一次,
# 压得实一点对显示效果毫无帮助, 只会白白多花几十毫秒。仅用于预览, 不影响批处理。
PREVIEW_PNG_COMPRESSION = 1

# 处理中拦截弹窗的冷却时间(秒): 连续拖参数时不在每次改动都弹一次原生提示窗,
# 改为弹一次后在冷却期内静默忽略(提示内容不变, 只是不再刷屏)。
INTERCEPT_COOLDOWN_S = 5.0

# 初始窗口"工作区高 - 本值" = 客户区高度。为标题栏+边框(约 70px)与上下留白留余量;
# 窗口映射后 _fit_to_work_area() 会用实测外框把它精确收紧, 不会把底部挤出屏幕。
WINDOW_V_MARGIN = 110

# 真实星期名(星期一~星期日), 用于把添加文字中的"星期几"替换为真实星期
WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

# 逐字符规则里支持的中文颜色名 → 十六进制
COLOR_NAME_MAP = {
    "黑": "#000000", "黑色": "#000000",
    "白": "#ffffff", "白色": "#ffffff",
    "红": "#ff0000", "红色": "#ff0000",
    "绿": "#00ff00", "绿色": "#00ff00",
    "蓝": "#0000ff", "蓝色": "#0000ff",
    "黄": "#ffff00", "黄色": "#ffff00",
    "灰": "#808080", "灰色": "#808080",
    "橙": "#ff8000", "橙色": "#ff8000",
    "紫": "#8000ff", "紫色": "#8000ff",
}

# 常见 ffmpeg 颜色名 → 十六进制, 仅用于"自动描边"的亮度判断
_COLOR_NAME_HEX = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "lime": "#00ff00", "blue": "#0000ff", "yellow": "#ffff00", "cyan": "#00ffff",
    "aqua": "#00ffff", "magenta": "#ff00ff", "fuchsia": "#ff00ff", "gray": "#808080",
    "grey": "#808080", "silver": "#c0c0c0", "maroon": "#800000", "olive": "#808000",
    "navy": "#000080", "purple": "#800080", "teal": "#008080", "orange": "#ffa500",
}

# 日志面板等宽字体优先级(VSCode 同款在前), 取本机第一个可用者
LOG_MONO_FONTS = ("Cascadia Mono", "Cascadia Code", "JetBrains Mono",
                  "Fira Code", "Consolas", "Courier New")

# 日志正文里的"代码风"高亮: 路径 / 文件名 / URL 用字符串橙, 数字用数字绿。
# 用 lastgroup 区分: path 组 → 路径色, num 组 → 数字色。
LOG_TOKEN_RE = re.compile(
    r"(?P<path>"
    r"[A-Za-z]:[\\/][^\s'\"<>|]+"                       # Windows 绝对路径
    r"|(?<![\w./\\-])[\w\-]+\.(?:mp4|mkv|avi|mov|flv|wmv|m4v|ts|webm|mpg|mpeg"
    r"|aac|mp3|wav|jpg|jpeg|png|bmp|json|csv|txt|log|bat|cmd|ps1|py|exe|ass|srt|vtt"
    r"|ttf|otf|ttc|ini|yaml|yml)\b"                     # 裸文件名
    r"|https?://[^\s'\"<>]+"                            # URL
    r")"
    r"|(?P<num>-?\d+(?:\.\d+)?)"
)


# ---------------------------------------------------------------------------
# 处理结束提示音
# ---------------------------------------------------------------------------
# 成功 = C6-E6-G6 上行三音; 失败 = A4-D4 下行两音(带一小段休止)。
# 波形在内存里现算成 16bit 单声道 WAV 再交给系统播放, 不依赖任何外部音频文件,
# 打包成 exe 后同样可用; 播放失败只退化为系统提示音, 绝不影响主流程。
try:
    import winsound
except Exception:                                   # 非 Windows 平台
    winsound = None

CUE_NOTES = {
    "success": [(1046.5, 0.09), (1318.5, 0.09), (1568.0, 0.17)],
    "failure": [(440.0, 0.16), (0.0, 0.05), (293.7, 0.30)],
}

_CUE_WAV_CACHE = {}          # kind -> WAV 字节串
_CUE_FILE_CACHE = {}          # kind -> 落盘后的 wav 路径
_CUE_FILE_LOCK = threading.Lock()


def _build_cue_wav(notes, sample_rate=22050, volume=0.75):
    """把 [(频率Hz, 时长秒), ...] 合成 16bit 单声道 WAV 字节串。

    频率 <= 0 表示静音。每段首尾各做 8ms 淡入淡出, 避免起止爆音。
    """
    pcm = bytearray()
    fade = max(1, int(sample_rate * 0.008))
    for freq, dur in notes:
        n = max(1, int(sample_rate * dur))
        for i in range(n):
            if freq <= 0:
                wave = 0.0
            else:
                t = i / sample_rate
                # 基波 + 少量二次谐波, 听感更"电子"一点
                wave = 0.85 * math.sin(2.0 * math.pi * freq * t) + \
                       0.15 * math.sin(4.0 * math.pi * freq * t)
            env = min(1.0, i / fade, (n - 1 - i) / fade)
            if env < 0.0:
                env = 0.0
            pcm += struct.pack("<h", int(max(-1.0, min(1.0, wave * env)) * volume * 32767))
    data = bytes(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE", b"fmt ",
        16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", len(data),
    )
    return header + data


def _cue_wav_file(kind):
    """把提示音 WAV 落到临时文件并缓存路径, 只生成一次。

    **为什么不直接用内存播放**: Python 的 winsound 文档明确写了
    "This module does not support playing from a memory image asynchronously",
    实际调用 `PlaySound(data, SND_MEMORY | SND_ASYNC)` 会直接抛
    `RuntimeError: Cannot play asynchronously from memory`。而同步播
    (SND_MEMORY | SND_SYNC) 会阻塞调用线程 0.35~0.5 秒。
    所以这里把波形落到 wav 文件, 用 SND_FILENAME | SND_ASYNC 播放:
    既能异步、又与"系统声音方案"完全无关(直接播 PCM, 不查注册表里的系统音效)。
    """
    with _CUE_FILE_LOCK:
        path = _CUE_FILE_CACHE.get(kind)
        if path and os.path.exists(path):
            return path
        data = _CUE_WAV_CACHE.get(kind)
        if data is None:
            data = _build_cue_wav(CUE_NOTES[kind])
            _CUE_WAV_CACHE[kind] = data
        try:
            fd, path = tempfile.mkstemp(prefix=f"vb_cue_{kind}_", suffix=".wav")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            _CUE_FILE_CACHE[kind] = path
            return path
        except Exception:
            return None


def play_cue(kind):
    """播放提示音。kind: 'success' / 'failure'。任何异常都吞掉, 绝不影响主流程。

    播放顺序(逐级退化):
      ① SND_FILENAME | SND_ASYNC  —— 首选, 异步不卡界面
      ② SND_FILENAME | SND_SYNC   —— 放到后台守护线程里同步播, 同样不卡界面
      ③ MessageBeep(MB_ICON*)     —— 最后兜底(注意: 若系统声音方案为"无声"则静音)
    """
    if winsound is None:
        return
    path = None
    try:
        path = _cue_wav_file(kind)
    except Exception:
        path = None

    if path:
        try:
            winsound.PlaySound(
                path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return
        except Exception:
            pass
        try:
            # 退化: 后台线程里同步播, 不阻塞 UI/处理线程
            threading.Thread(
                target=lambda p=path: winsound.PlaySound(
                    p, winsound.SND_FILENAME | winsound.SND_SYNC | winsound.SND_NODEFAULT
                ),
                daemon=True,
            ).start()
            return
        except Exception:
            pass
    try:
        winsound.MessageBeep(
            winsound.MB_ICONASTERISK if kind == "success" else winsound.MB_ICONHAND
        )
    except Exception:
        pass


class ToggleSwitch(tk.Frame):
    """Toggle 切换开关(自绘轨道 + 滑块), 用于替换 tk.Checkbutton。

    画法: 胶囊形轨道 = 左半圆 + 中间矩形 + 右半圆; 滑块 = 一个圆。
    开启 = 主题蓝轨道 + 滑块靠右; 关闭 = 浅灰轨道 + 滑块靠左。
    尺寸不写死魔数: 轨道宽/高按标签字体的实际像素高度(linespace)推导, 因此
    跟随 DPI 缩放与字体大小一起变。Canvas 宽度 == 轨道绘制宽度, 不额外留白,
    开关与其右侧文字紧贴。

    与 BooleanVar 双向联动: 外部 set() 也会重绘, 不会出现"变量变了但开关没动"。
    """

    TRACK_ON = "#0d6efd"
    TRACK_HOVER_ON = "#0b5ed7"
    TRACK_OFF = "#cbd3da"
    TRACK_HOVER_OFF = "#b6c0ca"
    KNOB = "#ffffff"

    def __init__(self, master, text, variable, command=None,
                 font=("Microsoft YaHei", 9, "bold"), bg="#ffffff"):
        # 字号 9pt bold: 与面板其余标签(SubHeader.TLabel)一致; 四个开关一字排开时
        # 才不会超出面板宽度。轨道宽度按字体实际像素高度推导, 跟随 DPI 缩放。
        f = tkfont.Font(font=font)
        th = max(18, f.metrics("linespace"))
        tw = int(round(th * 1.7))
        knob_d = th - 6
        super().__init__(master, bg=bg)
        self.text = text
        self.variable = variable
        self.command = command
        self._on = bool(variable.get())
        self._hover = False
        self._track_w = tw
        self._track_h = th
        self._knob_d = knob_d

        self.switch = tk.Canvas(
            self, width=tw, height=th,
            highlightthickness=0, bd=0, bg=bg, cursor="hand2",
        )
        self.switch.pack(side=tk.LEFT)
        self.label = tk.Label(self, text=text, bg=bg, font=font,
                              anchor=tk.W, cursor="hand2")
        # padx 尽量小: Canvas 宽度已等于轨道实际绘制宽度(不再多留 knob_d 的
        # 空白尾巴), 所以这里只需一点点视觉间隙, 否则开关与文字之间会显得很空。
        self.label.pack(side=tk.LEFT, padx=(3, 0))

        for w in (self.switch, self.label):
            w.bind("<Button-1>", self.toggle)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self.toggle)

        variable.trace_add("write", self._on_var_change)
        self._draw()

    def _track_color(self):
        if self._on:
            return self.TRACK_HOVER_ON if self._hover else self.TRACK_ON
        return self.TRACK_HOVER_OFF if self._hover else self.TRACK_OFF

    def _draw(self):
        w, h, knob_d = self._track_w, self._track_h, self._knob_d
        color = self._track_color()
        c = self.switch
        c.delete("all")
        # 胶囊轨道: 左右两个半圆 + 中间矩形
        c.create_oval(0, 0, h, h, fill=color, outline="")
        c.create_oval(w - h, 0, w, h, fill=color, outline="")
        c.create_rectangle(h / 2.0, 0, w - h / 2.0, h, fill=color, outline="")
        # 滑块
        kx = w - knob_d if self._on else 0
        ky = (h - knob_d) / 2.0
        c.create_oval(kx, ky, kx + knob_d, ky + knob_d, fill=self.KNOB, outline="")

    def _on_var_change(self, *_args):
        """外部改 BooleanVar 时同步外观(内部 set 不会死循环, 因为值相同则跳过)。"""
        on = bool(self.variable.get())
        if on != self._on:
            self._on = on
            self._draw()

    def _on_enter(self, _event=None):
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None):
        self._hover = False
        self._draw()

    def toggle(self, _event=None):
        self.variable.set(not bool(self.variable.get()))
        if self.command:
            self.command()


class ButtonTooltip:
    """为按钮提供鼠标悬浮说明。"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.window = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event=None):
        if self.window or str(self.widget["state"]) == "disabled":
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
        label = tk.Label(
            self.window, text=self.text, bg="#fff8dc", fg="#202020",
            relief="solid", borderwidth=1, padx=6, pady=3,
            font=("Microsoft YaHei", 9)
        )
        label.pack()
        self.window.update_idletasks()
        x = self.widget.winfo_rootx() + 8
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.geometry(f"+{x}+{y}")

    def hide(self, _event=None):
        if self.window:
            self.window.destroy()
            self.window = None

class VideoBatchToolApp:
    def __init__(self, root):
        self.root = root
        self.root.title("视频动态时间戳批量处理工具（阿董）")
        # 初始小窗: 宽 2500(不超过屏幕), 高 = 工作区高 - WINDOW_V_MARGIN。
        # 用主监视器尺寸计算, 避免多显示器时 winfo_screenwidth 返回虚拟桌面总宽
        # 导致窗口整体向右偏移。
        # 高度从"屏幕高的 3/4"改为贴近工作区(见 WINDOW_V_MARGIN): 3/4 时底部
        # 「处理进度与日志」面板被压得只剩几行, 日志几乎看不到内容。
        # 窗口映射后还会调 _fit_to_work_area() 按真实标题栏/边框精确收紧一次。
        screen_w, _screen_h = self._screen_main_size()
        _work_w, work_h = self._screen_work_area()
        win_w = min(2500, max(1180, screen_w - 40))
        win_h = max(720, work_h - WINDOW_V_MARGIN)
        pos_x = max(0, (screen_w - win_w) // 2)
        pos_y = max(0, (work_h - win_h) // 2)
        self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.root.minsize(1180, 720)

        # Style configuration
        self.style = ttk.Style()
        self.setup_styles()

        # State Variables - Path & Encoding
        self.input_path_var = tk.StringVar()
        self.save_dir_var = tk.StringVar()
        self.ffmpeg_path_var = tk.StringVar()
        self.preset_var = tk.StringVar(value="极速模式 (ultrafast - 强烈推荐)")
        self.status_var = tk.StringVar(value="就绪")
        # 是否执行"裁剪 + 拉伸到 1920x1080"。裁剪四边宽度可自定义(源视频像素),
        # 滤镜串: crop=iw-(左+右):ih-(上+下):左:上。旧版固定裁剪"上 110px",
        # 现默认四边均为 0(不裁剪, 仅拉伸)。
        self.enable_crop_scale_var = tk.BooleanVar(value=True)
        self.crop_top_var = tk.StringVar(value="0")
        self.crop_bottom_var = tk.StringVar(value="0")
        self.crop_left_var = tk.StringVar(value="0")
        self.crop_right_var = tk.StringVar(value="0")

        # State Variables - Timestamp & Controls
        self.enable_timestamp_var = tk.BooleanVar(value=True)
        self.enable_outline_var = tk.BooleanVar(value=True)
        self.time_format_var = tk.StringVar(value=TIMESTAMP_FORMATS[0][0])
        self.position_var = tk.StringVar(value="左上")
        self.font_color_var = tk.StringVar(value="#ffffff")
        # 描边(黑边): 单色 TTF 一个字形只有一种颜色, "白字黑边"只能由渲染器描边实现。
        # 实测 FFmpeg drawtext 完全忽略 COLR 彩色字体的彩色层(白字黑边.ttf 渲染结果与
        # 原字体逐像素相同, 黑边像素 0), 所以必须走 drawtext 自带的 borderw/bordercolor。
        # 宽度按源视频像素标定(开启裁剪拉伸时自动换算), 0 = 关闭描边。
        self.outline_w_var = tk.StringVar(value="2")
        # 描边颜色: "自动" = 按字色取对比色(浅字配黑边 / 深字配白边);
        # 也可直填 #rgb / #rrggbb / #rrggbbaa 或 ffmpeg 认识的颜色名(black/red/...)。
        self.outline_color_var = tk.StringVar(value="自动")
        self.x_offset_var = tk.StringVar(value="50")
        
        self.start_time_var = tk.StringVar(value=datetime.now().strftime(TIMESTAMP_FORMATS[0][3]))
        self.font_size_var = tk.StringVar(value="49")
        self.font_file_var = tk.StringVar()
        self.y_offset_var = tk.StringVar(value="56")
        # 添加文字: 默认显示起始时间对应的真实星期; 用户输入静态文字后不再自动修改。
        self.add_text_var = tk.StringVar()
        self.add_text_pos_var = tk.StringVar(value="日期和时间之间")
        self._auto_weekday_text = ""
        self._update_auto_weekday_text()
        # 逐字符样式规则, 语法: 编号列表=颜色[@字号], 多条用 ; 分隔, reset 清空
        # 示例: 1,7,9-11=#000000  (编号1,7,9,10,11的字符改黑色, 其余保持面板颜色)
        self.char_rule_var = tk.StringVar(value="")
        # 自动反色: 字符所在背景暗 -> 白字; 背景浅 -> 黑字。开启时全局字体颜色与
        # 字符规则里的自定义颜色被忽略, 仅字号规则生效。
        self.auto_invert_var = tk.BooleanVar(value=True)
        
        self.is_processing = False
        self.stop_requested = False
        self.pause_requested = False
        self.cancel_requested = False
        self.resume_event = threading.Event()
        self.resume_event.set()
        self.log_queue = queue.Queue()

        # Preview panel state: background-thread thumbnail rendering with
        # throttle + trailing refresh (see _schedule_preview_refresh_internal).
        # _preview_queue ships rendered PNG paths (or errors) back to
        # the UI thread; _preview_pending coalesces rapid parameter changes so
        # the newest state always gets rendered after the current one finishes.
        self._preview_queue = queue.Queue()
        self._preview_after_id = None
        self._preview_running = False
        self._preview_pending = False
        self._preview_photo = None
        # 上一次"启动渲染"的时刻(time.monotonic, 秒), 用于限流:
        # 距它不足 PREVIEW_THROTTLE_MS 的改动不再立即起帧, 合并成一帧尾随渲染。
        # 初始 0.0 => 第一次改动总是立即渲染。
        self._preview_last_start = 0.0
        self._active_preview_source = None
        # 设置上面那个预览源时的"输入路径"快照: 用户一旦换了输入路径, 这个
        # 预览源就过期, 必须作废, 否则预览会一直停在上一个视频(见 _get_preview_source)
        self._active_preview_input = None
        self._jk_saved_defaults = None
        # 视频尺寸探测缓存: {(normcase路径, mtime, 文件大小): (宽, 高)}。
        # 裁剪拉伸的字号/偏移换算需要"源视频分辨率", 预览每次刷新都会用到,
        # 缓存后只在文件变化时重新探测。
        self._video_size_cache = {}
        # 处理中拦截状态: 用户修改"参数及控制"面板参数时拦截 + 决策;
        # 防止同一时刻多个拦截窗同时弹出
        self._intercept_dialog_active = False
        # 上一次弹拦截窗的时刻(time.monotonic, 秒), 见 _gate_during_processing
        self._intercept_last_shown_at = -1e9
        # 取消/暂停时记录当前文件未完成的子目录, 取消后清理
        self._current_sub_dir = None

        # ASCII temp copy of the user-selected font, prepared right before batch
        # processing starts. Using a pure-ASCII path avoids non-ASCII path and
        # filtergraph metacharacter issues when passing fontfile= to FFmpeg, so
        # the timestamp is ALWAYS rendered with the exact font the user picked.
        self._prepared_font_path = None

        # Build UI
        self.create_widgets()
        self._install_button_tooltips()
        # Auto detect FFmpeg & Font
        self.auto_detect_ffmpeg()
        self.auto_detect_font()
        # 启动即写明资源来源(内置 / exe 同目录 / 本机 PATH), 用来确认单文件 exe
        # 到底在用内置资源还是本机已安装的环境。队列随后由日志线程消费输出。
        self._log_environment_sources()

        # Start periodic log & preview consumers
        self.root.after(100, self.process_log_queue)
        self.root.after(100, self.process_preview_queue)

        # 窗口映射后重新校准居中, 并把预览面板初始宽度设为窗口宽度的一半
        self.root.after(80, self._post_init_layout)

    def setup_styles(self):
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Color Palette
        bg_color = "#f4f6f9"
        card_bg = "#ffffff"
        primary_color = "#0d6efd"
        primary_active = "#0b5ed7"
        text_color = "#212529"

        self.root.configure(bg=bg_color)

        self.style.configure(".", background=bg_color, foreground=text_color, font=("Microsoft YaHei", 9))
        self.style.configure("Card.TFrame", background=card_bg, relief="flat", borderwidth=1)
        self.style.configure("InnerCard.TFrame", background=card_bg)

        # Section Header
        self.style.configure("Header.TLabel", font=("Microsoft YaHei", 10, "bold"), foreground="#0d6efd", background=card_bg)
        self.style.configure("SubHeader.TLabel", font=("Microsoft YaHei", 9, "bold"), background=card_bg, foreground="#495057")
        self.style.configure("Status.TLabel", font=("Microsoft YaHei", 9), background=card_bg, foreground="#6c757d")

        # Custom Buttons
        self.style.configure("Primary.TButton", font=("Microsoft YaHei", 9, "bold"), background=primary_color, foreground="#ffffff", borderwidth=0, padding=(16, 8))
        self.style.map("Primary.TButton", background=[("active", primary_active), ("disabled", "#9ec5fe")])

        self.style.configure("Stop.TButton", font=("Microsoft YaHei", 9, "bold"), background="#dc3545", foreground="#ffffff", borderwidth=0, padding=(16, 8))
        self.style.map("Stop.TButton", background=[("active", "#bb2d3b"), ("disabled", "#f8d7da")])

        # Customizing Combobox and Spinbox arrow sizes & padding (Significantly larger & wider)
        self.style.configure("TCombobox", font=("Microsoft YaHei", 9), arrowsize=26, padding=(8, 6), arrowcolor=primary_color)
        self.style.map("TCombobox",
                       fieldbackground=[("readonly", "#ffffff")],
                       selectbackground=[("readonly", primary_color)],
                       selectforeground=[("readonly", "#ffffff")])

        self.style.configure("TSpinbox", font=("Microsoft YaHei", 9), arrowsize=24, padding=(6, 5), arrowcolor=primary_color)

        # Checkbutton (Enlarged)
        self.style.configure("TCheckbutton", background=card_bg, font=("Microsoft YaHei", 10, "bold"), indicatorsize=26, padding=(8, 6))

        # Progressbar
        self.style.configure("TProgressbar", thickness=12, troughcolor="#e9ecef", background=primary_color)

        # Preview Panel inner black frame (matches the log box background #1e1e1e)
        self.style.configure("PreviewCard.TFrame", background="#1e1e1e")

        # 提示弹窗不再自绘: 全部走 messagebox.showwarning 的系统原生外观,
        # 因此这里刻意不定义任何 Dialog.* 样式, 避免把主窗口外观套到消息框上。

        # 日志面板等宽字体(VSCode 系列优先)
        self.log_font_family = self._pick_mono_font()

    def _pick_mono_font(self):
        """挑一个本机可用的等宽字体用于日志面板, 优先 VSCode 同款的
        Cascadia 系列, 再退到 Consolas。"""
        try:
            fams = {str(f).lower() for f in tkfont.families(self.root)}
        except Exception:
            return "Consolas"
        for name in LOG_MONO_FONTS:
            if name.lower() in fams:
                return name
        return "Consolas"

    def auto_detect_ffmpeg(self):
        """自动定位 ffmpeg: exe 同目录/内置资源(单文件打包) > 系统 PATH。

        界面上的 FFmpeg 路径输入框已删除(资源内置后它只会显示一个每次都变的临时
        解压目录), 这里是唯一入口; 想换 ffmpeg 版本, 把新的 ffmpeg.exe 放到程序同
        目录即可覆盖内置版本。
        """
        exe = find_ffmpeg_exe()
        if exe:
            self.ffmpeg_path_var.set(exe)

    def _format_entry(self, display_name):
        """返回时间戳显示名对应的 (显示名, FFmpeg格式, strptime格式, strftime格式)。"""
        for entry in TIMESTAMP_FORMATS:
            if entry[0] == display_name:
                return entry
        return TIMESTAMP_FORMATS[0]  # 兜底: YYYY-MM-DD HH:MM:SS

    def on_time_format_changed(self, event=None):
        """时间戳格式改变: 不直接覆盖"起始时间", 仅尝试按旧格式重新格式化。

        起始时间只在应用打开时读取一次本地电脑时间, 此后任何操作都不应被
        自动修改 (切换时间戳格式/拖动滑块等)。若当前起始时间能按某个
        已有格式解析, 则按新格式重格式化, 让同一时刻在新格式下正确显示;
        若解析失败 (用户改过/手动输入无效字符串), 则保留原值不动。"""
        new_entry = self._format_entry(self.time_format_var.get())
        cur = self.start_time_var.get().strip()
        for old in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(cur, old[2])
            except Exception:
                continue
            try:
                self.start_time_var.set(parsed.strftime(new_entry[3]))
            except Exception:
                pass
            break
        self._update_auto_weekday_text()
        self.schedule_preview_refresh()

    def on_start_time_changed(self, event=None):
        """起始时间被用户修改后, 空的添加文字恢复为真实星期示例。"""
        self._update_auto_weekday_text()
        self.schedule_preview_refresh()

    def on_add_text_changed(self, event=None):
        """用户编辑添加文字后, 非空静态文字不再随起始时间自动变化。"""
        current = self.add_text_var.get().strip()
        if current != self._auto_weekday_text:
            self._auto_weekday_text = "" if not current else None
        self.schedule_preview_refresh()

    def _update_auto_weekday_text(self):
        """在添加文字为空或仍为自动示例时更新真实星期。"""
        current = self.add_text_var.get().strip()
        if current and self._auto_weekday_text not in (current, ""):
            return
        try:
            entry = self._format_entry(self.time_format_var.get())
            start_dt = datetime.strptime(self.start_time_var.get().strip(), entry[2])
        except Exception:
            start_dt = datetime.now()
        weekday_text = WEEKDAY_CN[start_dt.weekday()]
        self.add_text_var.set(weekday_text)
        self._auto_weekday_text = weekday_text

    def auto_detect_font(self):
        """默认字体: 资源目录下任一 .ttf > 系统 msyh.ttc > simhei > arial。

        资源目录包括 exe 同目录与单文件打包的解压目录(sys._MEIPASS), 见
        find_font_file()。这样"单文件 exe"双击即可用, 无需手动选字体;
        用户想换字体, 把 ttf 放到 exe 同目录即可覆盖内置字体。"""
        font = find_font_file()
        if font:
            self.font_file_var.set(font)

    def _log_environment_sources(self):
        """启动时写明实际使用的 ffmpeg/字体来自哪里, 并落一份快照文件。

        单文件 exe 的资源是内置的, 但 exe 同目录若放了 ffmpeg.exe / *.ttf 会优先
        覆盖内置版本(刻意留的替换口子), 本机 PATH 上的 ffmpeg 只在前两者都缺失时
        才会启用。把来源写进日志和 %TEMP%\\video_batch_tool_last_run.txt, 可避免
        "到底用了内置还是本机装的"这种疑问。
        """
        try:
            ffmpeg = self.ffmpeg_path_var.get().strip()
            ffmpeg_src = describe_source(ffmpeg)
            ffprobe = find_ffprobe_exe(ffmpeg)
            font = self.font_file_var.get().strip()
            font_src = describe_source(font)
            local_ffmpeg = shutil.which("ffmpeg")
            local_ffprobe = shutil.which("ffprobe")

            self.log(f"  └─ FFmpeg: {ffmpeg_src}", "INFO")
            if ffmpeg_src != "系统 PATH(本机安装)" and local_ffmpeg:
                self.log(
                    f"  └─ 本机 PATH 上另有 {os.path.normpath(local_ffmpeg)}，未被使用",
                    "INFO",
                )
            self.log(f"  └─ 字体: {font_src}", "INFO")

            lines = [
                "=== 本次运行实际使用的资源(程序启动时自动写出) ===",
                f"时间          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"frozen        : {getattr(sys, 'frozen', False)}",
                f"exe 目录      : {APP_DIR}",
                f"内置资源目录  : {getattr(sys, '_MEIPASS', '(无, 非单文件打包)')}",
                f"ffmpeg        : [{ffmpeg_src}] {ffmpeg or '未找到'}",
                f"ffprobe       : [{describe_source(ffprobe)}] {ffprobe or '未找到'}",
                f"字体          : [{font_src}] {font or '未找到'}",
                "--- 本机已安装环境(仅作对比, 内置/同目录资源存在时不会被使用) ---",
                f"本机 PATH ffmpeg : {os.path.normpath(local_ffmpeg) if local_ffmpeg else '无'}",
                f"本机 PATH ffprobe: {os.path.normpath(local_ffprobe) if local_ffprobe else '无'}",
            ]
            with open(os.path.join(tempfile.gettempdir(), "video_batch_tool_last_run.txt"),
                      "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except Exception:
            pass

    def choose_color(self):
        color = colorchooser.askcolor(initialcolor=self.font_color_var.get(), title="选择字体颜色")
        if color[1]:
            self.font_color_var.set(color[1])
            self._refresh_color_swatches()
            self.schedule_preview_refresh()

    def choose_outline_color(self):
        """描边颜色取色器: 初始色 = 当前生效色("自动"时取算出来的对比色)。
        描边总开关关闭时控件已置灰, 这里直接忽略点击, 保证"无法修改"。"""
        if not self.enable_outline_var.get():
            return
        initial = self._resolve_outline_color()
        color = colorchooser.askcolor(initialcolor=initial, title="选择描边颜色")
        if color[1]:
            self.outline_color_var.set(color[1])
            self._refresh_color_swatches()
            self.schedule_preview_refresh()

    def on_color_changed(self):
        """两个颜色输入框共用的输入回调: 刷新色块 + 重绘预览(行为完全一致)。"""
        self._refresh_color_swatches()
        self.schedule_preview_refresh()

    def _refresh_color_swatches(self):
        """刷新两个颜色色块。描边色块显示"实际会被用到的颜色":
        选「自动」或颜色名时显示解析后的色值, 方便一眼确认。
        描边总开关关闭时描边色块显示置灰色, 与置灰的输入框保持一致。"""
        try:
            self.color_preview.configure(bg=self.font_color_var.get().strip() or "#ffffff")
        except Exception:
            pass
        try:
            if self.enable_outline_var.get():
                self.outline_color_preview.configure(bg=self._resolve_outline_color())
            else:
                self.outline_color_preview.configure(bg="#dee2e6")
        except Exception:
            pass

    def _build_color_picker(self, parent, var, swatch_bg, picker_cmd):
        """构建一个颜色选择控件: 色块(点击开取色器) + 可输入输入框。

        「描边颜色」用的就是「字体颜色」这一套控件「复制粘贴」出来的同一结构:
        控件类型(TFrame + Label + ttk.Entry)、pack 顺序与内边距、事件绑定、
        色块尺寸/边框全部一致, 两个调用点除了摆放的行列不同之外没有差别。
        返回 (容器frame, 色块Label, 输入框Entry)。
        """
        box = ttk.Frame(parent, style="InnerCard.TFrame")

        swatch = tk.Label(box, bg=swatch_bg, width=3, relief="solid", bd=1)
        swatch.pack(side=tk.LEFT, padx=(0, 6), fill=tk.Y)
        swatch.bind("<Button-1>", lambda e: picker_cmd())

        entry = ttk.Entry(box, textvariable=var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<KeyRelease>", lambda e: self.on_color_changed())
        return box, swatch, entry

    def create_widgets(self):
        # Main Outer Container
        main_container = ttk.Frame(self.root, padding=12)
        main_container.pack(fill=tk.BOTH, expand=True)

        # 横向内容区: 左列三面板 + 右侧预览面板, 中间分隔条可拖动调整预览宽度
        content = ttk.Frame(main_container)
        content.pack(fill=tk.BOTH, expand=True)

        paned = ttk.Panedwindow(content, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self._paned = paned

        left_col = ttk.Frame(content)
        paned.add(left_col, weight=1)

        # ---------------- 📁 Section 1: Path & Encoding Settings Card ----------------
        path_card = ttk.Frame(left_col, style="Card.TFrame", padding=12)
        path_card.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        # Header Title
        header_frame = ttk.Frame(path_card, style="InnerCard.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header_frame, text="📁  路径与编码设置", style="Header.TLabel").pack(side=tk.LEFT)

        # Responsive Grid Layout inside Path Card
        grid_frame = ttk.Frame(path_card, style="InnerCard.TFrame")
        grid_frame.pack(fill=tk.X, expand=True)
        grid_frame.columnconfigure(1, weight=1)

        # Row 0: Input Path Entry & Buttons
        ttk.Label(grid_frame, text="输入路径:", style="SubHeader.TLabel").grid(row=0, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        input_entry = ttk.Entry(grid_frame, textvariable=self.input_path_var)
        input_entry.grid(row=0, column=1, sticky=tk.EW, pady=3, padx=(0, 6))
        input_entry.bind("<KeyRelease>", lambda e: self._on_input_path_edited())
        
        input_btn_box = ttk.Frame(grid_frame, style="InnerCard.TFrame")
        input_btn_box.grid(row=0, column=2, sticky=tk.EW, pady=3)
        input_btn_box.columnconfigure(0, weight=1)
        input_btn_box.columnconfigure(1, weight=1)
        ttk.Button(input_btn_box, text="选择文件", style="Primary.TButton", command=self.browse_input_file).grid(row=0, column=0, sticky=tk.EW, padx=(0, 2))
        ttk.Button(input_btn_box, text="选择文件夹", style="Primary.TButton", command=self.browse_input_dir).grid(row=0, column=1, sticky=tk.EW, padx=(2, 0))

        # Row 1: Save Directory Entry & Browse Button
        ttk.Label(grid_frame, text="保存目录:", style="SubHeader.TLabel").grid(row=1, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        save_entry = ttk.Entry(grid_frame, textvariable=self.save_dir_var)
        save_entry.grid(row=1, column=1, sticky=tk.EW, pady=3, padx=(0, 6))

        ttk.Button(grid_frame, text="浏览", style="Primary.TButton", command=self.browse_save_dir).grid(row=1, column=2, sticky=tk.EW, pady=3)

        # Row 2: Encoding Speed Combo
        # FFmpeg 路径行已删除: 单文件打包后 ffmpeg/ffprobe/字体全部内置, 程序启动时
        # 自动定位(见 resource_dirs()/find_ffmpeg_exe())。ffmpeg_path_var 因此变成了
        # 纯内部变量, 不再有输入框绑定; 想换版本就把新的 ffmpeg.exe 放到程序同目录
        # (同目录优先级高于内置), 或运行 --selftest 排查内置资源。
        ttk.Label(grid_frame, text="编码速度:", style="SubHeader.TLabel").grid(row=2, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        preset_combobox = ttk.Combobox(
            grid_frame,
            textvariable=self.preset_var,
            values=[
                "极速模式 (ultrafast - 强烈推荐)",
                "快速模式 (fast - 速度与体积兼顾)",
                "标准模式 (medium - 高压缩率)",
                "GPU 显卡硬件加速 (NVIDIA / Intel / AMD)"
            ],
            state="readonly"
        )
        preset_combobox.grid(row=2, column=1, columnspan=2, sticky=tk.EW, pady=3)

        # ---------------- 📑 Section 2: Timestamp Parameters & Controls Card ----------------
        param_card = ttk.Frame(left_col, style="Card.TFrame", padding=12)
        param_card.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        # Title & Checkbox
        param_header = ttk.Frame(param_card, style="InnerCard.TFrame")
        param_header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(param_header, text="📑  参数及控制", style="Header.TLabel").pack(side=tk.LEFT)

        # 2-Column Grid inside Param Card
        p_grid = ttk.Frame(param_card, style="InnerCard.TFrame")
        p_grid.pack(fill=tk.X, expand=True)
        p_grid.columnconfigure(1, weight=1)
        p_grid.columnconfigure(3, weight=1)

        # Left Column: Row 0 - Timestamp Format
        ttk.Label(p_grid, text="时间戳格式:", style="SubHeader.TLabel").grid(row=0, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        time_fmt_combo = ttk.Combobox(
            p_grid,
            textvariable=self.time_format_var,
            values=[entry[0] for entry in TIMESTAMP_FORMATS],
            state="readonly"
        )
        time_fmt_combo.grid(row=0, column=1, sticky=tk.EW, pady=3, padx=(0, 12))
        # When the timestamp format changes, refresh the "起始时间" field so it
        # always displays the start time in the newly selected format.
        time_fmt_combo.bind("<<ComboboxSelected>>", self.on_time_format_changed)

        # Right Column: Row 0 - Start Time
        ttk.Label(p_grid, text="起始时间:", style="SubHeader.TLabel").grid(row=0, column=2, sticky=tk.W, pady=3, padx=(0, 6))
        start_time_entry = ttk.Entry(p_grid, textvariable=self.start_time_var)
        start_time_entry.grid(row=0, column=3, sticky=tk.EW, pady=3)
        # 起始时间任何写入都要刷新预览: <KeyRelease> 覆盖普通键入,
        # <<Paste>> 覆盖 Ctrl+V / 右键粘贴 / 编程粘贴 (后者 <KeyRelease> 不保证触发)。
        start_time_entry.bind("<KeyRelease>", self.on_start_time_changed)
        start_time_entry.bind("<<Paste>>", self.on_start_time_changed)

        # Left Column: Row 1 - Display Position
        ttk.Label(p_grid, text="显示位置:", style="SubHeader.TLabel").grid(row=1, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        pos_combo = ttk.Combobox(
            p_grid,
            textvariable=self.position_var,
            values=["正中", "左上", "右上", "左下", "右下", "中上", "中下"],
            state="readonly"
        )
        pos_combo.grid(row=1, column=1, sticky=tk.EW, pady=3, padx=(0, 12))
        pos_combo.bind("<<ComboboxSelected>>", lambda e: self.schedule_preview_refresh())

        # Right Column: Row 1 - Font Size (px, 可直接输入或上下箭头调整)
        ttk.Label(p_grid, text="字体大小:", style="SubHeader.TLabel").grid(row=1, column=2, sticky=tk.W, pady=3, padx=(0, 6))
        font_size_spin = ttk.Spinbox(p_grid, from_=10, to=300, textvariable=self.font_size_var, command=self.schedule_preview_refresh)
        font_size_spin.grid(row=1, column=3, sticky=tk.EW, pady=3)
        font_size_spin.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())

        # Left Column: Row 2 - Font Color (本控件是标准件, 见 _build_color_picker)
        ttk.Label(p_grid, text="字体颜色:", style="SubHeader.TLabel").grid(row=2, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        color_box, self.color_preview, self.font_color_entry = self._build_color_picker(
            p_grid, self.font_color_var, self.font_color_var.get(), self.choose_color)
        color_box.grid(row=2, column=1, sticky=tk.EW, pady=3, padx=(0, 12))

        # Right Column: Row 2 - Font File
        ttk.Label(p_grid, text="字体文件:", style="SubHeader.TLabel").grid(row=2, column=2, sticky=tk.W, pady=3, padx=(0, 6))
        font_file_box = ttk.Frame(p_grid, style="InnerCard.TFrame")
        font_file_box.grid(row=2, column=3, sticky=tk.EW, pady=3)
        font_file_box.columnconfigure(0, weight=1)

        font_file_entry = ttk.Entry(font_file_box, textvariable=self.font_file_var)
        font_file_entry.grid(row=0, column=0, sticky=tk.EW, padx=(0, 4))
        font_file_entry.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())
        ttk.Button(font_file_box, text="浏览", style="Primary.TButton", command=self.browse_font_file).grid(row=0, column=1, sticky=tk.E)

        # Left Column: Row 3 - X Offset (px)
        ttk.Label(p_grid, text="X偏移(px):", style="SubHeader.TLabel").grid(row=3, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        x_offset_spin = ttk.Spinbox(p_grid, from_=-1000, to=1000, textvariable=self.x_offset_var, command=self.schedule_preview_refresh)
        x_offset_spin.grid(row=3, column=1, sticky=tk.EW, pady=3, padx=(0, 12))
        x_offset_spin.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())

        # Right Column: Row 3 - Y Offset (px)
        ttk.Label(p_grid, text="Y偏移(px):", style="SubHeader.TLabel").grid(row=3, column=2, sticky=tk.W, pady=3, padx=(0, 6))
        y_offset_spin = ttk.Spinbox(p_grid, from_=-1000, to=1000, textvariable=self.y_offset_var, command=self.schedule_preview_refresh)
        y_offset_spin.grid(row=3, column=3, sticky=tk.EW, pady=3)
        y_offset_spin.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())

        # Left Column: Row 4 - Add Text (custom text appended/between the timestamp)
        ttk.Label(p_grid, text="添加文字:", style="SubHeader.TLabel").grid(row=4, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        add_text_entry = ttk.Entry(p_grid, textvariable=self.add_text_var)
        add_text_entry.grid(row=4, column=1, sticky=tk.EW, pady=3, padx=(0, 12))
        add_text_entry.bind("<KeyRelease>", self.on_add_text_changed)

        # Right Column: Row 4 - Add Text Position
        ttk.Label(p_grid, text="文字位置:", style="SubHeader.TLabel").grid(row=4, column=2, sticky=tk.W, pady=3, padx=(0, 6))
        add_pos_combo = ttk.Combobox(
            p_grid,
            textvariable=self.add_text_pos_var,
            values=["时间戳开头", "日期和时间之间", "时间戳末尾"],
            state="readonly"
        )
        add_pos_combo.grid(row=4, column=3, sticky=tk.EW, pady=3)
        add_pos_combo.bind("<<ComboboxSelected>>", lambda e: self.schedule_preview_refresh())

        # Left Column: Row 5 - 描边宽度(按源视频像素标定, 开启裁剪拉伸时自动换算)
        ttk.Label(p_grid, text="描边(px):", style="SubHeader.TLabel").grid(row=5, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        outline_spin = ttk.Spinbox(p_grid, from_=0, to=20, textvariable=self.outline_w_var, command=self.schedule_preview_refresh)
        self.outline_spin = outline_spin
        outline_spin.grid(row=5, column=1, sticky=tk.EW, pady=3, padx=(0, 12))
        outline_spin.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())
        ButtonTooltip(
            outline_spin,
            "描边宽度(源视频像素标定, 开启裁剪拉伸时自动换算), 0=不描边。\n"
            "点阵字体换算: 字号49时 1 个点阵格 ≈ 3px,\n"
            "想复刻原监控那种'半格黑边'填 1~2。"
        )

        # Right Column: Row 5 - 描边颜色(与"字体颜色"是同一套控件, 复制粘贴不差异化)
        # 摆放上的差别只有行列与"左列控件右侧留 12px 列间距"这一条面板约定:
        # 第 3 列已是最后一列, 不需要右留白, 加了反而和同列其它控件右边缘对不齐。
        ttk.Label(p_grid, text="描边颜色:", style="SubHeader.TLabel").grid(row=5, column=2, sticky=tk.W, pady=3, padx=(0, 6))
        outline_color_box, self.outline_color_preview, self.outline_color_entry = self._build_color_picker(
            p_grid, self.outline_color_var, "#000000", self.choose_outline_color)
        outline_color_box.grid(row=5, column=3, sticky=tk.EW, pady=3)
        # 初始化两个色块(描边"自动"时要按当前字色解析出实际色值)
        self.root.after(0, self._refresh_color_swatches)

        # 左列 Row 6 / 右列 Row 6: 自定义裁剪宽度(上、下), 单位=源视频像素
        ttk.Label(p_grid, text="裁剪上(px):", style="SubHeader.TLabel").grid(row=6, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        self.crop_top_spin = ttk.Spinbox(p_grid, from_=0, to=4000, textvariable=self.crop_top_var, command=self.schedule_preview_refresh)
        self.crop_top_spin.grid(row=6, column=1, sticky=tk.EW, pady=3, padx=(0, 12))
        self.crop_top_spin.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())

        ttk.Label(p_grid, text="裁剪下(px):", style="SubHeader.TLabel").grid(row=6, column=2, sticky=tk.W, pady=3, padx=(0, 6))
        self.crop_bottom_spin = ttk.Spinbox(p_grid, from_=0, to=4000, textvariable=self.crop_bottom_var, command=self.schedule_preview_refresh)
        self.crop_bottom_spin.grid(row=6, column=3, sticky=tk.EW, pady=3)
        self.crop_bottom_spin.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())

        # 左列 Row 7 / 右列 Row 7: 自定义裁剪宽度(左、右), 单位=源视频像素
        ttk.Label(p_grid, text="裁剪左(px):", style="SubHeader.TLabel").grid(row=7, column=0, sticky=tk.W, pady=3, padx=(0, 6))
        self.crop_left_spin = ttk.Spinbox(p_grid, from_=0, to=4000, textvariable=self.crop_left_var, command=self.schedule_preview_refresh)
        self.crop_left_spin.grid(row=7, column=1, sticky=tk.EW, pady=3, padx=(0, 12))
        self.crop_left_spin.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())

        ttk.Label(p_grid, text="裁剪右(px):", style="SubHeader.TLabel").grid(row=7, column=2, sticky=tk.W, pady=3, padx=(0, 6))
        self.crop_right_spin = ttk.Spinbox(p_grid, from_=0, to=4000, textvariable=self.crop_right_var, command=self.schedule_preview_refresh)
        self.crop_right_spin.grid(row=7, column=3, sticky=tk.EW, pady=3)
        self.crop_right_spin.bind("<KeyRelease>", lambda e: self.schedule_preview_refresh())

        self._crop_spins = (
            self.crop_top_spin, self.crop_bottom_spin,
            self.crop_left_spin, self.crop_right_spin,
        )
        for spin, tip in (
            (self.crop_top_spin, "上边框裁掉的像素数(源视频像素, 在拉伸之前裁剪)。\n默认 0 = 不裁上方。"),
            (self.crop_bottom_spin, "下边框裁掉的像素数(源视频像素)。"),
            (self.crop_left_spin, "左边框裁掉的像素数(源视频像素)。"),
            (self.crop_right_spin, "右边框裁掉的像素数(源视频像素)。\n四边全填 0 = 不裁剪, 只做拉伸。"),
        ):
            ButtonTooltip(spin, tip)

        # Row 8: 四个总开关排在"参数及控制"面板下方, 两端对齐 + 等间隔
        toggle_row = ttk.Frame(param_card, style="InnerCard.TFrame")
        toggle_row.pack(fill=tk.X, pady=(8, 0))
        self._toggle_row = toggle_row
        self._toggle_widgets = (
            ToggleSwitch(toggle_row, text="启用裁剪拉伸",
                         variable=self.enable_crop_scale_var,
                         command=self.on_crop_toggle_changed),
            ToggleSwitch(toggle_row, text="启用动态时间戳",
                         variable=self.enable_timestamp_var,
                         command=self._on_toggle_click),
            ToggleSwitch(toggle_row, text="启用字体自动反色",
                         variable=self.auto_invert_var,
                         command=self._on_toggle_click),
            ToggleSwitch(toggle_row, text="启用字体描边",
                         variable=self.enable_outline_var,
                         command=self.on_outline_toggle_changed),
        )
        self.crop_toggle_btn = self._toggle_widgets[0]
        self.timestamp_toggle_btn = self._toggle_widgets[1]
        self.invert_toggle_btn = self._toggle_widgets[2]
        self.outline_toggle_btn = self._toggle_widgets[3]
        # None = 尚未排布, 首次 <Configure> 时按可用宽度决定单行/双行
        self._toggle_single_row = None
        toggle_row.bind("<Configure>", self._on_toggle_row_configure)

        # 按当前开关状态初始化四个裁剪输入框的可用
        self._sync_crop_widgets()
        # 按当前开关状态初始化描边宽度/描边颜色输入的可用
        self._sync_outline_widgets()

        # ---------------- ▶️ Action Bar: Start / Stop (between Param & Progress) ----------------
        action_bar = ttk.Frame(left_col, padding=(0, 2, 0, 0))
        action_bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))
        # 左右对称占位列使按钮组水平居中
        action_bar.columnconfigure(0, weight=1)
        action_bar.columnconfigure(4, weight=1)

        self.clear_btn = ttk.Button(action_bar, text="⌫  清空", style="Primary.TButton", command=self.clear_workspace)
        self.clear_btn.grid(row=0, column=1, sticky=tk.E)

        self.cancel_btn = ttk.Button(action_bar, text="✖  取消", style="Stop.TButton", command=self._on_cancel_btn_clicked, state=tk.DISABLED)
        self.cancel_btn.grid(row=0, column=2, sticky=tk.E, padx=(6, 0))

        self.stop_btn = ttk.Button(action_bar, text="⏸  暂停", style="Stop.TButton", command=self.stop_processing, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=3, sticky=tk.E, padx=(6, 0))

        self.start_btn = ttk.Button(action_bar, text="▶  开始", style="Primary.TButton", command=self.start_processing)
        self.start_btn.grid(row=0, column=4, sticky=tk.W, padx=(6, 0))

        # ---------------- ⚙️ Section 3: Progress & Log Card (Middle, Flexible Height) ----------------
        progress_card = ttk.Frame(left_col, style="Card.TFrame", padding=12)
        progress_card.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Header Title & Status Badge
        prog_header = ttk.Frame(progress_card, style="InnerCard.TFrame")
        prog_header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(prog_header, text="⚙️  处理进度与日志", style="Header.TLabel").pack(side=tk.LEFT)
        self.status_label = ttk.Label(prog_header, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.pack(side=tk.RIGHT)

        # Progress bar
        self.progressbar = ttk.Progressbar(progress_card, mode="determinate", maximum=100)
        self.progressbar.pack(fill=tk.X, pady=(0, 8))

        # Log Text Box Container
        log_frame = ttk.Frame(progress_card, style="InnerCard.TFrame")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            font=(self.log_font_family, 10),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#aeafad",
            selectbackground="#264f78",
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=1,
            padx=8,
            pady=6,
            height=8
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        # 终端质感: 块状光标(Tk 8.6 才有, 老版本忽略即可)。
        try:
            self.log_text.configure(blockcursor=True)
        except Exception:
            pass
        # 深色滚动条, 与 #1e1e1e 日志底同色系, 避免右侧挂一条浅色滑块。
        try:
            self.style.configure(
                "Dark.Vertical.TScrollbar",
                background="#3e3e42", troughcolor="#1e1e1e", bordercolor="#1e1e1e",
                arrowcolor="#9d9d9d", darkcolor="#3e3e42", lightcolor="#3e3e42",
                relief="flat", arrowsize=12
            )
            self.log_text.vbar.configure(style="Dark.Vertical.TScrollbar")
        except Exception:
            pass

        # ---- 日志配色: 取自 VSCode Dark+ 编辑器主题 ----
        # 时间戳 = 注释绿, 级别前缀 = 关键字蓝/类型青/警告黄/错误红,
        # 正文里的路径与数字再按字符串橙、数字浅绿高亮, 整体呈代码编辑器观感。
        self.log_text.tag_config("TIMESTAMP", foreground="#6a9955")
        self.log_text.tag_config("INFO", foreground="#569cd6")
        self.log_text.tag_config("SUCCESS", foreground="#4ec9b0")
        self.log_text.tag_config("WARNING", foreground="#cca700")
        self.log_text.tag_config("ERROR", foreground="#f14c4c")
        self.log_text.tag_config("LOGBOLD", font=(self.log_font_family, 10, "bold"))
        self.log_text.tag_config("LOGPATH", foreground="#ce9178")
        self.log_text.tag_config("LOGNUM", foreground="#b5cea8")

# ---------------- 🖼️ Section 4: Preview Panel (Right Side) ----------------
        # 高度=左列三面板之和; 宽度=整个窗口宽度的一半。白色卡片外框内嵌
        # 一块黑色预览区, 黑色区域与面板外框四周保持留白距离。
        self.preview_card = ttk.Frame(content, style="Card.TFrame", padding=12, width=1250)
        self._paned.add(self.preview_card, weight=0)

        preview_header = ttk.Frame(self.preview_card, style="InnerCard.TFrame")
        preview_header.pack(fill=tk.X, pady=(0, 6))
        # 图标刻意写成 "\U0001F5BC"(🖼) 而不是 "\U0001F5BC\ufe0f"(🖼️):
        # 前者已能正常渲染, 后者多带的变体选择符 U+FE0F 在本程序字体下会被
        # 渲染成一个整宽空白字形, 导致该标题"图标-文字"间距比其它三个面板宽一倍。
        ttk.Label(preview_header, text="\U0001F5BC  效果预览", style="Header.TLabel").pack(side=tk.LEFT)
        # 提示文字放在预览面板标题行右上角, 与"处理进度与日志"的状态标签同一位置语义
        ttk.Label(preview_header, text="修改参数自动刷新预览", style="Status.TLabel").pack(side=tk.RIGHT)

        # 黑色内圈预览区: 背景 #181818(与日志面板一致), 与外框四周留白
        self.preview_box = ttk.Frame(self.preview_card, style="PreviewCard.TFrame", padding=(0, 12))
        self.preview_box.pack(fill=tk.BOTH, expand=True, pady=(8, 10))
        # 拖动分隔条/缩放窗口改变预览区宽度时, 按新宽度重新渲染预览图
        self.preview_box.bind("<Configure>", self._on_preview_box_configure)

        self.preview_label = tk.Label(
            self.preview_box,
            bg="#181818", fg="#aeb6c2",
            text="请先在“输入路径”中\n选择视频文件或文件夹\n\n修改参数后此处将自动刷新",
            font=("Microsoft YaHei", 9),
            justify="center",
            relief="flat", bd=0
        )
        self.preview_label.pack(fill=tk.BOTH, expand=True)

    def _on_toggle_row_configure(self, event):
        """开关行宽度变化时按可用宽度重新排布(单行/双行切换)。"""
        if event.widget is not self._toggle_row:
            return
        self._layout_toggles(event.width)

    def _layout_toggles(self, avail_w):
        """把四个 ToggleSwitch 按"两端对齐 + 等间隔"排进开关行。

        单行(宽度够时, 默认): 7 列 = [开关][间隔][开关][间隔][开关][间隔][开关]。
            三个间隔列 weight 相同 → 三段间距严格等宽; 首尾开关贴住面板左右两端。
        双行(单行放不下时): 折成 2x2, 每行左一个右一个, 同样两端对齐。
            这样窄窗口/高 DPI 下也不会把末尾标签裁掉。

        已在当前布局时不重排, 避免 <Configure> 与 grid 互相触发死循环。"""
        if avail_w <= 1:
            return
        widgets = self._toggle_widgets
        need = (sum(w.winfo_reqwidth() for w in widgets)
                + 3 * TOGGLE_GAP_MIN)
        single_row = need <= avail_w
        if single_row == self._toggle_single_row:
            return
        self._toggle_single_row = single_row

        row = self._toggle_row
        for c in range(7):
            row.grid_columnconfigure(c, weight=0, minsize=0)
        if single_row:
            for c in (1, 3, 5):
                row.grid_columnconfigure(c, weight=1, minsize=TOGGLE_GAP_MIN)
            for i, w in enumerate(widgets):
                w.grid(row=0, column=i * 2, sticky=tk.W)
        else:
            row.grid_columnconfigure(1, weight=1, minsize=TOGGLE_GAP_MIN)
            row.grid_columnconfigure(3, weight=1, minsize=TOGGLE_GAP_MIN)
            widgets[0].grid(row=0, column=0, sticky=tk.W)
            widgets[1].grid(row=0, column=4, sticky=tk.W)
            widgets[2].grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
            widgets[3].grid(row=1, column=4, sticky=tk.W, pady=(6, 0))

    def _install_button_tooltips(self):
        """递归为窗口中的按钮和复选按钮绑定使用说明。"""
        descriptions = {
            "选择文件": "选择一个视频文件作为输入。",
            "选择文件夹": "选择包含视频的文件夹作为输入。",
            "浏览": "选择对应的保存目录或字体文件。",
            "清空": "清空路径、日志和预览显示。处理期间不可清空。",
            "取消": "取消当前任务并删除当前未完成的视频。",
            "暂停": "暂停当前任务，当前文件停止后可点击继续。",
            "继续": "继续处理当前未完成的视频。",
            "开始": "开始批量处理视频。",
            "启用裁剪拉伸": "按下方四边裁剪宽度裁掉画面边缘, 再拉伸到 1920x1080。",
            "启用动态时间戳": "在视频画面上叠加动态时间戳水印。",
            "启用字体自动反色": "字色随背景明暗自动切换: 暗底白字 / 浅底黑字。",
            "启用字体描边": "在时间戳字符周围画一圈描边 (FFmpeg drawtext borderw/bordercolor)。取消勾选则不画描边。",
        }

        def visit(parent):
            for child in parent.winfo_children():
                if isinstance(child, ToggleSwitch):
                    # ToggleSwitch 自绘控件, 没有 cget("text"), 直接用 text 属性
                    tip = descriptions.get(child.text, f"切换{child.text}设置。")
                    child._button_tooltip = ButtonTooltip(child, tip)
                    visit(child)
                    continue
                if isinstance(child, (ttk.Button, ttk.Checkbutton, tk.Checkbutton)):
                    text = str(child.cget("text")).replace("⏸  ", "").replace("⏹  ", "").replace("▶  ", "")
                    text = text.replace("✖  ", "").replace("⌫  ", "")
                    tip = descriptions.get(text, f"切换{text}设置。")
                    child._button_tooltip = ButtonTooltip(child, tip)
                visit(child)

        visit(self.root)

    # File browsing callbacks
    def _apply_jk_to_ui(self, filename):
        """检测文件名中的 JK16/JK5 规则并更新 UI 控件。

        首次检测到 JK 时保存当前 UI 值, 之后切换到非 JK 文件时恢复。
        用户可在自动设置后手动修改, 手动值不会被额外保护。
        """
        jk_rule, jk_overrides = self._detect_jk_rule(filename)
        if jk_overrides:
            if self._jk_saved_defaults is None:
                self._jk_saved_defaults = {
                    "time_format": self.time_format_var.get(),
                    "x_offset": self.x_offset_var.get(),
                    "char_rules": self.char_rule_var.get(),
                }
            self.time_format_var.set(jk_overrides["time_format"])
            self.x_offset_var.set(str(jk_overrides["x_off"]))
            self.char_rule_var.set(jk_overrides["char_rules"])
            try:
                old_entry = self._format_entry(self._jk_saved_defaults["time_format"])
                old_dt = datetime.strptime(self.start_time_var.get().strip(), old_entry[2])
                new_entry = self._format_entry(jk_overrides["time_format"])
                self.start_time_var.set(old_dt.strftime(new_entry[3]))
            except Exception:
                pass
        else:
            if self._jk_saved_defaults is not None:
                d = self._jk_saved_defaults
                self.time_format_var.set(d["time_format"])
                self.x_offset_var.set(d["x_offset"])
                self.char_rule_var.set(d["char_rules"])
                self._jk_saved_defaults = None

    def browse_input_file(self):
        file_path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[("视频文件", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.m4v *.ts *.webm"), ("所有文件", "*.*")]
        )
        if file_path:
            self.input_path_var.set(os.path.normpath(file_path))
            if not self.save_dir_var.get():
                self.save_dir_var.set(os.path.dirname(os.path.normpath(file_path)))
            self._apply_jk_to_ui(os.path.basename(file_path))
            self._clear_active_preview_source()
            self.schedule_preview_refresh()

    def browse_input_dir(self):
        dir_path = filedialog.askdirectory(title="选择视频输入文件夹")
        if dir_path:
            self.input_path_var.set(os.path.normpath(dir_path))
            if not self.save_dir_var.get():
                self.save_dir_var.set(os.path.normpath(dir_path))
            fname = None
            for f in sorted(os.listdir(dir_path)):
                if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS:
                    fname = f
                    break
            self._apply_jk_to_ui(fname or "")
            self._clear_active_preview_source()
            self.schedule_preview_refresh()

    def browse_save_dir(self):
        dir_path = filedialog.askdirectory(title="选择保存目录")
        if dir_path:
            self.save_dir_var.set(os.path.normpath(dir_path))

    def browse_font_file(self):
        file_path = filedialog.askopenfilename(
            title="选择字体文件",
            filetypes=[("字体文件", "*.ttf *.otf *.ttc"), ("所有文件", "*.*")]
        )
        if file_path:
            self.font_file_var.set(os.path.normpath(file_path))
            self.schedule_preview_refresh()

    # Logger helper
    def log(self, message, level="INFO"):
        self.log_queue.put((level, message))

    @staticmethod
    def _log_segments(msg):
        """把一条日志正文切成 (文本, 标签) 片段: 路径/文件名/URL → LOGPATH,
        数字 → LOGNUM, 其余 → None(用面板默认前景色)。"""
        segments = []
        pos = 0
        for m in LOG_TOKEN_RE.finditer(msg):
            if m.start() > pos:
                segments.append((msg[pos:m.start()], None))
            tag = "LOGNUM" if m.lastgroup == "num" else "LOGPATH"
            segments.append((m.group(0), tag))
            pos = m.end()
        if pos < len(msg):
            segments.append((msg[pos:], None))
        return segments or [(msg, None)]

    def process_log_queue(self):
        while not self.log_queue.empty():
            level, msg = self.log_queue.get_nowait()
            now_str = datetime.now().strftime("[%H:%M:%S] ")
            level_tag = level if level in ("INFO", "SUCCESS", "WARNING", "ERROR") else "INFO"

            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, now_str, "TIMESTAMP")
            self.log_text.insert(tk.END, f"[{level}] ", (level_tag, "LOGBOLD"))
            for text, tag in self._log_segments(str(msg)):
                self.log_text.insert(tk.END, text, tag or ())
            self.log_text.insert(tk.END, "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        self.root.after(100, self.process_log_queue)

    def clear_workspace(self):
        """清空路径、日志和预览显示，不改变正在运行任务的线程控制状态。"""
        if self.is_processing:
            messagebox.showwarning(
                "提示",
                "处理视频当中，请任务结束或取消后方可执行清空操作！"
            )
            return
        self.input_path_var.set("")
        self.save_dir_var.set("")
        self._clear_active_preview_source()
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)
            self._preview_after_id = None
        self._preview_pending = False
        while True:
            try:
                self._preview_queue.get_nowait()
            except queue.Empty:
                break
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
        self._preview_photo = None
        self.preview_label.config(
            image="", text="请先在“输入路径”中\n选择视频文件或文件夹\n\n修改参数后此处将自动刷新"
        )

    def _set_active_preview_source(self, source):
        """在 UI 线程切换批处理当前视频的预览源。

        同时记下此刻的输入路径做"快照": 只要输入路径没变, 这个预览源就继续有效
        (批处理跑完也会保留在最后一个文件上); 输入路径一变, 立刻作废。

        使用内部入口 (不弹拦截窗, 处理中也不刷新), 因为这是 worker 自己的
        内部动作, 不是用户主动修改参数。"""
        self._active_preview_source = source
        try:
            self._active_preview_input = self.input_path_var.get().strip()
        except Exception:
            self._active_preview_input = None
        self._schedule_preview_refresh_internal(0)

    def _clear_active_preview_source(self):
        """作废"跟随批处理当前视频"的预览源。

        用户一旦重新选择/改写输入路径, 之前批处理留下的预览源就过期了;
        不作废的话预览会一直停在上一个视频的画面上(见 _get_preview_source)。
        """
        self._active_preview_source = None
        self._active_preview_input = None

    def _on_input_path_edited(self):
        """输入路径被编辑: 作废过期预览源 + 限流刷新预览。"""
        self._clear_active_preview_source()
        self.schedule_preview_refresh()

    # Preview helpers ---------------------------------------------------------
    def _preview_prepare_font(self):
        """Preview-only font prep: copy to ASCII temp path, no modal dialogs."""
        font_path = self.font_file_var.get().strip()
        if not font_path or not os.path.exists(font_path):
            self._prepared_font_path = None
            return False
        ext = os.path.splitext(font_path)[1].lower() or ".ttf"
        dst = os.path.join(tempfile.gettempdir(), f"video_batch_tool_font{ext}")
        try:
            shutil.copy2(font_path, dst)
            self._prepared_font_path = dst
            return True
        except Exception:
            self._prepared_font_path = None
            return False

    def _get_preview_source(self):
        """返回预览源视频: 输入为文件则直接用, 为目录则取第一个视频文件
        (含递归子目录)。

        `_active_preview_source` 是批处理"当前正在处理的文件", 只在**输入路径没变**
        的前提下优先——这样批处理过程中预览会跟着走, 跑完也停在最后一个文件上;
        而用户一旦换选/改写输入路径, 它就过期了, 若继续优先就会一直显示上一个
        视频(曾经的 bug: 换选新文件后预览不更新)。
        """
        act = self._active_preview_source
        if act and os.path.isfile(act):
            try:
                same_input = (self._active_preview_input
                              == self.input_path_var.get().strip())
            except Exception:
                same_input = False
            if same_input:
                return act
        p = self.input_path_var.get().strip()
        if not p:
            return None
        if os.path.isfile(p) and os.path.splitext(p)[1].lower() in VIDEO_EXTENSIONS:
            return os.path.normpath(p)
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                full = os.path.join(p, f)
                if os.path.isfile(full) and os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS:
                    return os.path.normpath(full)
            for dirpath, _dirs, files in os.walk(p):
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS:
                        return os.path.normpath(os.path.join(dirpath, f))
        return None

    def _preview_width(self):
        """预览图目标宽度 = 黑色预览区的完整内容宽度。"""
        try:
            return max(200, self.preview_box.winfo_width())
        except Exception:
            return 446

    def _screen_main_size(self):
        """主监视器尺寸(逻辑像素)。多显示器下 winfo_screenwidth 返回整个
        虚拟桌面的总宽度, 用 Windows API 取真实主屏保证居中数学正确。"""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        except Exception:
            return self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _screen_work_area(self):
        """主监视器可用工作区(逻辑像素, 已排除任务栏)。
        初始窗口高度按工作区算, 否则整窗连标题栏一起会压到任务栏下面。"""
        try:
            import ctypes
            import ctypes.wintypes as wt
            SPI_GETWORKAREA = 0x0030
            r = wt.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                    SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
                return r.right - r.left, r.bottom - r.top
        except Exception:
            pass
        return self._screen_main_size()

    def _frame_metrics(self):
        """返回 (外框额外宽, 外框额外高) = 整窗尺寸 - 客户区尺寸, 即标题栏+边框。
        用来把整窗(而不只是客户区)摆进可用工作区。"""
        try:
            import ctypes
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
            wr, cr = wt.RECT(), wt.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(wr)):
                return 0, 0
            if not user32.GetClientRect(hwnd, ctypes.byref(cr)):
                return 0, 0
            return ((wr.right - wr.left) - (cr.right - cr.left),
                    (wr.bottom - wr.top) - (cr.bottom - cr.top))
        except Exception:
            return 0, 0

    def _fit_to_work_area(self, margin=40):
        """按实测外框把客户区高度收紧到 工作区 - 外框 - 留白, 保证整窗
        (含标题栏/边框)全部落在工作区内, 底部不被屏幕边缘切掉。"""
        try:
            self.root.update_idletasks()
            _fw, frame_h = self._frame_metrics()
            _ww, work_h = self._screen_work_area()
            w, h = self.root.winfo_width(), self.root.winfo_height()
            if w <= 1 or h <= 1 or frame_h <= 0:
                return
            target = max(720, min(h, work_h - frame_h - margin))
            if abs(target - h) >= 2:
                self.root.geometry(f"{w}x{target}")
                self.root.update_idletasks()
        except Exception:
            pass

    def _recenter_window(self):
        """窗口映射后按实际尺寸重新校准居中, 消除设定尺寸与真实窗口尺寸
        不一致(标题栏/边框/系统调整)导致的偏移。"""
        try:
            self.root.update_idletasks()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            fw, fh = self._frame_metrics()
            sw, _sh = self._screen_main_size()
            _ww, wh = self._screen_work_area()
            # 按"整窗尺寸"(客户区 + 标题栏/边框)居中, 否则窗口会整体偏下
            if w > 1 and h > 1:
                x = max(0, (sw - w - fw) // 2)
                y = max(0, (wh - h - fh) // 2)
                self.root.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _post_init_layout(self):
        """窗口显示完成后: 按真实外框收紧高度 + 重新校准居中 +
        预览面板初始宽度=初始窗口宽度的一半。"""
        self._fit_to_work_area()
        self._recenter_window()
        self._set_initial_sash()

    def _set_initial_sash(self):
        """把分隔条定位到预览面板初始宽度(初始窗口宽度的一半)。"""
        try:
            w = self.root.winfo_width()
            if w <= 1:
                w = 2500
            half = w // 2
            self._paned.sashpos(0, max(300, half))
        except Exception:
            pass

    def _on_preview_box_configure(self, event):
        """预览区宽度变化(拖动分隔条/缩放窗口)时按新宽度重新渲染,
        并让提示文字自动换行以保证在任意宽度下都完整显示。"""
        if getattr(self, "_preview_box_last_w", None) != event.width:
            self._preview_box_last_w = event.width
            try:
                self.preview_label.config(wraplength=max(120, event.width - 24))
            except Exception:
                pass
            self.schedule_preview_refresh()

    def schedule_preview_refresh(self, delay=None):
        """用户参数变更入口: 处理中拦截 + 限流触发预览刷新。

        处理视频过程中 (is_processing=True 且 cancel_requested=False):
          先弹原生拦截提示窗, 告知本次参数改动被忽略, 然后不刷新预览
          (避免资源冲突与 WinError 1224), 当前任务继续跑;
        未在处理中 / 已取消: 交给 _schedule_preview_refresh_internal 限流调度。

        delay=None(默认) = 自动: 没在渲染就等满限流间隔的精确时刻起帧, 正在
        渲染则直接挂"待刷新"由渲染结束立刻补帧 (详见内部入口注释)。
        delay=0 = 强制立即; delay=正数 = 强制等待该毫秒数。"""
        status = self._gate_during_processing()
        if status != "free":
            return  # continue: 处理中不刷新预览, 防止 WinError 1224 等资源冲突
        self._schedule_preview_refresh_internal(delay)

    def _schedule_preview_refresh_internal(self, delay=None):
        """内部入口 (worker 更新预览源用): 不弹拦截窗, 处理中也不刷新。

        调度策略是"限流 + 尾随", 而不是纯尾沿防抖。纯防抖的做法是每次改动都
        after_cancel 重置一个 500ms 计时器, 于是按住 Spinbox 箭头 / 方向键连续
        调整时计时器一直被重置, 表现为"松手后才刷新"。

        这里改成:
          · 上一帧还在渲染 —— 直接置 _preview_pending 就走人, 不排任何计时器。
            渲染结束(done 事件)时会立刻补渲最新状态, 所以这段时间零额外延迟;
            排一个固定延迟的计时器反而会在渲染结束后白等那段时间。
          · 没在渲染 —— 等到"距上次起帧满 PREVIEW_THROTTLE_MS"的精确时刻再起帧,
            连续微调(打字、拖分隔条)合并成一帧, 但绝不白白多等。
        不管走哪条分支, 最多只会有一个待触发计时器, 且不会排队积压。"""
        if self.is_processing:
            return
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)
            self._preview_after_id = None

        if delay is None:
            if self._preview_running:
                # 正在渲染: 记下"待刷新", done 事件负责立刻补一帧
                self._preview_pending = True
                return
            # 还差多久才允许起下一帧(精确计算, 不引入额外等待)
            wait_ms = PREVIEW_THROTTLE_MS - (time.monotonic() - self._preview_last_start) * 1000.0
            delay = max(0, wait_ms)
        self._preview_after_id = self.root.after(delay, self.refresh_preview)

    def refresh_preview(self):
        self._preview_after_id = None
        if self._preview_running:
            # 上一帧还在渲染, 记录待刷新, 完成后自动补一帧最新状态
            self._preview_pending = True
            return

        ffmpeg_exe = self.ffmpeg_path_var.get().strip()
        if not ffmpeg_exe or not os.path.exists(ffmpeg_exe):
            msg = "未找到可用的 FFmpeg，无法预览（可把 ffmpeg.exe 放到程序同目录，或运行 --selftest 自检）"
            self._preview_queue.put(("tip", msg))
            return

        src = self._get_preview_source()
        if not src:
            self._preview_queue.put(("tip", "请先在「输入路径」中选择视频文件或文件夹"))
            return

        # 每次渲染预览前检测 JK16/JK5 规则并更新 UI
        self._apply_jk_to_ui(os.path.basename(src))

        # Snapshot every parameter on the UI thread - the worker thread must
        # never touch Tk variables (not thread-safe).
        try:
            x_off = int(re.sub(r"[^\d\-]", "", self.x_offset_var.get()))
        except Exception:
            x_off = 20
        try:
            y_off = int(re.sub(r"[^\d\-]", "", self.y_offset_var.get()))
        except Exception:
            y_off = 20
        try:
            font_size = int(re.sub(r"[^\d]", "", self.font_size_var.get()))
        except Exception:
            font_size = 54
        entry = self._format_entry(self.time_format_var.get())
        try:
            start_dt = datetime.strptime(self.start_time_var.get().strip(), entry[2])
        except Exception:
            start_dt = datetime.now()

        snap = {
            "crop_scale": self.enable_crop_scale_var.get(),
            "crop": self._crop_values(),
            "timestamp": self.enable_timestamp_var.get(),
            "auto_invert": self.auto_invert_var.get(),
            "slots": self._char_slots(start_dt, self._resolve_add_text(start_dt)),
            "rules": self._parse_char_rules(),
            "position": self.position_var.get(),
            "x_off": x_off,
            "y_off": y_off,
            "font_pct": font_size,
            "font_file": self.font_file_var.get().strip(),
            "font_color": (self.font_color_var.get().strip() or "#ffffff"),
            "outline": self._outline_spec(self.font_color_var.get().strip() or "#ffffff"),
            "outline_w": self._outline_width(),
            "preview_w": self._preview_width(),
        }

        self._preview_running = True
        self._preview_last_start = time.monotonic()
        # 只有"还没有任何画面"时才显示占位文字。已有画面时保持上一帧不动,
        # 否则连续调整参数时预览区会被反复清空成"预览刷新中...", 反而看不清变化。
        if self._preview_photo is None:
            self.preview_label.config(image="", text="预览刷新中...")
        threading.Thread(target=self._preview_worker, args=(src, ffmpeg_exe, snap), daemon=True).start()

    def _preview_worker(self, src_file, ffmpeg_exe, snap):
        """后台线程: 用当前全部参数渲染一帧"实际效果"预览图并回传 UI 队列。"""
        try:
            prefix_parts = self._crop_scale_filters(
                snap.get("crop_scale"), snap.get("crop", (0, 0, 0, 0))
            )

            # 面板的字号/偏移按"源视频像素"定义, 这里一次性换算到输出坐标系,
            # 反色与非反色两条链路共用同一组数值(见 _scale_factors 注释)。
            kx, ky = self._scale_factors(
                ffmpeg_exe, src_file,
                snap.get("crop_scale"), snap.get("crop", (0, 0, 0, 0))
            )
            if kx != 1.0 or ky != 1.0:
                snap["x_off"] = int(round(snap["x_off"] * kx))
                snap["y_off"] = int(round(snap["y_off"] * ky))
                snap["rules"] = self._scale_rules(snap["rules"], kx)
                # 描边宽度也按"源视频像素"标定, 同系数换算(颜色已在 UI 线程解析)
                if snap.get("outline"):
                    _ow, _oc = snap["outline"]
                    snap["outline"] = (max(1, int(round(_ow * kx))), _oc)
                if snap.get("outline_w"):
                    snap["outline_w"] = max(1, int(round(snap["outline_w"] * kx)))
            snap["size_scale"] = kx

            # 修复时间戳偏差: 强制把当前帧的 pts 重置为 0,确保 drawtext
            # 渲染的时间 = 用户在"起始时间"里设置的精确时刻(起始时间 + 0 秒)。
            # 之前 -ss 1 直接截帧,实际取到的是最近的 keyframe,pts 通常为几秒
            # (GOP=3~4s 时常见 ≈3s),导致预览时间总比面板多 3 秒左右。
            # 这里把 pts 归零后,无论后续 -ss 调到哪个时间点,都稳定显示起始时间。
            prefix_parts.append("setpts=PTS-STARTPTS")

            out_png = os.path.join(tempfile.gettempdir(), "video_batch_tool_preview.png")

            use_invert = snap["timestamp"] and snap.get("auto_invert") and snap.get("slots")

            if use_invert:
                # 自动反色: maskedmerge 每帧动态合成, 裁剪小区域+chained tblend消抖
                font_path = snap["font_file"]
                ext = os.path.splitext(font_path)[1].lower() or ".ttf"
                font_dst = os.path.join(tempfile.gettempdir(), f"video_batch_tool_font{ext}")
                shutil.copy2(font_path, font_dst)
                font_escaped = font_dst.replace("\\", "/").replace(":", "\\:")
                vid_w, vid_h = self._probe_video_size(ffmpeg_exe, src_file)
                for p in prefix_parts:
                    m = re.search(r"scale=(\d+):(\d+)", p)
                    if m:
                        vid_w, vid_h = int(m.group(1)), int(m.group(2))
                        break
                filter_complex = self.build_invert_filtergraph(prefix_parts, {
                    "slots": snap["slots"],
                    "rules": snap["rules"],
                    "fontsize": self._scaled_fontsize(snap["font_pct"], snap["size_scale"]),
                    "position": snap["position"],
                    "x_off": snap["x_off"],
                    "y_off": snap["y_off"],
                    "font_file_escaped": font_escaped,
                    "vid_w": vid_w, "vid_h": vid_h,
                    "outline_w": snap.get("outline_w", 0),
                }, preview_w=snap["preview_w"])
                cmd = [
                    ffmpeg_exe, "-y", "-ss", "0", "-i", src_file,
                    # 只取第一帧视频: 明确关掉音频/字幕/数据流, 省掉打开与
                    # 初始化这些解码器的时间(预览每次改动都要跑一遍 ffmpeg)
                    "-an", "-sn", "-dn",
                    "-frames:v", "1",
                    "-filter_complex", filter_complex, "-map", "[vout]",
                    "-compression_level", str(PREVIEW_PNG_COMPRESSION),
                    out_png
                ]
            else:
                filter_parts = list(prefix_parts)
                if snap["timestamp"]:
                    font_path = snap["font_file"]
                    if font_path and os.path.exists(font_path) and snap.get("slots"):
                        try:
                            ext = os.path.splitext(font_path)[1].lower() or ".ttf"
                            font_dst = os.path.join(tempfile.gettempdir(), f"video_batch_tool_font{ext}")
                            shutil.copy2(font_path, font_dst)
                            font_escaped = font_dst.replace("\\", "/").replace(":", "\\:")
                            fontsize = self._scaled_fontsize(snap["font_pct"], snap["size_scale"])
                            color_val = snap["font_color"]
                            if not color_val.startswith("#") and not color_val.isalnum():
                                color_val = "#ffffff"
                            chain = self._build_char_chain(
                                snap["slots"], snap["rules"], font_escaped,
                                fontsize, color_val,
                                snap["position"], snap["x_off"], snap["y_off"],
                                outline=snap.get("outline")
                            )
                            if chain:
                                filter_parts.append(chain)
                        except Exception:
                            pass

                filter_parts.append(f"scale={snap['preview_w']}:-2")
                filter_str = ",".join(filter_parts)
                # -ss 0: 从视频开头读取; 配合 setpts=PTS-STARTPTS 让 pts 从 0 起算,
                # drawtext 渲染的时间精确等于"起始时间",与面板输入完全一致。
                cmd = [
                    ffmpeg_exe, "-y", "-ss", "0", "-i", src_file,
                    # 同上: 预览只要第一帧视频, 不必打开音频/字幕/数据流
                    "-an", "-sn", "-dn",
                    "-frames:v", "1", "-vf", filter_str,
                    # 预览专用: PNG 用最快压缩等级, 少花几十毫秒换回一帧
                    "-compression_level", str(PREVIEW_PNG_COMPRESSION),
                    out_png
                ]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
            )
            if proc.returncode == 0 and os.path.exists(out_png):
                self._preview_queue.put(("ok", out_png))
            else:
                err_lines = [l for l in (proc.stderr or "").splitlines() if l.strip()]
                self._preview_queue.put(("err", err_lines[-1] if err_lines else "渲染失败"))
        except Exception as e:
            self._preview_queue.put(("err", str(e)))
        finally:
            self._preview_running = False
            self._preview_queue.put(("done", None))

    def process_preview_queue(self):
        try:
            while True:
                kind, payload = self._preview_queue.get_nowait()
                if kind == "ok" and os.path.exists(payload):
                    img = tk.PhotoImage(file=payload)
                    self._preview_photo = img
                    self.preview_label.config(image=img, text="")
                elif kind == "err":
                    self._preview_photo = None
                    self.preview_label.config(image="", text="预览渲染失败:\n" + payload)
                elif kind == "tip":
                    self._preview_photo = None
                    self.preview_label.config(image="", text=payload)
                elif kind == "done":
                    if self._preview_pending:
                        self._preview_pending = False
                        # 走同一条限流通道补一帧最新状态(而不是直接 refresh_preview):
                        # 若这一帧渲染得比 PREVIEW_THROTTLE_MS 还快, 会自动退化成
                        # 尾随帧, 不会把 CPU 空转成死循环。
                        self._schedule_preview_refresh_internal()
        except queue.Empty:
            pass
        self.root.after(PREVIEW_QUEUE_POLL_MS, self.process_preview_queue)

    # Process Management
    def start_processing(self):
        input_path = self.input_path_var.get().strip()
        save_dir = self.save_dir_var.get().strip()
        ffmpeg_path = self.ffmpeg_path_var.get().strip()

        # Validation
        if not input_path or not os.path.exists(input_path):
            messagebox.showwarning("提示", "请输入有效的输入文件或目录路径！")
            return
        if not save_dir:
            messagebox.showwarning("提示", "请指定保存目录！")
            return
        if not ffmpeg_path or not os.path.exists(ffmpeg_path):
            messagebox.showwarning(
                "提示",
                "未找到可用的 FFmpeg，无法开始处理！\n\n"
                "请把 ffmpeg.exe 放到程序同目录后重试；若内置资源损坏，\n"
                "可用 video_batch_tool.exe --selftest 自检（结果写入 %TEMP%）。"
            )
            return

        # Timestamp rendering requires the exact font the user selected - prepare
        # it before starting. If the font is missing/invalid, abort with a clear
        # message instead of silently rendering with a default font.
        if self.enable_timestamp_var.get():
            if not self._prepare_font_file():
                return

        self.is_processing = True
        self.stop_requested = False
        self.pause_requested = False
        self.cancel_requested = False
        self.resume_event.set()
        self.start_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL)
        self.progressbar["value"] = 0
        self.status_var.set("准备中...")

        # Start thread
        threading.Thread(target=self.batch_worker, daemon=True).start()

    def stop_processing(self):
        if self.is_processing and not self.pause_requested:
            self.pause_requested = True
            self.stop_requested = True
            self.resume_event.clear()
            self.stop_btn.config(text="▶  继续", style="Primary.TButton", command=self.resume_processing)
            self.stop_btn._button_tooltip.text = "继续处理当前未完成的视频。"
            self.log("收到暂停指令，当前文件停止后可继续处理...", "WARNING")
            self.status_var.set("已暂停，等待继续...")

    def resume_processing(self):
        if self.is_processing and self.pause_requested and not self.cancel_requested:
            self.pause_requested = False
            self.stop_requested = False
            self.resume_event.set()
            self.stop_btn.config(text="⏸  暂停", style="Stop.TButton", command=self.stop_processing)
            self.stop_btn._button_tooltip.text = "暂停当前任务，当前文件停止后可点击继续。"
            self.log("继续处理视频...", "INFO")

    def cancel_processing(self):
        if self.is_processing:
            self.cancel_requested = True
            self.stop_requested = True
            self.resume_event.set()
            self.log("收到取消指令，正在删除当前未完成的视频...", "WARNING")
            self.status_var.set("正在取消...")

    def _on_cancel_btn_clicked(self):
        """取消按钮 (✖) 点击: 走取消流程 + 显示成功提示窗口 (3 秒后自动关闭)。"""
        if not self.is_processing:
            return
        self.cancel_processing()
        self._show_notice(
            "已取消本次任务",
            "任务已成功取消，您可以重新调整参数后再开始处理。\n\n"
            "如需确认取消结果，请前往保存目录查看对应子目录是否已被清理。",
        )

    def _gate_during_processing(self):
        """处理视频中用户修改参数拦截门控。

        返回 "free" / "continue":
          free — 不在处理中(或已取消), 正常走后续预览刷新
          continue — 处理中弹了拦截提示窗, 本次参数改动被忽略, 任务继续

        多个参数控件同时触发时, _intercept_dialog_active 防重入, 只弹一个窗;
        连按箭头/方向键连续改参数时 (现在预览是实时的, 事件来得更密), 再加一层
        INTERCEPT_COOLDOWN_S 冷却: 冷却期内静默忽略, 不再反复弹窗刷屏。"""
        if not self.is_processing or self.cancel_requested:
            return "free"
        now = time.monotonic()
        if self._intercept_dialog_active:
            # 已经有拦截窗打开, 后续触发的参数变更静默忽略(等同 continue)
            return "continue"
        if (now - self._intercept_last_shown_at) < INTERCEPT_COOLDOWN_S:
            # 冷却期内: 同一次连续调整不再重复弹窗
            return "continue"
        self._intercept_dialog_active = True
        self._intercept_last_shown_at = now
        try:
            return self._show_intercept_dialog()
        finally:
            self._intercept_dialog_active = False

    def _show_intercept_dialog(self):
        """处理中参数修改拦截弹窗。始终返回 "continue"。

        全部提示弹窗统一走 tkinter.messagebox 的警告样式(系统原生标题栏/边框/
        主题/DPI/字体/颜色), 不再自绘弹窗、不套用主窗口的 ttk 样式。
        原生 messagebox 只有一个确定按钮, 因此"继续当前任务"是唯一出口:
        弹窗告知本次参数改动已被忽略, 若要按新参数重跑请先点"取消"。
        """
        messagebox.showwarning(
            "正在处理中",
            "您刚刚调整了一个正在运行任务的参数。\n\n"
            "此时重新渲染会与正在运行的处理线程产生资源冲突，"
            "本次参数改动已被忽略，当前任务将继续执行。\n\n"
            "若确需按新参数重新处理，请先点击“取消”结束本次任务，"
            "再调整参数并重新开始。",
        )
        return "continue"

    @staticmethod
    def _show_notice(title, body):
        """系统原生提示窗(messagebox.showwarning), 所有提示弹窗的唯一出口。

        保持 Windows 原生外观: 不设背景色/圆角/阴影/图标, 不套用主窗口的
        ttk 样式, 由系统主题与 DPI 决定一切。"""
        messagebox.showwarning(title, body)

    def _prepare_font_file(self):
        """Copy the user-selected font to a pure-ASCII temp path for FFmpeg.

        Returns True on success and stores the prepared path in
        self._prepared_font_path. On any failure it logs the exact reason and
        returns False - the caller must abort processing. We NEVER fall back to
        another font silently, otherwise the timestamp style would not match
        the font the user picked.
        """
        font_path = self.font_file_var.get().strip()
        if not font_path:
            msg = "未选择字体文件！请点击“字体文件”旁的“浏览”按钮选择字体后再处理。"
            self.log("  └─ ⚠️ " + msg, "ERROR")
            messagebox.showwarning("字体错误", msg)
            return False

        if not os.path.exists(font_path):
            msg = f"所选字体文件不存在或无法访问：\n{font_path}\n\n请重新点击“浏览”选择有效的字体文件。"
            self.log("  └─ ⚠️ " + msg, "ERROR")
            messagebox.showwarning("字体错误", msg)
            return False

        ext = os.path.splitext(font_path)[1].lower() or ".ttf"
        # Temp dir always resolves to a plain ASCII path like
        # C:/Users/<name>/AppData/Local/Temp/... - safe for FFmpeg fontfile.
        dst = os.path.join(tempfile.gettempdir(), f"video_batch_tool_font{ext}")
        try:
            shutil.copy2(font_path, dst)
        except Exception as e:
            msg = f"字体文件复制失败：{e}"
            self.log("  └─ ⚠️ " + msg, "ERROR")
            messagebox.showwarning("字体错误", msg)
            return False

        self._prepared_font_path = dst
        self.log(f"  └─ 时间戳字体已准备: {font_path}", "INFO")
        self.log(f"  └─ 实际渲染字体路径: {dst}", "INFO")
        return True

    def detect_video_codec(self, ffmpeg_exe, file_path):
        """Detect input video codec using ffmpeg probe or ffprobe."""
        ffprobe_exe = find_ffprobe_exe(ffmpeg_exe)
        if os.path.exists(ffprobe_exe):
            cmd = [
                ffprobe_exe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ]
            try:
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    check=True
                )
                codec = res.stdout.strip().lower()
                if codec:
                    return codec
            except Exception:
                pass

        # Fallback to ffmpeg -i
        cmd = [ffmpeg_exe, "-i", file_path]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            stderr = res.stderr
            for line in stderr.splitlines():
                if "Stream #" in line and "Video:" in line:
                    parts = line.split("Video:")[1].strip().split()
                    if parts:
                        return parts[0].lower().strip(",")
        except Exception:
            pass

        return "h264"

    def _probe_video_size(self, ffmpeg_exe, file_path):
        """获取视频宽高(像素), 带缓存(键含 mtime+大小, 文件变了自动重探)。
        裁剪拉伸的字号换算每次预览都要用, 不缓存会在每次刷新时多跑一次探测。"""
        key = None
        try:
            st = os.stat(file_path)
            key = (os.path.normcase(os.path.abspath(file_path)), int(st.st_mtime), st.st_size)
        except Exception:
            key = None
        cache = getattr(self, "_video_size_cache", None)
        if cache is not None and key is not None and key in cache:
            return cache[key]
        size = self._probe_video_size_uncached(ffmpeg_exe, file_path)
        if cache is not None and key is not None:
            cache[key] = size
        return size

    def _probe_video_size_uncached(self, ffmpeg_exe, file_path):
        """获取视频宽高(像素)。优先 ffprobe, 回退 ffmpeg -i 解析。"""
        ffprobe_exe = find_ffprobe_exe(ffmpeg_exe)
        if os.path.exists(ffprobe_exe):
            cmd = [
                ffprobe_exe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0", file_path
            ]
            try:
                res = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
                )
                parts = res.stdout.strip().split(',')
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    return int(parts[0]), int(parts[1])
            except Exception:
                pass
        try:
            cmd = [ffmpeg_exe, "-i", file_path]
            res = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
            )
            for line in res.stderr.splitlines():
                m = re.search(r'(\d{2,5})x(\d{2,5})', line)
                if m and 'Video:' in line:
                    return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
        return 1920, 1080

    def _probe_video_duration(self, ffmpeg_exe, file_path):
        """获取视频时长(秒)。优先 ffprobe, 回退 ffmpeg -i 解析。"""
        ffprobe_exe = find_ffprobe_exe(ffmpeg_exe)
        if os.path.exists(ffprobe_exe):
            cmd = [
                ffprobe_exe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", file_path
            ]
            try:
                res = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
                )
                val = res.stdout.strip()
                if val:
                    return float(val)
            except Exception:
                pass
        try:
            cmd = [ffmpeg_exe, "-i", file_path]
            res = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
            )
            for line in res.stderr.splitlines():
                m = re.search(r'Duration:\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)', line)
                if m:
                    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) * 0.1
        except Exception:
            pass
        return 0.0

    def _compress_to_target_size(self, ffmpeg_exe, src_file, out_file,
                                  target_mb=15, log_prefix="", duration=None):
        """两阶段编码将视频压缩到目标大小(MB)。

        target_mb: 目标大小, 默认 15MB
        duration:  调用方已知时传入(秒), 避免再次 ffprobe; 否则本函数探测。
                  衔接优化: 处理视频阶段 ffmpeg 已经把 Duration 行打到 stderr,
                  batch_worker 解析后传进来, 节省 ~300ms ffprobe 冷启动。
        返回: True 成功, False 失败 (含 stop_requested 触发的中止)。
        """
        # 先检查文件大小: 已小于目标大小直接跳过, 也能顺带省下 ffprobe 调用
        try:
            file_size_mb = os.path.getsize(src_file) / (1024 * 1024)
        except OSError:
            file_size_mb = 0.0
        if file_size_mb <= target_mb * 1.1:
            self.log(f"{log_prefix}源文件已小于 {target_mb}MB ({file_size_mb:.1f}MB), 无需压缩", "INFO")
            return False

        # 需要压缩才探测/接收 duration
        if duration is None or duration <= 0:
            duration = self._probe_video_duration(ffmpeg_exe, src_file)
        if duration <= 0:
            self.log(f"{log_prefix}无法探测视频时长, 跳过压缩", "WARNING")
            return False

        # 目标视频码率 = (目标大小 * 8192 / 时长) - 音频码率
        # 留 3% 给容器封装开销
        total_kbits = target_mb * 8192 * 0.97
        audio_kbps = 96
        video_kbps = max(100, int(total_kbits / duration) - audio_kbps)

        dur_str = self._fmt_hms(duration)
        self.log(f"{log_prefix}开始压缩: 时长{duration:.0f}s, 目标视频码率{video_kbps}kbps", "INFO")

        passlog_prefix = os.path.join(os.path.dirname(out_file), "ffmpeg2pass")
        devnull = "NUL" if sys.platform.startswith("win") else "/dev/null"

        if self.stop_requested:
            return False

        # Pass 1 — Popen + readline polling, 过程中显示进度避免"长时间等待"显得卡住
        # 注意: 第 1 遍必须与第 2 遍使用同一 preset, 否则 x264 会因 weightp 等统计参数不一致
        #       直接拒绝编码 ("different weightp setting than first pass")。
        cmd1 = [
            ffmpeg_exe, "-y", "-i", src_file,
            "-c:v", "libx264", "-preset", "slow",
            "-b:v", f"{video_kbps}k",
            "-pass", "1", "-passlogfile", passlog_prefix,
            "-an", "-f", "mp4", devnull
        ]
        self.status_var.set(f"压缩分析中{(' / '+dur_str) if dur_str else ''}")
        self.log(f"{log_prefix}压缩分析中: 正在统计复杂度...", "INFO")
        proc1 = subprocess.Popen(
            cmd1, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        )
        last_err_lines = []
        while True:
            line = proc1.stderr.readline()
            if not line and proc1.poll() is not None:
                break
            if self.stop_requested:
                proc1.kill()
                break
            if line:
                s = line.strip()
                if s:
                    last_err_lines.append(s)
                    if len(last_err_lines) > 20:
                        last_err_lines.pop(0)
                if "time=" in s:
                    try:
                        time_match = re.search(r"time=(\d{2}:\d{2}:\d{2})", s)
                        if time_match:
                            cur = time_match.group(1)
                            if dur_str:
                                self.status_var.set(f"压缩分析中: {cur} / {dur_str}")
                            else:
                                self.status_var.set(f"压缩分析中: {cur}")
                    except Exception:
                        pass
        proc1.wait()

        if self.stop_requested:
            self._cleanup_passlog(passlog_prefix)
            return False
        if proc1.returncode != 0:
            tail = last_err_lines[-1] if last_err_lines else "未知"
            self._cleanup_passlog(passlog_prefix)
            self.log(f"{log_prefix}Pass 1 失败 (err {proc1.returncode}): {tail}", "ERROR")
            return False

        self.log(f"{log_prefix}分析完成, 开始压缩...", "INFO")

        # Pass 2
        cmd2 = [
            ffmpeg_exe, "-y", "-i", src_file,
            "-c:v", "libx264", "-preset", "slow",
            "-b:v", f"{video_kbps}k",
            "-pass", "2", "-passlogfile", passlog_prefix,
            "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            out_file
        ]
        proc2 = subprocess.Popen(
            cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        )
        last_err_lines2 = []
        while True:
            line = proc2.stderr.readline()
            if not line and proc2.poll() is not None:
                break
            if self.stop_requested:
                proc2.kill()
                break
            if line:
                s2 = line.strip()
                if s2:
                    last_err_lines2.append(s2)
                    if len(last_err_lines2) > 20:
                        last_err_lines2.pop(0)
                if "time=" in s2:
                    try:
                        time_match = re.search(r"time=(\d{2}:\d{2}:\d{2}\.\d+)", s2)
                        if time_match:
                            t_str = time_match.group(1).split(".")[0]
                            if dur_str:
                                self.status_var.set(f"压缩中: {t_str} / {dur_str}")
                            else:
                                self.status_var.set(f"压缩中: {t_str}")
                    except Exception:
                        pass
        proc2.wait()
        self._cleanup_passlog(passlog_prefix)

        if proc2.returncode == 0 and os.path.exists(out_file):
            final_mb = os.path.getsize(out_file) / (1024 * 1024)
            self.log(f"{log_prefix}压缩完成: {final_mb:.1f}MB", "SUCCESS")
            return True

        # 压缩失败: 记录原因并清掉半成品, 交由上层回退使用原始处理结果
        tail2 = last_err_lines2[-1] if last_err_lines2 else "未知"
        self.log(f"{log_prefix}压缩失败 (err {proc2.returncode}): {tail2}", "ERROR")
        if os.path.exists(out_file):
            try:
                os.remove(out_file)
            except OSError:
                pass
        return False

    def _cleanup_passlog(self, passlog_prefix):
        """删除 two-pass 日志文件。"""
        for suffix in ["-0.log", "-0.log.mbtree"]:
            f = passlog_prefix + suffix
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def _fmt_hms(self, seconds):
        """秒 -> HH:MM:SS 字符串(用于压缩进度显示)。"""
        try:
            total = max(0, int(round(float(seconds))))
        except Exception:
            return ""
        h = total // 3600
        m = (total % 3600) // 60
        s_rem = total % 60
        return f"{h:02d}:{m:02d}:{s_rem:02d}"

    def export_cover_image(self, ffmpeg_exe, video_file):
        """Export the first frame of a processed video as a same-name JPG."""
        cover_file = os.path.splitext(video_file)[0] + ".jpg"
        if os.path.exists(cover_file):
            try:
                os.remove(cover_file)
            except OSError:
                return None
        cmd = [
            ffmpeg_exe, "-y", "-i", video_file,
            "-map", "0:v:0", "-frames:v", "1", "-q:v", "2", "-an",
            cover_file,
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
            )
            if result.returncode == 0 and os.path.exists(cover_file):
                return cover_file
        except Exception:
            pass
        return None

    def get_file_list(self, input_path):
        files_to_process = []
        if os.path.isfile(input_path):
            ext = os.path.splitext(input_path)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                files_to_process.append(input_path)
        elif os.path.isdir(input_path):
            for file in os.listdir(input_path):
                full_p = os.path.join(input_path, file)
                if os.path.isfile(full_p):
                    ext = os.path.splitext(file)[1].lower()
                    if ext in VIDEO_EXTENSIONS:
                        files_to_process.append(full_p)

            if not files_to_process:
                for root, dirs, files in os.walk(input_path):
                    for file in files:
                        ext = os.path.splitext(file)[1].lower()
                        if ext in VIDEO_EXTENSIONS:
                            files_to_process.append(os.path.join(root, file))

        return files_to_process

    def _detect_jk_rule(self, filename):
        """检测文件名中的 JK16/JK5 特殊规则, 返回 (rule_name, overrides) 或 (None, None)。

        overrides 为参数覆盖字典: time_format, x_off, char_rules。
        自动反色保持开启, 仅指定字符固定白色不参与反色。
        """
        fname_upper = filename.upper()
        if "JK16" in fname_upper:
            return ("JK16", {
                "time_format": "YYYY年MM月DD日 HH:MM:SS",
                "x_off": 0,
                "char_rules": "1-4=#ffffff",
            })
        if "JK5" in fname_upper:
            return ("JK5", {
                "time_format": "YYYY年MM月DD日 HH:MM:SS",
                "x_off": 0,
                "char_rules": "6-7=#ffffff;12-14=#ffffff",
            })
        return (None, None)

    def get_encoder_params(self, raw_codec):
        preset_choice = self.preset_var.get()

        if "GPU" in preset_choice:
            # Try GPU acceleration
            if raw_codec in ["hevc", "h265"]:
                return ["-c:v", "hevc_nvenc", "-preset", "p1"]
            else:
                return ["-c:v", "h264_nvenc", "-preset", "p1"]

        # CPU mode
        if raw_codec in ["hevc", "h265"]:
            vcodec = "libx265"
        else:
            vcodec = "libx264"

        if "ultrafast" in preset_choice:
            preset = "ultrafast"
        elif "fast" in preset_choice:
            preset = "fast"
        else:
            preset = "medium"

        return ["-c:v", vcodec, "-preset", preset, "-crf", "26"]

    def _fontsize_value(self, font_size):
        """字体大小(px)。过低时用 40px 兜底保证可读。"""
        try:
            fontsize = int(font_size)
        except Exception:
            fontsize = 54
        if fontsize < 10:
            fontsize = 40
        return fontsize

    def _outline_width(self, scale=1.0):
        """描边宽度, 解析失败或 <=0 或"启用字体描边"未勾选都视为关闭描边。
        scale: 开启裁剪拉伸时的输出换算系数(见 _scale_factors)——描边宽度和
        字号一样按"源视频像素"标定, 否则开关前后描边相对粗细会变。"""
        if not self.enable_outline_var.get():
            return 0
        try:
            w = int(re.sub(r"[^\d\-]", "", str(self.outline_w_var.get())))
        except Exception:
            return 0
        w = max(0, min(20, w))
        if w <= 0 or scale == 1.0:
            return w
        return max(1, int(round(w * scale)))

    @staticmethod
    def _normalize_color(raw):
        """把用户输入的颜色规整成 drawtext 能识别的写法。
        支持: #rgb / #rrggbb / #rrggbbaa / ffmpeg 颜色名(black/red/navy/...)
        以及中文色名(黑 白 红 ...)。无法识别返回 None。"""
        s = str(raw or "").strip()
        if not s:
            return None
        if s in COLOR_NAME_MAP:
            return COLOR_NAME_MAP[s]
        if s.startswith("#"):
            h = s[1:]
            if len(h) in (3, 4) and all(c in "0123456789abcdefABCDEF" for c in h):
                return "#" + "".join(c * 2 for c in h)
            if len(h) in (6, 8) and all(c in "0123456789abcdefABCDEF" for c in h):
                return "#" + h.lower()
            return None
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", s):
            # ffmpeg 的 av_parse_color 支持一长串颜色名, 原样交给它判断
            return s.lower()
        return None

    @staticmethod
    def _contrast_outline(text_color):
        """按字色亮度取对比色: 浅字 -> 黑边, 深字 -> 白边。
        字色不是十六进制时(颜色名/中文色名)先查表换算。"""
        c = str(text_color or "").strip()
        c = VideoBatchToolApp._normalize_color(c) or c
        c = c.lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        if not re.fullmatch(r"[0-9a-fA-F]{6,8}", c):
            c = _COLOR_NAME_HEX.get(str(text_color or "").strip().lower(), "000000")
        try:
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        except Exception:
            return "black"
        return "black" if (0.299 * r + 0.587 * g + 0.114 * b) > 127 else "white"

    def _resolve_outline_color(self, text_color=None):
        """解析描边颜色输入, 返回实际会用于 borderw/bordercolor 的颜色字符串。
        「自动」或无法识别的输入 → 按字色取对比色。"""
        if text_color is None:
            text_color = self.font_color_var.get().strip() or "#ffffff"
        raw = (self.outline_color_var.get() or "").strip()
        if raw in ("", "自动", "auto", "AUTO"):
            return self._contrast_outline(text_color)
        return self._normalize_color(raw) or self._contrast_outline(text_color)

    def _outline_spec(self, text_color, width_scale=1.0):
        """返回 drawtext 描边参数 (宽度px, 颜色) ; 关闭时返回 None。
        COLR 彩色字体在 drawtext 里不生效, 描边只能靠这里的 borderw/bordercolor。"""
        w = self._outline_width(width_scale)
        if w <= 0:
            return None
        return (w, self._resolve_outline_color(text_color))

    # ------------------------------------------------------------------
    # 裁剪拉伸: 四边宽度可自定义(源视频像素), 先裁剪再拉伸到 1920x1080
    # ------------------------------------------------------------------

    def _crop_values(self):
        """读取四个裁剪输入框, 返回 (上, 下, 左, 右), 单位=源视频像素。
        解析失败按 0 处理; 单项钳制到 0..4000, 防止把整幅画面裁没。"""
        def one(var):
            try:
                v = int(re.sub(r"[^\d\-]", "", str(var.get())))
            except Exception:
                return 0
            return max(0, min(4000, v))

        return (one(self.crop_top_var), one(self.crop_bottom_var),
                one(self.crop_left_var), one(self.crop_right_var))

    @staticmethod
    def _crop_scale_filters(enable, crop):
        """按四边裁剪宽度生成滤镜前缀列表。
        crop = (上, 下, 左, 右), 单位=源视频像素; 四边全 0 时只做拉伸, 不插 crop。"""
        if not enable:
            return []
        top, bottom, left, right = crop
        parts = []
        if top or bottom or left or right:
            w_expr = f"iw-{left + right}" if (left or right) else "iw"
            h_expr = f"ih-{top + bottom}" if (top or bottom) else "ih"
            parts.append(f"crop={w_expr}:{h_expr}:{left}:{top}")
        parts.append(f"scale={CROP_OUT_W}:{CROP_OUT_H}")
        return parts

    # ------------------------------------------------------------------
    # 裁剪拉伸下的坐标换算
    # 面板里的 字体大小 / X偏移 / Y偏移 都按"源视频像素"定义(关闭开关时就是
    # 直接在源分辨率上画字)。开启裁剪拉伸后滤镜是 crop → scale=1920:1080,
    # 输出帧 = 裁剪后的源画面按 x*(1920/裁剪后宽)、y*(1080/裁剪后高) 线性映射,
    # 所以这三个参数必须乘同一系数, 否则开关前后看到的大小/位置不一致:
    # 源 2560x1440 时字号 48 占画面宽的 48/2560, 拉伸到 1920 后仍按 48px 画,
    # 相对宽度变成 48/1920, 看起来就凭空放大了 2560/1920 = 1.33 倍。
    # ------------------------------------------------------------------

    def _src_video_size(self, ffmpeg_exe, path):
        """源视频分辨率(带缓存), 探测失败按 1920x1080 兜底。"""
        try:
            return self._probe_video_size(ffmpeg_exe, path)
        except Exception:
            return (CROP_OUT_W, CROP_OUT_H)

    def _scale_factors(self, ffmpeg_exe, path, enable, crop):
        """返回 (kx, ky): 源视频像素 → 输出(拉伸后)像素 的换算系数。
        未启用裁剪拉伸时返回 (1.0, 1.0), 即完全保持旧行为。"""
        if not enable:
            return 1.0, 1.0
        src_w, src_h = self._src_video_size(ffmpeg_exe, path)
        top, bottom, left, right = crop
        cropped_w = max(1, int(src_w) - int(left) - int(right))
        cropped_h = max(1, int(src_h) - int(top) - int(bottom))
        return CROP_OUT_W / float(cropped_w), CROP_OUT_H / float(cropped_h)

    def _scaled_fontsize(self, nominal_px, k):
        """字号换算: 面板字号(源视频像素) × 系数 = 输出坐标系里的字号。
        字体大小只能用横向系数(drawtext 无法对字形做横竖不等比缩放);
        源是 16:9 时 kx == ky, 不存在歧义。"""
        return max(1, int(round(self._fontsize_value(nominal_px) * k)))

    @staticmethod
    def _scale_rules(rules, k):
        """逐字符规则里的字号也是"源视频像素", 按同一系数换算。"""
        if not rules or k == 1.0:
            return rules
        scaled = {}
        for idx, rule in rules.items():
            r = dict(rule)
            if "size" in r:
                try:
                    r["size"] = max(1, int(round(float(r["size"]) * k)))
                except Exception:
                    pass
            scaled[idx] = r
        return scaled

    def _sync_crop_widgets(self):
        """开关关闭时把四个裁剪输入框置灰, 避免误以为改了会生效。"""
        state = "normal" if self.enable_crop_scale_var.get() else "disabled"
        for spin in getattr(self, "_crop_spins", ()):
            try:
                spin.configure(state=state)
            except Exception:
                pass

    def on_crop_toggle_changed(self):
        """"启用裁剪拉伸"切换: 同步输入框可用性并刷新预览。"""
        self._sync_crop_widgets()
        self._on_toggle_click()

    def _sync_outline_widgets(self):
        """描边总开关关闭时, 把"描边(px)"与"描边颜色"控件置灰禁用,
        与关闭"启用裁剪拉伸"时四个裁剪输入框置灰的行为完全一致。"""
        enabled = self.enable_outline_var.get()
        state = "normal" if enabled else "disabled"
        for widget in (getattr(self, "outline_spin", None),
                       getattr(self, "outline_color_entry", None)):
            try:
                widget.configure(state=state)
            except Exception:
                pass
        # 描边色块跟随开关置灰/恢复实际颜色
        self._refresh_color_swatches()

    def on_outline_toggle_changed(self):
        """"启用字体描边"切换: 同步描边宽度/描边颜色控件可用性并刷新预览。"""
        self._sync_outline_widgets()
        self._on_toggle_click()

    def _on_toggle_click(self):
        """4 个总开关 (启用裁剪拉伸 / 启用动态时间戳 / 启用字体自动反色 / 启用字体描边)
        共用的点击回调: 强制立即触发预览刷新 (delay=0, 不走限流延迟),
        保证处理视频过程中勾选/取消也能即时看到预览图的变化。"""
        self.schedule_preview_refresh(0)

    # ------------------------------------------------------------------
    # 逐字符时间戳引擎: 拆解 → 编号 → 每字符一条 drawtext(独立字号/颜色)
    # ------------------------------------------------------------------

    def _resolve_add_text(self, start_dt):
        """返回用户当前定义的添加文字。"""
        return self.add_text_var.get().strip()

    def _char_slots(self, start_dt, add_text):
        """把时间戳(所选格式+添加文字)拆解成字符槽列表。
        槽结构: {"idx": 编号(空格为None), "kind": "space"/"static"/"dyn",
                "char": 静态字符或动态位在 t=0 的字符, "expr": 动态位表达式}
        编号规则: 可见字符从 1 连续编号; 空格参与排版但不占用编号。
        - 日期数字/分隔符/年月日/添加文字 → 静态字符: 由起始时间在 Python
          端算出, 播放期间不变(仅跨午夜/跨年的超长视频会停留在起始日)。
        - 时/分/秒共 6 个数字位 → 动态: drawtext eif 表达式按 (U+t) 实时
          计算。U = 起始"墙上时钟"秒数 = calendar.timegm(起始时间),
          中国无夏令时, 播放期间不会漂移。"""
        entry = self._format_entry(self.time_format_var.get())
        clean_fmt = entry[3]
        U = calendar.timegm(start_dt.timetuple())

        # 格式串拆 token: strftime 字段(%Y/%m/%d/%H/%M/%S) 或单个字面字符
        tokens = re.findall(r"%[YmdHMS]|[^%]", clean_fmt)

        # 插入添加文字(布局与旧版一致: 开头/日期和时间之间/末尾, 两侧补空格)
        def add_text_tokens(text, prefix):
            chars = list(text)
            if text.startswith("星期") and len(chars) >= 3:
                return [(f"{prefix}_label", c) for c in chars[:2]] + [
                    (f"{prefix}_value", c) for c in chars[2:]
                ]
            return [(prefix, c) for c in chars]

        if add_text:
            pos = self.add_text_pos_var.get()
            add_chars = add_text_tokens(add_text, "add_text")
            if pos == "时间戳开头":
                tokens = add_chars + [" "] + tokens
            elif pos == "时间戳末尾":
                tokens = tokens + [" "] + add_chars
            elif pos == "日期和时间之间":
                for i, tk in enumerate(tokens):
                    if tk.startswith("%H"):
                        # 吞掉 %H 前原有的空格, 保证只有一个分隔空格
                        # (与旧版 _apply_add_text 的 rstrip+单空格行为一致)
                        j = i
                        while j > 0 and tokens[j - 1] == " ":
                            j -= 1
                        tokens = tokens[:j] + [" "] + add_chars + [" "] + tokens[i:]
                        break

        slots = []

        def add_static(ch, group=None):
            slots.append({
                "idx": None,
                "kind": "space" if ch == " " else "static",
                "char": ch, "expr": None, "group": group,
            })

        def add_dyn(expr_tpl, char0, group=None):
            slots.append({
                "idx": None, "kind": "dyn", "char": char0,
                "expr": expr_tpl.format(U=U), "group": group,
            })

        for tk in tokens:
            token_group = None
            token_value = tk
            if isinstance(tk, tuple):
                token_group, token_value = tk
            if token_group:
                add_static(token_value, token_group)
                continue
            if tk == "%Y":
                for c in start_dt.strftime("%Y"):
                    add_static(c, "year")
            elif tk == "%m":
                for c in start_dt.strftime("%m"):
                    add_static(c, "month")
            elif tk == "%d":
                for c in start_dt.strftime("%d"):
                    add_static(c, "day")
            elif tk == "%H":
                h = start_dt.strftime("%H")
                add_dyn("floor(mod(floor(({U}+t)/3600),24)/10)", h[0], "hour")
                add_dyn("mod(mod(floor(({U}+t)/3600),24),10)", h[1], "hour")
            elif tk == "%M":
                m = start_dt.strftime("%M")
                add_dyn("mod(floor(({U}+t)/600),6)", m[0], "minute")
                add_dyn("mod(floor(({U}+t)/60),10)", m[1], "minute")
            elif tk == "%S":
                sec = start_dt.strftime("%S")
                add_dyn("mod(floor(({U}+t)/10),6)", sec[0], "second")
                add_dyn("mod(floor({U}+t),10)", sec[1], "second")
            else:
                add_static(tk)

        # 将字段前的分隔符并入后一个字段，例如“-09”和“:05”。
        for i, slot in enumerate(slots[:-1]):
            if slot["kind"] == "static" and slot["char"] in ("-", ":"):
                next_group = slots[i + 1].get("group")
                if next_group:
                    slot["group"] = next_group

        for i in range(1, len(slots)):
            slot = slots[i]
            if slot["kind"] == "static" and slot["char"] in ("年", "月", "日"):
                prev_group = slots[i - 1].get("group")
                if prev_group:
                    slot["group"] = prev_group

        # 编号: 跳过空格, 可见字符从 1 连续编号
        n = 0
        for s in slots:
            if s["kind"] != "space":
                n += 1
                s["idx"] = n
        return slots

    def _parse_char_rules(self):
        """解析逐字符样式规则字符串 → {编号: {"color": "#rrggbb", "size": int}}。
        语法: 编号列表=颜色[@字号], 多条规则用 ; 分隔, reset 清空全部。
        编号列表支持 单个(7) / 逗号(1,7,9) / 范围(9-11) 混合, 如 "1,7,9-11"。
        颜色支持 #rrggbb / rrggbb / 中文色名(黑色/白色/红色...)。"""
        return self._parse_char_rules_str(self.char_rule_var.get())

    def _parse_char_rules_str(self, raw):
        """解析规则字符串的核心逻辑, 不依赖 GUI 变量。"""
        rules = {}
        raw = raw.strip()
        if not raw:
            return rules
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if part.lower() == "reset":
                return {}
            m = re.match(r"^([\d,\-\s]+?)\s*=\s*(.+)$", part)
            if not m:
                continue
            idx_part, style = m.group(1).strip(), m.group(2).strip()
            style = COLOR_NAME_MAP.get(style, style)
            color, size = None, None
            if "@" in style:
                c, s_sz = style.split("@", 1)
                color = c.strip()
                digits = re.sub(r"[^\d]", "", s_sz)
                if digits:
                    size = max(8, int(digits))
            else:
                color = style
            # 校验颜色: #rrggbb 或 rrggbb
            hex_part = color[1:] if color.startswith("#") else color
            if not re.fullmatch(r"[0-9a-fA-F]{6}", hex_part):
                continue
            color = "#" + hex_part.lower()
            for piece in idx_part.split(","):
                piece = piece.strip()
                if re.fullmatch(r"\d+\s*-\s*\d+", piece):
                    a, b = (int(x) for x in piece.split("-"))
                    idx_range = range(min(a, b), max(a, b) + 1)
                elif piece.isdigit():
                    idx_range = [int(piece)]
                else:
                    continue
                for i in idx_range:
                    r = rules.setdefault(i, {})
                    if color:
                        r["color"] = color
                    if size:
                        r["size"] = size
        return rules

    def _char_width(self, slot, size):
        """估算槽字符以 size 号渲染时的宽度(px)。
        全角=字号 / 半角=字号一半 —— 点阵体、雅黑、黑体等双语等宽字体
        严格遵循该规律, 默认场景可达像素级精确; 纯比例字体可能偏差几px。
        注意: 这个网格与字体"真实步进量"并不相等(见 _build_char_chain 的
        说明), 因此每个字符必须各自单独落位, 不能合并成一条 drawtext。"""
        ch = slot.get("char") or " "
        return size if unicodedata.east_asian_width(ch) in ("F", "W") else size / 2.0

    def _escape_static_char(self, ch):
        """静态字符的 drawtext text= 转义; 返回 None 表示无法安全渲染(跳过)。
        引号/反斜杠/百分号直接剔除, 避免破坏 text='...' 包裹与 %{...} 展开。"""
        if ch in ("'", "\\", "%"):
            return None
        return ch.replace(":", "\\:").replace(",", "\\,")

    def _build_char_chain(self, slots, rules, font_escaped, base_size, base_color,
                          pos_choice, x_off, y_off, outline=None):
        """逐字符构建 drawtext 过滤器链(逗号连接)。
        每个可见字符一条 drawtext, 拥有独立 fontsize/fontcolor; x 坐标 =
        整行基准 + 前序字符宽度累计。rules 为 _parse_char_rules() 的结果,
        未覆盖的编号继承 base_size/base_color(面板全局设置)。
        outline=(宽度px, 颜色) 时追加 borderw/bordercolor 实现黑边。

        【为什么坚持一字符一条, 不合并成整段?】曾试过把相邻同字号同颜色的字符合并
        进一条 drawtext, 预览单帧能从 ~500ms 降到 ~150ms(fmpeg 每条 drawtext 都要
        重新加载一次字体建 FreeType face, 实测 ≈10ms/条, 21 个字符就是 ~210ms)。
        实测证明这样**会改变成品画面**, 所以没有采用 —— 原因如下, 勿轻易再动:

        合并后, 段内字符的落点由 ffmpeg 按字体**真实步进量**排版; 而本函数按
        _char_width() 的"全角=字号 / 半角=字号一半"网格逐个定位。用 ffmpeg 画一串
        相同字符、量相邻字形的实际间距, 得到的真实步进量与该网格并不相等:
          · 随包的 VonwaonBitmap 点阵体: 字号 60 时数字步进 33px(网格按 30px)、
            汉字步进 36px(网格按 60px);
          · 微软雅黑: 字号 60 时数字步进 ~35px(网格按 30px)。
        也就是说合并会把整行字距从"网格"改成"字体设计值", 全行累积下来几十像素,
        预览与成品视频都会变形。要让两者一致就只能改 _char_width() 本身, 那等于
        改掉已有成品视频的排版, 更不能接受。

        预览提速因此改走别的路子(见 PREVIEW_THROTTLE_MS / PREVIEW_QUEUE_POLL_MS),
        宁可多花点 CPU 也不动渲染结果。"""
        if not slots:
            return ""

        def slot_size(slot):
            if slot["idx"]:
                o = rules.get(slot["idx"], {})
                return int(o.get("size", base_size))
            return base_size

        def slot_size(slot):
            if slot["idx"]:
                o = rules.get(slot["idx"], {})
                return int(o.get("size", base_size))
            return base_size

        # 整行总宽 W 与行高(取各槽最大字号, 近似一行文字的高度)
        total_w = 0.0
        line_h = base_size
        for s in slots:
            sz = slot_size(s)
            line_h = max(line_h, sz)
            total_w += self._char_width(s, sz)
        W = round(total_w, 1)

        # 整行基准 x/y 表达式: 右侧/居中用整行宽度 W, 而非单字符 text_w
        if pos_choice in ("右上", "右下"):
            x_base = f"w-{W}-({x_off})"
        elif pos_choice in ("左上", "左下"):
            x_base = f"{x_off}"
        else:  # 中上/中下/正中
            x_base = f"(w-{W})/2+({x_off})"
        if pos_choice in ("左下", "右下", "中下"):
            y_base = f"h-{line_h}-({y_off})"
        elif pos_choice == "正中":
            y_base = f"(h-{line_h})/2+({y_off})"
        else:
            y_base = f"{y_off}"

        # Drawtext's default y reference is the glyph box top, which makes
        # punctuation and CJK glyphs appear at different vertical positions.
        # Use one shared baseline for every character instead.
        baseline = f"{y_base}+{line_h}"

        parts = []
        cum = 0.0
        for s in slots:
            sz = slot_size(s)
            if s["kind"] == "space":
                cum += self._char_width(s, sz)
                continue
            color = base_color
            if s["idx"]:
                o = rules.get(s["idx"], {})
                color = o.get("color", base_color)
            x_expr = f"{x_base}+{cum:.1f}" if cum else x_base
            if s["kind"] == "static":
                ch = self._escape_static_char(s["char"])
                if ch is None:
                    cum += self._char_width(s, sz)
                    continue
                text_val = f"text='{ch}'"
            else:  # 动态数字位: eif 表达式按 (U+t) 实时计算, 逗号需转义
                expr = s["expr"].replace(",", "\\,")
                text_val = f"text='%{{eif\\:{expr}\\:d}}'"
            parts.append(
                f"drawtext=fontfile='{font_escaped}':"
                f"{text_val}:"
                f"x={x_expr}:y={baseline}:y_align=baseline:"
                f"fontsize={sz}:"
                f"fontcolor='{color}'"
                + (f":borderw={outline[0]}:bordercolor='{outline[1]}'" if outline else "")
            )
            cum += self._char_width(s, sz)
        return ",".join(parts)

    def build_drawtext_filter(self, filename="", time_format=None,
                               start_time=None, x_offset=None,
                               char_rules=None, size_scale=1.0,
                               x_scale=1.0, y_scale=1.0):
        """构建时间戳过滤器: 逐字符 drawtext 链(预览与批处理共用)。
        起始时刻始终以面板"起始时间"为准; 每个字符可经"字符规则"单独
        覆盖颜色与字号, 未覆盖的字符继承面板全局设置。
        可选参数用于批处理中 JK16/JK5 局部覆盖, 不传则读取 GUI 值。
        size_scale/x_scale/y_scale: 面板字号与偏移按"源视频像素"定义, 开启
        裁剪拉伸(输出被缩放到 1920x1080)时按系数换算, 见 _scale_factors()。"""
        if not self.enable_timestamp_var.get():
            return ""

        fmt = time_format if time_format is not None else self.time_format_var.get()
        st = start_time if start_time is not None else self.start_time_var.get()
        xo = x_offset if x_offset is not None else self.x_offset_var.get()
        cr = char_rules if char_rules is not None else self.char_rule_var.get()

        entry = self._format_entry(fmt)
        try:
            start_dt = datetime.strptime(st.strip(), entry[2])
        except Exception:
            start_dt = datetime.now()

        slots = self._char_slots(start_dt, self._resolve_add_text(start_dt))
        rules = self._parse_char_rules_str(cr)

        try:
            x_off = int(re.sub(r"[^\d\-]", "", str(xo)))
        except Exception:
            x_off = 20
        try:
            y_off = int(re.sub(r"[^\d\-]", "", self.y_offset_var.get()))
        except Exception:
            y_off = 20
        try:
            font_size_px = int(re.sub(r"[^\d]", "", self.font_size_var.get()))
        except Exception:
            font_size_px = 54
        fontsize = self._fontsize_value(font_size_px)
        if size_scale != 1.0 or x_scale != 1.0 or y_scale != 1.0:
            fontsize = self._scaled_fontsize(font_size_px, size_scale)
            x_off = int(round(x_off * x_scale))
            y_off = int(round(y_off * y_scale))
            rules = self._scale_rules(rules, size_scale)

        # 字体文件: 使用批处理启动前准备的 ASCII 临时副本,
        # 保证渲染所用字体与用户选择完全一致(不会静默回退)。
        if not self._prepared_font_path:
            self.log("  └─ ⚠️ 时间戳字体未准备就绪，已中止该文件处理", "ERROR")
            return None
        font_path_escaped = self._prepared_font_path.replace("\\", "/").replace(":", "\\:")

        color_val = self.font_color_var.get().strip()
        if not color_val.startswith("#") and not color_val.isalnum():
            color_val = "#ffffff"

        return self._build_char_chain(
            slots, rules, font_path_escaped, fontsize, color_val,
            self.position_var.get(), x_off, y_off,
            outline=self._outline_spec(color_val, size_scale)
        )

    @staticmethod
    def _size_only_rules(rules):
        """自动反色模式下只保留字号规则, 丢弃用户自定义颜色。"""
        return {i: {"size": r["size"]} for i, r in rules.items() if "size" in r}

    def build_invert_filtergraph(self, prefix_parts, params, preview_w=None):
        """构建自动反色 filter_complex: 每帧动态 + 分组整组同色 + 时间消抖。

        性能优化: 将 mask 处理裁剪到时间戳小区域(约 700x60), 而非全 1920x1080,
        gblur/geq/tmix 均在小区域上运行, 性能提升约 50 倍。
        时间消抖: tmix=frames=75 均匀时间平均, 平均窗口 75 帧(25fps≈3s)。
        背景明暗翻转后, 平均 mask 需持续约半窗口(≈1.5s)才穿过 128 阈值。
        日期、时间字段及添加文字分别作为组, 同组字符共享一个背景采样点,
        避免人物经过时出现逐字符接力反色的“麦浪”效果。
        注意: 早期用级联 tblend(每级仅平均当前帧与上一帧), 其时间窗口只有
        N+1 帧(线性), 并非误以为的 2^N 帧(指数) - 5~7 级窗口仅 6~8 帧,
        实测切换延迟仅 ~0.1s, 这就是"消抖无效"的原因。tmix 才能指定
        真正的均匀窗口帧数; 在小区域上其 N-1 帧缓存仅约 1.6MB, 开销可忽略。
        """
        slots = params["slots"]
        rules = params["rules"]
        fontsize = params["fontsize"]
        position = params["position"]
        x_off = params["x_off"]
        y_off = params["y_off"]
        font_escaped = params["font_file_escaped"]
        vid_w = params.get("vid_w", 1920)
        vid_h = params.get("vid_h", 1080)

        # 反色模式下每个字符的字色在黑白之间切换, 黑边必须取相反色才看得见:
        # 黑字配白边, 白字配黑边。宽度与主面板一致。
        try:
            ow = max(0, min(20, int(params.get("outline_w", 0) or 0)))
        except Exception:
            ow = 0
        black_chain = self._build_char_chain(
            slots, rules, font_escaped, fontsize, "black",
            position, x_off, y_off,
            outline=(ow, "white") if ow > 0 else None
        )
        white_chain = self._build_char_chain(
            slots, rules, font_escaped, fontsize, "white",
            position, x_off, y_off,
            outline=(ow, "black") if ow > 0 else None
        )
        if not black_chain or not white_chain:
            return ""

        prefix = ",".join(prefix_parts) if prefix_parts else "null"

        # --- 计算字符位置(镜像 _build_char_chain 的排版逻辑) ---
        def slot_size(slot):
            if slot["idx"]:
                o = rules.get(slot["idx"], {})
                return int(o.get("size", fontsize))
            return fontsize

        total_w = 0.0
        line_h = fontsize
        for s in slots:
            sz = slot_size(s)
            line_h = max(line_h, sz)
            total_w += self._char_width(s, sz)
        W = round(total_w, 1)

        # 计算 x_base / y_base 的数值(用于裁剪)
        if position in ("右上", "右下"):
            x_base = vid_w - W - x_off
        elif position in ("左上", "左下"):
            x_base = float(x_off)
        else:
            x_base = (vid_w - W) / 2.0 + x_off
        if position in ("左下", "右下", "中下"):
            y_base = vid_h - line_h - y_off
        elif position == "正中":
            y_base = (vid_h - line_h) / 2.0 + y_off
        else:
            y_base = float(y_off)

        # 每组使用自己的最小矩形采样区，避免人物进入相邻字符区域时提前
        # 影响本组判断。四周额外覆盖字形的抗锯齿像素，保证整字同色。
        crop_y = max(0, int(y_base) - 6)
        crop_h = int(line_h) + 16

        # 计算每组的水平范围。每个组只采样一次，组内所有字符共用结果。
        cum = 0.0
        group_spans = []
        current_group = None
        group_start = 0.0
        group_end = 0.0
        group_index = 0
        for s in slots:
            sz = slot_size(s)
            cw = self._char_width(s, sz)
            if s["kind"] == "space":
                cum += self._char_width(s, sz)
                continue
            group = s.get("group") or f"slot_{group_index}"
            if group != current_group:
                if current_group is not None:
                    group_spans.append((group_start, group_end))
                current_group = group
                group_start = cum
            group_end = cum + cw
            cum += cw
            group_index += 1
        if current_group is not None:
            group_spans.append((group_start, group_end))
        if not group_spans:
            return ""

        crop_x = max(0, int(x_base) - 1)
        split_count = len(group_spans) + 2
        split_labels = [f"[luma_in{i}]" for i in range(len(group_spans))]
        split_labels += ["[blank1]", "[blank2]"]
        segments = [
            f"[0:v]{prefix},format=rgb24,split={split_count}{''.join(split_labels)}",
            f"[blank2]lut=r=0:g=0:b=0[mask_canvas0]",
        ]

        # 时间消抖: 均匀平均 75 帧(25fps≈3s), 亮度翻转需持续约1.5s。
        debounce_chain = "tmix=frames=75"
        previous_canvas = "mask_canvas0"
        for group_index, (start, end) in enumerate(group_spans):
            group_x = max(0, int(x_base + start) - 3)
            group_w = max(1, int(end - start) + 6)
            sample_x = (x_base + (start + end) / 2.0) - group_x
            sample_y = (y_base + line_h / 2.0) - crop_y
            geq_expr = f"lum({sample_x:.1f},{sample_y:.1f})"
            segments.extend([
                f"[luma_in{group_index}]crop={group_w}:{crop_h}:{group_x}:{crop_y},"
                f"format=gray,gblur=sigma=40:sigmaV=15,"
                f"lut=y='if(lt(val,128),255,0)'[group_raw{group_index}]",
                f"[group_raw{group_index}]geq=lum='{geq_expr}'[group_q{group_index}]",
                f"[group_q{group_index}]{debounce_chain},"
                f"lut=y='if(gt(val,128),255,0)',format=rgb24[group_mask{group_index}]",
                f"[{previous_canvas}][group_mask{group_index}]"
                f"overlay={group_x}:{crop_y}[mask_canvas{group_index + 1}]",
            ])
            previous_canvas = f"mask_canvas{group_index + 1}"

        segments.extend([
            f"[{previous_canvas}]format=gray[mask_q]",
            f"[mask_q]format=rgb24[mask_rgb]",
            f"[blank1]split=2[blank_k][blank_w]",
            f"[blank_k]{black_chain}[black_ver]",
            f"[blank_w]{white_chain}[white_ver]",
            f"[black_ver][white_ver][mask_rgb]maskedmerge=planes=7,format=yuv420p[v1]",
        ])
        if preview_w:
            segments.append(f"[v1]scale={preview_w}:-2[vout]")
        else:
            segments.append(f"[v1]null[vout]")
        return ";".join(segments)

    def batch_worker(self):
        input_path = self.input_path_var.get().strip()
        save_dir = self.save_dir_var.get().strip()
        ffmpeg_exe = self.ffmpeg_path_var.get().strip()

        # 提示音策略: 输入选的是"文件" -> 该文件处理完就响一次;
        # 输入选的是"文件夹" -> 等全部文件处理完再统一响一次。
        single_file_mode = os.path.isfile(input_path)

        self.log("=== 开始查找视频文件 ===", "INFO")
        file_list = self.get_file_list(input_path)
        total_files = len(file_list)

        if total_files == 0:
            self.log("未在输入路径找到符合条件的视频文件！", "WARNING")
            self._play_cue("failure")
            self.finish_processing("未找到视频文件")
            return

        self.log(f"共找到 {total_files} 个待处理视频文件。", "INFO")

        # 进入处理流程前, 重要清理 (防御性):
        # - 当前文件子目录指针 必须清零, 否则上一批残留会让本次"取消"误删已成功文件
        # - 拦截窗防重入状态 重置 (上一批崩溃/异常态)
        self._current_sub_dir = None
        self._intercept_dialog_active = False

        # 衔接优化: 暖机 ffmpeg/ffprobe, 降低冷启动延迟。
        # 顺便抓一次 -version 首行打进日志: 那是"实际被调用的那份 ffmpeg"的指纹,
        # 可以和本机安装的版本对比(内置的是 9.0.1-essentials_build-www.gyan.dev)。
        t0 = time.perf_counter()
        warmed = 0
        ffmpeg_version = ""
        try:
            res_ver = subprocess.run(
                [ffmpeg_exe, "-hide_banner", "-version"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
                timeout=5,
            )
            warmed += 1
            vlines = (res_ver.stdout or "").strip().splitlines()
            ffmpeg_version = vlines[0].strip() if vlines else ""
        except Exception:
            pass
        try:
            ffprobe_exe_warm = find_ffprobe_exe(ffmpeg_exe)
            if os.path.exists(ffprobe_exe_warm):
                subprocess.run(
                    [ffprobe_exe_warm, "-hide_banner", "-version"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
                    timeout=5,
                )
                warmed += 1
        except Exception:
            pass
        try:
            if warmed > 0:
                self.log(
                    f"  └─ {'ffmpeg/ffprobe' if warmed == 2 else 'ffmpeg'} 暖机完成 ({(time.perf_counter() - t0) * 1000:.0f}ms)",
                    "INFO"
                )
            if ffmpeg_version:
                self.log(f"  └─ 实际调用: {ffmpeg_version}", "INFO")
        except Exception:
            pass

        success_count = 0
        failed_count = 0

        target_dir = os.path.normpath(save_dir)
        os.makedirs(target_dir, exist_ok=True)

        idx = 0
        while idx < total_files:
            if self.cancel_requested:
                self.log("批量处理过程已取消！", "WARNING")
                break
            if self.pause_requested:
                self.status_var.set("已暂停，等待继续...")
                self.resume_event.wait()
                if self.cancel_requested:
                    break
                continue

            src_file = file_list[idx]
            display_idx = idx + 1
            # 记录进入本文件前的计数, 处理完用增量判断该文件是成功还是失败
            _ok_before, _bad_before = success_count, failed_count
            self.root.after(0, self._set_active_preview_source, src_file)

            self.status_var.set(f"处理中: {display_idx}/{total_files}")
            self.progressbar["value"] = int((idx / total_files) * 100)

            filename = os.path.basename(src_file)
            name_without_ext, _ = os.path.splitext(filename)

            sub_dir = os.path.join(target_dir, name_without_ext)
            os.makedirs(sub_dir, exist_ok=True)
            # 记录当前正在处理的子目录: 取消时清理未完成的目录, 成功后清空
            self._current_sub_dir = sub_dir
            out_file = os.path.join(sub_dir, f"{name_without_ext}.mp4")
            temp_file = os.path.join(sub_dir, f"{name_without_ext}_tmp.mp4")

            if os.path.abspath(src_file) == os.path.abspath(out_file):
                out_file = os.path.join(sub_dir, f"{name_without_ext}_cropped.mp4")
                temp_file = os.path.join(sub_dir, f"{name_without_ext}_cropped_tmp.mp4")

            self.log(f"[{display_idx}/{total_files}] 正在处理: {filename}", "INFO")

            # 文件名特殊规则: JK16/JK5 局部覆盖参数 (不修改 UI 变量)
            jk_rule, jk_overrides = self._detect_jk_rule(filename)
            if jk_rule:
                cur_time_format = jk_overrides["time_format"]
                cur_x_off = jk_overrides["x_off"]
                cur_char_rules = jk_overrides["char_rules"]
                try:
                    old_entry = self._format_entry(self.time_format_var.get())
                    old_dt = datetime.strptime(self.start_time_var.get().strip(), old_entry[2])
                    new_entry = self._format_entry(cur_time_format)
                    cur_start_time = old_dt.strftime(new_entry[3])
                except Exception:
                    cur_start_time = self.start_time_var.get()
                if jk_rule == "JK16":
                    self.log(f"  └─ 检测到JK16: 年份数字固定白色(不参与反色), 格式=YYYY年MM月DD日 HH:MM:SS, X偏移=0", "INFO")
                else:
                    self.log(f"  └─ 检测到JK5: 月份和星期固定白色(不参与反色), 格式=YYYY年MM月DD日 HH:MM:SS, X偏移=0", "INFO")
            else:
                cur_time_format = self.time_format_var.get()
                cur_x_off = self.x_offset_var.get()
                cur_char_rules = self.char_rule_var.get()
                cur_start_time = self.start_time_var.get()

            # Codec detection & encoder parameter selection
            raw_codec = self.detect_video_codec(ffmpeg_exe, src_file)
            encoder_args = self.get_encoder_params(raw_codec)

            # Build filter chain: 裁剪拉伸(可选) + 动态时间戳(可选)
            crop_enabled = self.enable_crop_scale_var.get()
            crop = self._crop_values()
            prefix_parts = self._crop_scale_filters(crop_enabled, crop)
            # 面板的字号/偏移按"源视频像素"定义, 开启裁剪拉伸后输出帧被缩放到
            # 1920x1080, 这里换算出系数, 与预览走同一套换算(见 _scale_factors)。
            kx, ky = self._scale_factors(ffmpeg_exe, src_file, crop_enabled, crop)
            if kx != 1.0 or ky != 1.0:
                self.log(
                    f"  └─ 字号/偏移按输出比例换算: x{kx:.3f} y{ky:.3f} "
                    f"(与预览一致, 保证开关裁剪拉伸前后时间戳大小位置不变)",
                    "INFO"
                )
            if crop_enabled:
                if any(crop):
                    self.log(
                        f"  └─ 已执行裁剪拉伸: 上{crop[0]} 下{crop[1]} "
                        f"左{crop[2]} 右{crop[3]} px, 裁剪后拉伸至 1920x1080",
                        "INFO"
                    )
                else:
                    self.log("  └─ 已执行裁剪拉伸: 四边裁剪均为 0 (不裁剪), 仅拉伸至 1920x1080", "INFO")

            use_invert = self.enable_timestamp_var.get() and self.auto_invert_var.get()
            filter_str = ""
            filter_complex = ""

            if use_invert:
                # 自动反色: maskedmerge 每帧动态合成, 两次模糊+阈值化保证整字同色
                if not self._prepared_font_path:
                    self.log("=== 因时间戳字体问题中止批处理，请修正字体后再试 ===", "ERROR")
                    self.finish_processing("已中止：时间戳字体无效")
                    return
                entry = self._format_entry(cur_time_format)
                try:
                    start_dt = datetime.strptime(cur_start_time.strip(), entry[2])
                except Exception:
                    start_dt = datetime.now()
                slots = self._char_slots(start_dt, self._resolve_add_text(start_dt))
                rules = self._parse_char_rules_str(cur_char_rules)
                try:
                    x_off = int(re.sub(r"[^\d\-]", "", str(cur_x_off)))
                except Exception:
                    x_off = 20
                try:
                    y_off = int(re.sub(r"[^\d\-]", "", self.y_offset_var.get()))
                except Exception:
                    y_off = 20
                try:
                    font_size_px = int(re.sub(r"[^\d]", "", self.font_size_var.get()))
                except Exception:
                    font_size_px = 54
                fontsize = self._scaled_fontsize(font_size_px, kx)
                # 偏移与逐字符字号规则同样按源视频像素定义, 一并换算
                x_off = int(round(x_off * kx))
                y_off = int(round(y_off * ky))
                rules = self._scale_rules(rules, kx)
                font_path_escaped = self._prepared_font_path.replace("\\", "/").replace(":", "\\:")
                vid_w, vid_h = self._probe_video_size(ffmpeg_exe, src_file)
                for p in prefix_parts:
                    m = re.search(r"scale=(\d+):(\d+)", p)
                    if m:
                        vid_w, vid_h = int(m.group(1)), int(m.group(2))
                        break
                filter_complex = self.build_invert_filtergraph(prefix_parts, {
                    "slots": slots, "rules": rules,
                    "fontsize": fontsize,
                    "position": self.position_var.get(),
                    "x_off": x_off, "y_off": y_off,
                    "font_file_escaped": font_path_escaped,
                    "vid_w": vid_w, "vid_h": vid_h,
                    "outline_w": self._outline_width(kx),
                })
                if not filter_complex:
                    self.log("=== 自动反色滤镜构建失败, 中止批处理 ===", "ERROR")
                    self.finish_processing("已中止：反色滤镜无效")
                    return
                self.log("  └─ 已叠加自动反色动态时间戳水印 (逐帧动态+消抖: 暗底白字/浅底黑字, 整字同色, 非黑即白)", "INFO")
            else:
                drawtext_str = self.build_drawtext_filter(filename, cur_time_format,
                                                           cur_start_time, cur_x_off,
                                                           cur_char_rules,
                                                           size_scale=kx, x_scale=kx, y_scale=ky)
                if drawtext_str is None:
                    self.log("=== 因时间戳字体问题中止批处理，请修正字体后再试 ===", "ERROR")
                    self.finish_processing("已中止：时间戳字体无效")
                    return
                filter_parts = list(prefix_parts)
                if drawtext_str:
                    filter_parts.append(drawtext_str)
                    self.log("  └─ 已叠加动态时间戳水印", "INFO")
                filter_str = ",".join(filter_parts)

            self.log(f"  └─ 识别原始编码: {raw_codec} -> 参数配置: {' '.join(encoder_args)}", "INFO")

            cmd = [ffmpeg_exe, "-y", "-i", src_file]
            if filter_complex:
                cmd += ["-filter_complex", filter_complex, "-map", "[vout]"]
            elif filter_str:
                cmd += ["-vf", filter_str]
            cmd += encoder_args + [
                "-c:a", "aac",
                "-b:a", "96k",
                temp_file
            ]

            try:
                # 取消/暂停时希望保留 _current_sub_dir 指向不完整子目录, 让 after-loop 删除;
                # 正常成功/失败/异常时清空 (避免下次取消误删已完成的子目录)
                _keep_sub_dir = False
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
                )

                last_error_lines = []
                _src_duration = None

                while True:
                    line = proc.stderr.readline()
                    if not line and proc.poll() is not None:
                        break

                    if self.stop_requested:
                        proc.kill()
                        break

                    if line:
                        line_str = line.strip()
                        if line_str:
                            last_error_lines.append(line_str)
                            if len(last_error_lines) > 20:
                                last_error_lines.pop(0)
                            # 提前捕获 Duration, 避免流出尾部只保留20行时被丢弃
                            if _src_duration is None and "Duration:" in line_str:
                                _m_d = re.search(r'Duration:\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)', line_str)
                                if _m_d:
                                    try:
                                        _src_duration = (
                                            int(_m_d.group(1)) * 3600
                                            + int(_m_d.group(2)) * 60
                                            + int(_m_d.group(3))
                                            + int(_m_d.group(4)) * 0.1
                                        )
                                    except Exception:
                                        _src_duration = None

                        if "time=" in line_str:
                            try:
                                time_match = re.search(r"time=(\d{2}:\d{2}:\d{2}\.\d+)", line_str)
                                if time_match:
                                    t_str = time_match.group(1).split(".")[0]
                                    self.status_var.set(f"处理中: {display_idx}/{total_files} ({t_str})")
                            except Exception:
                                pass

                proc.wait()

                if self.stop_requested:
                    self.log(f"  └─ 已终止该文件处理: {filename}", "WARNING")
                    for f in (temp_file, out_file):
                        if os.path.exists(f):
                            try:
                                os.remove(f)
                            except Exception:
                                pass
                    if self.cancel_requested:
                        _keep_sub_dir = True
                        break
                    _keep_sub_dir = True
                    self.stop_requested = False
                    self.status_var.set("已暂停，等待继续...")
                    self.resume_event.wait()
                    if self.cancel_requested:
                        _keep_sub_dir = True
                        break
                    continue

                # 衔接优化: 复用处理阶段 ffmpeg stderr 里已经打出来的 Duration 行,
                # 免去 _compress_to_target_size 里再 ffprobe 一次的 ~300ms 冷启动。
                # 解析失败则传 None, 压缩阶段会自探。
                # (上方循环已尽量捕获; 如未捕获则回退到尾部20行再试一次, 保险起见)
                if _src_duration is None:
                    for _err in last_error_lines:
                        _m = re.search(r'Duration:\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)', _err)
                        if _m:
                            try:
                                _src_duration = (
                                    int(_m.group(1)) * 3600
                                    + int(_m.group(2)) * 60
                                    + int(_m.group(3))
                                    + int(_m.group(4)) * 0.1
                                )
                                break
                            except Exception:
                                _src_duration = None

                if proc.returncode == 0:
                    # 时间戳处理成功, 开始压缩到目标大小
                    # 取消/暂停时 _compress_to_target_size 会自己检测 stop_requested,
                    # 此时 dist/video_batch_tool.exe 处理+压缩视为一个总任务:
                    # 任何阶段取消都要把 _current_sub_dir 留到 after-loop 删除
                    compressed = False
                    if os.path.exists(temp_file):
                        if not self.stop_requested:
                            compressed = self._compress_to_target_size(
                                ffmpeg_exe, temp_file, out_file,
                                target_mb=15, log_prefix="  └─ ",
                                duration=_src_duration,
                            )
                    if compressed:
                        try:
                            os.remove(temp_file)
                        except Exception:
                            pass
                        success_count += 1
                        self.log(f"  └─ 处理成功: {out_file}", "SUCCESS")
                    elif os.path.exists(temp_file) and not self.stop_requested:
                        # 压缩失败, 直接用时间戳处理后的临时文件
                        try:
                            os.replace(temp_file, out_file)
                            success_count += 1
                            self.log(f"  └─ 压缩失败, 使用原始处理结果: {out_file}", "WARNING")
                        except Exception:
                            failed_count += 1
                            self.log(f"  └─ 压缩失败且无法移动临时文件", "ERROR")
                    elif os.path.exists(temp_file) and self.stop_requested:
                        # 总任务取消: 删 temp_file, 保留 sub_dir 让 after-loop 整体清理
                        try:
                            os.remove(temp_file)
                        except Exception:
                            pass
                        # FIX(2026-10-15): 之前这里 continue 时没设 _keep_sub_dir=True,
                        # finally 把它清零 → after-loop 看不到要清理的目录 → 残留文件夹。
                        # 现在把 _keep_sub_dir=True, 让 after-loop 把整个 sub_dir 删掉。
                        if self.cancel_requested:
                            _keep_sub_dir = True
                            self._current_sub_dir = sub_dir
                            break
                        _keep_sub_dir = True
                        self._current_sub_dir = sub_dir
                        continue
                    else:
                        failed_count += 1
                        self.log("  └─ 临时文件不存在", "ERROR")

                    if success_count > 0 and os.path.exists(out_file):
                        cover_file = self.export_cover_image(ffmpeg_exe, out_file)
                        if cover_file:
                            self.log(f"  └─ 封面截图已输出: {cover_file}", "SUCCESS")
                        else:
                            self.log("  └─ 封面截图输出失败，但视频处理已成功", "WARNING")
                else:
                    if "GPU" in self.preset_var.get():
                        self.log("  └─ GPU 硬件加速不可用，自动降级为 CPU 极速模式重试...", "WARNING")
                        fallback_args = ["-c:v", "libx265" if raw_codec in ["hevc", "h265"] else "libx264", "-preset", "ultrafast", "-crf", "26"]
                        cmd_fb = [ffmpeg_exe, "-y", "-i", src_file]
                        if filter_complex:
                            cmd_fb += ["-filter_complex", filter_complex, "-map", "[vout]"]
                        elif filter_str:
                            cmd_fb += ["-vf", filter_str]
                        cmd_fb += fallback_args + ["-c:a", "aac", "-b:a", "96k", temp_file]
                        proc_fb = subprocess.run(cmd_fb, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
                        if proc_fb.returncode == 0:
                            # 降级路径同理: 从 proc_fb.stderr 末尾的 Duration 行解析时长
                            _fb_duration = _src_duration
                            if _fb_duration is None:
                                _fb_err_tail = (proc_fb.stderr or "").splitlines()
                                for _err in _fb_err_tail:
                                    _m = re.search(r'Duration:\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)', _err)
                                    if _m:
                                        try:
                                            _fb_duration = (
                                                int(_m.group(1)) * 3600
                                                + int(_m.group(2)) * 60
                                                + int(_m.group(3))
                                                + int(_m.group(4)) * 0.1
                                            )
                                            break
                                        except Exception:
                                            _fb_duration = None

                            compressed = False
                            if os.path.exists(temp_file) and not self.stop_requested:
                                compressed = self._compress_to_target_size(
                                    ffmpeg_exe, temp_file, out_file,
                                    target_mb=15, log_prefix="  └─ ",
                                    duration=_fb_duration,
                                )
                            if compressed:
                                try:
                                    os.remove(temp_file)
                                except Exception:
                                    pass
                                success_count += 1
                                self.log(f"  └─ CPU 降级+压缩成功: {out_file}", "SUCCESS")
                            elif os.path.exists(temp_file) and not self.stop_requested:
                                try:
                                    os.replace(temp_file, out_file)
                                    success_count += 1
                                    self.log(f"  └─ CPU 降级成功(压缩失败): {out_file}", "WARNING")
                                except Exception:
                                    failed_count += 1
                                    self.log("  └─ 降级后移动临时文件失败", "ERROR")
                            elif os.path.exists(temp_file) and self.stop_requested:
                                # 总任务取消: 同样保留 sub_dir 给 after-loop 删
                                try:
                                    os.remove(temp_file)
                                except Exception:
                                    pass
                                if self.cancel_requested:
                                    _keep_sub_dir = True
                                    self._current_sub_dir = sub_dir
                                    break
                                _keep_sub_dir = True
                                self._current_sub_dir = sub_dir
                                continue
                            else:
                                failed_count += 1
                                self.log("  └─ 降级后临时文件不存在", "ERROR")

                            if success_count > 0 and os.path.exists(out_file):
                                cover_file = self.export_cover_image(ffmpeg_exe, out_file)
                                if cover_file:
                                    self.log(f"  └─ 封面截图已输出: {cover_file}", "SUCCESS")
                                else:
                                    self.log("  └─ 封面截图输出失败，但视频处理已成功", "WARNING")
                            # 降级路径同样要把该文件推进到下一个(否则会原地重跑同一文件)
                            idx += 1
                            self._notify_file_result(
                                single_file_mode,
                                success_count - _ok_before, failed_count - _bad_before)
                            continue

                    failed_count += 1
                    err_summary = last_error_lines[-1] if last_error_lines else "未知错误"
                    self.log(f"  └─ 处理失败 (错误码 {proc.returncode}): {err_summary}", "ERROR")

            except Exception as e:
                failed_count += 1
                self.log(f"  └─ 发生异常: {str(e)}", "ERROR")

            finally:
                # 成功 / 失败 / 异常正常完成 -> 清空当前子目录指针,
                # 防止下次取消时误删此前已成功完成的子目录
                if not _keep_sub_dir:
                    self._current_sub_dir = None

            idx += 1
            self._notify_file_result(
                single_file_mode,
                success_count - _ok_before, failed_count - _bad_before)

        # 取消时清理未完成的子目录 (PRD #3)
        if self.cancel_requested and self._current_sub_dir is not None:
            sd = self._current_sub_dir
            self._current_sub_dir = None
            if os.path.isdir(sd):
                try:
                    shutil.rmtree(sd, ignore_errors=True)
                    self.log(f"已清理未完成的子目录: {sd}", "INFO")
                except Exception as e:
                    self.log(f"清理子目录失败: {sd} ({e})", "WARNING")
            else:
                self._current_sub_dir = None

        self.progressbar["value"] = 100
        summary = f"处理完成！成功: {success_count}，失败: {failed_count}"
        if self.cancel_requested:
            summary = f"处理已取消！已完成: {success_count}，失败: {failed_count}"
        self.log(f"=== {summary} ===", "SUCCESS" if failed_count == 0 else "WARNING")
        if not single_file_mode and not self.cancel_requested:
            # 选择的是文件夹: 全部处理完之后再给一次提示音(有失败 → 失败音)
            self._play_cue("failure" if failed_count > 0 else "success")
        self.finish_processing(summary)

    def _play_cue(self, kind):
        """播放提示音(kind: 'success' / 'failure')。

        切到 UI 线程执行, 不阻塞处理线程; 播放本身失败也不影响主流程。
        """
        try:
            self.root.after(0, lambda k=kind: play_cue(k))
        except Exception:
            play_cue(kind)

    def _notify_file_result(self, single_file_mode, success_delta, failed_delta):
        """单个文件跑完后的即时提示音。

        只有"选择文件"模式在这里响; "选择文件夹"模式由 batch_worker 全部处理完
        之后统一响一次, 避免文件多时响个不停。
        """
        if not single_file_mode:
            return
        if success_delta > 0:
            self._play_cue("success")
        elif failed_delta > 0:
            self._play_cue("failure")

    def finish_processing(self, status_msg):
        self.is_processing = False
        self.stop_requested = False
        self.pause_requested = False
        self.cancel_requested = False
        self.resume_event.set()
        self.status_var.set(status_msg)
        self.start_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.stop_btn.config(text="⏸  暂停", style="Stop.TButton", command=self.stop_processing)
        self.stop_btn._button_tooltip.text = "暂停当前任务，当前文件停止后可点击继续。"

def run_selftest():
    """打包自检(--selftest): 确认单文件 exe 自带 ffmpeg/ffprobe/字体, 无需外部依赖。

    打包成无控制台窗口的程序后看不到 stdout, 所以结果同时写入
    %TEMP%\\video_batch_tool_selftest.txt。返回 0 表示自检通过。
    """
    lines = []

    def add(s=""):
        lines.append(str(s))

    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0

    add("=== 视频动态时间戳批量处理工具 自检 ===")
    add(f"frozen       : {getattr(sys, 'frozen', False)}")
    add(f"exe 目录     : {APP_DIR}")
    add(f"内置资源目录 : {getattr(sys, '_MEIPASS', '(无, 非单文件打包)')}")

    ffmpeg = find_ffmpeg_exe()
    ffprobe = find_ffprobe_exe(ffmpeg)
    font = find_font_file()
    add(f"ffmpeg       : {ffmpeg or '未找到'}")
    add(f"ffprobe      : {ffprobe or '未找到'}")
    add(f"字体         : {font or '未找到'}")

    # 来源标注 + 本机环境对比: 让"用的是内置资源还是本机安装"一目了然
    ffmpeg_src = describe_source(ffmpeg)
    add(f"ffmpeg 来源  : {ffmpeg_src}")
    add(f"ffprobe 来源 : {describe_source(ffprobe)}")
    add(f"字体来源     : {describe_source(font)}")
    local_ffmpeg = shutil.which("ffmpeg")
    local_ffprobe = shutil.which("ffprobe")
    add("--- 本机已安装环境(仅作对比; 内置/同目录资源存在时不会被使用) ---")
    add(f"本机 PATH 上的 ffmpeg : {os.path.normpath(local_ffmpeg) if local_ffmpeg else '无'}")
    add(f"本机 PATH 上的 ffprobe: {os.path.normpath(local_ffprobe) if local_ffprobe else '无'}")

    ok = True
    for name, exe in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        if not exe:
            ok = False
            add(f"[失败] {name} 缺失")
            continue
        try:
            res = subprocess.run([exe, "-hide_banner", "-version"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace",
                                 creationflags=flags, timeout=60)
            head = (res.stdout or "").strip().splitlines()
            good = res.returncode == 0
            ok = ok and good
            add(f"[{'OK' if good else '失败'}] {name} -version: {head[0] if head else '(无输出)'}")
        except Exception as e:
            ok = False
            add(f"[失败] {name} 无法执行: {e}")

    if not font or not os.path.exists(font):
        ok = False
        add("[失败] 字体文件缺失")
    else:
        add(f"[OK] 字体文件存在: {os.path.getsize(font)} bytes")

    # 真实渲染测试: 走与批处理相同的"复制到纯 ASCII 临时路径"流程, 让 ffmpeg 画一次字
    if ok and font:
        try:
            tmp_font = os.path.join(tempfile.gettempdir(), "video_batch_tool_font.ttf")
            shutil.copy2(font, tmp_font)
            esc = tmp_font.replace("\\", "/").replace(":", "\\:")
            out_png = os.path.join(tempfile.gettempdir(), "video_batch_tool_selftest.png")
            res = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-f", "lavfi",
                 "-i", "color=c=black:s=320x120:d=1", "-frames:v", "1",
                 "-vf", f"drawtext=fontfile='{esc}':text='自检 OK 12\\:34\\:56':"
                        f"fontcolor=white:fontsize=32:x=10:y=40",
                 out_png],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=flags, timeout=120)
            if res.returncode == 0 and os.path.exists(out_png):
                add(f"[OK] 时间戳字体渲染测试通过: {out_png}")
            else:
                ok = False
                tail = (res.stderr or "").strip().splitlines()
                add(f"[失败] 字体渲染测试: {tail[-1] if tail else '(无输出)'}")
        except Exception as e:
            ok = False
            add(f"[失败] 字体渲染测试异常: {e}")

    if not ok:
        add("=== 结论: 自检未通过 ===")
    elif ffmpeg_src == "系统 PATH(本机安装)":
        add("=== 结论: 自检通过, 但用的是本机 PATH 上的 ffmpeg(内置资源缺失, 请检查打包) ===")
    else:
        add(f"=== 结论: 自检通过; 实际使用 [{ffmpeg_src}] 的 ffmpeg/ffprobe/字体, 不依赖本机安装 ===")
    report = "\n".join(lines)
    try:
        dst = os.path.join(tempfile.gettempdir(), "video_batch_tool_selftest.txt")
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
    except Exception:
        pass
    try:
        print(report)
    except Exception:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    # 诊断开关(双击启动不受影响, 只在命令行显式带参数时生效):
    #   video_batch_tool.exe --selftest
    # 检查 ffmpeg/ffprobe/字体是否齐全可用(单文件打包后自检), 结果写入
    # %TEMP%\video_batch_tool_selftest.txt。
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())

    #   video_batch_tool.exe --cue-test
    # 依次播一次成功音、一次失败音, 用来确认"本机到底能不能听见提示音"。
    if "--cue-test" in sys.argv:
        play_cue("success")
        time.sleep(1.2)
        play_cue("failure")
        time.sleep(1.5)
        sys.exit(0)

    root = tk.Tk()
    app = VideoBatchToolApp(root)
    root.mainloop()
