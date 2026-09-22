import sys
import os
import re
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import ctypes
from ctypes import wintypes

# 全局低级鼠标钩子：捕获鼠标滚轮事件
WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 522

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 显式声明函数原型，64 位下指针返回值必须指定类型
# （SetWindowsHookExW 返回钩子句柄，CallNextHookEx 返回指针）
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p,
]
user32.UnhookWindowsHookEx.restype = ctypes.c_bool
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [ctypes.c_void_p]

# 低级鼠标钩子回调类型
LOW_LEVEL_MOUSE_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_int,
    ctypes.c_size_t,
    ctypes.c_void_p,
)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


hook_id = None


def low_level_mouse_proc(nCode, wParam, lParam):
    # 只处理鼠标滚轮消息
    if nCode >= 0 and wParam == WM_MOUSEWHEEL:
        # mouseData 高 16 位是滚轮增量（有符号）
        ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        delta = ctypes.c_int(ms.mouseData).value >> 16
        if text_widget and scroll_direction:
            # 向上滚：回退；向下滚：前进
            if delta > 0:
                scroll_direction(-1)
            else:
                scroll_direction(1)
    return user32.CallNextHookEx(hook_id, nCode, wParam, lParam)

# 回调必须保持引用，否则会被 GC 回收导致崩溃
# 保存为模块级变量，生命周期与进程一致
# （PyInstaller 打包后同样有效）
_mouse_proc_cb = LOW_LEVEL_MOUSE_PROC(low_level_mouse_proc)


def set_global_hook():
    global hook_id
    hook_id = user32.SetWindowsHookExW(
        WH_MOUSE_LL,
        _mouse_proc_cb,
        kernel32.GetModuleHandleW(None),
        0,
    )
    return bool(hook_id)


def remove_global_hook():
    global hook_id
    if hook_id:
        user32.UnhookWindowsHookEx(hook_id)
        hook_id = None


# 老板键：F1
WM_HOTKEY = 786
VK_F1 = 112
VK_LEFT = 37
VK_RIGHT = 39
MOD_NOREPEAT = 16384

# 自动滚动速度：0.6 行/秒起步，每档 0.2 行/秒，最高 6.0 行/秒
AUTO_SPEED_MIN = 0.6
AUTO_SPEED_MAX = 6.0
AUTO_SPEED_STEP = 0.2
AUTO_SPEED_DEFAULT = 1.0

user32.RegisterHotKey.restype = ctypes.c_bool
user32.RegisterHotKey.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32,
]
user32.UnregisterHotKey.restype = ctypes.c_bool
user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]

# 查询按键是否正被按住（不拦截按键，仅读取状态）
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]


def register_hotkey(hotkey_id, modifiers, vk):
    return bool(user32.RegisterHotKey(None, hotkey_id, modifiers, vk))


def unregister_hotkey(hotkey_id):
    user32.UnregisterHotKey(None, hotkey_id)


def key_pressed(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class HotkeyFilter(QAbstractNativeEventFilter):
    """拦截 WM_HOTKEY 消息，触发老板键回调（在 Qt 主线程内执行）"""

    def __init__(self, hotkey_id, callback):
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, eventType, message):
        if eventType == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                # 交给 Qt 主线程执行，避免在过滤器里直接操作窗口
                QTimer.singleShot(0, self._callback)
                return True, 0
        return False, 0


# 阅读进度标记：写在文件末尾的 #FTX#<id>#<offset>#
# （每次保存只保留最近 3 条，导入时取 id 最大的那条作为断点）
# 标记行在导入时会被自动剥离，不会显示在窗口里
MARKER_PREFIX = "#FTX#"
MARKER_RE = re.compile(r"^\s*#FTX#(\d+)#(\d+)#\s*$")


def build_marker(marker_id, offset):
    return f"{MARKER_PREFIX}{marker_id}#{offset}#"


def parse_markers(raw):
    """剥离标记行，返回 (正文文本, 标记列表[(id, offset)], 最大id)"""
    body_lines = []
    markers = []
    max_id = 0
    for line in raw.split("\n"):
        m = MARKER_RE.match(line)
        if m:
            mid, off = int(m.group(1)), int(m.group(2))
            markers.append((mid, off))
            max_id = max(max_id, mid)
        else:
            body_lines.append(line)
    return "\n".join(body_lines).rstrip("\n"), markers, max_id



class FloatingTextWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.text = "导入小说后显示第一行"
        self.font_size = 24
        self.text_color = QColor(255, 255, 255)
        self.bg_opacity = 0.3
        self.scroll_mode = "horizontal"
        self.line_width = 18
        self.line_count = 1
        self.current_index = 0
        self.lines = []
        self.display_rows = []
        self.row_starts = []
        self.file_path = None
        self.raw_content = None
        self.encoding = None

        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.setInterval(2000)
        self.auto_save_timer.timeout.connect(self.save_marker)

        # 显示模式：toggle = F1 切换显示/隐藏（默认），hold = 按住 F1 时显示
        self.display_mode = "toggle"
        # 滚动模式：False = 手动滚轮翻页（默认），True = 自动滚动
        self.auto_scroll = False
        self.auto_speed = AUTO_SPEED_DEFAULT
        self.auto_direction = 1
        self.f1_down = False
        self.left_down = False
        self.right_down = False

        # 轮询 F1 / 左右方向键的按下状态（不拦截按键）
        self.key_poll_timer = QTimer(self)
        self.key_poll_timer.setInterval(40)
        self.key_poll_timer.timeout.connect(self.poll_keys)
        self.key_poll_timer.start()

        self.auto_scroll_timer = QTimer(self)
        self.auto_scroll_timer.timeout.connect(self.auto_step)

        # 无边框 + 置顶 + 不在任务栏显示
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setObjectName("FloatingTextWindow")
        self.setStyleSheet("QWidget#FloatingTextWindow { background: transparent; }")

        # 鼠标拖动
        self.setMouseTracking(True)
        self.drag_pos = None

        # 文字标签（不接收鼠标事件，让拖动落到窗口上）
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(False)

        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)

        # 用一个垂直布局撑满窗口
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        # 右上角临时提示条（调速/换向时闪现，不打断阅读）
        self.hint = QLabel(self)
        self.hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hint.setFont(QFont("Microsoft YaHei", 10))
        self.hint.setStyleSheet(
            "QLabel { background: rgba(0, 0, 0, 170); color: #ffffff;"
            " padding: 2px 8px; border-radius: 6px; }"
        )
        self.hint.hide()
        self.hint_timer = QTimer(self)
        self.hint_timer.setSingleShot(True)
        self.hint_timer.timeout.connect(self.hint.hide)

        self.update_display()

        # 初始尺寸与位置
        self.resize_to_content()
        self.center_on_screen()

        # 全局滚轮钩子
        if not set_global_hook():
            print("⚠️ 全局钩子安装失败，请以管理员权限运行")

        # 老板键：F1
        self.hotkey_id = 1
        self.hotkey_filter = HotkeyFilter(self.hotkey_id, self.toggle_boss_key)
        QApplication.instance().installNativeEventFilter(self.hotkey_filter)
        if not register_hotkey(self.hotkey_id, MOD_NOREPEAT, VK_F1):
            print("⚠️ 老板键(F1)注册失败，可能已被其他程序占用")

        # ESC 退出
        self.shortcut = QShortcut(QKeySequence("Esc"), self)
        self.shortcut.activated.connect(self.close)

        # 右键菜单
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2
        )

    def update_display(self):
        """更新文字显示"""
        if not self.display_rows:
            self.label.setText("请导入小说文件（右键菜单）")
        else:
            # 只显示 line_count 行，越界时自动回到底部
            max_index = max(0, len(self.display_rows) - self.line_count)
            self.current_index = max(0, min(self.current_index, max_index))

            chunk = self.display_rows[self.current_index:self.current_index + self.line_count]
            while len(chunk) < self.line_count:
                chunk.append("")
            self.label.setText("\n".join(chunk))

        # 字体与颜色
        font = QFont("Microsoft YaHei", self.font_size)
        self.label.setFont(font)
        self.label.setStyleSheet(f"""
            color: rgba({self.text_color.red()}, {self.text_color.green()},
                        {self.text_color.blue()}, 255);
            background: transparent;
            padding: 10px;
        """)


        self.setWindowOpacity(self.bg_opacity)

    def scroll_text(self, direction):
        """滚动文字：direction=1 前进，-1 后退"""
        if self.auto_scroll:
            # 自动滚动模式下滚轮改为调速；窗口隐藏时不响应，
            # 否则在别的程序里滚动滚轮会偷偷改掉速度挡位
            if self.isVisible():
                self.set_auto_speed(
                    self.auto_speed + AUTO_SPEED_STEP * (1 if direction > 0 else -1)
                )
            return
        if not self.display_rows:
            return

        if not self.isVisible() or self.isMinimized():
            return

        if QApplication.activeModalWidget() is not None:
            return
        if self.scroll_mode == "horizontal":
            step = 1
        else:
            step = self.line_count
        self.advance(direction, step)

    def advance(self, direction, step):
        """按步长滚动，返回是否真的滚动了"""
        if not self.display_rows:
            return False

        if not self.isVisible() or self.isMinimized():
            return False

        if QApplication.activeModalWidget() is not None:
            return False
        self.current_index += direction * step

        max_index = max(0, len(self.display_rows) - self.line_count)
        self.current_index = max(0, min(self.current_index, max_index))
        self.update_display()

        self.auto_save_timer.start()
        return True

    def auto_step(self):
        """自动滚动定时器：每次走一个显示行"""
        self.advance(self.auto_direction, 1)

    def auto_interval(self):
        """速度（行/秒）换算成每行走一行的毫秒数"""
        speed = max(AUTO_SPEED_MIN, min(AUTO_SPEED_MAX, self.auto_speed))
        return max(50, int(round(1000.0 / speed)))

    def set_auto_scroll(self, enabled):
        """开启/关闭自动滚动（默认关闭）"""
        self.auto_scroll = bool(enabled)
        if self.auto_scroll:
            self.auto_scroll_timer.start(self.auto_interval())
            self.show_hint("自动滚动：%.1f 行/秒，滚轮调速，←→ 换向" % self.auto_speed)
        else:
            self.auto_scroll_timer.stop()
            self.show_hint("已切回手动滚动（滚轮翻页）")

    def set_auto_speed(self, speed):
        """调节自动滚动速度：滚轮上=加速，下=减速，每档 0.2 行/秒"""
        speed = round(speed / AUTO_SPEED_STEP) * AUTO_SPEED_STEP
        speed = max(AUTO_SPEED_MIN, min(AUTO_SPEED_MAX, speed))
        self.auto_speed = round(speed, 1)
        if self.auto_scroll:
            self.auto_scroll_timer.start(self.auto_interval())
        self.show_hint("滚动速度：%.1f 行/秒" % self.auto_speed)

    def set_auto_direction(self, direction):
        """调节自动滚动方向（→ 前进，← 后退）"""
        self.auto_direction = 1 if direction > 0 else -1
        self.show_hint("滚动方向：→ 前进" if self.auto_direction > 0 else "滚动方向：← 后退")

    def set_display_mode(self, mode):
        """切换显示模式：toggle = F1 切换（默认），hold = 按住 F1 才显示"""
        self.display_mode = "hold" if mode == "hold" else "toggle"
        if self.display_mode == "hold":
            self.show_hint("按住 F1 显示，松开隐藏（右键菜单可切回）")
            QTimer.singleShot(1500, self.hide)
        else:
            self.show()
            self.raise_()
            self.show_hint("F1 切换显示 / 隐藏")

    def show_for_hold(self):
        """按住模式：显示窗口但不抢焦点"""
        self.show()
        self.raise_()

    def poll_keys(self):
        """轮询 F1（按住显示）与左右方向键（自动滚动换向）"""
        f1_down = key_pressed(VK_F1)
        if self.display_mode == "hold":
            if f1_down and not self.isVisible():
                self.show_for_hold()
            elif not f1_down and self.isVisible():
                self.hide()
        self.f1_down = f1_down

        # 方向键只在自动滚动且窗口可见时生效，避免在别的程序里按键被误改
        if self.auto_scroll and self.isVisible():
            left_down = key_pressed(VK_LEFT)
            right_down = key_pressed(VK_RIGHT)
            if right_down and not self.right_down:
                self.set_auto_direction(1)
            if left_down and not self.left_down:
                self.set_auto_direction(-1)
            self.left_down = left_down
            self.right_down = right_down

    def show_hint(self, text):
        """在窗口右上角短暂显示一行提示"""
        self.hint.setText(text)
        self.hint.adjustSize()
        self.hint.move(max(0, self.width() - self.hint.width() - 6), 4)
        self.hint.show()
        self.hint.raise_()
        self.hint_timer.start(1500)


    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.drag_pos:
            self.move(self.pos() + event.globalPos() - self.drag_pos)
            self.drag_pos = event.globalPos()


    def show_context_menu(self, pos):
        menu = QMenu(self)


        import_action = QAction("📂 导入TXT小说", self)
        import_action.triggered.connect(self.load_txt)
        menu.addAction(import_action)

        menu.addSeparator()


        size_menu = menu.addMenu("🔤 字体大小")
        for s in (6, 7, 8, 9, 10, 11, 12, 16, 20, 24, 28, 32):
            act = QAction(str(s), self)
            act.triggered.connect(lambda checked, v=s: self.set_font_size(v))
            size_menu.addAction(act)


        width_menu = menu.addMenu("📏 每行字数")
        for w in (10, 12, 15, 18, 20, 24, 30, 40):
            act = QAction(str(w), self)
            act.triggered.connect(lambda checked, v=w: self.set_line_width(v))
            width_menu.addAction(act)


        rows_menu = menu.addMenu("📄 显示行数")
        for n in (1, 2, 3, 4, 5, 6, 8, 10):
            act = QAction(str(n), self)
            act.triggered.connect(lambda checked, v=n: self.set_line_count(v))
            rows_menu.addAction(act)


        color_action = QAction("🎨 文字颜色", self)
        color_action.triggered.connect(self.choose_color)
        menu.addAction(color_action)


        alpha_menu = menu.addMenu("🌫️ 窗口透明度")
        for a in (0.1, 0.2, 0.3, 0.5, 0.7, 1.0):
            act = QAction(f"{int(a * 100)}%", self)
            act.triggered.connect(lambda checked, v=a: self.set_bg_opacity(v))
            alpha_menu.addAction(act)


        mode_action = QAction("🔄 切换滚动模式", self)
        mode_action.triggered.connect(self.toggle_scroll_mode)
        menu.addAction(mode_action)

        # 显示模式（默认：F1 切换显示 / 隐藏）
        display_menu = menu.addMenu("🖥️ 显示模式")
        for value, label in (("toggle", "F1 切换显示 / 隐藏"),
                             ("hold", "按住 F1 显示，松开消失")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.display_mode == value)
            act.triggered.connect(lambda checked, v=value: self.set_display_mode(v))
            display_menu.addAction(act)

        # 滚动模式（默认：手动滚轮翻页）
        scroll_menu = menu.addMenu("▶️ 滚动模式")
        for value, label in ((False, "手动滚动（滚轮翻页）"),
                             (True, "自动滚动（滚轮调速，←→ 换向）")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.auto_scroll == value)
            act.triggered.connect(lambda checked, v=value: self.set_auto_scroll(v))
            scroll_menu.addAction(act)

        menu.addAction("当前: %s / %s（%s）" % (
            "按住 F1 显示" if self.display_mode == "hold" else "F1 切换显示",
            "自动滚动" if self.auto_scroll else "手动滚动",
            "速度 %.1f 行/秒" % self.auto_speed if self.auto_scroll else self.scroll_mode,
        ))

        menu.addSeparator()
        menu.addAction("❌ 退出 (ESC)", self.close)

        menu.exec_(self.mapToGlobal(pos))

    def load_txt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择小说文件", "", "Text Files (*.txt)"
        )
        if not file_path:
            return

        self.save_marker()
        try:

            content = None
            for encoding in ("utf-8", "gbk", "utf-16"):
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        content = f.read()
                    self.encoding = encoding
                    break
                except UnicodeDecodeError:
                    continue
            if content is None:
                QMessageBox.critical(self, "错误", "无法识别文件编码（已尝试 UTF-8 / GBK / UTF-16）")
                return


            body, markers, _ = parse_markers(content)
            resume_offset = max(markers, key=lambda m: m[0])[1] if markers else None

            self.file_path = file_path
            self.raw_content = content


            self.lines = [line.strip() for line in body.split("\n") if line.strip()]
            self.rebuild_rows()
            self.resize_to_content()


            if resume_offset is not None and self.row_starts:
                idx = 0
                for i, s in enumerate(self.row_starts):
                    if s <= resume_offset:
                        idx = i
                    else:
                        break
                self.current_index = idx

            self.update_display()
            msg = f"已导入 {len(self.lines)} 行"
            if resume_offset is not None:
                msg += "，已恢复到上次进度"
            QMessageBox.information(self, "成功", msg)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取失败: {e}")

    def set_font_size(self, size):
        self.font_size = size
        self.update_display()
        self.resize_to_content()

    def set_line_width(self, width):
        # 记录当前字符偏移，重排后尽量回到同一位置
        if self.display_rows and self.row_starts:
            offset = self.row_starts[self.current_index]
        else:
            offset = None
        self.line_width = width
        self.rebuild_rows()
        if offset is not None and self.row_starts:
            idx = 0
            for i, s in enumerate(self.row_starts):
                if s <= offset:
                    idx = i
                else:
                    break
            self.current_index = idx
        self.resize_to_content()
        self.update_display()

    def set_line_count(self, count):
        self.line_count = count
        self.resize_to_content()
        self.update_display()

    def rebuild_rows(self):
        """把每行文本按 line_width 切分成显示行（不跨文件行），并记录每行的起始字符偏移"""
        self.display_rows = []
        self.row_starts = []
        offset = 0
        for line in self.lines:
            for i in range(0, len(line), self.line_width):
                chunk = line[i:i + self.line_width]
                self.display_rows.append(chunk)
                self.row_starts.append(offset)
                offset += len(chunk)
        self.current_index = 0

    def resize_to_content(self):
        """窗口尺寸随字号、行宽、行数自适应"""
        fm = self.label.fontMetrics()

        char_w = fm.horizontalAdvance("文") if hasattr(fm, "horizontalAdvance") else fm.width("文")
        padding = 20
        w = self.line_width * char_w + padding
        h = max(60, self.line_count * fm.height() + padding)
        self.resize(w, h)
        if self.hint.isVisible():
            self.hint.move(max(0, self.width() - self.hint.width() - 6), 4)

    def choose_color(self):
        color = QColorDialog.getColor(self.text_color, self, "选择文字颜色")
        if color.isValid():
            self.text_color = color
            self.update_display()

    def set_bg_opacity(self, opacity):
        self.bg_opacity = opacity
        self.update_display()

    def toggle_scroll_mode(self):
        self.scroll_mode = "vertical" if self.scroll_mode == "horizontal" else "horizontal"
        QMessageBox.information(self, "提示", f"切换为 {self.scroll_mode} 滚动模式")

    def toggle_boss_key(self):
        """老板键：F1 隐藏，再按一次恢复"""
        if self.display_mode == "hold":
            # 按住模式：先显示，松手交给 poll_keys 隐藏
            self.show_for_hold()
            return

        # 隐藏前先保存进度，避免刚滚过就按 F1 丢失
        if self.isVisible():
            self.save_marker()
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def save_marker(self):
        """把当前阅读位置写入文件文末的标记行（最多保留最近 3 条）"""
        if not self.file_path or not self.raw_content or not self.display_rows:
            return
        if self.current_index >= len(self.row_starts):
            return
        offset = self.row_starts[self.current_index]
        body, markers, max_id = parse_markers(self.raw_content)
        markers.append((max_id + 1, offset))
        markers.sort()
        keep = markers[-3:]
        new_content = body + "\n" + "\n".join(build_marker(mid, off) for mid, off in keep)
        try:

            with open(self.file_path, "w", encoding=self.encoding, newline="") as f:
                f.write(new_content)

            self.raw_content = new_content
        except Exception as e:
            QMessageBox.warning(self, "提示", f"进度保存失败：{e}")

    def closeEvent(self, event):

        self.save_marker()

        if getattr(self, "hotkey_filter", None):
            QApplication.instance().removeNativeEventFilter(self.hotkey_filter)
        if hasattr(self, "hotkey_id"):
            unregister_hotkey(self.hotkey_id)
        remove_global_hook()
        self.key_poll_timer.stop()
        self.auto_scroll_timer.stop()
        event.accept()

        QApplication.instance().quit()



text_widget = None
scroll_direction = None
_single_instance_guard = None


def main():
    global text_widget, scroll_direction, _single_instance_guard

    app = QApplication(sys.argv)

    # 单实例保护：避免重复启动（多个实例会抢同一个滚轮钩子和老板键）
    # 用共享内存做互斥标记，进程退出后自动释放
    _single_instance_guard = QSharedMemory("FloatingTextReader_InstanceGuard")
    if not _single_instance_guard.create(1):
        QMessageBox.warning(None, "提示", "程序已在运行，请勿重复启动")
        return


    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        if not is_admin:
            print("⚠️ 建议以管理员权限运行，否则全局滚轮监听可能失效")
    except Exception:
        pass

    window = FloatingTextWindow()
    text_widget = window
    scroll_direction = window.scroll_text
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
