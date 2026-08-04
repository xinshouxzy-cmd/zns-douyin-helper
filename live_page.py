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
    QHeaderView, QMessageBox, QTextEdit, QComboBox,
)
from selenium.webdriver.common.by import By
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

# ── 热键下拉选项（避免手输出错）──
MOD_OPTIONS = [
    ("无", ""), ("Ctrl", "ctrl"), ("Alt", "alt"), ("Shift", "shift"),
    ("Ctrl+Alt", "ctrl+alt"), ("Ctrl+Shift", "ctrl+shift"),
    ("Alt+Shift", "alt+shift"), ("Ctrl+Alt+Shift", "ctrl+alt+shift"),
]
KEY_OPTIONS = ([("数字" + str(i), str(i)) for i in range(10)] +
               [(c, c.lower()) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] +
               [("F" + str(i), "f" + str(i)) for i in range(1, 13)] +
               [("小键盘" + str(i), "num" + str(i)) for i in range(10)])
NUM_KEY_OPTIONS = [("小键盘" + str(i), "num" + str(i)) for i in range(10)]


def parse_hotkey(text):
    parts = [p.strip().lower() for p in str(text or "").split("+")]
    codes = [VK[p] for p in parts if p in VK]
    return codes if len(codes) == len(parts) and codes else None


def send_hotkey(codes, hold=0.06, gap=0.03):
    """Windows API 发送热键（SendInput 优先，失败自动回退 keybd_event）；
    按下/抬起之间保留真实按键时序（hold=按住时长），避免目标软件把瞬时事件当噪音丢弃。
    非 Windows 返回 False（仅日志）"""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    UP = 0x0002
    INPUT_KEYBOARD = 1

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]   # ULONG_PTR

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    def make_input(vk, scan, flags):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.wScan = scan
        inp.ki.dwFlags = flags
        return inp

    mods = [c for c in codes if c in (0x11, 0x10, 0x12, 0x5B)]
    keys = [c for c in codes if c not in mods]
    scan = {c: u.MapVirtualKeyW(c, 0) for c in codes}
    seq = []
    for c in mods:
        seq.append((c, scan[c], 0))
    for c in keys:
        seq.append((c, scan[c], 0))
        seq.append((c, scan[c], UP))
    for c in reversed(mods):
        seq.append((c, scan[c], UP))

    # 方式1：SendInput（结构体带 union，大小必须与系统一致，否则 API 直接失败）
    ok = True
    for vk, sc, fl in seq:
        inp = make_input(vk, sc, fl)
        if u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            ok = False
            break
        time.sleep(hold if fl == UP else gap)
    if ok:
        return True

    # 方式2：keybd_event 回退（部分软件只认这种注入方式）
    for c in mods:
        u.keybd_event(c, 0, 0, 0)
        time.sleep(gap)
    for c in keys:
        u.keybd_event(c, 0, 0, 0)
        time.sleep(hold)
        u.keybd_event(c, 0, UP, 0)
        time.sleep(gap)
    for c in reversed(mods):
        u.keybd_event(c, 0, UP, 0)
        time.sleep(gap)
    return True


DEFAULT_CONFIG = {
    "live_url": "https://anchor.douyin.com/anchor/dashboard",
    "comment_selector": ".comment-item",
    "comment_selectors": [
        ".comment-item",
        ".webcast-chatroom___items .webcast-chatroom___item",
        "[class*='chatroom'] [class*='item']",
        "[class*='comment'] [class*='item']",
        "[class*='chat'] [class*='item']",
    ],
    "poll_interval": 0.5, "cooldown": 2.0,
    "default_scene_key": "num9", "scene_switch_delay": 0.3,
    "scene_hold_seconds": 7.0,
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
            # 旧配置没有 comment_selectors 时补默认链
            if not cfg.get("comment_selectors"):
                cfg["comment_selectors"] = list(DEFAULT_CONFIG["comment_selectors"])
            if str(cfg.get("comment_selector", "")).strip() and \
               str(cfg["comment_selector"]).strip() not in cfg["comment_selectors"]:
                cfg["comment_selectors"].insert(0, str(cfg["comment_selector"]).strip())
        except Exception:
            pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def live_profile_dir():
    """直播浏览器登录态目录（同一台电脑复用，免重复扫码）。
    打包版：软件目录/chrome_profiles/live；源码版：代码目录/chrome_profiles/live"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = BASE_DIR
    return os.path.join(base, "chrome_profiles", "live")


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
STYLE_COMBO = (f"QComboBox {{ background: {C_CARD2}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 3px 8px; }}"
               f"QComboBox QAbstractItemView {{ background: {C_CARD2}; color: {C_TEXT}; selection-background-color: {C_ACCENT}; }}")


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
        self._active_sel = None   # 命中并缓存的选择器（heartbeat 日志使用）

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
        # 持久化登录态：同一台电脑复用同一份 Chrome 配置目录，扫码一次后不再重复登录
        profile_dir = live_profile_dir()
        try:
            os.makedirs(profile_dir, exist_ok=True)
            opt.add_argument(f"--user-data-dir={profile_dir}")
            self.L(f"登录态目录：{profile_dir}（扫码一次，下次免登录）")
        except Exception as e:
            self.L(f"[yellow]⚠ 登录态目录创建失败（{e}），本次为临时登录")
        opt.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        })
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

    # ── 评论采集：选择器链 + MutationObserver 双通道 ──
    UI_NOISE = {
        "我知道了", "评论发送", "评论", "发送", "暂无礼物记录", "暂无权限查看",
        "预览流看播", "看播", "在线人数", "音浪收入", "送礼人数", "评论人数",
        "点赞次数", "实时在线人数", "实时进房人数", "新增渠道营收占比",
        "直播中", "未开播", "已开播", "互动", "商品", "数据", "更多",
    }
    NOISE_PREFIX = ("预览流看播", "在线人数音浪收入送礼人数评论人数点赞次数")

    @staticmethod
    def _looks_like_comment(t):
        """粗过滤：去掉纯数字/纯符号/超长文本/后台界面文案，剩下的按评论处理"""
        t = (t or "").strip()
        if not t or len(t) < 1 or len(t) > 120:
            return False
        if t.isdigit():
            return False
        if re.fullmatch(r"[\W_\s]+", t):
            return False
        if t in LiveMonitor.UI_NOISE:
            return False
        if t.startswith(LiveMonitor.NOISE_PREFIX):
            return False
        return True

    def _inject_observer(self, d):
        """注入 MutationObserver：页面新增的短文本实时收集到 window.__liveCommentBuf
        不依赖任何 class 名，评论 DOM 怎么变都能抓到。
        注意：观察目标必须是 document.documentElement —— 登录跳转等场景会整页替换
        document.body，若观察 body 就会全部失效（旧评论能抓、新评论全丢就是这个原因）。"""
        js = r"""
        (function(){
          if (window.__liveObserverInstalled) {
            try { window.__liveObserver.disconnect(); } catch(e){}
          }
          window.__liveCommentBuf = [];
          window.__liveObserverBody = document.body;
          var buf = window.__liveCommentBuf;
          function pushText(t){
            t = (t||'').replace(/\s+/g,' ').trim();
            if (t && t.length >= 1 && t.length <= 120) buf.push({text:t, t:Date.now()});
          }
          function sniff(n){
            if (n.nodeType === 3) { pushText(n.nodeValue); return; }
            if (n.nodeType !== 1) return;
            var tag = (n.tagName||'').toLowerCase();
            if (tag === 'script' || tag === 'style' || tag === 'svg') return;
            pushText(n.textContent);
            var w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT, null);
            while (w.nextNode()) pushText(w.currentNode.nodeValue);
          }
          var mo = new MutationObserver(function(recs){
            for (var i=0;i<recs.length;i++){
              var r = recs[i];
              for (var j=0;j<r.addedNodes.length;j++) sniff(r.addedNodes[j]);
            }
          });
          mo.observe(document.documentElement, {childList:true, subtree:true});
          window.__liveObserver = mo;
          window.__liveObserverInstalled = true;
          return 'ok';
        })()
        """
        try:
            return d.execute_script(js)
        except Exception as e:
            return "err:" + str(e)

    def _sniff_all(self, d):
        """兜底通道：全量扫描页面上的叶子级短文本（新评论即使观察器失效也能抓到）"""
        js = r"""
        (function(){
          var out = [];
          var els = document.querySelectorAll('div,span,p,section,li');
          for (var i=0;i<els.length;i++){
            var el = els[i];
            if (el.children && el.children.length > 0) continue;
            var t = (el.textContent||'').replace(/\s+/g,' ').trim();
            if (t && t.length >= 1 && t.length <= 120) out.push({text:t, t:Date.now()});
          }
          return out;
        })()
        """
        try:
            return d.execute_script(js)
        except Exception:
            return []

    def _drain_js_comments(self, d):
        """取走 JS 缓冲里的新文本（取完清空）"""
        try:
            return d.execute_script(
                "var a=window.__liveCommentBuf||[];window.__liveCommentBuf=[];return a;")
        except Exception:
            return []

    def _schedule_return_main(self, delay, codes):
        """场景特效保持 delay 秒后，自动发送主镜头热键（后台线程，不阻塞监控循环）"""
        def _do():
            time.sleep(delay)
            if self._run:
                try:
                    send_hotkey(codes)
                    self.log.emit(f"[cyan]↩ 场景已保持 {delay:g} 秒，已自动返回主镜头")
                except Exception as e:
                    self.log.emit(f"[red]自动返回主镜头失败：{e}")
        threading.Thread(target=_do, daemon=True).start()

    def _pick_selector(self, d, selectors):
        """依次尝试选择器，返回第一个能命中元素的选择器（缓存到 self._active_sel）"""
        if getattr(self, "_active_sel", None):
            try:
                if d.find_elements(By.CSS_SELECTOR, self._active_sel):
                    return self._active_sel
            except Exception:
                pass
        for sel in selectors:
            try:
                if d.find_elements(By.CSS_SELECTOR, sel):
                    self._active_sel = sel
                    return sel
            except Exception:
                continue
        return None

    def _scan_selector(self, d, sel):
        """选择器通道：读取每个评论元素的文本"""
        out = []
        try:
            for node in d.find_elements(By.CSS_SELECTOR, sel):
                try:
                    t = node.text.strip()
                except Exception:
                    continue
                if t:
                    out.append(t)
        except Exception:
            pass
        return out

    def _monitor(self):
        cfg = self.cfg
        url = cfg.get("live_url") or DEFAULT_CONFIG["live_url"]
        sel_chain = list(cfg.get("comment_selectors") or [])
        if not sel_chain:
            sel_chain = [cfg.get("comment_selector") or ".comment-item"]
        interval = max(0.2, float(cfg.get("poll_interval", 0.5)))
        cooldown = max(0.0, float(cfg.get("cooldown", 2.0)))
        switch_delay = max(0.0, float(cfg.get("scene_switch_delay", 0.3)))
        hold_seconds = max(0.0, float(cfg.get("scene_hold_seconds", 7.0)))
        scenes = []
        for s in cfg.get("scenes", []):
            ks = [k.strip() for k in re.split(r"[,，]", str(s.get("keywords", ""))) if k.strip()]
            hk = str(s.get("hotkey", "")).strip()
            if ks and hk:
                scenes.append([ks, hk, 0.0])
        knowledge = []
        for k in cfg.get("knowledge", []):
            ks = [x.strip() for x in re.split(r"[,，]", str(k.get("keywords", ""))) if x.strip()]
            ans = str(k.get("answer", "")).strip()
            if ks and ans:
                knowledge.append((ks, ans))
        if not scenes:
            self.L("[yellow]⚠ 未配置场景规则，仅执行知识库问答")
        d = self._open_browser()
        self.L(f"打开直播后台：{url}")
        self.status.emit("等待登录…", C_YELLOW)
        d.get(url)
        self.L("正在注入评论采集器…")
        inj = self._inject_observer(d)
        observer_ok = inj in ("ok", "already")
        if not observer_ok:
            try:
                observer_ok = bool(d.execute_script("return window.__liveObserverInstalled===true"))
            except Exception:
                observer_ok = False
        if not observer_ok:
            time.sleep(1.0)
            inj = self._inject_observer(d)
            try:
                observer_ok = bool(d.execute_script("return window.__liveObserverInstalled===true"))
            except Exception:
                observer_ok = False
        self.L("✓ 评论采集器就绪（选择器 + 实时捕获双通道）" if observer_ok
               else "[yellow]⚠ 实时捕获未就绪，仅用选择器通道（评论仍可识别）")
        waited = 0
        try:
            while self._run and waited < 180 and not self._confirmed.is_set():
                if self._pick_selector(d, sel_chain):
                    break
                if not d.execute_script("return window.__liveObserverInstalled===true"):
                    self._inject_observer(d)
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
            self.L("[yellow]提示：请确认已打开直播后台「互动」面板，或已进入直播间页面；检测到评论会自动记录并触发")
            self.status.emit("监控中", C_GREEN)
        elif waited >= 180:
            self.L("[yellow]⚠ 未检测到评论区，请确认已扫码登录且正在开播")
            self.status.emit("未检测到评论区", C_RED)
        else:
            self.L(f"✓ 评论区就绪（选择器：{self._active_sel}），开始监控（间隔 {interval}s）")
            self.status.emit("监控中", C_GREEN)
        main_codes = parse_hotkey(str(cfg.get("default_scene_key") or "").strip())
        seen = {}          # 文本 -> 最近出现时间（30 秒窗口去重，防止双通道重复 & 同条刷屏）
        DEDUPE_WIN = 30.0
        last_beat = time.time()
        round_no = 0
        while self._run:
            round_no += 1
            # 采集：选择器 + MutationObserver + 全量快照兜底
            texts = []
            sel = self._pick_selector(d, sel_chain)
            if sel:
                texts.extend(self._scan_selector(d, sel))
            try:
                ok = d.execute_script(
                    "return window.__liveObserverInstalled===true && "
                    "window.__liveObserverBody===document.body")
                if not ok:
                    self._inject_observer(d)
            except Exception:
                pass
            js_texts = [x.get("text", "") for x in self._drain_js_comments(d) if isinstance(x, dict)]
            texts.extend(js_texts)
            if round_no % 4 == 0:  # 每约 2 秒全量扫描一次，观察器漏抓也能兜住
                texts.extend(x.get("text", "") for x in self._sniff_all(d) if isinstance(x, dict))
            fresh = 0
            for text in texts:
                if not self._looks_like_comment(text):
                    continue
                key = re.sub(r"\s+", "", text)[-40:]
                now = time.time()
                if key in seen and now - seen[key] < DEDUPE_WIN:
                    continue
                seen[key] = now
                if len(seen) > 1000:
                    seen = {k: v for k, v in seen.items() if now - v < DEDUPE_WIN * 3}
                fresh += 1
                self.log.emit(f"[white]💬 {text[:60]}")
                for item in scenes:
                    ks, hk, last_t = item
                    if any(kw in text for kw in ks):
                        if now - last_t >= cooldown:
                            item[2] = now
                            self.log.emit(f"[green]⚡ 命中场景「{ks[0]}」→ 发送热键 {hk}")
                            self.scene_triggered.emit(hk, f"观众发送「{ks[0]}」")
                            if switch_delay > 0:
                                time.sleep(switch_delay)
                            # 特效保持 hold_seconds 秒后自动返回主镜头（直播伴侣全局热键）
                            if main_codes and sys.platform == "win32" and hold_seconds > 0:
                                self._schedule_return_main(hold_seconds, main_codes)
                        break
                for ks, ans in knowledge:
                    if any(kw in text for kw in ks):
                        self.log.emit(f"[cyan]📚 知识库命中「{ks[0]}」→ 弹窗提示")
                        self.knowledge_hit.emit(ks[0], ans)
                        break
            # 心跳日志：让用户确认软件活着（避免"毫无反应"的错觉）
            if time.time() - last_beat >= 20:
                last_beat = time.time()
                sel_info = f"选择器 {self._active_sel}" if self._active_sel else "等待评论区出现"
                self.log.emit(f"[yellow]监控中… {sel_info}，累计识别 {len(seen)} 条（最近 20 秒 {fresh} 条）")
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
        self.msg_boxes = []
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
        # 后台地址/评论选择器保留在配置里（自动适配），不占用界面
        self.ed_url = QLineEdit()
        self.ed_sel = QLineEdit()
        gl.addWidget(self._mk("检测间隔(秒)", 11, C_SUB), 0, 0)
        self.sp_interval = QDoubleSpinBox(); self.sp_interval.setRange(0.2, 10); self.sp_interval.setSingleStep(0.1)
        gl.addWidget(self.sp_interval, 0, 1)
        gl.addWidget(self._mk("触发冷却(秒)", 11, C_SUB), 0, 2)
        self.sp_cooldown = QDoubleSpinBox(); self.sp_cooldown.setRange(0.0, 60); self.sp_cooldown.setSingleStep(0.5)
        gl.addWidget(self.sp_cooldown, 0, 3)
        gl.addWidget(self._mk("主镜头热键(回切)", 11, C_SUB), 1, 0)
        self.cmb_main_key = QComboBox()
        for label, val in NUM_KEY_OPTIONS:
            self.cmb_main_key.addItem(label, val)
        self.cmb_main_key.setStyleSheet(STYLE_COMBO)
        gl.addWidget(self.cmb_main_key, 1, 1)
        gl.addWidget(self._mk("场景保持(秒)", 11, C_SUB), 1, 2)
        self.sp_hold = QDoubleSpinBox(); self.sp_hold.setRange(0.0, 60); self.sp_hold.setSingleStep(0.5)
        gl.addWidget(self.sp_hold, 1, 3)
        gl.addWidget(self._mk("场景切换延迟(秒)", 11, C_SUB), 2, 0)
        self.sp_delay = QDoubleSpinBox(); self.sp_delay.setRange(0.0, 5); self.sp_delay.setSingleStep(0.1)
        gl.addWidget(self.sp_delay, 2, 1)
        gl.addWidget(self._mk("热键用下拉选择不会输错：数字 7 = 横排数字（如 ctrl+7）；小键盘 9 = num9。每条规则一个关键词，想加关键词就加一行。", 10, C_SUB), 3, 0, 1, 4)
        for w in (self.ed_url, self.ed_sel, self.sp_interval, self.sp_cooldown, self.sp_delay, self.sp_hold):
            w.setStyleSheet(STYLE_EDIT)
        outer.addWidget(card)
        # ── 规则表格区 ──
        mid = QHBoxLayout()
        f_scene = self._card(); sv = QVBoxLayout(f_scene); sv.setContentsMargins(12, 10, 12, 10)
        sh = QHBoxLayout(); sh.addWidget(self._mk("🎬 场景触发规则", 13, C_TEXT, True)); sh.addStretch(1)
        b1 = QPushButton("＋ 添加规则"); b1.setStyleSheet(STYLE_BTN_ACC); b1.clicked.connect(lambda: self._add_scene_row())
        sh.addWidget(b1); sv.addLayout(sh)
        self.tbl_scene = QTableWidget(0, 5)
        self.tbl_scene.setHorizontalHeaderLabels(["触发关键词", "修饰键", "按键", "测试", "删除"])
        self.tbl_scene.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3, 4):
            self.tbl_scene.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.tbl_scene.verticalHeader().setVisible(False)
        self.tbl_scene.setStyleSheet(STYLE_TBL)
        sv.addWidget(self.tbl_scene)
        mid.addWidget(f_scene, 3)
        f_kn = self._card(); kv = QVBoxLayout(f_kn); kv.setContentsMargins(12, 10, 12, 10)
        kh = QHBoxLayout(); kh.addWidget(self._mk("📚 知识库问答", 13, C_TEXT, True)); kh.addStretch(1)
        b2 = QPushButton("＋ 添加条目"); b2.setStyleSheet(STYLE_BTN_ACC); b2.clicked.connect(lambda: self._add_row(self.tbl_kn, 3))
        kh.addWidget(b2); kv.addLayout(kh)
        self.tbl_kn = QTableWidget(0, 3)
        self.tbl_kn.setHorizontalHeaderLabels(["触发关键词", "回复答案", "操作"])
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
        self.btn_start = QPushButton("▶ 启动")
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
        self.btn_save = QPushButton("💾 保存设置")
        self.btn_save.setStyleSheet(STYLE_BTN)
        self.btn_save.clicked.connect(self._save)
        self.lb_saved = QLabel("")
        self.lb_saved.setStyleSheet(f"color: {C_GREEN}; background: transparent;")
        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_confirm)
        ctrl.addWidget(self.btn_stop)
        ctrl.addWidget(self.btn_save)
        ctrl.addWidget(self.lb_saved)
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

    def _add_scene_row(self, kw="", mod="", key=""):
        """场景规则行：单个关键词 + 修饰键/按键下拉 + 测试 + 删除"""
        r = self.tbl_scene.rowCount()
        self.tbl_scene.insertRow(r)
        item = QTableWidgetItem(kw)
        item.setForeground(Qt.white)
        self.tbl_scene.setItem(r, 0, item)
        cmb_m = QComboBox()
        for label, val in MOD_OPTIONS:
            cmb_m.addItem(label, val)
        if mod:
            i = cmb_m.findData(mod)
            if i >= 0:
                cmb_m.setCurrentIndex(i)
        cmb_m.setStyleSheet(STYLE_COMBO)
        self.tbl_scene.setCellWidget(r, 1, cmb_m)
        cmb_k = QComboBox()
        for label, val in KEY_OPTIONS:
            cmb_k.addItem(label, val)
        if key:
            i = cmb_k.findData(key)
            if i >= 0:
                cmb_k.setCurrentIndex(i)
        cmb_k.setStyleSheet(STYLE_COMBO)
        self.tbl_scene.setCellWidget(r, 2, cmb_k)
        bt = QPushButton("⚡ 测试")
        bt.setStyleSheet(f"QPushButton {{ background: #1a2b4d; color: {C_ACCENT}; border: 1px solid #2b4a80; border-radius: 5px; padding: 3px 10px; }}")
        bt.clicked.connect(lambda _, rr=r: self._test_hotkey(rr))
        self.tbl_scene.setCellWidget(r, 3, bt)
        bd = QPushButton("删除")
        bd.setStyleSheet(f"QPushButton {{ background: #3a2222; color: {C_RED}; border: none; border-radius: 5px; padding: 3px 8px; }}")
        bd.clicked.connect(lambda _, rr=r: self.tbl_scene.removeRow(rr))
        self.tbl_scene.setCellWidget(r, 4, bd)

    def _scene_hotkey(self, r):
        """读取某行下拉组合出的热键字符串，如 ctrl+7 / num9"""
        cmb_m = self.tbl_scene.cellWidget(r, 1)
        cmb_k = self.tbl_scene.cellWidget(r, 2)
        if not cmb_m or not cmb_k:
            return ""
        mod = cmb_m.currentData() or ""
        key = cmb_k.currentData() or ""
        if not key:
            return ""
        return f"{mod}+{key}" if mod else key

    def _test_hotkey(self, r):
        """手动测试某行热键：立即模拟按下，验证直播伴侣能否响应"""
        hk = self._scene_hotkey(r)
        if not hk:
            self._append_log("[red]✗ 该行热键不完整，请选择按键")
            return
        codes = parse_hotkey(hk)
        if not codes:
            self._append_log(f"[red]✗ 热键「{hk}」无法解析")
            return
        self._append_log(f"[green]⚡ 测试热键「{hk}」已模拟按下…")
        if send_hotkey(codes):
            self._append_log("[cyan]  已发送。若直播伴侣没切换场景，检查：①直播伴侣已打开且设置同款全局快捷键；②本软件与直播伴侣都以管理员身份运行；③按键组合与直播伴侣设置一致")
        else:
            self._append_log("[yellow]  非 Windows 环境，测试热键已跳过")

    # ── 配置读写 ──
    def _load_to_ui(self):
        self.ed_url.setText(self.cfg.get("live_url", ""))
        self.ed_sel.setText(self.cfg.get("comment_selector", ""))
        self.sp_interval.setValue(float(self.cfg.get("poll_interval", 0.5)))
        self.sp_cooldown.setValue(float(self.cfg.get("cooldown", 2.0)))
        main_key = str(self.cfg.get("default_scene_key", "num9") or "num9")
        i = self.cmb_main_key.findData(main_key)
        if i >= 0:
            self.cmb_main_key.setCurrentIndex(i)
        self.sp_delay.setValue(float(self.cfg.get("scene_switch_delay", 0.3)))
        self.sp_hold.setValue(float(self.cfg.get("scene_hold_seconds", 7.0)))
        for s in self.cfg.get("scenes", []):
            hk = str(s.get("hotkey", "")).strip()
            parts = [p.strip() for p in hk.split("+")] if hk else []
            mod = "+".join(parts[:-1]) if len(parts) > 1 else ""
            key = parts[-1] if parts else ""
            for kw in re.split(r"[,，]", str(s.get("keywords", ""))):
                kw = kw.strip()
                if kw:
                    self._add_scene_row(kw, mod, key)
        for k in self.cfg.get("knowledge", []):
            for kw in re.split(r"[,，]", str(k.get("keywords", ""))):
                kw = kw.strip()
                if kw:
                    self._add_row(self.tbl_kn, 3, kw, k.get("answer", ""))

    def _collect(self):
        scenes = []
        for r in range(self.tbl_scene.rowCount()):
            kw = (self.tbl_scene.item(r, 0).text() if self.tbl_scene.item(r, 0) else "").strip()
            hk = self._scene_hotkey(r)
            if kw and hk:
                scenes.append({"keywords": kw, "hotkey": hk})
        knowledge = []
        for r in range(self.tbl_kn.rowCount()):
            kw = (self.tbl_kn.item(r, 0).text() if self.tbl_kn.item(r, 0) else "").strip()
            ans = (self.tbl_kn.item(r, 1).text() if self.tbl_kn.item(r, 1) else "").strip()
            if kw and ans:
                knowledge.append({"keywords": kw, "answer": ans})
        custom = [s.strip() for s in re.split(r"[\n,]", self.ed_sel.text()) if s.strip()]
        chain = custom + [s for s in DEFAULT_CONFIG["comment_selectors"] if s not in custom]
        return {
            "live_url": self.ed_url.text().strip(),
            "comment_selector": self.ed_sel.text().strip() or ".comment-item",
            "comment_selectors": chain,
            "poll_interval": self.sp_interval.value(),
            "cooldown": self.sp_cooldown.value(),
            "default_scene_key": self.cmb_main_key.currentData() or "num9",
            "scene_switch_delay": self.sp_delay.value(),
            "scene_hold_seconds": self.sp_hold.value(),
            "scenes": scenes,
            "knowledge": knowledge,
        }

    def _save(self):
        """保存设置到 live_config.json 并给出可见反馈"""
        cfg = self._collect()
        save_config(cfg)
        self.cfg = cfg
        now = time.strftime("%H:%M:%S")
        self.lb_saved.setText(f"✅ 已保存 {now}")
        self._append_log("[green]✅ 设置已保存（live_config.json），下次打开自动加载")

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
