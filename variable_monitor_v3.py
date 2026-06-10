#!/usr/bin/env python3
"""
智能车 UDP 变量监视器 v3
- 实时变量表格 + 迷你波形图 + 双向调参 + 统计/过滤/阈值/深色模式
- 接收下位机 UdpTuner::send_data() 发送的 name:value,name:value 格式
- 可向下位机 UdpTuner::receive_command() 发送调参指令
- v3 新增: MJPEG 图传 / 变量名重映射 / 变量值重映射 / 变量类型设置

by RMxiaotaobao
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import socket
import threading
import time
import csv
import platform
import json
import os
import re
from collections import deque, OrderedDict
from queue import Queue, Empty

# ══════════════════════════════════════════════════════════════ 工具函数
def get_local_ips():
    """获取本机所有网卡 IP 地址"""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = item[4][0]
            if ip not in ips and ip != "127.0.0.1":
                ips.append(ip)
    except Exception:
        pass
    if platform.system() == "Windows":
        try:
            import subprocess
            result = subprocess.run(
                ["ipconfig"], capture_output=True, text=True, encoding="gbk"
            )
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line.startswith("IPv4"):
                    parts = line.split(":")
                    if len(parts) >= 2:
                        ip = parts[1].strip().split("(")[0].strip()
                        if ip not in ips and ip != "127.0.0.1":
                            ips.append(ip)
        except Exception:
            pass
    if not ips:
        ips.append("0.0.0.0")
    ips = list(dict.fromkeys(ips))
    fallback = "0.0.0.0" if "0.0.0.0" in ips else None
    if fallback:
        ips.remove(fallback)
    ips_sorted = sorted(ips, key=lambda x: (not x.startswith("192.168"), x))
    if fallback:
        ips_sorted.append(fallback)
    return ips_sorted


def guess_stream_url(local_ip):
    """根据本机 IP 推断板子图传地址（末段改为 1）"""
    parts = local_ip.split(".")
    if len(parts) == 4:
        parts[3] = "1"
        return "http://{}:8080/stream".format(".".join(parts))
    return "http://192.168.1.1:8080/stream"


def get_app_dir():
    """获取应用程序所在目录（打包后为exe所在目录，开发时为脚本所在目录）"""
    import sys
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_config_path():
    """获取配置文件完整路径"""
    return os.path.join(get_app_dir(), "config.json")


def load_config(path=None):
    """加载配置文件，缺失字段用默认值填充"""
    if path is None:
        path = get_config_path()
    default = {
        "udp_port": 8080,
        "display_mode": 1,
        "stream_url": "",
        "name_map": {},
        "value_map": {},
        "var_types": {},
        "channels": 6,
        "channel_colors": [
            "#1a6aff", "#ff4444", "#22aa22", "#ff8800",
            "#aa44ff", "#00bbbb", "#ff44aa", "#888800",
            "#44aaff", "#ff6644", "#44cc44", "#cc8800",
        ],
        "only_newest": False,
        "only_newest_count": 8,
        "stream_width": 640,
        "stream_height": 480,
    }
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in default.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except Exception:
            pass
    return default


def save_config(cfg, path="config.json"):
    """保存配置到文件"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True, None
    except Exception as e:
        return False, e


# ══════════════════════════════════════════════════════════════ 配色主题
THEMES = {
    "light": {
        "bg": "#f0f0f0", "fg": "#000000",
        "tree_bg": "#ffffff", "tree_fg": "#000000",
        "tree_selected": "#cce5ff",
        "chart_bg": "#ffffff", "chart_line": "#1a6aff", "chart_grid": "#e0e0e0",
        "positive_fg": "#0055cc", "negative_fg": "#cc2200",
        "alert_bg": "#ffe0e0", "pinned_bg": "#e0f0ff",
        "entry_bg": "#ffffff", "entry_fg": "#000000",
        "frame_bg": "#f0f0f0", "status_fg": "#333333",
    },
    "dark": {
        "bg": "#1e1e2e", "fg": "#cdd6f4",
        "tree_bg": "#1e1e2e", "tree_fg": "#cdd6f4",
        "tree_selected": "#45475a",
        "chart_bg": "#181825", "chart_line": "#89b4fa", "chart_grid": "#313244",
        "positive_fg": "#89b4fa", "negative_fg": "#f38ba8",
        "alert_bg": "#45273a", "pinned_bg": "#1e3a5f",
        "entry_bg": "#313244", "entry_fg": "#cdd6f4",
        "frame_bg": "#1e1e2e", "status_fg": "#a6adc8",
    },
}

CURVE_COLORS = [
    "#1a6aff", "#ff4444", "#22aa22", "#ff8800",
    "#aa44ff", "#00bbbb", "#ff44aa", "#888800",
    "#44aaff", "#ff6644", "#44cc44", "#cc8800",
]


# ══════════════════════════════════════════════════════════════ 视频流类
class VideoStream:
    """MJPEG 视频流读取器（后台线程读取，Tk 主界面显示）"""

    def __init__(self, url, window_name="图传", config=None):
        self.url = url
        self.window_name = window_name
        self.config = config or {}
        self._running = False
        self.thread = None
        self.cap = None
        self.frame = None
        self.frame_id = 0
        self.lock = threading.Lock()
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.screenshot_dir = "screenshots"
        self.error_msg = ""
        self.status_msg = ""
        self._stopping = False
        self.stream_resolution = ""

    @property
    def running(self):
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        self._stopping = False
        self.error_msg = ""
        self.status_msg = "连接中..."
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        """安全停止：先设标志，等线程自行退出"""
        if not self._running:
            return
        self._stopping = True
        self._running = False
        # 释放 cap，让阻塞的 read() 返回
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        # 等线程退出（最多 0.5 秒）。读流阻塞时不等待，避免卡住 UI。
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)

    def _loop(self):
        print(f"[图传] 线程启动, url={self.url}")
        try:
            import cv2
            print(f"[图传] cv2 导入成功: {cv2.__version__}")
        except ImportError as e:
            self.error_msg = f"未安装 OpenCV: {e}"
            print(f"[图传] {self.error_msg}")
            self._running = False
            return
        except Exception as e:
            self.error_msg = f"导入错误: {type(e).__name__}: {e}"
            print(f"[图传] {self.error_msg}")
            self._running = False
            return

        RETRY_INTERVAL = 0.5
        read_fail_count = 0
        read_fail_threshold = 2
        first_frame = True

        def _try_connect():
            """尝试连接，返回 (cap, success)"""
            try:
                cap = cv2.VideoCapture(self.url)
                try:
                    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 800)
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 800)
                except Exception:
                    pass
                if cap.isOpened():
                    return cap, True
            except Exception:
                pass
            return None, False

        def _wait(seconds):
            """分段等待，True=应退出"""
            steps = max(1, int(seconds * 20))
            for _ in range(steps):
                if not self._running or self._stopping:
                    return True
                time.sleep(seconds / steps)
            return False

        print(f"[图传] 启动, url={self.url}")

        # ── 主循环 ──
        while self._running:

            # ── 连接阶段 ──
            if self.cap is None:
                self.status_msg = "连接中..."
                cap, ok = _try_connect()
                if ok:
                    self.cap = cap
                    read_fail_count = 0
                    first_frame = True
                    self.status_msg = "已连接"
                    self.error_msg = ""
                    print("[图传] 连接成功")
                    continue
                else:
                    if cap:
                        try: cap.release()
                        except: pass
                    if _wait(RETRY_INTERVAL):
                        break
                    continue

            # ── 读帧阶段 ──
            ret, frame = self._safe_read()

            if ret and frame is not None:
                read_fail_count = 0
                with self.lock:
                    self.frame = frame
                    self.frame_id += 1

                # 首帧：记录分辨率
                if first_frame:
                    first_frame = False
                    fh, fw = frame.shape[:2]
                    self.config["stream_width"] = fw
                    self.config["stream_height"] = fh
                    ok, err = save_config(self.config, get_config_path())
                    if not ok:
                        print(f"[图传] 保存配置失败: {err}")
                    print(f"[图传] 分辨率: {fw}x{fh}")

                # FPS 计算
                self.frame_count += 1
                now = time.time()
                elapsed = now - self.last_fps_time
                if elapsed >= 1.0:
                    self.fps = self.frame_count / elapsed
                    self.frame_count = 0
                    self.last_fps_time = now

                # 记录分辨率供 UI 显示
                h, w = frame.shape[:2]
                self.stream_resolution = f"{w}x{h}"
                self.status_msg = "已连接"
            else:
                # 读帧失败
                read_fail_count += 1
                if self._stopping:
                    break
                if read_fail_count >= read_fail_threshold:
                    print("[图传] 断联，自动重连")
                    self.status_msg = "断联重连中..."
                    if self.cap:
                        try: self.cap.release()
                        except: pass
                        self.cap = None
                    if _wait(RETRY_INTERVAL):
                        break
                else:
                    time.sleep(0.02)

        # 清理
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self._running = False
        self.status_msg = "已停止"
        print("[图传] 线程已退出")

    def _safe_read(self):
        """读取一帧。运行在后台线程，不能阻塞 Tk 主线程。"""
        try:
            if self.cap and self.cap.isOpened():
                return self.cap.read()
        except Exception:
            pass
        return False, None

    @staticmethod
    def _make_status_image(cv2, w, h, lines, color):
        """生成状态提示画面（黑底+居中文字，支持中文）"""
        import numpy as np
        img = np.zeros((h, w, 3), dtype=np.uint8)
        if isinstance(lines, str):
            lines = [lines]

        # 用 PIL 渲染中文
        try:
            from PIL import Image, ImageDraw, ImageFont
            pil_img = Image.fromarray(img)
            draw = ImageDraw.Draw(pil_img)
            # 尝试加载中文字体
            font = None
            for font_path in [
                "C:/Windows/Fonts/msyh.ttc",    # 微软雅黑
                "C:/Windows/Fonts/simhei.ttf",   # 黑体
                "C:/Windows/Fonts/simsun.ttc",   # 宋体
            ]:
                try:
                    font = ImageFont.truetype(font_path, 22)
                    break
                except Exception:
                    continue
            if font is None:
                font = ImageFont.load_default()

            total_h = len(lines) * 36
            y0 = (h - total_h) // 2
            for i, line in enumerate(lines):
                y = y0 + i * 36
                bbox = draw.textbbox((0, 0), line, font=font)
                tw = bbox[2] - bbox[0]
                x = (w - tw) // 2
                # PIL 颜色是 RGB, OpenCV 是 BGR
                pil_color = (color[2], color[1], color[0])
                draw.text((x, y), line, fill=pil_color, font=font)
            return np.array(pil_img)
        except ImportError:
            # PIL 不可用，回退到 cv2（只支持英文）
            total_h = len(lines) * 36
            y0 = (h - total_h) // 2
            for i, line in enumerate(lines):
                y = y0 + i * 36
                # 只保留 ASCII 字符
                safe_line = line.encode("ascii", "ignore").decode("ascii")
                if not safe_line:
                    safe_line = "[text]"
                (tw, th), _ = cv2.getTextSize(safe_line, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                x = (w - tw) // 2
                cv2.putText(img, safe_line, (x, y + th), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            return img

    def _save_screenshot(self, frame):
        import cv2
        os.makedirs(self.screenshot_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.screenshot_dir, f"snap_{ts}.png")
        cv2.imwrite(path, frame)

    def get_frame(self):
        """获取最新帧（供外部使用）"""
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def get_frame_snapshot(self):
        """获取最新帧和帧序号。序号不变表示没有新帧。"""
        with self.lock:
            if self.frame is None:
                return None, self.frame_id
            return self.frame.copy(), self.frame_id


# ══════════════════════════════════════════════════════════════ 变量记录
class VarRecord:
    """单个变量的完整记录"""
    __slots__ = ("name", "display_name", "var_type", "value", "prev",
                 "history", "time_history", "start_time",
                 "min", "max", "sum", "count",
                 "alert_min", "alert_max", "pinned", "alert_triggered")

    def __init__(self, name, maxlen=300):
        self.name = name
        self.display_name = name       # 显示名（可被映射覆盖）
        self.var_type = "auto"         # auto / int / float / float2 / float3 / bool / enum
        self.value = None
        self.prev = None
        self.history = deque(maxlen=maxlen)
        self.time_history = deque(maxlen=maxlen)
        self.start_time = None
        self.min = None
        self.max = None
        self.sum = 0.0
        self.count = 0
        self.alert_min = None
        self.alert_max = None
        self.pinned = False
        self.alert_triggered = False

    def update(self, val):
        self.prev = self.value
        self.value = val
        if isinstance(val, (int, float)):
            now = time.time()
            if self.start_time is None:
                self.start_time = now
            self.history.append(val)
            self.time_history.append(now - self.start_time)
            self.count += 1
            self.sum += val
            if self.min is None or val < self.min:
                self.min = val
            if self.max is None or val > self.max:
                self.max = val
            self.alert_triggered = False
            if self.alert_min is not None and val < self.alert_min:
                self.alert_triggered = True
            if self.alert_max is not None and val > self.alert_max:
                self.alert_triggered = True

    @property
    def avg(self):
        return self.sum / self.count if self.count else None

    def reset_stats(self):
        self.min = None
        self.max = None
        self.sum = 0.0
        self.count = 0
        self.history.clear()
        self.time_history.clear()
        self.start_time = None

    def resize_history(self, new_maxlen):
        if self.history.maxlen == new_maxlen:
            return
        old_vals = list(self.history)
        old_times = list(self.time_history)
        self.history = deque(old_vals, maxlen=new_maxlen)
        self.time_history = deque(old_times, maxlen=new_maxlen)


# ══════════════════════════════════════════════════════════════ 主程序
class VariableMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("Genesis 智能车队 UDP 图传调试助手  by RMxiaotaobao")
        self.root.geometry("960x680")
        self.root.minsize(700, 420)

        # 加载配置
        self.config_path = get_config_path()
        self.config = load_config(self.config_path)

        # 状态
        self.running = False
        self.paused = False
        self.sock = None
        self.recv_thread = None
        self.recv_queue = Queue()
        self.variables = OrderedDict()
        self.recv_count = 0
        self.last_recv_time = 0
        self.car_addr = None
        self.csv_logging = False
        self.csv_file = None
        self.csv_writer = None
        self.csv_start_time = None
        self.selected_var = None
        self.chart_vars = []
        self.dashboard_vars = []
        self.chart_mode = "single"
        self.zoom_level = 0
        self.view_right_edge = None
        self.auto_follow = True
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_edge = 0
        self.max_history = 300
        self.theme_name = "light"
        self.theme = THEMES["light"]
        self.refresh_interval = 100
        self.refresh_after_id = None

        # 映射表（从配置加载）
        self.name_map = dict(self.config.get("name_map", {}))
        self.value_map = {}  # {var_name: {raw_val: display_val}}
        for k, v in self.config.get("value_map", {}).items():
            self.value_map[k] = {str(sk): str(sv) for sk, sv in v.items()}
        self.var_types = dict(self.config.get("var_types", {}))

        # 视频流
        self.video_stream = None
        self.stream_url = self.config.get("stream_url", "")
        self.stream_after_id = None
        self.stream_last_frame_id = -1
        self.stream_render_fps = 0
        self.stream_render_count = 0
        self.stream_render_last_time = time.time()

        self._build_ui()
        self._apply_theme()
        self._refresh_table()

    def _save_config_or_alert(self):
        ok, err = save_config(self.config, self.config_path)
        if not ok:
            messagebox.showerror("保存失败", str(err))
        return ok

    def _clear_recv_queue(self):
        while True:
            try:
                self.recv_queue.get_nowait()
            except Empty:
                break

    # ─────────────────────────────────────────────────────────── UI 构建
    def _build_ui(self):
        # ---- 顶部工具栏 ----
        toolbar = ttk.Frame(self.root, padding=4)
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="本机 IP:").pack(side=tk.LEFT)
        self.ip_combo = ttk.Combobox(toolbar, width=16, values=get_local_ips(), state="readonly")
        self.ip_combo.pack(side=tk.LEFT, padx=(2, 6))
        ips = get_local_ips()
        if ips:
            self.ip_combo.set(ips[0])

        ttk.Label(toolbar, text="端口:").pack(side=tk.LEFT)
        self.port_entry = ttk.Entry(toolbar, width=7)
        self.port_entry.insert(0, str(self.config.get("udp_port", 8080)))
        self.port_entry.pack(side=tk.LEFT, padx=(2, 6))

        self.connect_btn = ttk.Button(toolbar, text="▶ 连接", width=8, command=self._toggle_connection)
        self.connect_btn.pack(side=tk.LEFT, padx=2)

        self.pause_btn = ttk.Button(toolbar, text="⏸ 暂停", width=8, command=self._toggle_pause)
        self.pause_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self.csv_btn = ttk.Button(toolbar, text="📄 CSV", width=6, command=self._toggle_csv)
        self.csv_btn.pack(side=tk.LEFT, padx=2)

        self.clear_btn = ttk.Button(toolbar, text="🗑 清空", width=6, command=self._clear_table)
        self.clear_btn.pack(side=tk.LEFT, padx=2)

        self.theme_btn = ttk.Button(toolbar, text="🌙 深色", width=6, command=self._toggle_theme)
        self.theme_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self.chart_mode_btn = ttk.Button(toolbar, text="📊 单曲线", width=9, command=self._toggle_chart_mode)
        self.chart_mode_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # 图传按钮
        self.stream_btn = ttk.Button(toolbar, text="📷 图传", width=7, command=self._toggle_stream)
        self.stream_btn.pack(side=tk.LEFT, padx=2)

        # 设置按钮
        self.settings_btn = ttk.Button(toolbar, text="⚙ 设置", width=7, command=self._open_settings)
        self.settings_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(toolbar, text="刷新:").pack(side=tk.LEFT)
        self.refresh_combo = ttk.Combobox(
            toolbar, width=8, state="readonly",
            values=["最快", "50ms", "100ms", "200ms", "500ms", "1s", "2s"]
        )
        self.refresh_combo.set("100ms")
        self.refresh_combo.pack(side=tk.LEFT, padx=(2, 0))
        self.refresh_combo.bind("<<ComboboxSelected>>", lambda _: self._on_refresh_rate_changed())

        ttk.Label(toolbar, text=" 数据量:").pack(side=tk.LEFT)
        self.hist_combo = ttk.Combobox(
            toolbar, width=6, state="readonly",
            values=["300", "500", "1000", "2000", "5000"]
        )
        self.hist_combo.set("300")
        self.hist_combo.pack(side=tk.LEFT, padx=(2, 0))
        self.hist_combo.bind("<<ComboboxSelected>>", lambda _: self._on_history_len_changed())

        # ---- 图传地址栏 ----
        stream_bar = ttk.Frame(self.root, padding=(8, 2))
        stream_bar.pack(fill=tk.X)

        ttk.Label(stream_bar, text="图传地址:").pack(side=tk.LEFT)
        self.stream_url_var = tk.StringVar()
        default_stream_url = self.config.get("stream_url", "").strip()
        if not default_stream_url:
            ip = self.ip_combo.get() if self.ip_combo.get() else "192.168.1.1"
            default_stream_url = guess_stream_url(ip)
        self.stream_url_var.set(default_stream_url)
        self.stream_url_entry = ttk.Entry(stream_bar, textvariable=self.stream_url_var, width=52)
        self.stream_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6))
        self.stream_url_entry.bind("<Return>", lambda _event: self._refresh_stream())
        self.stream_refresh_btn = ttk.Button(stream_bar, text="刷新图传", width=10, command=self._refresh_stream)
        self.stream_refresh_btn.pack(side=tk.LEFT)

        # ---- 搜索栏 ----
        search_bar = ttk.Frame(self.root, padding=(8, 2))
        search_bar.pack(fill=tk.X)

        ttk.Label(search_bar, text="🔍").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        self.search_entry = ttk.Entry(search_bar, textvariable=self.search_var, width=20)
        self.search_entry.pack(side=tk.LEFT, padx=4)
        ttk.Label(search_bar, text="（支持原始名/显示名搜索）", foreground="gray").pack(side=tk.LEFT)

        # ---- 中部：变量表格 ----
        tree_frame = ttk.Frame(self.root, padding=4)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("name", "display", "value", "prev", "delta", "min", "max", "avg")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name",    text="原始名")
        self.tree.heading("display", text="显示名")
        self.tree.heading("value",   text="当前值")
        self.tree.heading("prev",    text="上次值")
        self.tree.heading("delta",   text="变化量")
        self.tree.heading("min",     text="Min")
        self.tree.heading("max",     text="Max")
        self.tree.heading("avg",     text="Avg")
        self.tree.column("name",    width=100, anchor=tk.W)
        self.tree.column("display", width=110, anchor=tk.W)
        self.tree.column("value",   width=90,  anchor=tk.CENTER)
        self.tree.column("prev",    width=80,  anchor=tk.CENTER)
        self.tree.column("delta",   width=80,  anchor=tk.CENTER)
        self.tree.column("min",     width=80,  anchor=tk.CENTER)
        self.tree.column("max",     width=80,  anchor=tk.CENTER)
        self.tree.column("avg",     width=80,  anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Button-3>", self._on_right_click)

        # ---- 下半部：波形图 + 发送面板 ----
        self.bottom_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.bottom_pane.pack(fill=tk.BOTH, expand=True, pady=(0, 0))

        self.chart_frame = ttk.LabelFrame(self.bottom_pane, text="波形图（点击表格变量查看）", padding=4)
        self.chart_canvas = tk.Canvas(self.chart_frame, height=140, bg="#ffffff", highlightthickness=0)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True)

        slider_frame = ttk.Frame(self.chart_frame)
        slider_frame.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(slider_frame, text="◀ 时间轴 ▶", font=("Consolas", 7)).pack(side=tk.LEFT)
        self.time_slider = ttk.Scale(slider_frame, from_=0, to=1, orient=tk.HORIZONTAL,
                                      command=self._on_slider_move)
        self.time_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.slider_label = ttk.Label(slider_frame, text="", font=("Consolas", 7), foreground="gray")
        self.slider_label.pack(side=tk.LEFT)

        self.chart_canvas.bind("<MouseWheel>", self._on_chart_scroll)
        self.chart_canvas.bind("<Button-4>",   self._on_chart_scroll_up)
        self.chart_canvas.bind("<Button-5>",   self._on_chart_scroll_down)
        self.chart_canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.chart_canvas.bind("<B1-Motion>",     self._on_drag_move)
        self.chart_canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        self.bottom_pane.add(self.chart_frame, weight=3)

        # 发送面板
        self.send_frame = ttk.LabelFrame(self.bottom_pane, text="发送调参指令", padding=4)
        send_frame = self.send_frame
        ttk.Label(send_frame, text="变量名:").grid(row=0, column=0, sticky=tk.W)
        self.send_name_entry = ttk.Entry(send_frame, width=12)
        self.send_name_entry.grid(row=0, column=1, padx=2)
        ttk.Label(send_frame, text="值:").grid(row=0, column=2, sticky=tk.W)
        self.send_value_entry = ttk.Entry(send_frame, width=10)
        self.send_value_entry.grid(row=0, column=3, padx=2)
        self.send_btn = ttk.Button(send_frame, text="发送", command=self._send_command)
        self.send_btn.grid(row=0, column=4, padx=4)

        ttk.Label(send_frame, text="多参数（name:val,name:val）:").grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(4,0))
        self.send_batch_entry = ttk.Entry(send_frame, width=36)
        self.send_batch_entry.grid(row=1, column=3, columnspan=2, padx=2, pady=(4,0))

        self.car_addr_label = ttk.Label(send_frame, text="下位机地址: 未检测到", foreground="gray")
        self.car_addr_label.grid(row=2, column=0, columnspan=5, sticky=tk.W, pady=(4,0))

        ttk.Label(send_frame, text="💡 点击表格变量自动填入名称", foreground="gray").grid(
            row=3, column=0, columnspan=5, sticky=tk.W, pady=(2,0))
        self.bottom_pane.add(send_frame, weight=2)

        # 内嵌图传面板。打开图传时替换右下角发送面板。
        self.stream_frame = ttk.LabelFrame(self.bottom_pane, text="图传", padding=4)
        stream_toolbar = ttk.Frame(self.stream_frame)
        stream_toolbar.pack(fill=tk.X)
        self.stream_panel_status = ttk.Label(stream_toolbar, text="未连接", foreground="gray")
        self.stream_panel_status.pack(side=tk.LEFT)
        ttk.Button(stream_toolbar, text="关闭", width=6, command=self._toggle_stream).pack(side=tk.RIGHT)

        self.stream_canvas = tk.Canvas(self.stream_frame, width=320, height=180,
                                       bg="#111111", highlightthickness=0)
        self.stream_canvas.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.stream_canvas.create_text(160, 90, text="图传未开启", fill="#aaaaaa", tags=("status",))
        self.stream_photo = None
        self.stream_canvas.bind("<Configure>", lambda _event: self._render_stream_frame())

        # ---- 底部状态栏 ----
        status = ttk.Frame(self.root, padding=(4, 2))
        status.pack(fill=tk.X)

        self.status_label = ttk.Label(status, text="未连接")
        self.status_label.pack(side=tk.LEFT)

        self.recv_label = ttk.Label(status, text="接收: 0")
        self.recv_label.pack(side=tk.LEFT, padx=16)

        self.var_count_label = ttk.Label(status, text="变量: 0")
        self.var_count_label.pack(side=tk.LEFT, padx=16)

        self.stream_status = ttk.Label(status, text="", foreground="gray")
        self.stream_status.pack(side=tk.LEFT, padx=16)

        self.rate_label = ttk.Label(status, text="")
        self.rate_label.pack(side=tk.RIGHT, padx=8)

        ttk.Label(status, text="by RMxiaotaobao", foreground="gray").pack(side=tk.RIGHT, padx=8)

    # ─────────────────────────────────────────────────────────── 主题
    def _toggle_theme(self):
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.theme = THEMES[self.theme_name]
        self.theme_btn.config(text="☀ 浅色" if self.theme_name == "dark" else "🌙 深色")
        self._apply_theme()

    def _apply_theme(self):
        t = self.theme
        self.root.configure(bg=t["bg"])
        self.chart_canvas.configure(bg=t["chart_bg"])
        style = ttk.Style()
        style.configure("Treeview",
                        background=t["tree_bg"], foreground=t["tree_fg"],
                        fieldbackground=t["tree_bg"])
        style.configure("Treeview.Heading",
                        background=t["bg"], foreground=t["fg"])
        style.map("Treeview",
                  background=[("selected", t["tree_selected"])])
        style.configure("TEntry",
                        fieldbackground=t["entry_bg"], foreground=t["entry_fg"])
        style.configure("TLabel", background=t["bg"], foreground=t["fg"])
        style.configure("TLabelframe", background=t["bg"], foreground=t["fg"])
        style.configure("TLabelframe.Label", background=t["bg"], foreground=t["fg"])
        style.configure("TFrame", background=t["bg"])
        style.configure("TButton", background=t["bg"])
        self._redraw_chart()

    # ─────────────────────────────────────────────────────────── 连接管理
    def _toggle_connection(self):
        if self.running:
            self._stop_listening()
        else:
            self._start_listening()

    def _start_listening(self):
        ip = self.ip_combo.get()
        try:
            port = int(self.port_entry.get())
        except ValueError:
            messagebox.showerror("错误", "端口号必须是整数")
            return
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((ip, port))
            self.sock.settimeout(1.0)
        except Exception as e:
            messagebox.showerror("绑定失败", str(e))
            return

        self.running = True
        self.recv_count = 0
        self.car_addr = None
        self._clear_recv_queue()
        self.car_addr_label.config(text="下位机地址: 未检测到", foreground="gray")
        self.recv_thread = threading.Thread(target=self._udp_recv_loop, daemon=True)
        self.recv_thread.start()

        self.connect_btn.config(text="⏹ 断开")
        self.status_label.config(text=f"监听中 {ip}:{port}")
        self.ip_combo.config(state="disabled")
        self.port_entry.config(state="disabled")

    def _stop_listening(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connect_btn.config(text="▶ 连接")
        self.status_label.config(text="未连接")
        self.car_addr = None
        self._clear_recv_queue()
        self.car_addr_label.config(text="下位机地址: 未检测到", foreground="gray")
        self.ip_combo.config(state="readonly")
        self.port_entry.config(state="normal")

    # ─────────────────────────────────────────────────────────── 暂停
    def _toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.config(text="▶ 继续" if self.paused else "⏸ 暂停")

    # ─────────────────────────────────────────────────────────── UDP 接收
    def _udp_recv_loop(self):
        while self.running:
            try:
                sock = self.sock
                if sock is None:
                    break
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except (AttributeError, OSError):
                break

            try:
                text = data.decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            if not text:
                continue

            self.recv_queue.put((text, addr, time.time()))

    def _drain_recv_queue(self):
        updated = False
        while True:
            try:
                text, addr, recv_time = self.recv_queue.get_nowait()
            except Empty:
                break

            if self.car_addr != addr:
                self.car_addr = addr
                self.car_addr_label.config(text=f"下位机地址: {addr[0]}:{addr[1]}", foreground="green")

            self._parse_data(text)
            self.recv_count += 1
            self.last_recv_time = recv_time
            updated = True
        return updated

    def _parse_data(self, data_str):
        pairs = data_str.split(",")
        for pair in pairs:
            pair = pair.strip()
            if ":" not in pair:
                continue
            colon_pos = pair.index(":")
            name = pair[:colon_pos].strip()
            value_str = pair[colon_pos + 1:].strip()
            if not name:
                continue
            try:
                value = float(value_str)
                if value == int(value) and "." not in value_str:
                    value = int(value)
            except ValueError:
                value = value_str

            if name not in self.variables:
                rec = VarRecord(name, maxlen=self.max_history)
                # 应用名称映射
                if name in self.name_map:
                    rec.display_name = self.name_map[name]
                # 应用类型设置
                if name in self.var_types:
                    rec.var_type = self.var_types[name]
                self.variables[name] = rec
            self.variables[name].update(value)

            # CSV
            if self.csv_logging and self.csv_writer:
                now = time.time()
                ts = time.strftime("%H:%M:%S") + f".{int(now*1000)%1000:03d}"
                t_s = f"{now - self.csv_start_time:.3f}" if self.csv_start_time else "0.000"
                rec = self.variables[name]
                display = rec.display_name if rec.display_name != name else name
                try:
                    self.csv_writer.writerow([ts, t_s, name, display, value])
                    self.csv_file.flush()
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────── 值格式化
    def _format_value(self, rec, raw_val):
        """根据变量类型和值映射格式化显示值"""
        if raw_val is None:
            return "-"

        name = rec.name

        # 值映射优先
        if name in self.value_map and str(raw_val) in self.value_map[name]:
            return self.value_map[name][str(raw_val)]

        # 类型格式化
        vtype = rec.var_type
        if vtype == "bool":
            if isinstance(raw_val, (int, float)):
                return "True" if raw_val != 0 else "False"
            return str(raw_val)
        elif vtype == "int":
            if isinstance(raw_val, (int, float)):
                return str(int(raw_val))
            return str(raw_val)
        elif vtype == "float1":
            if isinstance(raw_val, (int, float)):
                return f"{raw_val:.1f}"
            return str(raw_val)
        elif vtype == "float":
            if isinstance(raw_val, (int, float)):
                return f"{raw_val:.1f}"
            return str(raw_val)
        elif vtype == "float2":
            if isinstance(raw_val, (int, float)):
                return f"{raw_val:.2f}"
            return str(raw_val)
        elif vtype == "float3":
            if isinstance(raw_val, (int, float)):
                return f"{raw_val:.3f}"
            return str(raw_val)
        elif vtype == "enum":
            # enum 类型但没有值映射，显示原始值
            if isinstance(raw_val, (int, float)):
                return str(int(raw_val)) if raw_val == int(raw_val) else f"{raw_val:.3f}"
            return str(raw_val)
        else:  # auto
            if isinstance(raw_val, float):
                return f"{raw_val:.3f}"
            return str(raw_val)

    def _format_delta(self, rec, cur, prev):
        if not isinstance(cur, (int, float)) or not isinstance(prev, (int, float)):
            return ""
        d = cur - prev
        vtype = rec.var_type
        if vtype in ("float1", "float"):
            return f"{d:+.1f}"
        elif vtype == "float2":
            return f"{d:+.2f}"
        elif vtype == "int":
            return f"{int(d):+d}"
        return f"{d:+.3f}"

    # ─────────────────────────────────────────────────────────── 发送指令
    def _send_command(self):
        if not self.running or not self.sock:
            messagebox.showinfo("提示", "请先连接")
            return
        if not self.car_addr:
            messagebox.showinfo("提示", "尚未收到下位机数据，无法确定目标地址")
            return

        batch = self.send_batch_entry.get().strip()
        if batch:
            msg = batch
        else:
            name = self.send_name_entry.get().strip()
            val = self.send_value_entry.get().strip()
            if not name or not val:
                messagebox.showinfo("提示", "请输入变量名和值")
                return
            msg = f"{name}:{val}"

        try:
            data = msg.encode("utf-8")
            self.sock.sendto(data, self.car_addr)
        except Exception as e:
            messagebox.showerror("发送失败", str(e))

    # ─────────────────────────────────────────────────────────── 刷新频率
    def _on_refresh_rate_changed(self):
        sel = self.refresh_combo.get()
        if sel == "最快":
            self.refresh_interval = 0
        else:
            self.refresh_interval = int(sel.replace("ms", ""))

    def _on_history_len_changed(self):
        self.max_history = int(self.hist_combo.get())
        for rec in self.variables.values():
            rec.resize_history(self.max_history)

    # ─────────────────────────────────────────────────────────── 表格刷新
    def _refresh_table(self):
        has_new_data = self._drain_recv_queue()
        if not self.paused:
            self.recv_label.config(text=f"接收: {self.recv_count}")
            self.var_count_label.config(text=f"变量: {len(self.variables)}")
            if self.last_recv_time > 0:
                elapsed = time.time() - self.last_recv_time
                color = "green" if elapsed < 1.5 else ("orange" if elapsed < 5 else "red")
                self.rate_label.config(text=f"最新: {elapsed:.1f}s 前", foreground=color)
            else:
                self.rate_label.config(text="")

            # 视频流状态
            if self.video_stream:
                if self.video_stream.running:
                    fps = self.video_stream.fps
                    res = self.video_stream.stream_resolution
                    parts = []
                    if fps > 0:
                        parts.append(f"{fps:.0f}fps")
                    if res:
                        parts.append(res)
                    info = " ".join(parts) if parts else "已连接"
                    self.stream_status.config(text=f"图传: {info}", foreground="green")
                elif self.video_stream.error_msg:
                    self.stream_status.config(text=f"图传: {self.video_stream.error_msg}", foreground="red")
                else:
                    self.stream_status.config(text="图传: 连接中...", foreground="orange")
            else:
                self.stream_status.config(text="")

            if has_new_data or self.variables:
                self._rebuild_tree()

        interval = self.refresh_interval if self.refresh_interval > 0 else 1
        self.refresh_after_id = self.root.after(interval, self._refresh_table)

    def _rebuild_tree(self):
        search = self.search_var.get().strip().lower()

        sorted_names = sorted(self.variables.keys(),
                               key=lambda n: (not self.variables[n].pinned, n))

        for item in self.tree.get_children():
            self.tree.delete(item)

        t = self.theme
        for name in sorted_names:
            rec = self.variables[name]
            # 搜索过滤（支持原始名和显示名）
            if search:
                match_name = search in name.lower()
                match_display = search in rec.display_name.lower()
                if not match_name and not match_display:
                    continue

            display_name = rec.display_name
            val_str = self._format_value(rec, rec.value)
            prev_str = self._format_value(rec, rec.prev) if rec.prev is not None else "-"
            delta_str = self._format_delta(rec, rec.value, rec.prev)
            min_str = self._format_value(rec, rec.min) if rec.min is not None else "-"
            max_str = self._format_value(rec, rec.max) if rec.max is not None else "-"
            avg_str = self._format_value(rec, rec.avg) if rec.avg is not None else "-"

            tags = ()
            if rec.alert_triggered:
                tags = ("alert",)
            elif rec.pinned:
                tags = ("pinned",)
            elif isinstance(rec.value, (int, float)) and isinstance(rec.prev, (int, float)) and rec.value != rec.prev:
                tags = ("positive" if rec.value > rec.prev else "negative",)

            self.tree.insert("", tk.END,
                             iid=name,
                             values=(name, display_name, val_str, prev_str, delta_str, min_str, max_str, avg_str),
                             tags=tags)

        self.tree.tag_configure("positive", foreground=t["positive_fg"])
        self.tree.tag_configure("negative", foreground=t["negative_fg"])
        self.tree.tag_configure("alert",    background=t["alert_bg"])
        self.tree.tag_configure("pinned",   background=t["pinned_bg"])

        if self.selected_var and self.selected_var in self.variables:
            try:
                self.tree.selection_set(self.selected_var)
                self.tree.see(self.selected_var)
            except tk.TclError:
                pass

        self._redraw_chart()

    def _apply_filter(self):
        if not self.paused:
            self._rebuild_tree()

    # ─────────────────────────────────────────────────────────── 波形图
    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        if sel:
            self.selected_var = sel[0]
            self._redraw_chart()
            self.send_name_entry.delete(0, tk.END)
            self.send_name_entry.insert(0, self.selected_var)
            rec = self.variables.get(self.selected_var)
            if rec and isinstance(rec.value, (int, float)):
                self.send_value_entry.delete(0, tk.END)
                self.send_value_entry.insert(0, f"{rec.value:.3f}")

    def _redraw_chart(self):
        if self.chart_mode == "single":
            if self.selected_var and self.selected_var in self.variables:
                self._draw_chart(self.selected_var)
            else:
                self.chart_canvas.delete("all")
        elif self.chart_mode == "overlay":
            self._draw_overlay_chart()
        else:
            self._draw_dashboard()

    def _draw_chart(self, var_name):
        c = self.chart_canvas
        c.delete("all")
        rec = self.variables.get(var_name)
        if not rec or not rec.history:
            c.create_text(c.winfo_width() // 2, 70, text="暂无数据",
                          fill=self.theme["fg"], font=("Arial", 11))
            return

        w = c.winfo_width()
        h = c.winfo_height()
        if w < 20 or h < 20:
            return

        data = list(rec.history)
        times = list(rec.time_history)
        data_t_min, data_t_max = times[0], times[-1]

        view_left, view_right = self._calc_view_window(data_t_min, data_t_max)
        view_range = view_right - view_left if view_right != view_left else 1.0

        vis_vals = [v for v, t in zip(data, times) if view_left <= t <= view_right]
        if not vis_vals:
            vis_vals = [data[-1]]

        v_min = min(vis_vals)
        v_max = max(vis_vals)
        v_range = v_max - v_min if v_max != v_min else 1.0

        pad_l, pad_r, pad_t, pad_b = 50, 10, 20, 24
        cw = w - pad_l - pad_r
        ch = h - pad_t - pad_b
        t = self.theme

        for i in range(5):
            y = pad_t + ch * i / 4
            c.create_line(pad_l, y, w - pad_r, y, fill=t["chart_grid"], dash=(2, 4))
            val = v_max - (v_range * i / 4)
            c.create_text(pad_l - 4, y, anchor=tk.E, text=f"{val:.2f}",
                          fill=t["fg"], font=("Consolas", 7))

        self._draw_time_axis(c, [view_left, view_right], pad_l, pad_r, cw, h - pad_b, w)

        display = rec.display_name if rec.display_name != var_name else var_name
        avg_str = f"  avg={rec.avg:.2f}" if rec.avg is not None else ""
        c.create_text(pad_l + 4, 8, anchor=tk.W,
                      text=f"{display}  [{v_min:.2f} ~ {v_max:.2f}]{avg_str}",
                      fill=t["fg"], font=("Arial", 9, "bold"))

        points = []
        for val, tv in zip(data, times):
            if tv < view_left or tv > view_right:
                continue
            x = pad_l + cw * (tv - view_left) / view_range
            y = pad_t + ch * (1 - (val - v_min) / v_range)
            points.append(x)
            points.append(y)

        if len(points) >= 4:
            c.create_line(points, fill=t["chart_line"], width=1.5, smooth=True)

        if points:
            last_x, last_y = points[-2], points[-1]
            c.create_oval(last_x - 3, last_y - 3, last_x + 3, last_y + 3,
                          fill=t["chart_line"], outline=t["chart_line"])
            c.create_text(last_x, last_y - 10, text=f"{vis_vals[-1]:.3f}",
                          fill=t["chart_line"], font=("Consolas", 9, "bold"))

        self._draw_threshold_lines(c, rec, v_min, v_range, pad_l, pad_r, pad_t, ch, w)
        self._update_slider(view_left, view_right, data_t_min, data_t_max)

    def _draw_overlay_chart(self):
        c = self.chart_canvas
        c.delete("all")

        valid = []
        for name in self.chart_vars:
            rec = self.variables.get(name)
            if rec and rec.history:
                valid.append((name, rec))

        if not valid:
            c.create_text(c.winfo_width() // 2, 70,
                          text="右键变量 → 加入叠加图",
                          fill=self.theme["fg"], font=("Arial", 11))
            return

        w = c.winfo_width()
        h = c.winfo_height()
        if w < 20 or h < 20:
            return

        all_times = []
        for _, rec in valid:
            all_times.extend(rec.time_history)
        data_t_min, data_t_max = min(all_times), max(all_times)
        view_left, view_right = self._calc_view_window(data_t_min, data_t_max)
        view_range = view_right - view_left if view_right != view_left else 1.0

        vis_vals = []
        for _, rec in valid:
            for v, t in zip(rec.history, rec.time_history):
                if view_left <= t <= view_right:
                    vis_vals.append(v)
        if not vis_vals:
            return
        v_min, v_max = min(vis_vals), max(vis_vals)
        v_range = v_max - v_min if v_max != v_min else 1.0

        pad_l, pad_r, pad_t, pad_b = 50, 10, 20, 24
        cw = w - pad_l - pad_r
        ch = h - pad_t - pad_b
        t = self.theme

        for i in range(5):
            y = pad_t + ch * i / 4
            c.create_line(pad_l, y, w - pad_r, y, fill=t["chart_grid"], dash=(2, 4))
            val = v_max - (v_range * i / 4)
            c.create_text(pad_l - 4, y, anchor=tk.E, text=f"{val:.2f}",
                          fill=t["fg"], font=("Consolas", 7))

        self._draw_time_axis(c, [view_left, view_right], pad_l, pad_r, cw, h - pad_b, w)

        c.create_text(pad_l + 4, 8, anchor=tk.W,
                      text=f"叠加图  [{v_min:.2f} ~ {v_max:.2f}]",
                      fill=t["fg"], font=("Arial", 9, "bold"))

        legend_y = 8
        legend_x = w - pad_r - 4
        for idx, (name, rec) in enumerate(reversed(valid)):
            color = CURVE_COLORS[(len(valid) - 1 - idx) % len(CURVE_COLORS)]
            vals = list(rec.history)
            times = list(rec.time_history)

            points = []
            for val, tv in zip(vals, times):
                if tv < view_left or tv > view_right:
                    continue
                x = pad_l + cw * (tv - view_left) / view_range
                y = pad_t + ch * (1 - (val - v_min) / v_range)
                points.append(x)
                points.append(y)

            if len(points) >= 4:
                c.create_line(points, fill=color, width=1.5, smooth=True)

            if points:
                lx, ly = points[-2], points[-1]
                c.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                              fill=color, outline=color)

            display = rec.display_name if rec.display_name != name else name
            display = display if len(display) <= 12 else display[:11] + "…"
            cur_val = f"{vals[-1]:.2f}" if vals else "-"
            label = f"● {display}={cur_val}"
            c.create_text(legend_x, legend_y, anchor=tk.NE, text=label,
                          fill=color, font=("Consolas", 8, "bold"))
            legend_y += 14

        self._update_slider(view_left, view_right, data_t_min, data_t_max)

    def _draw_dashboard(self):
        c = self.chart_canvas
        c.delete("all")

        valid = []
        for name in self.dashboard_vars:
            rec = self.variables.get(name)
            if rec and rec.history:
                valid.append((name, rec))

        if not valid:
            c.create_text(c.winfo_width() // 2, 70,
                          text="右键变量 → 加入仪表盘",
                          fill=self.theme["fg"], font=("Arial", 11))
            return

        w = c.winfo_width()
        h = c.winfo_height()
        if w < 20 or h < 20:
            return

        n_charts = len(valid)
        t = self.theme
        pad_l, pad_r = 50, 10
        gap = 4
        total_gap = gap * (n_charts - 1)
        chart_h = (h - total_gap) / n_charts

        all_times = []
        for _, rec in valid:
            all_times.extend(rec.time_history)
        data_t_min, data_t_max = min(all_times), max(all_times)
        view_left, view_right = self._calc_view_window(data_t_min, data_t_max)
        view_range = view_right - view_left if view_right != view_left else 1.0

        for idx, (name, rec) in enumerate(valid):
            vals = list(rec.history)
            times = list(rec.time_history)
            if not vals:
                continue

            y0 = idx * (chart_h + gap)
            ch = chart_h - 22
            pad_t = y0 + 18
            cw = w - pad_l - pad_r

            vis_vals = [v for v, tv in zip(vals, times) if view_left <= tv <= view_right]
            if not vis_vals:
                vis_vals = [vals[-1]]
            v_min, v_max = min(vis_vals), max(vis_vals)
            v_range = v_max - v_min if v_max != v_min else 1.0

            if idx > 0:
                c.create_line(pad_l, y0, w - pad_r, y0, fill=t["chart_grid"])

            y_top = pad_t
            y_bot = pad_t + ch
            c.create_text(pad_l - 4, y_top, anchor=tk.E, text=f"{v_max:.1f}",
                          fill=t["fg"], font=("Consolas", 6))
            c.create_text(pad_l - 4, y_bot, anchor=tk.E, text=f"{v_min:.1f}",
                          fill=t["fg"], font=("Consolas", 6))

            color = CURVE_COLORS[idx % len(CURVE_COLORS)]
            cur_val = vals[-1]
            display = rec.display_name if rec.display_name != name else name
            short_name = display if len(display) <= 16 else display[:15] + "…"
            c.create_text(pad_l + 4, y0 + 2, anchor=tk.NW,
                          text=f"{short_name} = {cur_val:.3f}",
                          fill=color, font=("Consolas", 8, "bold"))

            points = []
            for val, tv in zip(vals, times):
                if tv < view_left or tv > view_right:
                    continue
                x = pad_l + cw * (tv - view_left) / view_range
                py = pad_t + ch * (1 - (val - v_min) / v_range)
                points.append(x)
                points.append(py)

            if len(points) >= 4:
                c.create_line(points, fill=color, width=1.2, smooth=True)

            if points:
                lx, ly = points[-2], points[-1]
                c.create_oval(lx - 2, ly - 2, lx + 2, ly + 2, fill=color, outline=color)

        self._draw_time_axis(c, [view_left, view_right], pad_l, pad_r, w - pad_l - pad_r, h, w)
        self._update_slider(view_left, view_right, data_t_min, data_t_max)

    # ── 辅助绘制方法 ──────────────────────────────────────────────

    def _draw_time_axis(self, canvas, times, pad_l, pad_r, cw, chart_bottom, w):
        if not times or len(times) < 2:
            return
        t_min, t_max = times[0], times[-1]
        t_range = t_max - t_min
        if t_range <= 0:
            return
        t = self.theme

        raw_step = t_range / 5
        for candidate in [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]:
            if candidate >= raw_step:
                step = candidate
                break
        else:
            step = raw_step

        import math
        start = math.ceil(t_min / step) * step
        tv = start
        while tv <= t_max:
            x = pad_l + cw * (tv - t_min) / t_range
            if pad_l <= x <= w - pad_r:
                canvas.create_line(x, chart_bottom + 6, x, chart_bottom + 10,
                                   fill=t["fg"])
                canvas.create_text(x, chart_bottom + 12, anchor=tk.N,
                                   text=f"{tv:.1f}s",
                                   fill=t["fg"], font=("Consolas", 7))
            tv += step

    def _draw_threshold_lines(self, canvas, rec, v_min, v_range, pad_l, pad_r, pad_t, ch, w):
        if rec.alert_min is not None:
            y = pad_t + ch * (1 - (rec.alert_min - v_min) / v_range)
            canvas.create_line(pad_l, y, w - pad_r, y, fill="#ff4444", dash=(6, 3), width=1)
            canvas.create_text(pad_l + 4, y - 8, anchor=tk.W, text=f"min={rec.alert_min:.2f}",
                               fill="#ff4444", font=("Arial", 7))
        if rec.alert_max is not None:
            y = pad_t + ch * (1 - (rec.alert_max - v_min) / v_range)
            canvas.create_line(pad_l, y, w - pad_r, y, fill="#ff4444", dash=(6, 3), width=1)
            canvas.create_text(pad_l + 4, y + 10, anchor=tk.W, text=f"max={rec.alert_max:.2f}",
                               fill="#ff4444", font=("Arial", 7))

    # ── 视窗计算 ─────────────────────────────────────────────────

    def _get_global_time_range(self):
        all_times = []
        names = self._get_active_var_names()
        for name in names:
            rec = self.variables.get(name)
            if rec and rec.time_history:
                all_times.extend(rec.time_history)
        if not all_times:
            return 0.0, 1.0
        return min(all_times), max(all_times)

    def _get_active_var_names(self):
        if self.chart_mode == "single":
            return [self.selected_var] if self.selected_var else []
        elif self.chart_mode == "overlay":
            return self.chart_vars
        else:
            return self.dashboard_vars

    def _calc_view_window(self, data_t_min, data_t_max):
        data_range = data_t_max - data_t_min
        if data_range <= 0:
            data_range = 1.0

        zoom_factor = 1.0 + 0.6 * self.zoom_level
        win_size = data_range / zoom_factor
        win_size = max(win_size, data_range * 0.01)

        if self.auto_follow or self.view_right_edge is None:
            right = data_t_max
        else:
            right = self.view_right_edge

        left = right - win_size
        if left < data_t_min:
            left = data_t_min
            right = left + win_size
        if right > data_t_max:
            right = data_t_max
            left = right - win_size

        return left, right

    def _update_slider(self, view_left, view_right, data_t_min, data_t_max):
        data_range = data_t_max - data_t_min
        if data_range <= 0:
            return
        self.time_slider.configure(from_=data_t_min, to=data_t_max)
        if self.auto_follow:
            self.time_slider.set(data_t_max)
        else:
            self.time_slider.set(view_right)
        self.slider_label.config(text=f"{view_left:.1f}s ~ {view_right:.1f}s")

    def _on_slider_move(self, val):
        try:
            self.view_right_edge = float(val)
            self.auto_follow = False
        except ValueError:
            pass

    # ── 鼠标交互 ─────────────────────────────────────────────────

    def _on_chart_scroll(self, event):
        self._apply_zoom(-1 if event.delta > 0 else 1, event.x)

    def _on_chart_scroll_up(self, _event):
        self._apply_zoom(-1, _event.x)

    def _on_chart_scroll_down(self, _event):
        self._apply_zoom(1, _event.x)

    def _apply_zoom(self, direction, mouse_x):
        c = self.chart_canvas
        w = c.winfo_width()
        if w < 50:
            return

        pad_l, pad_r = 50, 10
        cw = w - pad_l - pad_r

        data_t_min, data_t_max = self._get_global_time_range()
        old_left, old_right = self._calc_view_window(data_t_min, data_t_max)
        old_range = old_right - old_left

        if mouse_x >= pad_l and mouse_x <= w - pad_r:
            mouse_frac = (mouse_x - pad_l) / cw
            mouse_time = old_left + old_range * mouse_frac
        else:
            mouse_frac = 0.5
            mouse_time = old_left + old_range * 0.5

        self.zoom_level = max(-5, min(20, self.zoom_level + direction))

        data_range = data_t_max - data_t_min
        zoom_factor = 1.0 + 0.6 * self.zoom_level
        new_range = data_range / zoom_factor
        new_range = max(new_range, data_range * 0.01)

        new_left = mouse_time - new_range * mouse_frac
        new_right = new_left + new_range
        if new_left < data_t_min:
            new_left = data_t_min
            new_right = new_left + new_range
        if new_right > data_t_max:
            new_right = data_t_max
            new_left = new_right - new_range

        self.view_right_edge = new_right
        self.auto_follow = False

    def _on_drag_start(self, event):
        self._dragging = True
        self._drag_start_x = event.x
        data_t_min, data_t_max = self._get_global_time_range()
        _, right = self._calc_view_window(data_t_min, data_t_max)
        self._drag_start_edge = right

    def _on_drag_move(self, event):
        if not self._dragging:
            return
        c = self.chart_canvas
        w = c.winfo_width()
        pad_l, pad_r = 50, 10
        cw = w - pad_l - pad_r
        if cw <= 0:
            return

        data_t_min, data_t_max = self._get_global_time_range()
        old_left, old_right = self._calc_view_window(data_t_min, data_t_max)
        time_range = old_right - old_left

        dx = self._drag_start_x - event.x
        time_shift = dx / cw * time_range
        self.view_right_edge = self._drag_start_edge + time_shift
        self.auto_follow = False

    def _on_drag_end(self, _):
        self._dragging = False

    # ─────────────────────────────────────────────────────────── 图传
    def _toggle_stream(self):
        if self.video_stream and self.video_stream.running:
            self._stop_stream()
            return

        self._refresh_stream()

    def _get_stream_url_from_entry(self):
        url = self.stream_url_var.get().strip()
        if not url:
            ip = self.ip_combo.get() if self.ip_combo.get() else "192.168.1.1"
            url = guess_stream_url(ip)
            self.stream_url_var.set(url)
        return url

    def _refresh_stream(self):
        url = self._get_stream_url_from_entry()
        if not url:
            messagebox.showinfo("提示", "请输入图传地址")
            return

        self.stream_url = url
        self.config["stream_url"] = url
        self._save_config_or_alert()
        self._start_stream(url)

    def _show_stream_panel(self):
        panes = set(self.bottom_pane.panes())
        if str(self.send_frame) in panes:
            self.bottom_pane.forget(self.send_frame)
        if str(self.stream_frame) not in set(self.bottom_pane.panes()):
            self.bottom_pane.add(self.stream_frame, weight=2)

    def _show_send_panel(self):
        panes = set(self.bottom_pane.panes())
        if str(self.stream_frame) in panes:
            self.bottom_pane.forget(self.stream_frame)
        if str(self.send_frame) not in set(self.bottom_pane.panes()):
            self.bottom_pane.add(self.send_frame, weight=2)

    def _stop_stream(self):
        self.stream_btn.config(text="📷 图传")
        self.stream_panel_status.config(text="正在关闭...", foreground="orange")

        stream = self.video_stream
        self.video_stream = None

        def _do_stop():
            if stream:
                stream.stop()
            self.root.after(0, lambda s=stream: self._on_stream_stopped(s))

        threading.Thread(target=_do_stop, daemon=True).start()

    def _on_stream_stopped(self, stopped_stream=None):
        if self.video_stream is not None and stopped_stream is not self.video_stream:
            return
        if self.stream_after_id:
            try:
                self.root.after_cancel(self.stream_after_id)
            except Exception:
                pass
            self.stream_after_id = None
        self.stream_photo = None
        self.stream_canvas.delete("all")
        self.stream_canvas.create_text(
            max(1, self.stream_canvas.winfo_width() // 2),
            max(1, self.stream_canvas.winfo_height() // 2),
            text="图传未开启", fill="#aaaaaa", tags=("status",)
        )
        self.stream_panel_status.config(text="未连接", foreground="gray")
        self._show_send_panel()

    def _render_stream_frame(self):
        if not hasattr(self, "stream_canvas"):
            return
        if not self.video_stream:
            return

        canvas = self.stream_canvas
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())
        frame, frame_id = self.video_stream.get_frame_snapshot()

        if frame is None:
            canvas.delete("all")
            status = self.video_stream.error_msg or self.video_stream.status_msg or "连接中..."
            self.stream_panel_status.config(text=status, foreground="orange")
            canvas.create_text(cw // 2, ch // 2, text=status, fill="#cccccc", tags=("status",))
            return

        if frame_id == self.stream_last_frame_id:
            return
        self.stream_last_frame_id = frame_id

        try:
            from PIL import Image, ImageTk
            import cv2

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            iw, ih = img.size
            scale = min(cw / iw, ch / ih)
            new_w = max(1, int(iw * scale))
            new_h = max(1, int(ih * scale))
            img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
            self.stream_photo = ImageTk.PhotoImage(img)

            canvas.delete("all")
            canvas.create_image(cw // 2, ch // 2, image=self.stream_photo, anchor=tk.CENTER)
            self.stream_render_count += 1
            now = time.time()
            elapsed = now - self.stream_render_last_time
            if elapsed >= 1.0:
                self.stream_render_fps = self.stream_render_count / elapsed
                self.stream_render_count = 0
                self.stream_render_last_time = now
            fps = self.video_stream.fps
            res = self.video_stream.stream_resolution
            text_parts = []
            if res:
                text_parts.append(res)
            if fps > 0:
                text_parts.append(f"收{fps:.0f}fps")
            if self.stream_render_fps > 0:
                text_parts.append(f"显{self.stream_render_fps:.0f}fps")
            self.stream_panel_status.config(text=" ".join(text_parts) or "已连接", foreground="green")
        except Exception as e:
            canvas.delete("all")
            msg = f"渲染失败: {e}"
            self.stream_panel_status.config(text=msg, foreground="red")
            canvas.create_text(cw // 2, ch // 2, text=msg, fill="#ff7777", tags=("status",))

    def _stream_render_loop(self):
        self.stream_after_id = None
        if not self.video_stream:
            return
        self._render_stream_frame()
        if self.video_stream:
            self.stream_after_id = self.root.after_idle(self._stream_render_loop)

    def _start_stream(self, url):
        if self.video_stream and self.video_stream.running:
            self._stop_stream()
        self._show_stream_panel()
        self.stream_canvas.delete("all")
        self.stream_canvas.create_text(160, 90, text="连接中...", fill="#cccccc", tags=("status",))
        self.stream_panel_status.config(text="连接中...", foreground="orange")
        self.stream_last_frame_id = -1
        self.stream_render_fps = 0
        self.stream_render_count = 0
        self.stream_render_last_time = time.time()
        self.video_stream = VideoStream(url, config=self.config)
        self.video_stream.start()
        self.stream_btn.config(text="⏹ 关图传")
        if self.stream_after_id:
            try:
                self.root.after_cancel(self.stream_after_id)
            except Exception:
                pass
        self.stream_after_id = self.root.after_idle(self._stream_render_loop)

    # ─────────────────────────────────────────────────────────── 设置对话框
    def _open_settings(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("⚙ 设置 - 变量映射与类型")
        dlg.geometry("700x500")
        dlg.resizable(True, True)
        dlg.transient(self.root)
        dlg.grab_set()

        notebook = ttk.Notebook(dlg)
        notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # === Tab 1: 名称映射 ===
        tab_name = ttk.Frame(notebook, padding=6)
        notebook.add(tab_name, text="🏷 名称映射")

        ttk.Label(tab_name, text="变量原始名 → 显示名称（支持中文）").pack(anchor=tk.W)
        name_frame = ttk.Frame(tab_name)
        name_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        name_cols = ("orig", "display")
        name_tree = ttk.Treeview(name_frame, columns=name_cols, show="headings", height=10)
        name_tree.heading("orig", text="原始变量名")
        name_tree.heading("display", text="显示名称")
        name_tree.column("orig", width=150)
        name_tree.column("display", width=200)
        name_scroll = ttk.Scrollbar(name_frame, orient=tk.VERTICAL, command=name_tree.yview)
        name_tree.configure(yscrollcommand=name_scroll.set)
        name_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        name_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for orig, display in self.name_map.items():
            name_tree.insert("", tk.END, values=(orig, display))

        def on_name_double_click(_=None):
            sel = name_tree.selection()
            if not sel:
                return
            vals = name_tree.item(sel[0], "values")
            old_orig, old_display = vals[0], vals[1]
            edit_dlg = tk.Toplevel(dlg)
            edit_dlg.title("编辑名称映射")
            edit_dlg.geometry("300x120")
            edit_dlg.transient(dlg)
            edit_dlg.grab_set()
            ttk.Label(edit_dlg, text="原始名:").grid(row=0, column=0, padx=6, pady=4, sticky=tk.W)
            orig_e = ttk.Entry(edit_dlg, width=20)
            orig_e.insert(0, old_orig)
            orig_e.grid(row=0, column=1, padx=6, pady=4)
            ttk.Label(edit_dlg, text="显示名:").grid(row=1, column=0, padx=6, pady=4, sticky=tk.W)
            disp_e = ttk.Entry(edit_dlg, width=20)
            disp_e.insert(0, old_display)
            disp_e.grid(row=1, column=1, padx=6, pady=4)

            def ok():
                o = orig_e.get().strip()
                d = disp_e.get().strip()
                if o and d:
                    # 删旧的
                    if old_orig in self.name_map:
                        del self.name_map[old_orig]
                    self.name_map[o] = d
                    name_tree.item(sel[0], values=(o, d))
                    if old_orig in self.variables:
                        self.variables[old_orig].display_name = o if o == old_orig else d
                    if o in self.variables:
                        self.variables[o].display_name = d
                    edit_dlg.destroy()

            ttk.Button(edit_dlg, text="确定", command=ok).grid(row=2, column=0, columnspan=2, pady=6)

        name_tree.bind("<Double-1>", on_name_double_click)

        name_btn_frame = ttk.Frame(tab_name)
        name_btn_frame.pack(fill=tk.X, pady=4)

        def add_name_map():
            edit_dlg = tk.Toplevel(dlg)
            edit_dlg.title("添加名称映射")
            edit_dlg.geometry("300x120")
            edit_dlg.transient(dlg)
            edit_dlg.grab_set()
            ttk.Label(edit_dlg, text="原始名:").grid(row=0, column=0, padx=6, pady=4, sticky=tk.W)
            orig_e = ttk.Entry(edit_dlg, width=20)
            orig_e.grid(row=0, column=1, padx=6, pady=4)
            ttk.Label(edit_dlg, text="显示名:").grid(row=1, column=0, padx=6, pady=4, sticky=tk.W)
            disp_e = ttk.Entry(edit_dlg, width=20)
            disp_e.grid(row=1, column=1, padx=6, pady=4)

            def ok():
                o = orig_e.get().strip()
                d = disp_e.get().strip()
                if o and d:
                    self.name_map[o] = d
                    name_tree.insert("", tk.END, values=(o, d))
                    # 更新已有变量
                    if o in self.variables:
                        self.variables[o].display_name = d
                    edit_dlg.destroy()

            ttk.Button(edit_dlg, text="确定", command=ok).grid(row=2, column=0, columnspan=2, pady=6)

        def del_name_map():
            sel = name_tree.selection()
            if sel:
                vals = name_tree.item(sel[0], "values")
                orig = vals[0]
                if orig in self.name_map:
                    del self.name_map[orig]
                if orig in self.variables:
                    self.variables[orig].display_name = orig
                name_tree.delete(sel[0])

        ttk.Button(name_btn_frame, text="➕ 添加", command=add_name_map).pack(side=tk.LEFT, padx=4)
        ttk.Button(name_btn_frame, text="❌ 删除", command=del_name_map).pack(side=tk.LEFT, padx=4)

        # === Tab 2: 值映射 ===
        tab_value = ttk.Frame(notebook, padding=6)
        notebook.add(tab_value, text="🔄 值映射")

        ttk.Label(tab_value, text="变量值 → 显示文字（如 0→停止, 1→前进）").pack(anchor=tk.W)

        val_outer = ttk.Frame(tab_value)
        val_outer.pack(fill=tk.BOTH, expand=True, pady=4)

        # 左侧：变量列表
        val_left = ttk.Frame(val_outer)
        val_left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        ttk.Label(val_left, text="变量名:").pack(anchor=tk.W)
        val_var_list = ttk.Treeview(val_left, columns=("vname",), show="headings", height=8)
        val_var_list.heading("vname", text="变量名")
        val_var_list.column("vname", width=120)
        val_var_list.pack(fill=tk.Y, expand=True)

        for vname in self.value_map:
            val_var_list.insert("", tk.END, values=(vname,))

        # 右侧：映射表
        val_right = ttk.Frame(val_outer)
        val_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(val_right, text="值映射:").pack(anchor=tk.W)
        val_map_tree = ttk.Treeview(val_right, columns=("raw", "disp"), show="headings", height=8)
        val_map_tree.heading("raw", text="原始值")
        val_map_tree.heading("disp", text="显示文字")
        val_map_tree.column("raw", width=80)
        val_map_tree.column("disp", width=150)
        val_map_tree.pack(fill=tk.BOTH, expand=True)

        def on_val_var_select(_=None):
            val_map_tree.delete(*val_map_tree.get_children())
            sel = val_var_list.selection()
            if not sel:
                return
            vname = val_var_list.item(sel[0], "values")[0]
            if vname in self.value_map:
                for raw, disp in self.value_map[vname].items():
                    val_map_tree.insert("", tk.END, values=(raw, disp))

        val_var_list.bind("<<TreeviewSelect>>", on_val_var_select)

        def on_val_var_double_click(_=None):
            sel = val_var_list.selection()
            if not sel:
                return
            vname = val_var_list.item(sel[0], "values")[0]
            edit_dlg = tk.Toplevel(dlg)
            edit_dlg.title(f"编辑值映射 - {vname}")
            edit_dlg.geometry("300x100")
            edit_dlg.transient(dlg)
            edit_dlg.grab_set()
            ttk.Label(edit_dlg, text="变量名:").grid(row=0, column=0, padx=6, pady=4, sticky=tk.W)
            vn_e = ttk.Entry(edit_dlg, width=20)
            vn_e.insert(0, vname)
            vn_e.grid(row=0, column=1, padx=6, pady=4)

            def ok():
                new_vn = vn_e.get().strip()
                if new_vn and new_vn != vname:
                    if vname in self.value_map:
                        self.value_map[new_vn] = self.value_map.pop(vname)
                    val_var_list.item(sel[0], values=(new_vn,))
                edit_dlg.destroy()

            ttk.Button(edit_dlg, text="确定", command=ok).grid(row=1, column=0, columnspan=2, pady=6)

        def on_val_map_double_click(_=None):
            sel_v = val_var_list.selection()
            sel_m = val_map_tree.selection()
            if not sel_v or not sel_m:
                return
            vname = val_var_list.item(sel_v[0], "values")[0]
            vals = val_map_tree.item(sel_m[0], "values")
            old_raw, old_disp = vals[0], vals[1]

            edit_dlg = tk.Toplevel(dlg)
            edit_dlg.title(f"编辑映射 - {vname}")
            edit_dlg.geometry("300x130")
            edit_dlg.transient(dlg)
            edit_dlg.grab_set()
            ttk.Label(edit_dlg, text="原始值:").grid(row=0, column=0, padx=6, pady=4, sticky=tk.W)
            raw_e = ttk.Entry(edit_dlg, width=20)
            raw_e.insert(0, old_raw)
            raw_e.grid(row=0, column=1, padx=6, pady=4)
            ttk.Label(edit_dlg, text="显示文字:").grid(row=1, column=0, padx=6, pady=4, sticky=tk.W)
            disp_e = ttk.Entry(edit_dlg, width=20)
            disp_e.insert(0, old_disp)
            disp_e.grid(row=1, column=1, padx=6, pady=4)

            def ok():
                raw = raw_e.get().strip()
                disp = disp_e.get().strip()
                if raw and disp:
                    if vname in self.value_map:
                        if old_raw != raw and old_raw in self.value_map[vname]:
                            del self.value_map[vname][old_raw]
                        self.value_map[vname][raw] = disp
                    val_map_tree.item(sel_m[0], values=(raw, disp))
                edit_dlg.destroy()

            ttk.Button(edit_dlg, text="确定", command=ok).grid(row=2, column=0, columnspan=2, pady=6)

        val_var_list.bind("<Double-1>", on_val_var_double_click)
        val_map_tree.bind("<Double-1>", on_val_map_double_click)

        val_btn_frame = ttk.Frame(tab_value)
        val_btn_frame.pack(fill=tk.X, pady=4)

        def add_val_var():
            edit_dlg = tk.Toplevel(dlg)
            edit_dlg.title("添加值映射变量")
            edit_dlg.geometry("300x100")
            edit_dlg.transient(dlg)
            edit_dlg.grab_set()
            ttk.Label(edit_dlg, text="变量名:").grid(row=0, column=0, padx=6, pady=4, sticky=tk.W)
            vn_e = ttk.Entry(edit_dlg, width=20)
            vn_e.grid(row=0, column=1, padx=6, pady=4)

            def ok():
                vn = vn_e.get().strip()
                if vn and vn not in self.value_map:
                    self.value_map[vn] = {}
                    val_var_list.insert("", tk.END, values=(vn,))
                    edit_dlg.destroy()

            ttk.Button(edit_dlg, text="确定", command=ok).grid(row=1, column=0, columnspan=2, pady=6)

        def add_val_mapping():
            sel = val_var_list.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选择一个变量")
                return
            vname = val_var_list.item(sel[0], "values")[0]

            edit_dlg = tk.Toplevel(dlg)
            edit_dlg.title(f"添加映射 - {vname}")
            edit_dlg.geometry("300x130")
            edit_dlg.transient(dlg)
            edit_dlg.grab_set()
            ttk.Label(edit_dlg, text="原始值:").grid(row=0, column=0, padx=6, pady=4, sticky=tk.W)
            raw_e = ttk.Entry(edit_dlg, width=20)
            raw_e.grid(row=0, column=1, padx=6, pady=4)
            ttk.Label(edit_dlg, text="显示文字:").grid(row=1, column=0, padx=6, pady=4, sticky=tk.W)
            disp_e = ttk.Entry(edit_dlg, width=20)
            disp_e.grid(row=1, column=1, padx=6, pady=4)

            def ok():
                raw = raw_e.get().strip()
                disp = disp_e.get().strip()
                if raw and disp:
                    if vname not in self.value_map:
                        self.value_map[vname] = {}
                    self.value_map[vname][raw] = disp
                    val_map_tree.insert("", tk.END, values=(raw, disp))
                    edit_dlg.destroy()

            ttk.Button(edit_dlg, text="确定", command=ok).grid(row=2, column=0, columnspan=2, pady=6)

        def del_val_mapping():
            sel_v = val_var_list.selection()
            sel_m = val_map_tree.selection()
            if sel_v and sel_m:
                vname = val_var_list.item(sel_v[0], "values")[0]
                raw = val_map_tree.item(sel_m[0], "values")[0]
                if vname in self.value_map and raw in self.value_map[vname]:
                    del self.value_map[vname][raw]
                val_map_tree.delete(sel_m[0])

        ttk.Button(val_btn_frame, text="➕ 添加变量", command=add_val_var).pack(side=tk.LEFT, padx=4)
        ttk.Button(val_btn_frame, text="➕ 添加映射", command=add_val_mapping).pack(side=tk.LEFT, padx=4)
        ttk.Button(val_btn_frame, text="❌ 删除映射", command=del_val_mapping).pack(side=tk.LEFT, padx=4)

        # === Tab 3: 变量类型 ===
        tab_type = ttk.Frame(notebook, padding=6)
        notebook.add(tab_type, text="📐 变量类型")

        ttk.Label(tab_type, text="设置变量的显示类型").pack(anchor=tk.W)
        type_frame = ttk.Frame(tab_type)
        type_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        type_cols = ("vname", "vtype")
        type_tree = ttk.Treeview(type_frame, columns=type_cols, show="headings", height=10)
        type_tree.heading("vname", text="变量名")
        type_tree.heading("vtype", text="类型")
        type_tree.column("vname", width=200)
        type_tree.column("vtype", width=150)
        type_scroll = ttk.Scrollbar(type_frame, orient=tk.VERTICAL, command=type_tree.yview)
        type_tree.configure(yscrollcommand=type_scroll.set)
        type_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        type_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for vname, vtype in self.var_types.items():
            type_tree.insert("", tk.END, values=(vname, vtype))

        def on_type_double_click(_=None):
            sel = type_tree.selection()
            if not sel:
                return
            vals = type_tree.item(sel[0], "values")
            old_vn, old_vt = vals[0], vals[1]
            edit_dlg = tk.Toplevel(dlg)
            edit_dlg.title("编辑变量类型")
            edit_dlg.geometry("300x140")
            edit_dlg.transient(dlg)
            edit_dlg.grab_set()
            ttk.Label(edit_dlg, text="变量名:").grid(row=0, column=0, padx=6, pady=4, sticky=tk.W)
            vn_e = ttk.Entry(edit_dlg, width=20)
            vn_e.insert(0, old_vn)
            vn_e.grid(row=0, column=1, padx=6, pady=4)
            ttk.Label(edit_dlg, text="类型:").grid(row=1, column=0, padx=6, pady=4, sticky=tk.W)
            type_combo = ttk.Combobox(edit_dlg, width=17, state="readonly",
                                       values=["auto", "int", "float", "float2", "float3", "bool", "enum"])
            type_combo.set(old_vt)
            type_combo.grid(row=1, column=1, padx=6, pady=4)

            def ok():
                vn = vn_e.get().strip()
                vt = type_combo.get()
                if vn:
                    if old_vn != vn and old_vn in self.var_types:
                        del self.var_types[old_vn]
                    self.var_types[vn] = vt
                    if vn in self.variables:
                        self.variables[vn].var_type = vt
                    type_tree.item(sel[0], values=(vn, vt))
                edit_dlg.destroy()

            ttk.Button(edit_dlg, text="确定", command=ok).grid(row=2, column=0, columnspan=2, pady=6)

        type_tree.bind("<Double-1>", on_type_double_click)

        type_btn_frame = ttk.Frame(tab_type)
        type_btn_frame.pack(fill=tk.X, pady=4)

        def add_type():
            edit_dlg = tk.Toplevel(dlg)
            edit_dlg.title("设置变量类型")
            edit_dlg.geometry("300x140")
            edit_dlg.transient(dlg)
            edit_dlg.grab_set()
            ttk.Label(edit_dlg, text="变量名:").grid(row=0, column=0, padx=6, pady=4, sticky=tk.W)
            vn_e = ttk.Entry(edit_dlg, width=20)
            vn_e.grid(row=0, column=1, padx=6, pady=4)
            ttk.Label(edit_dlg, text="类型:").grid(row=1, column=0, padx=6, pady=4, sticky=tk.W)
            type_combo = ttk.Combobox(edit_dlg, width=17, state="readonly",
                                       values=["auto", "int", "float", "float2", "float3", "bool", "enum"])
            type_combo.set("auto")
            type_combo.grid(row=1, column=1, padx=6, pady=4)

            def ok():
                vn = vn_e.get().strip()
                vt = type_combo.get()
                if vn:
                    self.var_types[vn] = vt
                    # 更新已有变量
                    if vn in self.variables:
                        self.variables[vn].var_type = vt
                    # 更新树
                    for item in type_tree.get_children():
                        if type_tree.item(item, "values")[0] == vn:
                            type_tree.item(item, values=(vn, vt))
                            break
                    else:
                        type_tree.insert("", tk.END, values=(vn, vt))
                    edit_dlg.destroy()

            ttk.Button(edit_dlg, text="确定", command=ok).grid(row=2, column=0, columnspan=2, pady=6)

        def del_type():
            sel = type_tree.selection()
            if sel:
                vname = type_tree.item(sel[0], "values")[0]
                if vname in self.var_types:
                    del self.var_types[vname]
                if vname in self.variables:
                    self.variables[vname].var_type = "auto"
                type_tree.delete(sel[0])

        ttk.Button(type_btn_frame, text="➕ 添加/修改", command=add_type).pack(side=tk.LEFT, padx=4)
        ttk.Button(type_btn_frame, text="❌ 删除", command=del_type).pack(side=tk.LEFT, padx=4)

        # === 保存按钮 ===
        def save_all():
            self.config["name_map"] = dict(self.name_map)
            self.config["value_map"] = {k: dict(v) for k, v in self.value_map.items()}
            self.config["var_types"] = dict(self.var_types)
            if self._save_config_or_alert():
                messagebox.showinfo("保存成功", f"配置已保存到 {self.config_path}")

        btn_save = ttk.Button(dlg, text="💾 保存到 config.json", command=save_all)
        btn_save.pack(pady=6)

    # ─────────────────────────────────────────────────────────── 右键菜单
    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)
        self.selected_var = item

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="📌 置顶 / 取消置顶", command=self._toggle_pin)
        menu.add_command(label="⚠ 设置阈值...", command=self._set_alert)
        menu.add_command(label="📋 复制当前值", command=self._copy_value)
        menu.add_command(label="🔄 重置统计", command=self._reset_stats)
        menu.add_separator()
        # 映射/类型快捷设置
        menu.add_command(label="🏷 设置显示名...", command=self._quick_set_display_name)
        menu.add_command(label="📐 设置类型...", command=self._quick_set_type)
        menu.add_command(label="🔄 设置值映射...", command=self._quick_set_value_map)
        menu.add_separator()
        # 图表相关
        in_overlay = item in self.chart_vars
        in_dash = item in self.dashboard_vars
        menu.add_command(
            label=("❌ 从叠加图移除" if in_overlay else "📈 加入叠加图"),
            command=self._toggle_chart_var)
        menu.add_command(
            label=("❌ 从仪表盘移除" if in_dash else "📊 加入仪表盘"),
            command=self._toggle_dashboard_var)
        menu.add_separator()
        menu.add_command(label="❌ 删除此变量", command=self._delete_var)
        menu.tk_popup(event.x_root, event.y_root)

    def _quick_set_display_name(self):
        if not self.selected_var or self.selected_var not in self.variables:
            return
        rec = self.variables[self.selected_var]
        dlg = tk.Toplevel(self.root)
        dlg.title(f"设置显示名 - {self.selected_var}")
        dlg.geometry("300x100")
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text=f"原始名: {self.selected_var}").pack(pady=(8, 2))
        entry = ttk.Entry(dlg, width=25)
        entry.insert(0, rec.display_name)
        entry.pack(pady=2)

        def ok():
            name = entry.get().strip()
            if name:
                rec.display_name = name
                self.name_map[self.selected_var] = name
                self.config["name_map"] = dict(self.name_map)
                self._save_config_or_alert()
            dlg.destroy()

        ttk.Button(dlg, text="确定", command=ok).pack(pady=6)

    def _quick_set_type(self):
        if not self.selected_var or self.selected_var not in self.variables:
            return
        rec = self.variables[self.selected_var]
        dlg = tk.Toplevel(self.root)
        dlg.title(f"设置类型 - {self.selected_var}")
        dlg.geometry("300x100")
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text=f"变量: {self.selected_var}").pack(pady=(8, 2))
        combo = ttk.Combobox(dlg, width=17, state="readonly",
                              values=["auto", "int", "float", "float2", "float3", "bool", "enum"])
        combo.set(rec.var_type)
        combo.pack(pady=2)

        def ok():
            vt = combo.get()
            rec.var_type = vt
            self.var_types[self.selected_var] = vt
            self.config["var_types"] = dict(self.var_types)
            self._save_config_or_alert()
            dlg.destroy()

        ttk.Button(dlg, text="确定", command=ok).pack(pady=6)

    def _quick_set_value_map(self):
        if not self.selected_var or self.selected_var not in self.variables:
            return
        name = self.selected_var
        dlg = tk.Toplevel(self.root)
        dlg.title(f"设置值映射 - {name}")
        dlg.geometry("360x250")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text=f"变量: {name}（每行一个: 原始值=显示文字）").pack(pady=(8, 2))

        text = tk.Text(dlg, width=38, height=8)
        text.pack(padx=8, pady=4)

        # 填入现有映射
        if name in self.value_map:
            lines = [f"{raw}={disp}" for raw, disp in self.value_map[name].items()]
            text.insert("1.0", "\n".join(lines))

        def ok():
            content = text.get("1.0", tk.END).strip()
            mapping = {}
            for line in content.split("\n"):
                line = line.strip()
                if "=" in line:
                    parts = line.split("=", 1)
                    mapping[parts[0].strip()] = parts[1].strip()
            self.value_map[name] = mapping
            self.config["value_map"] = {k: dict(v) for k, v in self.value_map.items()}
            self._save_config_or_alert()
            dlg.destroy()

        ttk.Button(dlg, text="确定", command=ok).pack(pady=6)

    def _toggle_pin(self):
        if self.selected_var and self.selected_var in self.variables:
            rec = self.variables[self.selected_var]
            rec.pinned = not rec.pinned

    def _set_alert(self):
        if not self.selected_var or self.selected_var not in self.variables:
            return
        rec = self.variables[self.selected_var]

        dlg = tk.Toplevel(self.root)
        dlg.title(f"设置阈值 - {self.selected_var}")
        dlg.geometry("280x150")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text=f"变量: {self.selected_var}").grid(row=0, column=0, columnspan=2, pady=6, padx=8)

        ttk.Label(dlg, text="下限 (min):").grid(row=1, column=0, sticky=tk.W, padx=8)
        min_entry = ttk.Entry(dlg, width=12)
        min_entry.grid(row=1, column=1, padx=8)
        if rec.alert_min is not None:
            min_entry.insert(0, f"{rec.alert_min}")

        ttk.Label(dlg, text="上限 (max):").grid(row=2, column=0, sticky=tk.W, padx=8)
        max_entry = ttk.Entry(dlg, width=12)
        max_entry.grid(row=2, column=1, padx=8)
        if rec.alert_max is not None:
            max_entry.insert(0, f"{rec.alert_max}")

        def apply():
            try:
                min_val = float(min_entry.get()) if min_entry.get().strip() else None
            except ValueError:
                min_val = None
            try:
                max_val = float(max_entry.get()) if max_entry.get().strip() else None
            except ValueError:
                max_val = None
            rec.alert_min = min_val
            rec.alert_max = max_val
            dlg.destroy()

        ttk.Button(dlg, text="确定", command=apply).grid(row=3, column=0, columnspan=2, pady=8)

    def _copy_value(self):
        if self.selected_var and self.selected_var in self.variables:
            val = self.variables[self.selected_var].value
            self.root.clipboard_clear()
            self.root.clipboard_append(str(val))

    def _reset_stats(self):
        if self.selected_var and self.selected_var in self.variables:
            self.variables[self.selected_var].reset_stats()

    def _delete_var(self):
        if self.selected_var and self.selected_var in self.variables:
            del self.variables[self.selected_var]
            if self.selected_var in self.chart_vars:
                self.chart_vars.remove(self.selected_var)
            if self.selected_var in self.dashboard_vars:
                self.dashboard_vars.remove(self.selected_var)
            self.selected_var = None

    def _toggle_chart_var(self):
        if not self.selected_var:
            return
        if self.selected_var in self.chart_vars:
            self.chart_vars.remove(self.selected_var)
        else:
            self.chart_vars.append(self.selected_var)
        if self.chart_vars and self.chart_mode == "single":
            self.chart_mode = "overlay"
            self.chart_mode_btn.config(text="📈 叠加图")
            self._update_chart_title()

    def _toggle_dashboard_var(self):
        if not self.selected_var:
            return
        if self.selected_var in self.dashboard_vars:
            self.dashboard_vars.remove(self.selected_var)
        else:
            self.dashboard_vars.append(self.selected_var)
        if self.dashboard_vars and self.chart_mode != "dashboard":
            self.chart_mode = "dashboard"
            self.chart_mode_btn.config(text="📊 仪表盘")
            self._update_chart_title()

    def _toggle_chart_mode(self):
        if self.chart_mode == "single":
            self.chart_mode = "overlay"
            self.chart_mode_btn.config(text="📈 叠加图")
        elif self.chart_mode == "overlay":
            self.chart_mode = "dashboard"
            self.chart_mode_btn.config(text="📊 仪表盘")
        else:
            self.chart_mode = "single"
            self.chart_mode_btn.config(text="📊 单曲线")
        self._update_chart_title()

    def _update_chart_title(self):
        if self.chart_mode == "single":
            self.chart_frame.config(text="波形图（点击表格变量查看）")
        elif self.chart_mode == "overlay":
            names = ", ".join(self.chart_vars) if self.chart_vars else "（右键变量加入）"
            self.chart_frame.config(text=f"叠加图 — {names}")
        else:
            n = len(self.dashboard_vars)
            self.chart_frame.config(text=f"仪表盘 — {n} 个变量（右键加入/移除）")

    # ─────────────────────────────────────────────────────────── CSV
    def _toggle_csv(self):
        if self.csv_logging:
            self._stop_csv()
        else:
            self._start_csv()

    def _start_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            initialfile=f"car_log_{time.strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not path:
            return
        try:
            self.csv_file = open(path, "w", newline="", encoding="utf-8-sig")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(["timestamp", "time_s", "variable", "display_name", "value"])
            self.csv_start_time = time.time()
            self.csv_logging = True
            self.csv_btn.config(text="📄 停止")
        except Exception as e:
            messagebox.showerror("CSV 错误", str(e))

    def _stop_csv(self):
        self.csv_logging = False
        self.csv_start_time = None
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None
        self.csv_btn.config(text="📄 CSV")

    # ─────────────────────────────────────────────────────────── 清空
    def _clear_table(self):
        self._clear_recv_queue()
        self.variables.clear()
        self.recv_count = 0
        self.selected_var = None
        self.chart_vars.clear()
        self.dashboard_vars.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.chart_canvas.delete("all")

    # ─────────────────────────────────────────────────────────── 关闭
    def on_closing(self):
        self.running = False
        if self.refresh_after_id:
            self.root.after_cancel(self.refresh_after_id)
        if self.stream_after_id:
            self.root.after_cancel(self.stream_after_id)
            self.stream_after_id = None
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        if self.video_stream and self.video_stream.running:
            self.video_stream.stop()
        self._stop_csv()
        self.root.destroy()


def main():
    import sys
    print(f"[启动] Python: {sys.executable}")
    print(f"[启动] 版本: {sys.version}")
    try:
        import cv2
        print(f"[启动] OpenCV: {cv2.__version__} @ {cv2.__file__}")
    except ImportError:
        print("[启动] OpenCV: 未安装！请运行 pip install opencv-python")

    root = tk.Tk()
    app = VariableMonitor(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
