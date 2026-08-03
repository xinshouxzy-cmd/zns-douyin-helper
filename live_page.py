# -*- coding: utf-8 -*-
"""
遵农商·抖音AI工作台 — 直播助手页面
直播评论关键词监控 → 自动触发热键 → 直播伴侣切换场景/特效 + 知识库问答
（整合自《与遵同行助农兴企AI直播助手 v1.5.9》，selenium 驱动方案与评论私信助手统一）
"""
import os, sys, json, time, re, threading
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QLineEdit, QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QTextEdit,
)
from worker import BASE_DIR, find_chromedriver, get_bundled_chrome

CONFIG_PATH = os.path.join(BASE_DIR, "live_config.json")

# ── Windows 虚拟键码表 ──
VK = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
      "enter": 0x0D, "space": 0x20, "tab": 0x09, "esc": 0x1B, "backspace": 0x08}
for _i in range(10):
    VK[str(_i)] = 0x30 + _i
    VK[f"num{_i}"] = 0x60 + _i
for _i in range(12):
    VK[f"f{_i+1}"] = 0x70 + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())


def parse_hotkey(text):
    parts = [p.strip().lower() for p in str(text or "").split("+")]
    codes = [VK[p] for p in parts if p in VK]
    return codes if len(codes) == len(parts) and codes else None


def send_hotkey(codes):
    """Windows API 发送热键；非 Windows 返回 False（仅日志）"""
    if sys.platform != "win32":
        return False
    import ctypes
    u = ctypes.windll.user32
    UP = 0x0002
    mods = [c for c in codes if c in (0x11, 0x10, 0x12, 0x5B)]
    keys = [c for c in codes if c not in mods]
    for c in mods:
        u.keybd_event(c, 0, 0, 0)
    for c in keys:
        u.keybd_event(c, 0, 0, 0)
        u.keybd_event(c, 0, UP, 0)
    for c in reversed(mods):
        u.keybd_event(c, 0, UP, 0)
    return True


DEFAULT_CONFIG = {
    "live_url": "https://anchor.douyin.com/anchor/dashboard",
    "comment_selector": ".comment-item",
    "poll_interval": 0.5, "cooldown": 2.0,
    "default_scene_key": "num9", "scene_switch_delay": 0.3,
    "scenes": [
        {"keywords": "嘉年华", "hotkey": "ctrl+1"},
        {"keywords": "抖音1号,抖音一号", "hotkey": "ctrl+2"},
        {"keywords": "助力百姓美好生活,遵义农商银行", "hotkey": "ctrl+3"},
    ],
    "knowledge": [
        {"keywords": "利率", "answer": "我行消费贷年化利率 3.5% 起，详情可拨打 96688 咨询。"},
        {"keywords": "贷款", "answer": "贷款业务可到就近网点办理，或拨打 96688 咨询。"},
        {"keywords": "存款,定期", "answer": "我行定期存款利率 3.0% 起，欢迎到网点办理。"},
        {"keywords": "信用卡", "answer": "信用卡办理请携带身份证到网点，或拨打 96688 咨询。"},
    ],
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k in cfg:
                if k in user:
                    cfg[k] = user[k]
        except Exception:
            pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 主题色 ──
C_BG = "#0d1117"; C_CARD = "#161b26"; C_CARD2 = "#1c2333"; C_BORDER = "#263040"
C_TEXT = "#e8eef7"; C_SUB = "#8b98ad"; C_ACCENT = "#3d8bff"
C_GREEN = "#2ecc71"; C_RED = "#e74c3c"; C_YELLOW = "#f1c40f"; C_CYAN = "#00d2ff"

STYLE_CARD = f"QFrame {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 12px; }}"
STYLE_BTN = f"QPushButton {{ background: {C_CARD2}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 8px; padding: 7px 14px; font-size: 13px; }} QPushButton:hover {{ border-color: {C_ACCENT}; color: {C_ACCENT}; }}"
STYLE_BTN_ACC = f"QPushButton {{ background: {C_ACCENT}; color: white; border: none; border-radius: 8px; padding: 7px 14px; font-size: 13px; }} QPushButton:hover {{ background: #5a9dff; }}"
STYLE_TBL = (f"QTableWidget {{ background: {C_CARD2}; border: 1px solid {C_BORDER}; border-radius: 8px; color: {C_TEXT}; gridline-color: {C_BORDER}; }}"
             f"QHeaderView::section {{ background: {C_CARD2}; color: {C_SUB}; border: none; padding: 6px; font-size: 11px; }}")
STYLE_EDIT = f"QLineEdit, QDoubleSpinBox {{ background: {C_CARD2}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 5px 8px; }} QLineEdit:focus {{ border-color: {C_ACCENT}; }}"


class LiveMonitor(QThread):
    log = pyqtSignal(str)
    scene_triggered = pyqtSignal(str, str)   # (热键, 场景描述)
    knowledge_hit = pyqtSignal(str, str)     # (关键词, 答案)
    status = pyqtSignal(str, str)
    done = pyqtSignal(str, bool)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._run = True
        self._confirmed = threading.Event()

    def stop(self):
        self._run = False

    def confirm_login(self):
        """用户已扫码登录，手动确认 → 跳过评论区元素等待，直接开始监控"""
        self._confirmed.set()

    def L(self, msg):
        self.log.emit(msg)

    def _open_browser(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        self.L("正在准备浏览器…")
        driver_path = find_chromedriver()
        bundled = get_bundled_chrome()
        opt = Options()
        if bundled and os.path.exists(bundled):
            opt.binary_location = bundled
            self.L("使用内置浏览器")
        elif not os.path.exists(driver_path) or driver_path in ("chromedriver", "chromedriver.exe"):
            self.L("检测系统 Chrome 版本…")
            try:
                import threading as _th
                from webdriver_manager.chrome import ChromeDriverManager
                _r = []
                def _do():
                    try:
                        _r.append(ChromeDriverManager().install())
                    except Exception as _e:
                        _r.append(_e)
                _t = _th.Thread(target=_do, daemon=True)
                _t.start()
                _t.join(timeout=25)
                if not _r:
                    raise RuntimeError("驱动下载超时，请检查网络后重试")
                if isinstance(_r[0], Exception):
                    raise _r[0]
                driver_path = _r[0]
                self.L("✓ 浏览器驱动就绪")
            except Exception as e:
                raise RuntimeError(f"浏览器驱动获取失败：{e}\n请检查网络，或手动把 chromedriver.exe 放入软件目录 runtime/ 文件夹")
        opt.add_argument("--disable-blink-features=AutomationControlled")
        opt.add_experimental_option("excludeSwitches", ["enable-automation"])
        opt.add_experimental_option("useAutomationExtension", False)
        opt.add_argument("--no-first-run")
        opt.add_argument("--no-default-browser-check")
        self.L("启动浏览器窗口…（请在弹出的窗口扫码登录直播后台）")
        d = webdriver.Chrome(service=Service(driver_path), options=opt)
        try:
            d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
        except Exception:
            pass
        d.set_window_size(1200, 860)
        return d

    def run(self):
        try:
            self._monitor()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.log.emit(f"[red]监控异常：{e}")
            self.done.emit(f"监控异常：{e}", False)

    def _monitor(self):
        from selenium.webdriver.common.by import By
        cfg = self.cfg
        url = cfg.get("live_url") or DEFAULT_CONFIG["live_url"]
        sel = cfg.get("comment_selector") or ".comment-item"
        interval = max(0.2, float(cfg.get("poll_interval", 0.5)))
        cooldown = max(0.0, float(cfg.get("cooldown", 2.0)))
        switch_delay = max(0.0, float(cfg.get("scene_switch_delay", 0.3)))
        scenes = []
        for s in cfg.get("scenes", []):
            ks = [k.strip() for k in str(s.get("keywords", "")).split(",") if k.strip()]
            hk = str(s.get("hotkey", "")).strip()
            if ks and hk:
                scenes.append([ks, hk, 0.0])
        knowledge = []
        for k in cfg.get("knowledge", []):
            ks = [x.strip() for x in str(k.get("keywords", "")).split(",") if x.strip()]
            ans = str(k.get("answer", "")).strip()
            if ks and ans:
                knowledge.append((ks, ans))
        if not scenes:
            self.L("[yellow]⚠ 未配置场景规则，仅执行知识库问答")
        d = self._open_browser()
        self.L(f"打开直播后台：{url}")
        self.status.emit("等待登录…", C_YELLOW)
        d.get(url)
        waited = 0
        try:
            while self._run and waited < 180 and not self._confirmed.is_set():
                if d.find_elements(By.CSS_SELECTOR, sel):
                    break
                time.sleep(0.5)
                waited += 0.5
        except Exception:
            pass
        if not self._run:
            try:
                d.quit()
            except Exception:
                pass
            self.done.emit("已停止", True)
            return
        if self._confirmed.is_set():
            # 用户手动确认已登录：不再依赖评论区元素，直接开始监控
            self.L("✓ 已确认登录，开始监控（间隔 {interval}s）".format(interval=interval))
            self.status.emit("监控中", C_GREEN)
        elif waited >= 180:
            self.L("[yellow]⚠ 未检测到评论区，请确认已扫码登录且正在开播")
            self.status.emit("未检测到评论区", C_RED)
        else:
            self.L(f"✓ 评论区就绪，开始监控（间隔 {interval}s）")
            self.status.emit("监控中", C_GREEN)
        seen = set()
        while self._run:
            try:
                nodes = d.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                nodes = []
            for node in nodes:
                try:
                    text = node.text.strip()
                except Exception:
                    continue
                if not text:
                    continue
                key = re.sub(r"\s+", "", text)[-40:]
                if key in seen:
                    continue
                seen.add(key)
                if len(seen) > 600:
                    seen = set(list(seen)[-400:])
                self.log.emit(f"[white]💬 {text[:60]}")
                now = time.time()
                for item in scenes:
                    ks, hk, last_t = item
                    if any(kw in text for kw in ks):
                        if now - last_t >= cooldown:
                            item[2] = now
                            self.log.emit(f"[green]⚡ 命中场景「{ks[0]}」→ 发送热键 {hk}")
                            self.scene_triggered.emit(hk, f"观众发送「{ks[0]}」")
                            if switch_delay > 0:
                                time.sleep(switch_delay)
                        break
                for ks, ans in knowledge:
                    if any(kw in text for kw in ks):
                        self.log.emit(f"[cyan]📚 知识库命中「{ks[0]}」→ 弹窗提示")
                        self.knowledge_hit.emit(ks[0], ans)
                        break
            try:
                time.sleep(interval)
            except Exception:
                break
        try:
            d.quit()
        except Exception:
            pass
        self.done.emit("已停止", True)


class LivePage(QWidget):
    """直播助手：评论关键词 → 触发热键切换场景/特效 + 知识库问答"""
    go_home = pyqtSignal()
    check_update = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = load_config()
        self.monitor = None
        self._build_ui()
        self._load_to_ui()

    def _mk(self, text, size=12, color=C_TEXT, bold=False):
        lb = QLabel(text)
        ft = QFont()
        ft.setPointSize(size)
        ft.setBold(bold)
        lb.setFont(ft)
        lb.setStyleSheet(f"color: {color}; background: transparent;")
        return lb

    def _card(self):
        f = QFrame()
        f.setStyleSheet(STYLE_CARD)
        return f

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)
        # ── 顶栏 ──
        top = QHBoxLayout()
        btn_back = QPushButton("← 返回首页")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(STYLE_BTN)
        btn_back.clicked.connect(self.go_home.emit)
        top.addWidget(btn_back)
        top.addSpacing(4)
        top.addWidget(self._mk("🎥 直播助手", 17, C_TEXT, True))
        top.addSpacing(10)
        top.addWidget(self._mk("评论关键词 → 触发场景特效 · 知识库问答", 11, C_SUB))
        top.addStretch(1)
        self.lb_status = QLabel("未启动")
        self.lb_status.setStyleSheet(f"color: {C_SUB}; background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px; padding: 6px 14px;")
        top.addWidget(self.lb_status)
        btn_upd = QPushButton("🔄 检查更新")
        btn_upd.setCursor(Qt.PointingHandCursor)
        btn_upd.setStyleSheet(STYLE_BTN)
        btn_upd.clicked.connect(self.check_update.emit)
        top.addWidget(btn_upd)
        outer.addLayout(top)
        # ── 设置卡片 ──
        card = self._card()
        gl = QGridLayout(card)
        gl.setContentsMargins(14, 12, 14, 12)
        gl.setSpacing(8)
        gl.addWidget(self._mk("直播后台地址", 11, C_SUB), 0, 0)
        self.ed_url = QLineEdit()
        gl.addWidget(self.ed_url, 0, 1)
        gl.addWidget(self._mk("评论选择器", 11, C_SUB), 0, 2)
        self.ed_sel = QLineEdit()
        gl.addWidget(self.ed_sel, 0, 3)
        gl.addWidget(self._mk("检测间隔(秒)", 11, C_SUB), 1, 0)
        self.sp_interval = QDoubleSpinBox(); self.sp_interval.setRange(0.2, 10); self.sp_interval.setSingleStep(0.1)
        gl.addWidget(self.sp_interval, 1, 1)
        gl.addWidget(self._mk("触发冷却(秒)", 11, C_SUB), 1, 2)
        self.sp_cooldown = QDoubleSpinBox(); self.sp_cooldown.setRange(0.0, 60); self.sp_cooldown.setSingleStep(0.5)
        gl.addWidget(self.sp_cooldown, 1, 3)
        gl.addWidget(self._mk("默认场景热键", 11, C_SUB), 2, 0)
        self.ed_defkey = QLineEdit()
        gl.addWidget(self.ed_defkey, 2, 1)
        gl.addWidget(self._mk("场景切换延迟(秒)", 11, C_SUB), 2, 2)
        self.sp_delay = QDoubleSpinBox(); self.sp_delay.setRange(0.0, 5); self.sp_delay.setSingleStep(0.1)
        gl.addWidget(self.sp_delay, 2, 3)
        gl.addWidget(self._mk("热键格式：ctrl+1 / num9 / f5（+ 组合修饰键；num 为小键盘）", 10, C_SUB), 3, 0, 1, 4)
        for w in (self.ed_url, self.ed_sel, self.ed_defkey, self.sp_interval, self.sp_cooldown, self.sp_delay):
            w.setStyleSheet(STYLE_EDIT)
        outer.addWidget(card)
        # ── 规则表格区 ──
        mid = QHBoxLayout()
        f_scene = self._card(); sv = QVBoxLayout(f_scene); sv.setContentsMargins(12, 10, 12, 10)
        sh = QHBoxLayout(); sh.addWidget(self._mk("🎬 场景触发规则", 13, C_TEXT, True)); sh.addStretch(1)
        b1 = QPushButton("＋ 添加规则"); b1.setStyleSheet(STYLE_BTN_ACC); b1.clicked.connect(lambda: self._add_row(self.tbl_scene, 2))
        sh.addWidget(b1); sv.addLayout(sh)
        self.tbl_scene = QTableWidget(0, 3)
        self.tbl_scene.setHorizontalHeaderLabels(["触发关键词（逗号分隔）", "发送热键", "操作"])
        self.tbl_scene.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_scene.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_scene.verticalHeader().setVisible(False)
        self.tbl_scene.setStyleSheet(STYLE_TBL)
        sv.addWidget(self.tbl_scene)
        mid.addWidget(f_scene, 3)
        f_kn = self._card(); kv = QVBoxLayout(f_kn); kv.setContentsMargins(12, 10, 12, 10)
        kh = QHBoxLayout(); kh.addWidget(self._mk("📚 知识库问答", 13, C_TEXT, True)); kh.addStretch(1)
        b2 = QPushButton("＋ 添加条目"); b2.setStyleSheet(STYLE_BTN_ACC); b2.clicked.connect(lambda: self._add_row(self.tbl_kn, 3))
        kh.addWidget(b2); kv.addLayout(kh)
        self.tbl_kn = QTableWidget(0, 3)
        self.tbl_kn.setHorizontalHeaderLabels(["触发关键词（逗号分隔）", "回复答案", "操作"])
        self.tbl_kn.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl_kn.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_kn.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_kn.verticalHeader().setVisible(False)
        self.tbl_kn.setStyleSheet(STYLE_TBL)
        kv.addWidget(self.tbl_kn)
        mid.addWidget(f_kn, 3)
        outer.addLayout(mid, 1)
        # ── 控制 + 日志 ──
        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("▶ 开始监控")
        self.btn_start.setStyleSheet(STYLE_BTN_ACC)
        self.btn_start.clicked.connect(self._start)
        self.btn_confirm = QPushButton("✅ 我已登录，开始监控")
        self.btn_confirm.setStyleSheet(f"QPushButton {{ background: #1a4d2e; color: #7dffb0; border: 1px solid #2e7d4f; border-radius: 6px; padding: 6px 14px; }}")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self._confirm_login)
        self.btn_stop = QPushButton("⏹ 停止监控")
        self.btn_stop.setStyleSheet(STYLE_BTN)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_confirm)
        ctrl.addWidget(self.btn_stop)
        ctrl.addStretch(1)
        ctrl.addWidget(self._mk("监控日志", 11, C_SUB))
        outer.addLayout(ctrl)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet(f"QTextEdit {{ background: {C_BG}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 8px; font-size: 12px; }}")
        outer.addWidget(self.txt_log, 1)

    # ── 表格操作 ──
    def _add_row(self, tbl, ncols, kw="", val=""):
        r = tbl.rowCount()
        tbl.insertRow(r)
        for i in range(ncols):
            item = QTableWidgetItem(kw if i == 0 else (val if i == 1 else ""))
            item.setForeground(Qt.white)
            tbl.setItem(r, i, item)
        if ncols == 3:
            b = QPushButton("删除")
            b.setStyleSheet(f"QPushButton {{ background: #3a2222; color: {C_RED}; border: none; border-radius: 5px; padding: 3px 8px; }}")
            b.clicked.connect(lambda _, rr=r: tbl.removeRow(rr))
            tbl.setCellWidget(r, ncols - 1, b)

    # ── 配置读写 ──
    def _load_to_ui(self):
        self.ed_url.setText(self.cfg.get("live_url", ""))
        self.ed_sel.setText(self.cfg.get("comment_selector", ""))
        self.sp_interval.setValue(float(self.cfg.get("poll_interval", 0.5)))
        self.sp_cooldown.setValue(float(self.cfg.get("cooldown", 2.0)))
        self.ed_defkey.setText(self.cfg.get("default_scene_key", ""))
        self.sp_delay.setValue(float(self.cfg.get("scene_switch_delay", 0.3)))
        for s in self.cfg.get("scenes", []):
            self._add_row(self.tbl_scene, 2, s.get("keywords", ""), s.get("hotkey", ""))
        for k in self.cfg.get("knowledge", []):
            self._add_row(self.tbl_kn, 3, k.get("keywords", ""), k.get("answer", ""))

    def _collect(self):
        scenes = []
        for r in range(self.tbl_scene.rowCount()):
            kw = (self.tbl_scene.item(r, 0).text() if self.tbl_scene.item(r, 0) else "").strip()
            hk = (self.tbl_scene.item(r, 1).text() if self.tbl_scene.item(r, 1) else "").strip()
            if kw and hk:
                scenes.append({"keywords": kw, "hotkey": hk})
        knowledge = []
        for r in range(self.tbl_kn.rowCount()):
            kw = (self.tbl_kn.item(r, 0).text() if self.tbl_kn.item(r, 0) else "").strip()
            ans = (self.tbl_kn.item(r, 1).text() if self.tbl_kn.item(r, 1) else "").strip()
            if kw and ans:
                knowledge.append({"keywords": kw, "answer": ans})
        return {
            "live_url": self.ed_url.text().strip(),
            "comment_selector": self.ed_sel.text().strip() or ".comment-item",
            "poll_interval": self.sp_interval.value(),
            "cooldown": self.sp_cooldown.value(),
            "default_scene_key": self.ed_defkey.text().strip() or "num9",
            "scene_switch_delay": self.sp_delay.value(),
            "scenes": scenes,
            "knowledge": knowledge,
        }

    # ── 控制 ──
    def _start(self):
        if self.monitor and self.monitor.isRunning():
            return
        cfg = self._collect()
        save_config(cfg)
        self.cfg = cfg
        self.txt_log.clear()
        self.monitor = LiveMonitor(cfg)
        self.monitor.log.connect(self._append_log)
        self.monitor.scene_triggered.connect(self._on_scene)
        self.monitor.knowledge_hit.connect(self._on_knowledge)
        self.monitor.status.connect(lambda t, c: self._set_status(t, c))
        self.monitor.done.connect(self._on_done)
        self.monitor.start()
        self.btn_start.setEnabled(False)
        self.btn_confirm.setEnabled(True)
        self.btn_stop.setEnabled(True)

    def _confirm_login(self):
        """用户扫码登录后手动确认：立即跳过等待，开始监控"""
        if self.monitor and self.monitor.isRunning():
            self.monitor.confirm_login()
            self._append_log("[green]✓ 已确认登录，立即开始监控")
            self.btn_confirm.setEnabled(False)

    def _stop(self):
        if self.monitor:
            self.monitor.stop()

    def _stop_if_running(self):
        """返回首页时调用：如正在监控则停止"""
        if self.monitor and self.monitor.isRunning():
            self.monitor.stop()

    def _on_done(self, msg, ok):
        self.btn_start.setEnabled(True)
        self.btn_confirm.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self._set_status(msg, C_GREEN if ok else C_RED)

    def _set_status(self, text, color):
        self.lb_status.setText(text)
        self.lb_status.setStyleSheet(f"color: {color}; background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px; padding: 6px 14px;")

    def _append_log(self, msg):
        color_map = {"red": C_RED, "green": C_GREEN, "yellow": C_YELLOW, "cyan": C_CYAN, "white": C_TEXT}
        m = re.match(r"^\[(\w+)\](.*)", msg)
        if m:
            color = color_map.get(m.group(1), C_TEXT)
            text = m.group(2)
        else:
            color, text = C_TEXT, msg
        self.txt_log.append(f'<span style="color:{color}">{text}</span>')

    def _on_scene(self, hotkey, desc):
        codes = parse_hotkey(hotkey)
        if not codes:
            self.txt_log.append(f'<span style="color:{C_RED}">✗ 热键「{hotkey}」无法解析，请检查格式（如 ctrl+1 / num9）</span>')
            return
        if send_hotkey(codes):
            self.txt_log.append(f'<span style="color:{C_ACCENT}">🎬 已发送热键 {hotkey} → 直播伴侣切换场景（{desc}）</span>')
        else:
            self.txt_log.append(f'<span style="color:{C_YELLOW}">（非 Windows 环境，模拟热键已跳过）{desc}</span>')

    def _on_knowledge(self, kw, answer):
        box = QMessageBox(self)
        box.setWindowTitle("📚 知识库问答")
        box.setText(f"观众提问命中：「{kw}」")
        box.setInformativeText(answer)
        box.setIcon(QMessageBox.Information)
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.setStyleSheet(f"QMessageBox {{ background: {C_CARD}; color: {C_TEXT}; }} QLabel {{ color: {C_TEXT}; }}")
        box.show()
        box.raise_()
        box.activateWindow()
        self.msg_boxes.append(box)
        if len(self.msg_boxes) > 3:
            old = self.msg_boxes.pop(0)
            old.close()
