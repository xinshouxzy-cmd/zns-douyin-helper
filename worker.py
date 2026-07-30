# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手 — 工作线程
双标签页：抖音首页(评论) + 私信页(私信)
- 评论回复：CDP 鼠标事件（Playwright 同款底层）+ 全页面 JS 找坐标
- 私信回复：基于 v42.1 成熟方案（不动）
- 分时轮流：30s评论 → 20s私信 → 10s休息
"""

import os, sys, json, time, re, subprocess, traceback
from datetime import datetime
from threading import Event

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException

from PyQt5.QtCore import QThread, pyqtSignal

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPLIED_DIR = os.path.join(BASE_DIR, "replied_records")
os.makedirs(REPLIED_DIR, exist_ok=True)

DY_HOME = "https://www.douyin.com"
PM_URL = "https://www.douyin.com/chat?isPopup=1"

TAB_HOME = 0
TAB_PM = 1
CMT_PHASE = 30
PM_PHASE = 20
REST_PHASE = 10


def find_chromedriver():
    for c in [
        os.path.join(BASE_DIR, "runtime", "chromedriver.exe"),
        os.path.join(BASE_DIR, "chromedriver.exe"),
        os.path.join(BASE_DIR, "chromedriver"),
        "chromedriver", "chromedriver.exe",
    ]:
        if os.path.exists(c) or c in ("chromedriver", "chromedriver.exe"):
            return c
    return "chromedriver"


def get_bundled_chrome():
    """返回内置 Chrome 路径（如果存在）"""
    p = os.path.join(BASE_DIR, "runtime", "chrome", "chrome.exe")
    return p if os.path.exists(p) else None


def _rpath(name):
    return os.path.join(REPLIED_DIR, f"{name.replace('/', '_').replace('\\', '_')}.json")


def load_replied(name):
    p = _rpath(name)
    if not os.path.exists(p):
        return {"pm_fps": [], "cmt_fps": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_replied(name, data):
    with open(_rpath(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class AccountWorker(QThread):
    log = pyqtSignal(str, str)
    status = pyqtSignal(str, str)
    waiting_login = pyqtSignal(str)
    pm_cnt = pyqtSignal(str, int)
    cmt_cnt = pyqtSignal(str, int)
    stopped = pyqtSignal(str)
    recal_done = pyqtSignal(str, bool)  # (账号名, 是否成功)
    calib_step = pyqtSignal(str, str)    # (账号名, 步骤描述) → 手动校准进度

    def __init__(self, cfg, pm_poll=5, cmt_poll=30):
        super().__init__()
        self.cfg = cfg
        self.name = cfg.get("name", "?")
        self.pm_on = cfg.get("pm_enabled", True)
        self.pm_text = cfg.get("pm_reply", "你好")
        self.cmt_on = cfg.get("comment_enabled", True)
        self.cmt_text = cfg.get("comment_reply", "感谢关注！")
        self.profile = os.path.join(BASE_DIR, cfg.get("chrome_profile", "chrome_profiles/account_1"))
        self._run = True
        self._d = None
        self._has_manual_calib = False
        self._pm_n = 0
        self._cmt_n = 0
        self._login_ok = Event()
        self._calib_requested = Event()  # 登录等待期间的手动校准请求
        self._last_reply = {}
        self._recal_requested = Event()  # 线程安全：GUI请求重新校准

    def L(self, msg, tag="white"):
        self.log.emit(self.name, f"[{tag}]{msg}")

    def stop(self):
        self._run = False
        self._login_ok.set()

    def confirm_login(self):
        self._login_ok.set()

    def start_calibration(self):
        """由主线程调用，请求在登录等待期间执行手动校准（3点5连点录制）"""
        self._calib_requested.set()

    # ── 浏览器 ──
    def _start_browser(self):
        self.L("正在准备浏览器...", "white")
        opt = Options()
        bundled = get_bundled_chrome()
        bundled_drv = find_chromedriver()

        if bundled:
            driver_path = bundled_drv
            opt.binary_location = bundled
            self.L("使用内置浏览器", "white")
        elif os.path.exists(bundled_drv):
            # 内置驱动 + 系统 Chrome
            driver_path = bundled_drv
            self.L("使用内置驱动", "white")
        else:
            # 兜底：webdriver_manager 在线下载（25秒超时）
            from webdriver_manager.chrome import ChromeDriverManager
            self.L("检测系统 Chrome 版本...", "white")
            lock_file = os.path.join(os.path.expanduser("~"), ".wdm", ".wdm-lock-chromedriver-win64")
            if os.path.exists(lock_file):
                try: os.remove(lock_file); self.L("清理残留锁文件", "white")
                except: pass
            try:
                self.L("⏳ 正在获取浏览器驱动...", "white")
                import threading as _th
                _install_result = []
                def _do_install():
                    try: _install_result.append(ChromeDriverManager().install())
                    except Exception as _e: _install_result.append(_e)
                _t = _th.Thread(target=_do_install, daemon=True)
                _t.start()
                _t.join(timeout=25)
                if not _install_result:
                    import platform as _pf, glob as _g
                    _pf_dir = {"Windows": "win64", "Darwin": "mac64", "Linux": "linux64"}.get(_pf.system(), "win64")
                    # Apple Silicon Mac 下 webdriver_manager 使用 mac-arm64 目录
                    _pf_dirs = [_pf_dir]
                    if _pf.system() == "Darwin":
                        _pf_dirs.append("mac-arm64")
                    _matches = []
                    for _d in _pf_dirs:
                        # 递归搜索 chromedriver 二进制（排除 .zip、.exe 及目录）
                        _base = os.path.join(os.path.expanduser("~"), ".wdm", "drivers", "chromedriver", _d)
                        _m = sorted([f for f in _g.glob(os.path.join(_base, "**", "chromedriver*"), recursive=True)
                                      if os.path.isfile(f) and not f.endswith(".zip") and not f.endswith(".exe")],
                                    reverse=True)
                        if _m:
                            _matches = _m
                            break
                    if _matches:
                        driver_path = _matches[0]; os.chmod(driver_path, 0o755)
                        self.L("⚠ 网络超时，使用本地缓存", "yellow")
                    else:
                        self.L("❌ 未找到驱动，请检查网络后重试", "red")
                        raise RuntimeError("驱动获取超时且无本地缓存")
                elif isinstance(_install_result[0], Exception):
                    raise _install_result[0]
                else:
                    driver_path = _install_result[0]
                    self.L("✓ 驱动就绪", "green")
            except Exception as e:
                msg2 = str(e)
                if "lock" in msg2.lower() or "wdm-lock" in msg2:
                    if os.path.exists(lock_file): os.remove(lock_file)
                    self.L("⚠ 驱动锁冲突，已清理，请重新启动", "yellow")
                else:
                    self.L(f"⚠ 驱动异常：{e}", "yellow")
                raise
        opt.add_argument("--disable-blink-features=AutomationControlled")
        opt.add_argument(f"--user-data-dir={self.profile}")
        opt.add_argument("--disable-backgrounding-occluded-windows")
        opt.add_argument("--disable-renderer-backgrounding")
        opt.add_argument("--disable-features=TranslateUI,CalculateNativeWinOcclusion")
        opt.add_argument("--force-device-scale-factor=1")
        opt.add_experimental_option("excludeSwitches", ["enable-automation"])
        opt.add_experimental_option("useAutomationExtension", False)
        opt.add_experimental_option("detach", True)
        if sys.platform == "darwin":
            opt.add_argument("--use-mock-keychain")
        self.L("启动浏览器窗口...", "white")
        try:
            d = webdriver.Chrome(service=Service(driver_path), options=opt)
        except Exception as e:
            msg = str(e)
            if "This version of ChromeDriver only supports" in msg:
                raise RuntimeError("Chrome 浏览器版本不匹配，请更新 Chrome 到最新版本后重试") from e
            if "cannot find Chrome binary" in msg or "chrome not found" in msg.lower():
                raise RuntimeError("未找到 Chrome 浏览器，请先安装：https://www.google.cn/chrome/") from e
            if "cannot connect" in msg.lower() or "connection refused" in msg.lower():
                raise RuntimeError("无法连接到浏览器，请检查是否有杀毒软件拦截") from e
            raise
        d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
        d.set_window_size(1100, 800)
        self.L("加载抖音首页...", "white")
        d.get(DY_HOME)
        time.sleep(5)
        self.L("✓ 浏览器就绪", "green")
        return d

    def _switch_tab(self, idx):
        """切换标签页（不最小化，elementFromPoint 需要窗口可见但不需焦点）"""
        try:
            hs = self._d.window_handles
            if idx < len(hs):
                self._d.switch_to.window(hs[idx])
        except:
            pass

    def _open_pm_tab(self):
        self._d.execute_script(f"window.open('{PM_URL}','_blank');")
        time.sleep(1.5)
        self._switch_tab(TAB_PM)
        time.sleep(2)
        self.L("等待加载...", "white")
        time.sleep(2)
        self._d.refresh()
        time.sleep(1.5)

    def _js(self, code):
        try:
            return self._d.execute_script(code)
        except:
            return None

    def _paste(self, text, elem=None):
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"))
            if elem:
                elem.send_keys(Keys.COMMAND, 'v')
            else:
                ActionChains(self._d).key_down(Keys.COMMAND).send_keys('v').key_up(Keys.COMMAND).perform()
        else:
            try:
                import pyperclip
                pyperclip.copy(text)
            except:
                pass
            if elem:
                elem.send_keys(Keys.CONTROL, 'v')
            else:
                ActionChains(self._d).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()

    def _clean_name(self, raw):
        return re.sub(
            r'(刚刚|\d+分钟前|\d+小时前|昨天|\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日|\d{2}/\d{2})$',
            '', raw).strip()

    # ═══════════ 私信回复（v42.1） ═══════════

    def _enter_stranger(self):
        found = self._js("""
            let row = document.querySelector('[class*="conversationStrangerBoxrowArea2"]');
            if (!row) row = document.querySelector('[class*="StrangerBoxwrapper"]');
            if (row) { row.setAttribute('data-sc', '1'); return true; }
            return false;
        """)
        if not found: return False
        try:
            el = self._d.find_element(By.CSS_SELECTOR, '[data-sc="1"]')
            ActionChains(self._d).move_to_element(el).click().perform()
            time.sleep(4)
            return True
        except:
            return False

    def _back_to_list(self):
        self._js("""
            let b=document.querySelector('[class*="back"],[class*="return"],[class*="arrow"]');
            if(b){b.closest('div,button,span').click();return;}
            let t=document.querySelectorAll('[class*="tab"] span,[class*="nav"] div');
            for(let x of t){if(/消息/.test(x.textContent)){x.click();return;}}
        """)

    def _send_pm_reply(self, text):
        found = self._js("""
            let inp=document.querySelector('[class*="zone-container"][class*="editor-kit-container"]');
            if(inp){inp.focus();inp.click();return true;}
            let all=document.querySelectorAll('div[contenteditable="true"],textarea');
            for(let e of all){
                let r=e.getBoundingClientRect();
                if(r.height>20&&r.height<200&&r.top>window.innerHeight*.35){inp=e;break;}
            }
            if(!inp)inp=document.querySelector('div[data-placeholder]')||document.querySelector('div[class*="rich-input"]');
            if(inp){inp.focus();inp.click();}
            return !!inp;
        """)
        if not found: return False
        time.sleep(0.3)
        for ch in text:
            ActionChains(self._d).send_keys(ch).perform()
        ActionChains(self._d).pause(0.3).send_keys(Keys.ENTER).perform()
        return True

    def _pm_cycle(self):
        try:
            self._switch_tab(TAB_PM)
            still_in = self._js("""
                let l=document.querySelector('[class*="StrangerConversationListlist"]');
                return l&&l.querySelectorAll('[class*="ConversationItemwrapper"]').length>0;
            """)
            if not still_in:
                if self._enter_stranger():
                    self.L("已进入陌生人消息", "white")
                    self._last_reply = {}
                return

            clicked = self._js("""
                let l=document.querySelector('[class*="StrangerConversationListlist"]');
                if(!l)return'';let its=l.querySelectorAll('[class*="ConversationItemwrapper"]');
                if(!its.length)return'';let f=its[0];
                let t=f.querySelector('[class*="ConversationItemtitle"]');
                let n=t?t.textContent.trim():'';
                f.focus();['mousedown','mouseup','click'].forEach(e=>f.dispatchEvent(new MouseEvent(e,{bubbles:true,cancelable:true})));
                return n;
            """)
            if not clicked: return
            fn = self._clean_name(clicked)
            if not fn: return

            now = time.time()
            if fn in self._last_reply and now - self._last_reply[fn] < 30: return

            rec = load_replied(self.name)
            if fn in rec.get("pm_fps", []): return

            self.L(f'💬 新私信: "{fn}"', "white")
            time.sleep(1)
            # 提取对方最后一条消息
            first_msg = self._js("""
                let containers = document.querySelectorAll('[class*="MessageItemTextcontainer"]');
                if (!containers.length) return '';
                let last = containers[containers.length-1];
                let spans = last.querySelectorAll('[class*="TextMessageTextpureText"]');
                let text = '';
                spans.forEach(s => { text += s.textContent; });
                return text.trim();
            """) or ""
            # 从对方消息中提取手机号
            phone = ""
            m = re.search(r'1[3-9]\d{9}', first_msg)
            if m:
                phone = m.group()
            time.sleep(1)
            if self.pm_text and self._send_pm_reply(self.pm_text):
                self._last_reply[fn] = now
                rec["pm_fps"].append(fn)
                # 回复后等一下，读对方后续回复
                time.sleep(3)
                follow_up = self._js("""
                    let containers = document.querySelectorAll('[class*="MessageItemTextcontainer"]');
                    if (!containers.length) return '';
                    let last = containers[containers.length-1];
                    let spans = last.querySelectorAll('[class*="TextMessageTextpureText"]');
                    let text = '';
                    spans.forEach(s => { text += s.textContent; });
                    return text.trim();
                """) or ""
                # 对方后续回复中也可能有手机号
                if not phone and follow_up:
                    m2 = re.search(r'1[3-9]\d{9}', follow_up)
                    if m2:
                        phone = m2.group()
                rec.setdefault("pm_records", []).append({
                    "nickname": fn,
                    "contact_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "first_msg": first_msg[:200],
                    "reply_text": self.pm_text,
                    "follow_up": follow_up[:200] if follow_up != first_msg else "",
                    "phone": phone
                })
                save_replied(self.name, rec)
                self._pm_n += 1
                self.pm_cnt.emit(self.name, self._pm_n)
                self.L(f"✅ 私信已回复: {fn} | 累计: {self._pm_n}", "green")
            else:
                self.L(f"⚠ 私信回复失败: {fn}", "yellow")
            self._back_to_list()
            time.sleep(1)
        except WebDriverException:
            pass
        except Exception as e:
            self.L(f"⚠ 私信异常: {e}", "yellow")

    # ═══════════ 评论回复（v2.0.37 ActionChains 真实鼠标点击 + 手动校准） ═══════════

    def _cmt_click_at(self, x, y, retries=3):
        """用 ActionChains 模拟真实鼠标点击（视口绝对坐标）。
        move_to_element_with_offset 会移动真实鼠标光标到目标位置，
        此移动过程本身就触发抖音的 hover 事件（如通知铃铛浮窗）。
        这是 v2.0.37 已验证的可靠方案。"""
        try:
            body = self._d.find_element(By.TAG_NAME, "body")
            cx, cy = self._d.execute_script("""
                const r = document.body.getBoundingClientRect();
                return [r.left + r.width/2, r.top + r.height/2];
            """)
            ox, oy = int(x - cx), int(y - cy)
            for i in range(retries):
                try:
                    ActionChains(self._d, duration=0) \
                        .move_to_element_with_offset(body, ox, oy) \
                        .click().perform()
                    return True
                except:
                    time.sleep(1)
            return False
        except:
            return False

    def _minimize_after(self):
        """已废弃：最小化会破坏 elementFromPoint，改为不干涉窗口状态"""
        pass

    def _reload_config(self):
        """运行时重新读取配置，支持实时开关私信/评论"""
        try:
            cfg = load_config()
            for ac in cfg.get("accounts", []):
                if ac.get("name") == self.name:
                    self.pm_on = ac.get("pm_enabled", True)
                    self.pm_text = ac.get("pm_reply", self.pm_text)
                    self.cmt_on = ac.get("comment_enabled", True)
                    self.cmt_text = ac.get("comment_reply", self.cmt_text)
                    break
        except:
            pass

    def _cmt_js(self, code):
        try:
            return self._d.execute_script(code)
        except:
            return None

    def recalibrate_now(self):
        """线程安全：请求在 worker 线程内重新校准"""
        self._recal_requested.set()

    # ── 手动校准：浏览器内5连点录制3个点位 ──
    def do_manual_calibration(self):
        """在浏览器内通过5连点录制3个点位（通知图标、全部消息、评论筛选）。
        全程无需切换窗口，用户直接在浏览器中操作。
        录制完成后自动保存到 positions.json。"""
        steps = [
            ("通知铃铛图标", "1_通知图标"),
            ("「全部消息」按钮", "2_全部消息"),
            ("「评论」筛选标签", "3_评论筛选"),
        ]
        results = {}
        vp = None

        # 注入5连点监听JS
        self._d.execute_script("""
            (function() {
                window._calibClickCount = 0;
                window._calibLastClick = {x:0, y:0, t:0};
                window._calibResult = null;
                document.addEventListener('click', function(e) {
                    var now = Date.now();
                    var dx = e.clientX - window._calibLastClick.x;
                    var dy = e.clientY - window._calibLastClick.y;
                    var dt = now - window._calibLastClick.t;
                    if (dt < 3000 && Math.abs(dx) < 40 && Math.abs(dy) < 40) {
                        window._calibClickCount++;
                    } else {
                        window._calibClickCount = 1;
                    }
                    window._calibLastClick = {x:e.clientX, y:e.clientY, t:now};
                    if (window._calibClickCount >= 5) {
                        window._calibResult = Math.round(e.clientX) + ',' + Math.round(e.clientY);
                        window._calibClickCount = 0;
                    }
                }, true);
            })();
        """)

        for i, (desc, key) in enumerate(steps):
            step_label = f"[校准 {i+1}/3]"
            self.L(f"📐 {step_label} 等待5连点: {desc}...", "white")
            self.calib_step.emit(self.name, f"{step_label} 请在浏览器中连续点击5次: {desc}")

            # 轮询等待5连点结果
            result = None
            start_ts = time.time()
            while time.time() - start_ts < 120:  # 2分钟超时
                if not self._run:
                    self.L(f"📐 {step_label} ⚠ 已中止", "yellow")
                    return None
                try:
                    r = self._d.execute_script("return window._calibResult;")
                except Exception:
                    time.sleep(0.5)
                    continue
                if r:
                    result = r
                    self._d.execute_script("window._calibResult = null;")
                    break
                time.sleep(0.6)

            if not result:
                self.L(f"📐 {step_label} ⚠ 超时（120秒无5连点）", "red")
                return None

            x_raw, y_raw = result.split(',')
            x_px, y_px = int(float(x_raw)), int(float(y_raw))
            self.L(f"📐 {step_label} ✅ 5连点确认: ({x_px}, {y_px})", "green")
            self.calib_step.emit(self.name, f"{step_label} ✓ 已录入: ({x_px}, {y_px})")

            # 获取视口尺寸，转百分比
            try:
                vp = self._d.execute_script(
                    "return {w:window.innerWidth, h:window.innerHeight, dpr:window.devicePixelRatio||1};")
            except Exception:
                vp = {"w": 1084, "h": 705, "dpr": 1}
            vw, vh = vp["w"], vp["h"]

            results[key] = {
                "x_pct": round(x_px / vw, 4),
                "y_pct": round(y_px / vh, 4),
                "raw_x": x_px,
                "raw_y": y_px,
            }

        # 3个点全部录完 → 保存
        self._d.execute_script("""
            document.removeEventListener('click', arguments[0]);
            window._calibResult = null;
            window._calibClickCount = 0;
        """)

        pos_file = os.path.join(BASE_DIR, "comment_data", "positions.json")
        os.makedirs(os.path.dirname(pos_file), exist_ok=True)

        # 保留已有的 positions.json 中的步骤4/5数据
        existing = {}
        if os.path.exists(pos_file):
            try:
                with open(pos_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        save_data = {
            "_manual_calib": True,
            "_calibrated_by": self.name,
            "_calibrated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "_dpr": vp.get("dpr", 1) if vp else 1,
            "_viewport": {"w": vp["w"], "h": vp["h"]} if vp else {"w": 1084, "h": 705},
        }
        # 合并手动校准的3个点
        for key, val in results.items():
            save_data[key] = {"x_pct": val["x_pct"], "y_pct": val["y_pct"],
                              "desc": key.replace("_", " ", 1)}
        # 保留已有的步骤4/5
        for k in ["4_第一条评论", "5_回复按钮"]:
            if k in existing and not k.startswith("_"):
                save_data[k] = existing[k]

        with open(pos_file, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        self._has_manual_calib = True
        self.L(f"📐 ✅ 校准已保存（手动校准 | 来源:{self.name}）", "green")
        self.calib_step.emit(self.name, "done")
        return results

    def _cmt_load_positions(self):
        """加载录制的坐标文件，按当前视口+DPI缩放"""
        pos_file = os.path.join(BASE_DIR, "comment_data", "positions.json")
        if not os.path.exists(pos_file):
            self.L("⚠ 未找到坐标文件 comment_data/positions.json", "yellow")
            return None
        try:
            with open(pos_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 检测是否为手动校准数据
            if data.get("_manual_calib"):
                if not self._has_manual_calib:
                    calib_src = data.get("_calibrated_by", "?")
                    self.L(f"📐 已加载校准坐标 (来源:{calib_src})", "green")
                self._has_manual_calib = True
            vp = self._d.execute_script(
                "return {w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1};")
            vw, vh = vp["w"], vp["h"]
            dpr = vp.get("dpr", 1)
            # 读取录制时的 DPR（如果有记录）
            rec_dpr = data.get("_dpr", 1)
            positions = {}
            for name, p in data.items():
                if name.startswith("_"):
                    continue
                if "x_pct" in p and p["x_pct"] > 0:
                    # 百分比坐标：直接按视口缩放（与DPR无关，因为视口单位就是CSS像素）
                    positions[name] = {"x": int(p["x_pct"] * vw), "y": int(p["y_pct"] * vh)}
                else:
                    # 兼容旧格式：标清录制分辨率 1084x705，校正 DPR 差异
                    scale = (vw / 1084) * (rec_dpr / max(dpr, 0.5))
                    y_scale = (vh / 705) * (rec_dpr / max(dpr, 0.5))
                    positions[name] = {"x": int(p.get("x", 0) * scale),
                                       "y": int(p.get("y", 0) * y_scale)}
            return positions
        except Exception as e:
            self.L(f"⚠ 坐标文件读取失败: {e}", "yellow")
            return None


    def _cmt_cycle(self):
        """一轮评论检测+回复（v2.0.37 ActionChains 真实鼠标 + 手动校准坐标）"""
        try:
            self._switch_tab(TAB_HOME)
            if "www.douyin.com" not in (self._d.current_url or ""):
                self._d.get(DY_HOME)
                self.L("\u23f3 加载抖音首页...", "white")
                time.sleep(5)

            # 加载录制的坐标
            pos = self._cmt_load_positions()
            if not pos:
                self.L("\u26a0 无坐标文件，跳过本轮", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            # ═══ Step 1: 点击通知铃铛（ActionChains 真实鼠标移动触发 hover） ═══
            n_coord = pos.get("1_通知图标")
            if not n_coord:
                self.L("\u274c 无通知按钮坐标，跳过本轮", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return
            
            nx, ny = n_coord["x"], n_coord["y"]
            calib_src = "手动校准" if self._has_manual_calib else "录制"
            self.L(f"\U0001f514 通知坐标 ({nx}, {ny}) [{calib_src}]", "white")
            
            notif_ok = False
            for attempt in range(3):
                if attempt > 0:
                    self.L(f"  重试通知 ({attempt+1}/3)...", "yellow")
                    self._d.refresh()
                    time.sleep(2)
                
                # v2.0.37 方式: ActionChains 移动真实鼠标→触发hover→点击
                self._cmt_click_at(nx, ny)
                time.sleep(2.5)
                
                # 简单验证：页面是否有变化
                ok = self._cmt_js("""
                    if (window.location.href.indexOf('/message')>=0 || window.location.href.indexOf('/notice')>=0) return 1;
                    var divs = document.querySelectorAll('div');
                    for (var i=0; i<divs.length; i++) {
                        var s = window.getComputedStyle(divs[i]);
                        var r = divs[i].getBoundingClientRect();
                        if (r.width>180 && r.height>180 && s.position==='fixed' && (parseInt(s.zIndex)||0)>10) return 1;
                    }
                    return 0;
                """)
                if ok:
                    notif_ok = True
                    self.L(f"  \u2713 通知面板已弹出", "green")
                    break
                self.L(f"  \u26a0 通知面板未弹出", "yellow")
            
            if not notif_ok:
                self.L("\u274c 通知面板3次均失败，跳过本轮", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            # ═══ Step 2: 点击「全部消息」 ═══
            time.sleep(1.5)
            m_coord = pos.get("2_全部消息")
            
            all_msg_ok = False
            if m_coord:
                # 优先用校准坐标（ActionChains点击）
                mx, my = m_coord["x"], m_coord["y"]
                self.L(f"\U0001f4cb 点击「全部消息」@ ({mx}, {my})", "white")
                for mt in range(3):
                    if mt > 0:
                        self.L(f"  重试全部消息 ({mt+1}/3)...", "yellow")
                        time.sleep(1)
                    self._cmt_click_at(mx, my)
                    time.sleep(2.5)
                    ok = self._cmt_js("""
                        if (window.location.href.indexOf('/message')>=0||window.location.href.indexOf('/notice')>=0) return 1;
                        var t = (document.body.innerText||'').length;
                        return t > 500 ? 1 : 0;
                    """)
                    if ok:
                        all_msg_ok = True
                        self.L(f"  \u2713 已进入消息页面", "green")
                        break
                    self.L(f"  \u26a0 未检测到消息页面", "yellow")
            else:
                # 无校准坐标，用DOM搜索
                self.L("\U0001f4cb 搜索「全部消息」...", "white")
                for mt in range(4):
                    if mt > 0: time.sleep(1.5)
                    el = None
                    try:
                        elements = self._d.find_elements(By.XPATH, "//*[text()='全部消息']")
                        for e in elements:
                            r = e.rect
                            if r['width'] > 40 and r['height'] > 10:
                                el = e; break
                    except: pass
                    if el:
                        try:
                            r = el.rect
                            self._cmt_click_at(r['x']+r['width']/2, r['y']+r['height']/2)
                        except:
                            el.click()
                    else:
                        found = self._cmt_js("""
                            var all=document.querySelectorAll('div,span,button,a');
                            for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim();
                            if(t==='全部消息'){var r=all[i].getBoundingClientRect();
                            if(r.width>40&&r.height>10){all[i].click();return 1;}}}return 0;
                        """)
                        if not found: break
                    time.sleep(2.5)
                    ok = self._cmt_js("""
                        return (document.body.innerText||'').length > 500 ? 1 : 0;
                    """)
                    if ok:
                        all_msg_ok = True
                        self.L(f"  \u2713 已进入消息页面", "green")
                        break
            
            if not all_msg_ok:
                self.L("\u274c 未进入消息页面，跳过本轮", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            # ═══ Step 3: 点击「评论」筛选 ═══
            time.sleep(1.0)
            c_coord = pos.get("3_评论筛选")
            
            cmt_clicked = False
            if c_coord:
                cx, cy = c_coord["x"], c_coord["y"]
                self.L(f"\U0001f4ac 点击「评论」@ ({cx}, {cy})", "white")
                self._cmt_click_at(cx, cy)
                time.sleep(2.0)
                cmt_clicked = True
            else:
                try:
                    elements = self._d.find_elements(By.XPATH,
                        "//div[contains(@class,'nav') or contains(@class,'sidebar') or contains(@class,'menu') or contains(@class,'tab')]//*[text()='评论']")
                    if not elements:
                        elements = self._d.find_elements(By.XPATH, "//*[text()='评论']")
                    for el in elements:
                        r = el.rect
                        if r['width'] > 0 and r['height'] > 0 and r['width'] < 200:
                            self._cmt_click_at(r['x']+r['width']/2, r['y']+r['height']/2)
                            cmt_clicked = True
                            break
                except: pass
                if not cmt_clicked:
                    found = self._cmt_js("""
                        var all=document.querySelectorAll('span,div,a,button,li');
                        for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim();
                        if(t!=='评论')continue;var r=all[i].getBoundingClientRect();
                        if(r.width>0&&r.height>0&&r.width<200){all[i].click();return 1;}}return 0;
                    """)
                    cmt_clicked = bool(found)
                if cmt_clicked:
                    time.sleep(2.5)
                    self.L(f"  搜索到「评论」", "white")
            
            if not cmt_clicked:
                self.L("\u26a0 未找到「评论」标签", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            # 简单验证评论列表
            time.sleep(1.5)
            cmt_loaded = self._cmt_js("""
                var txt = document.body.innerText || '';
                if (txt.indexOf('天前')>=0||txt.indexOf('小时前')>=0||txt.indexOf('回复')>=0) return 1;
                var all=document.querySelectorAll('div[class*="item"],div[class*="comment"],div[class*="msg"],li[class*="item"],li[class*="comment"]');
                for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim();var r=all[i].getBoundingClientRect();
                if(t.indexOf('滚动')>=0||t.indexOf('我知道了')>=0)continue;
                if(r.width>200&&r.height>40&&r.y>80&&t.length>15)return 1;}return 0;
            """)
            if not cmt_loaded:
                self.L("\u26a0 评论列表未加载", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return
            self.L("  \u2713 评论列表已加载", "green")

            # ═══ Step 4: 提取第一条评论（坐标优先 → 智能DOM兜底） ═══
            self.L("\U0001f50d 提取第一条评论...", "white")
            ct = None

            # 策略A：elementFromPoint 定位（v2.0.37 方式，最精准）
            p_item = pos.get("4_第一条评论") if pos else None
            if p_item:
                ct = self._d.execute_script("""
                    var el = document.elementFromPoint(arguments[0], arguments[1]);
                    if (!el) return '';
                    // 向上遍历找有意义的父元素
                    var target = el;
                    for (var i = 0; i < 5; i++) {
                        if (target.parentElement) target = target.parentElement;
                        var txt = (target.textContent || '').trim();
                        if (txt.length > 20) break;
                    }
                    var text = (target.textContent || '').trim().substring(0, 120);
                    if (text) target.setAttribute('data-cmt-first', '1');
                    return text;
                """, p_item['x'], p_item['y'])
                if ct:
                    self.L(f"  坐标定位到评论项 ({p_item['x']}, {p_item['y']})", "white")

            # 策略B：智能DOM扫描（按时间特征找评论项，排除视频描述/话题标签/提示文字）
            if not ct:
                ct = self._cmt_js("""
                    var TIME_RE = /(\\d+天前|\\d+小时前|\\d+分钟前|刚刚|昨天\\s*\\d|\\d{1,2}:\\d{2}|\\d{1,2}月\\d{1,2}日)/;
                    var HINT = ['滚动','鼠标','键盘','我知道了','查看更多','推荐视频','上下按钮','上一页','下一页'];
                    var all = document.querySelectorAll('div, li');
                    var cand = [];
                    for (var i = 0; i < all.length; i++) {
                        var el = all[i], r = el.getBoundingClientRect();
                        if (r.width < 180 || r.height < 35) continue;
                        if (r.y < 80 || r.y > window.innerHeight * 0.85) continue;
                        var txt = (el.textContent || '').trim();
                        if (txt.length < 15 || txt.length > 500) continue;
                        // 跳过纯提示文字
                        var skip = false;
                        for (var j = 0; j < HINT.length; j++) {
                            if (txt.indexOf(HINT[j]) >= 0) { skip = true; break; }
                        }
                        if (skip) continue;
                        // 排除视频描述特征：话题标签#xxx、竖线分隔符
                        if (/#[^\s#]+/.test(txt)) continue;
                        if (txt.indexOf('|') >= 0 && txt.length > 60) continue;
                        // 排除过大的容器元素
                        if (r.height > 350) continue;
                        var childCount = 0;
                        try { childCount = el.querySelectorAll('*').length; } catch(e) {}
                        if (childCount > 60) continue;
                        // 必须包含时间特征 或 「回复」按钮
                        if (TIME_RE.test(txt) || txt.indexOf('回复') >= 0) {
                            cand.push({el: el, y: r.y, text: txt.substring(0, 120)});
                        }
                    }
                    cand.sort(function(a, b) { return a.y - b.y; });
                    // 去重
                    var seen = {}, uniq = [];
                    for (var i = 0; i < cand.length; i++) {
                        var fp = cand[i].text.substring(0, 30);
                        if (!seen[fp]) { seen[fp] = 1; uniq.push(cand[i]); }
                    }
                    if (uniq.length > 0) {
                        uniq[0].el.setAttribute('data-cmt-first', '1');
                        return uniq[0].text;
                    }
                    return '';
                """)
            if not ct:
                self.L("\u26a0 未找到评论", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            fk = ct[:40]
            rec = load_replied(self.name)
            if fk in rec.get("cmt_fps", []):
                self.L("\u23ed 已回复过，跳过", "white")
                self._d.get(DY_HOME); time.sleep(3); return

            self.L(f'\U0001f4ac 新评论: "{ct[:60]}"', "white")

            # ═══ Step 5: 点击评论项 ═══
            info = self._cmt_js("""
                var el=document.querySelector('[data-cmt-first="1"]');if(!el)return null;
                var r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
            """)
            if not info:
                self._d.get(DY_HOME); time.sleep(3); return
            self._cmt_click_at(info["x"], info["y"])
            time.sleep(3)

            # ═══ Step 6: 找「回复」按钮 ═══
            self.L("\u270f\ufe0f 找「回复」按钮...", "white")
            candidates = self._cmt_js("""
                var all=document.querySelectorAll('span,button,div,a');var results=[];
                for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim();
                if(t==='回复'||t==='回复 '){var r=all[i].getBoundingClientRect();
                if(r.width>0&&r.height>0&&r.width<250&&r.y>80)
                results.push({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});}}
                if(results.length===0){
                var panels=document.querySelectorAll('[class*="reply"],[class*="panel"],[class*="drawer"]');
                for(var i=0;i<panels.length;i++){var r=panels[i].getBoundingClientRect();
                if(r.width>200&&r.y>60){
                var btns=panels[i].querySelectorAll('span,button,div');
                for(var j=0;j<btns.length;j++){var br=btns[j].getBoundingClientRect();var t=(btns[j].textContent||'').trim();
                if((t==='回复'||t.indexOf('回')>=0)&&br.y>r.y+r.height*0.7&&br.width>30&&br.width<200)
                results.push({x:Math.round(br.x+br.width/2),y:Math.round(br.y+br.height/2)});}}}}
                return results;
            """)
            all_c = list(candidates or [])
            p_reply = pos.get("5_回复按钮") if pos else None
            if p_reply and not all_c:
                all_c.append({"x": p_reply["x"], "y": p_reply["y"]})
            
            reply_ok = False
            for c in all_c:
                self._cmt_click_at(c["x"], c["y"])
                time.sleep(1.5)
                v = self._cmt_js("""
                    var spans=document.querySelectorAll('span');
                    for(var i=0;i<spans.length;i++){var t=(spans[i].textContent||'').trim();
                    if(t==='回复中'||t.indexOf('回复 @')>=0)return 1;}
                    var editables=document.querySelectorAll('[contenteditable="true"]');
                    for(var i=0;i<editables.length;i++){var r=editables[i].getBoundingClientRect();
                    if(r.width>100&&r.height>20&&r.y>window.innerHeight*0.4)return 1;}return 0;
                """)
                if v:
                    reply_ok = True
                    self.L("  \u2713 回复框已打开", "green")
                    break
            
            if not reply_ok:
                self.L("\u26a0 未打开回复框", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            # ═══ Step 7: 输入回复 + 回车发送 ═══
            time.sleep(0.5)

            # 7a. 定位输入框并点击，确保焦点在输入框
            self._cmt_js("""
                var el = document.querySelector('[contenteditable="true"]');
                if (!el) return;
                var r = el.getBoundingClientRect();
                if (r.width > 50 && r.height > 10) {
                    el.setAttribute('data-cmt-input', '1');
                }
            """)
            time.sleep(0.3)

            # 7b. 粘贴回复内容
            try:
                edt = self._d.find_element(By.CSS_SELECTOR, '[data-cmt-input="1"]')
                self._paste(self.cmt_text, edt)
            except:
                self._paste(self.cmt_text)
            time.sleep(0.8)

            # 7c. 回车发送（无需找红色SVG按钮）
            self.L("  \u21a9 回车发送", "white")
            try:
                edt = self._d.find_element(By.CSS_SELECTOR, '[contenteditable="true"]')
                edt.send_keys(Keys.RETURN)
            except:
                pass
            time.sleep(1.5)

            verify = self._cmt_js("""
                var el = document.querySelector('[contenteditable="true"]');
                if (!el) return 1;
                return (el.textContent || '').trim().length === 0 ? 1 : 0;
            """)
            if verify:
                self.L("  \u2713 发送成功", "green")
            else:
                self.L("  \u26a0 未验证到发送成功", "yellow")

            cmt_nickname = ct[:20]
            nick_match = re.match(r'^(.+?)(?:评论|回复|说|：|:)', ct)
            if nick_match:
                cmt_nickname = nick_match.group(1).strip()
            
            rec["cmt_fps"].append(fk)
            rec.setdefault("cmt_records", []).append({
                "nickname": cmt_nickname,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "comment_text": ct[:80],
                "reply_text": self.cmt_text or "感谢关注！"
            })
            save_replied(self.name, rec)
            self._cmt_n += 1
            self.cmt_cnt.emit(self.name, self._cmt_n)
            self.L("\u2705 评论已回复 | 累计: " + str(self._cmt_n), "green")

            self._d.get(DY_HOME)
            time.sleep(3)

        except WebDriverException:
            pass
        except Exception as e:
            self.L("\u26a0 评论异常: " + str(e), "yellow")
            try: self._d.get(DY_HOME)
            except: pass



    # ═══════════ 分时主循环 ═══════════

    def run(self):
        self.status.emit(self.name, "启动中...")
        self.L(f"▶ 启动 | 私信:{'开' if self.pm_on else '关'} 评论:{'开' if self.cmt_on else '关'}", "white")

        try:
            self._d = self._start_browser()
            self.status.emit(self.name, "📱 请扫码登录后点击确认")
            self.waiting_login.emit(self.name)
            self.L("📱 请扫码登录，完成后点击「确认已登录」", "white")
            self.L("💡 如需手动校准评论坐标，请先点击「📐 手动校准」再确认登录", "white")

            # 等待登录确认，期间允许手动校准
            while self._run and not self._login_ok.is_set():
                if self._calib_requested.is_set():
                    self._calib_requested.clear()
                    result = self.do_manual_calibration()
                    if result:
                        self.L("📐 校准完成！请点击「确认已登录」继续", "green")
                    else:
                        self.L("⚠ 校准未完成（可重试）", "yellow")
                self._login_ok.wait(1)
            if not self._run: return

            self.status.emit(self.name, "登录确认中...")
            self.L("⏳ 正在打开私信页面...", "white")
            self._open_pm_tab()
            self._switch_tab(TAB_HOME)
            self.status.emit(self.name, "已就绪")
            self.L(f"✅ 就绪 | 轮换模式: {CMT_PHASE}s评论→{PM_PHASE}s私信→{REST_PHASE}s休息", "green")

            # 准备首页环境
            if self.cmt_on:
                if "www.douyin.com" not in (self._d.current_url or ""):
                    self._d.get(DY_HOME)
                    time.sleep(3)

            while self._run:
                # 运行时热加载配置（支持随时开关私信/评论）
                self._reload_config()

                # ── 评论阶段 (30s) ──
                if self.cmt_on:
                    self.status.emit(self.name, f"🔍 评论检测中... ({CMT_PHASE}s)")
                    dl = time.time() + CMT_PHASE
                    while self._run and time.time() < dl:
                        ts = time.time()
                        self._cmt_cycle()
                        el = time.time() - ts
                        if el < 8:
                            time.sleep(8 - el)
                    self._minimize_after()

                # ── 私信阶段 (20s) ──
                if self.pm_on:
                    self.status.emit(self.name, f"💬 私信检测中... ({PM_PHASE}s)")
                    dl = time.time() + PM_PHASE
                    while self._run and time.time() < dl:
                        ts = time.time()
                        self._pm_cycle()
                        el = time.time() - ts
                        if el < 4:
                            time.sleep(4 - el)
                    self._minimize_after()

                # ── 休息 (10s) ──
                self.status.emit(self.name, f"⏸ 休息中... ({REST_PHASE}s)")
                for _ in range(REST_PHASE):
                    if not self._run: break
                    time.sleep(1)

                # ── 检查是否GUI请求了重新校准（线程安全：由worker线程自己执行）──
                if self._recal_requested.is_set():
                    self._recal_requested.clear()
                    self.L("🔄 收到重新校准请求...", "white")
                    # 重新加载坐标文件
                    pos = self._cmt_load_positions()
                    ok = bool(pos and self._has_manual_calib)
                    self.recal_done.emit(self.name, ok)
                    if ok:
                        self.L("✅ 校准坐标已重新加载", "green")
                    else:
                        self.L("⚠ 未找到手动校准数据，请手动校准", "yellow")

        except Exception as e:
            self.L(f"❌ 异常: {e}", "red")
            traceback.print_exc()
        finally:
            try: self._d.quit()
            except: pass
            self.status.emit(self.name, "已停止")
            self.stopped.emit(self.name)
