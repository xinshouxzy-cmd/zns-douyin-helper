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

from notification_scout import NotificationScout

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
        self._pm_n = 0
        self._cmt_n = 0
        self._login_ok = Event()
        self._last_reply = {}
        self._notify_coord = None  # 侦察兵校准后的通知按钮坐标
        self._recal_requested = Event()  # 线程安全：GUI请求重新校准

    def L(self, msg, tag="white"):
        self.log.emit(self.name, f"[{tag}]{msg}")

    def stop(self):
        self._run = False
        self._login_ok.set()

    def confirm_login(self):
        self._login_ok.set()

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

    # ═══════════ 评论回复（纯JS点击，零ActionChains，不抢前台窗口） ═══════════

    def _cmt_click_at(self, x, y, retries=3):
        """点击坐标 - 纯JS方案，绝不抢前台窗口（零 ActionChains）"""
        # 方法1: elementFromPoint + .click()（适合大多数元素）
        for i in range(retries):
            try:
                result = self._d.execute_script("""
                    var el = document.elementFromPoint(arguments[0], arguments[1]);
                    if (el) { el.click(); return 'ok'; }
                    return 'null';
                """, x, y)
                if result == "ok":
                    time.sleep(0.6)
                    return True
            except:
                time.sleep(0.5)

        # 方法2: dispatchEvent MouseEvent（比.click()更接近真实点击，也不抢焦点）
        for i in range(retries):
            try:
                result = self._d.execute_script("""
                    var el = document.elementFromPoint(arguments[0], arguments[1]);
                    if (!el) return 'null';
                    var opts = {bubbles: true, cancelable: true, view: window,
                                clientX: arguments[0], clientY: arguments[1]};
                    el.dispatchEvent(new MouseEvent('mousedown', opts));
                    el.dispatchEvent(new MouseEvent('mouseup', opts));
                    el.dispatchEvent(new MouseEvent('click', opts));
                    el.focus();
                    return 'ok';
                """, x, y)
                if result == "ok":
                    time.sleep(0.6)
                    return True
            except:
                time.sleep(0.5)

        # 方法3: 完整JS鼠标事件链（hover→mousedown→mouseup→click，不抢焦点）
        try:
            result = self._d.execute_script("""
                var el = document.elementFromPoint(arguments[0], arguments[1]);
                if (!el) return 'null';
                var seq = ['mouseenter','mouseover','mousemove','mousedown','focus','mouseup','click'];
                for (var i=0; i<seq.length; i++) {
                    el.dispatchEvent(new MouseEvent(seq[i], {bubbles:true,cancelable:true,
                        clientX:arguments[0],clientY:arguments[1],view:window}));
                }
                el.focus();
                return 'ok';
            """, x, y)
            if result == "ok":
                time.sleep(0.6)
                return True
        except:
            pass
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
        """线程安全：请求在 worker 线程内重新校准（设置标志位让 run() 循环处理）"""
        self._notify_coord = None
        self._recal_requested.set()

    # ── 侦察兵：自校准通知按钮坐标 ──
    def _calibrate_notify(self):
        """启动时运行一次侦察兵，精准定位通知按钮坐标"""
        if self._notify_coord is not None:
            return  # 已校准过，跳过

        self.L("[侦察兵] 开始自校准定位通知按钮...", "white")
        try:
            scout = NotificationScout(self._d, log_func=lambda m: self.L(m, "white"))
            self._notify_coord = scout.locate()
            if self._notify_coord:
                self.L(f"[侦察兵] ✅ 通知按钮已定位: ({self._notify_coord[0]}, {self._notify_coord[1]})", "green")
            else:
                self.L("[侦察兵] ⚠ 自校准失败，需要在抖音首页重新运行", "yellow")
        except Exception as e:
            self.L(f"[侦察兵] ❌ 异常: {e}", "red")
            self._notify_coord = None

    def _cmt_hover_at(self, x, y):
        """JS悬停坐标 — 纯 dispatchEvent，不移动真实鼠标，不抢前台窗口"""
        return self._cmt_js("""
            (function(cx,cy) {
                var el = document.elementFromPoint(cx, cy);
                if (!el) return false;
                ['pointerenter','mouseenter','pointerover','mouseover','pointermove','mousemove'].forEach(function(t){
                    el.dispatchEvent(new MouseEvent(t, {bubbles:true,cancelable:true,
                        clientX:cx,clientY:cy,view:window}));
                });
                return true;
            })(arguments[0], arguments[1]);
        """, x, y)

    def _cmt_load_positions(self):
        """加载录制的坐标文件，按当前视口+DPI缩放"""
        pos_file = os.path.join(BASE_DIR, "comment_data", "positions.json")
        if not os.path.exists(pos_file):
            self.L("⚠ 未找到坐标文件 comment_data/positions.json", "yellow")
            return None
        try:
            with open(pos_file, "r", encoding="utf-8") as f:
                data = json.load(f)
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
        """一轮评论检测+回复（JS动态检测为主，录制坐标兜底，零ActionChains）"""
        try:
            self._switch_tab(TAB_HOME)
            if "www.douyin.com" not in (self._d.current_url or ""):
                self._d.get(DY_HOME)
                self.L("⏳ 加载抖音首页...", "white")
                time.sleep(5)

            # 加载录制的坐标（兜底用）
            pos = self._cmt_load_positions()

            # ====== 1. 点击通知图标（侦察兵优先，录制坐标兜底） ======
            verified = ''
            nx = ny = 0
            if self._notify_coord:
                nx, ny = self._notify_coord
                self.L(f"🔔 侦察兵坐标 ({nx}, {ny})", "white")
            elif pos and "1_通知图标" in pos:
                nx, ny = pos["1_通知图标"]["x"], pos["1_通知图标"]["y"]
                self.L(f"🔔 录制坐标 ({nx}, {ny})", "yellow")
            else:
                self.L("❌ 无通知按钮坐标（侦察兵失败且无录制坐标），跳过本轮", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            for attempt in range(3):
                if attempt > 0:
                    self.L(f"  重试通知悬停 ({attempt+1}/3)...", "yellow")

                # 纯JS hover方案：dispatchEvent 模拟鼠标悬停（不抢前台窗口）
                # 先用 JS mouseenter/mouseover 触达通知面板（douyin通知是hover触发）
                self._cmt_js(f"""
                    (function(cx,cy) {{
                        var el = document.elementFromPoint(cx, cy);
                        if (!el) return;
                        ['mouseenter','mouseover','mousemove'].forEach(function(t){{
                            el.dispatchEvent(new MouseEvent(t, {{bubbles:true,cancelable:true,
                                clientX:cx,clientY:cy,view:window}}));
                        }});
                    }})({nx},{ny});
                """)
                time.sleep(1.8)

                # 然后尝试 JS click（某些douyin版本需要click触发）
                self._cmt_click_at(nx, ny)
                time.sleep(1.2)

                # 校验：通知面板是否弹出
                verified = self._cmt_js("""
                    if (window.location.href.indexOf('message')>=0 || window.location.href.indexOf('notice')>=0) return 'ok';
                    var panels=document.querySelectorAll('[class*="notice"],[class*="notify"],[class*="popup"],[class*="drawer"],[class*="panel"],[class*="menu"],[role="dialog"]');
                    for (var i=0;i<panels.length;i++){var r=panels[i].getBoundingClientRect();if(r.width>120&&r.height>120)return'ok';}
                    var divs=document.querySelectorAll('div');
                    for (var j=0;j<divs.length;j++){var rr=divs[j].getBoundingClientRect();var s=window.getComputedStyle(divs[j]);if(rr.width>150&&rr.height>150&&s.position==='fixed'&&(s.zIndex||'')>10)return'ok';}
                    return'';
                """)
                self.L(f"  {'✓' if verified=='ok' else '❌'} 通知面板{'已' if verified=='ok' else '未'}弹出", "white" if verified=="ok" else "yellow")

                if verified == "ok":
                    break
                # 失败则回首页再试
                if attempt < 2:
                    self._d.get(DY_HOME)
                    time.sleep(2)

            if verified != "ok":
                self.L("❌ 通知面板3次重试均失败，跳过本轮评论", "yellow")
                self._d.get(DY_HOME); time.sleep(3)
                return

            # ====== 2. 点击「全部消息」 → 校验 ======
            self.L("📋 点击「全部消息」...", "white")
            time.sleep(2.5)  # 等面板内容完全渲染

            # 调试：面板里有无「全部消息」
            debug_info = self._cmt_js("""
                var txt = (document.body.innerText || '').substring(0, 600);
                return {
                    hasAllMsg: txt.indexOf('全部消息')>=0,
                    hasComment: txt.indexOf('评论')>=0,
                    hasLike: txt.indexOf('赞')>=0,
                    hasAt: txt.indexOf('@我')>=0
                };
            """)
            self.L(f"  [调试] 全部消息={debug_info.get('hasAllMsg')}, 评论={debug_info.get('hasComment')}, 赞={debug_info.get('hasLike')}, @我={debug_info.get('hasAt')}")

            # ── 找「全部消息」并用纯JS点击 ──
            all_msg_clicked = False
            for all_try in range(4):
                if all_try > 0:
                    self.L(f"  重试「全部消息」({all_try+1}/4)...", "yellow")
                    time.sleep(1.5)

                # 重新检测通知面板（面板可能被之前的操作关闭了）
                if all_try > 0:
                    panel_ok = self._cmt_js("""
                        var panels=document.querySelectorAll('[class*="notice"],[class*="notify"],[class*="popup"],[class*="drawer"],[class*="panel"],[role="dialog"]');
                        for(var i=0;i<panels.length;i++){var r=panels[i].getBoundingClientRect();if(r.width>120&&r.height>120)return'ok';}
                        return'';
                    """)
                    if panel_ok != 'ok':
                        self.L("  通知面板已关闭，无法继续", "yellow")
                        break

                # 找到「全部消息」元素
                all_msg_el = None
                try:
                    elements = self._d.find_elements(By.XPATH, "//*[text()='全部消息']")
                    for el in elements:
                        r = el.rect
                        if r['width'] > 40 and r['height'] > 10:
                            all_msg_el = el
                            break
                except:
                    pass

                if all_msg_el:
                    try:
                        self._d.execute_script("arguments[0].scrollIntoView({block:'center'});", all_msg_el)
                        time.sleep(0.3)
                        all_msg_el.click()
                        self.L(f"  点击「全部消息」(WebElement)", "white")
                    except Exception as e:
                        self.L(f"  WebElement点击失败: {e}，改用坐标", "yellow")
                        r = all_msg_el.rect
                        self._cmt_click_at(r['x'] + r['width']/2, r['y'] + r['height']/2)
                else:
                    # JS 找
                    found_pos = self._cmt_js("""
                        var els = document.querySelectorAll('div,span,button,a,[role="button"]');
                        for (var i=0; i<els.length; i++) {
                            var t = (els[i].textContent||'').trim();
                            if (t==='全部消息' || t.indexOf('查看全部')>=0) {
                                var r = els[i].getBoundingClientRect();
                                if (r.width>40 && r.height>10) {
                                    els[i].click();
                                    return {x:r.x+r.width/2, y:r.y+r.height/2, text:t};
                                }
                            }
                        }
                        return null;
                    """)
                    if found_pos:
                        self._cmt_click_at(found_pos["x"], found_pos["y"])
                        self.L(f"  JS点击 '{found_pos.get('text','')}' @ ({found_pos['x']:.0f},{found_pos['y']:.0f})", "white")
                    else:
                        self.L("  ❌ 未找到「全部消息」元素", "yellow")
                        break

                time.sleep(3.0)

                # ═══ 验证：是否进入了消息页面 ═══
                # douyin 的「全部消息」可能是 SPA 路由不改变 URL
                # 关键是：面板变成了更大的消息列表页面
                verify_result = self._cmt_js("""
                    (function() {
                        var url = window.location.href;
                        if (url.indexOf('/message')>=0 || url.indexOf('/notice')>=0) return 'url';

                        // 检测消息列表的左侧导航（互动消息/评论/赞/@我/粉丝 等标签）
                        var bodyText = (document.body.innerText||'').substring(0, 1000);
                        var hasInteraction = bodyText.indexOf('互动消息') >= 0;
                        var hasComment = bodyText.indexOf('评论') >= 0;
                        var hasAll = bodyText.indexOf('全部') >= 0;

                        if (hasInteraction && (hasComment || hasAll)) return 'nav';

                        // 检测大的消息列表容器
                        var containers = document.querySelectorAll(
                            '[class*="message-list"],[class*="conversation"],[class*="msg-list"],' +
                            '[class*="chat-list"],[class*="notice-list"],[class*="inbox-list"],' +
                            '[class*="notification-list"]');
                        for (var i=0; i<containers.length; i++) {
                            var r = containers[i].getBoundingClientRect();
                            if (r.width>250 && r.height>300) return 'container';
                        }

                        return '';
                    })();
                """)

                if verify_result in ('url', 'nav', 'container'):
                    self.L(f"  ✓ 已进入消息页面({verify_result})", "green")
                    all_msg_clicked = True
                    break

                self.L(f"  ⚠ 未检测到消息页面 (result={verify_result})", "yellow")

            if not all_msg_clicked:
                self.L("  ❌ 4次重试均未进入消息列表，跳过本轮", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            # ====== 3. 点击「评论」筛选 → 校验 ======
            self.L("💬 找「评论」筛选...", "white")
            time.sleep(1.0)  # 等导航渲染

            # 精确找左侧导航中的「评论」（排除通知面板中的「评论」）
            cmt_clicked = False
            cmt_el = None
            try:
                # 优先找左侧导航区域中的「评论」
                elements = self._d.find_elements(By.XPATH,
                    "//div[contains(@class,'nav') or contains(@class,'sidebar') or contains(@class,'menu') or contains(@class,'tab')]//*[text()='评论']")
                if not elements:
                    # 宽松搜索
                    elements = self._d.find_elements(By.XPATH, "//*[text()='评论']")
                for el in elements:
                    r = el.rect
                    if r['width'] > 0 and r['height'] > 0 and r['width'] < 200:
                        cmt_el = el
                        break
            except:
                pass

            if cmt_el:
                try:
                    self._d.execute_script("arguments[0].scrollIntoView({block:'center'});", cmt_el)
                    time.sleep(0.3)
                    cmt_el.click()
                    self.L(f"  点击「评论」(WebElement)", "white")
                    cmt_clicked = True
                except:
                    pass

            if not cmt_clicked:
                found = self._cmt_js("""
                    var all = document.querySelectorAll('span, div, a, button, li');
                    for (var i = 0; i < all.length; i++) {
                        var t = (all[i].textContent || '').trim();
                        if (t !== '评论') continue;
                        var r = all[i].getBoundingClientRect();
                        if (r.width > 0 && r.height > 0 && r.width < 200) {
                            all[i].click();
                            return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)};
                        }
                    }
                    return null;
                """)
                if found:
                    self.L(f"  JS找到「评论」@ ({found['x']}, {found['y']})", "white")
                    self._cmt_click_at(found["x"], found["y"])
                    cmt_clicked = True
                else:
                    # 无录制兜底了
                    pass

            if not cmt_clicked:
                self.L("⚠ 未找到「评论」标签", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            time.sleep(2.5)

            # ═══ 校验3：评论列表是否加载 ═══
            cmt_loaded = self._cmt_js("""
                (function() {
                    // 找具体的评论项（有头像、用户名、内容、时间等特征）
                    var allDivs = document.querySelectorAll('div[class*="item"],div[class*="comment"],div[class*="msg"],li[class*="item"],li[class*="comment"]');
                    for (var i=0; i<allDivs.length; i++) {
                        var t = (allDivs[i].textContent||'').trim();
                        var r = allDivs[i].getBoundingClientRect();
                        if (t.indexOf('滚动')>=0||t.indexOf('我知道了')>=0) continue;
                        if (r.width>200 && r.height>40 && r.y>80 && t.length>15) return 'ok';
                    }
                    // 回退：找任何包含用户名+时间的元素（评论特有格式）
                    var allText = document.body.innerText || '';
                    // 评论区特征：包含日期(天前/小时前)或回复
                    if (allText.indexOf('天前')>=0||allText.indexOf('小时前')>=0||allText.indexOf('回复')>=0) return 'ok';
                    return '';
                })();
            """)
            self.L(f"  {'✓' if cmt_loaded=='ok' else '❌'} 评论列表{'已加载' if cmt_loaded=='ok' else '未加载'}", "white" if cmt_loaded=='ok' else "yellow")
            if cmt_loaded != "ok":
                self.L("  ❌ 评论列表未加载，无法提取评论", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            # ====== 4. 提取第一条真实评论（DOM结构识别，不依赖录制坐标） ======
            self.L("🔍 提取第一条评论...", "white")
            ct = self._cmt_js("""
                // 抖音教程提示文本的黑名单（这些不是真实评论）
                var BLACKLIST = ["滚动", "鼠标", "键盘上下键", "查看更多推荐视频", "我知道了", "上下按钮"];
                function isHint(text) {
                    text = text || '';
                    for (var i = 0; i < BLACKLIST.length; i++) {
                        if (text.indexOf(BLACKLIST[i]) >= 0) return true;
                    }
                    return false;
                }

                // 策略1：找所有可见的、有一定大小的、包含文本的容器
                var allDivs = document.querySelectorAll('div, li, section');
                var candidates = [];
                for (var i = 0; i < allDivs.length; i++) {
                    var el = allDivs[i];
                    var r = el.getBoundingClientRect();
                    // 过滤：必须在可见区域内，宽度>150，高度>40
                    if (r.width < 150 || r.height < 40) continue;
                    if (r.y < 60 || r.y > window.innerHeight * 0.9) continue;
                    var txt = (el.textContent || '').trim();
                    // 过滤：文本长度合理（20-200字符），且不是教程提示
                    if (txt.length < 15 || txt.length > 300) continue;
                    if (isHint(txt)) continue;
                    // 过滤：不能包含大量英文（可能是CSS类名泄露）
                    var engCount = (txt.match(/[a-zA-Z]/g) || []).length;
                    if (engCount > txt.length * 0.5) continue;
                    // 候选：子元素数量适中（不是整页容器）
                    var childEls = el.querySelectorAll('*');
                    if (childEls.length > 80) continue;

                    candidates.push({
                        el: el,
                        y: r.y,
                        text: txt.substring(0, 120)
                    });
                }

                // 按 y 坐标排序，取最靠上的（第一条评论）
                candidates.sort(function(a, b) { return a.y - b.y; });

                // 过滤掉相同文本的重复项（同一容器嵌套）
                var seen = {};
                var uniq = [];
                for (var i = 0; i < candidates.length; i++) {
                    var fp = candidates[i].text.substring(0, 30);
                    if (!seen[fp]) {
                        seen[fp] = 1;
                        uniq.push(candidates[i]);
                    }
                }

                // 取第一个作为目标
                if (uniq.length > 0) {
                    uniq[0].el.setAttribute('data-cmt-first', '1');
                    return uniq[0].text;
                }

                // 策略2：最后用录制坐标兜底
                return '';
            """)

            if not ct:
                # 录制坐标兜底
                p_item = pos.get("4_第一条评论") if pos else None
                if p_item:
                    ct = self._cmt_js(f"""
                        var el = document.elementFromPoint({p_item['x']}, {p_item['y']});
                        if (!el) return '';
                        var walk = el;
                        for (var i = 0; i < 6; i++) {{
                            if (walk.parentElement) walk = walk.parentElement;
                            var t = (walk.textContent || '').trim();
                            if (t.length > 15 && t.length < 300) {{
                                walk.setAttribute('data-cmt-first', '1');
                                return t.substring(0, 120);
                            }}
                        }}
                        return '';
                    """)

            if not ct:
                self.L("⚠ 未找到评论", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            fk = ct[:40]
            rec = load_replied(self.name)
            if fk in rec.get("cmt_fps", []):
                self.L("⏭ 已回复过，跳过", "white")
                self._d.get(DY_HOME); time.sleep(3); return

            self.L(f'💬 新评论: "{ct[:60]}"', "white")

            # ====== 5. 点击评论项 ======
            info = self._cmt_js("""
                var el = document.querySelector('[data-cmt-first="1"]');
                if (!el) return null;
                var r = el.getBoundingClientRect();
                return {x: r.x + r.width/2, y: r.y + r.height/2};
            """)
            if not info:
                self._d.get(DY_HOME); time.sleep(3); return
            self._cmt_click_at(info["x"], info["y"])
            time.sleep(3)

            # ====== 6. 找「回复」按钮（多策略JS搜索） ======
            self.L("✏️ 找「回复」按钮...", "white")
            candidates = self._cmt_js("""
                var results = [];
                // 策略A：精确文本"回复"
                var all = document.querySelectorAll('span, button, div, a');
                for (var i = 0; i < all.length; i++) {
                    var t = (all[i].textContent || '').trim();
                    if (t === '回复' || t === '回复 ') {
                        var r = all[i].getBoundingClientRect();
                        if (r.width > 0 && r.height > 0 && r.width < 250 && r.y > 80) {
                            results.push({x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), priority: 1});
                        }
                    }
                }
                // 策略B：找评论区面板内的回复入口（可能有图标+回复文字）
                if (results.length === 0) {
                    var panels = document.querySelectorAll('[class*="reply"],[class*="panel"],[class*="drawer"],[class*="detail"]');
                    for (var i = 0; i < panels.length; i++) {
                        var r = panels[i].getBoundingClientRect();
                        if (r.width > 200 && r.y > 60 && r.y < window.innerHeight * 0.95) {
                            // 在里面找靠底部、靠左边的按钮
                            var btns = panels[i].querySelectorAll('span, button, div');
                            for (var j = 0; j < btns.length; j++) {
                                var br = btns[j].getBoundingClientRect();
                                var t = (btns[j].textContent || '').trim();
                                if ((t === '回复' || t.indexOf('回') >= 0) && br.y > r.y + r.height * 0.7 && br.width > 30 && br.width < 200) {
                                    results.push({x: Math.round(br.x+br.width/2), y: Math.round(br.y+br.height/2), priority: 2});
                                }
                            }
                        }
                    }
                }
                // 按优先级排序
                results.sort(function(a,b) { return a.priority - b.priority; });
                return results;
            """)
            reply_ok = False
            all_candidates = list(candidates or [])
            p_reply = pos.get("5_回复按钮") if pos else None
            if p_reply and not all_candidates:
                all_candidates.append({"x": p_reply["x"], "y": p_reply["y"], "priority": 9})
            for c in all_candidates:
                self._cmt_click_at(c["x"], c["y"])
                time.sleep(1.5)
                # 验证：检查是否出现了回复输入框
                v = self._cmt_js("""
                    // 检查「回复中」标记
                    var spans = document.querySelectorAll('span');
                    for (var i = 0; i < spans.length; i++) {
                        var t = (spans[i].textContent || '').trim();
                        if (t === '回复中' || t.indexOf('回复 @') >= 0) return true;
                    }
                    // 检查输入框
                    var inputs = document.querySelectorAll('[contenteditable="true"], input[type="text"], textarea');
                    for (var i = 0; i < inputs.length; i++) {
                        var txt = (inputs[i].textContent || inputs[i].value || inputs[i].placeholder || '').trim();
                        if (txt.indexOf('回复 @') >= 0 || txt.indexOf('回复中') >= 0 || txt.indexOf('有爱评论') >= 0) return true;
                    }
                    // 检查是否有可编辑且可见的输入区域（兜底）
                    var editables = document.querySelectorAll('[contenteditable="true"]');
                    for (var i = 0; i < editables.length; i++) {
                        var r = editables[i].getBoundingClientRect();
                        if (r.width > 100 && r.height > 20 && r.y > window.innerHeight * 0.4) return true;
                    }
                    return false;
                """)
                if v:
                    reply_ok = True
                    break
            if not reply_ok:
                self.L("⚠ 未找到有效回复按钮", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return

            # ====== 7. 输入回复 ======
            info = self._cmt_js("""
                var el = document.querySelector('[contenteditable="true"]');
                if (!el) return null;
                var r = el.getBoundingClientRect();
                if (r.width > 50 && r.height > 10) {
                    el.setAttribute('data-cmt-input', '1');
                    return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)};
                }
                return null;
            """)
            if info:
                self._cmt_click_at(info["x"], info["y"])
                time.sleep(0.5)
            try:
                edt = self._d.find_element(By.CSS_SELECTOR, '[data-cmt-input="1"]')
                self._paste(self.cmt_text, edt)
            except:
                self._paste(self.cmt_text)
            time.sleep(1)

            # ====== 8. 发送（优先 JS 自动检测，录制坐标仅兜底）=====
            clicked = False
            for attempt in range(3):
                time.sleep(0.8)

                # 策略A: JS 自动检测发送按钮（无需录制坐标！）
                auto_send = self._cmt_js("""
                    (function() {
                        var input = document.querySelector('[contenteditable="true"]');
                        if (!input) return null;
                        var ir = input.getBoundingClientRect();
                        // 在输入框右侧附近找可点击的发送元素
                        var candidates = document.querySelectorAll(
                            'button, svg, span[class*="send"], div[class*="send"], ' +
                            '[class*="submit"], [class*="publish"], [class*="post"], [class*="confirm"], ' +
                            '[class*="icon-send"], [class*="send-btn"]');
                        var best = null, bestScore = 99999;
                        for (var i=0; i<candidates.length; i++) {
                            var r = candidates[i].getBoundingClientRect();
                            if (r.width < 8 || r.height < 8) continue;
                            if (r.width > 120 || r.height > 120) continue;
                            if (r.x < ir.x + ir.width * 0.2) continue;
                            if (r.y < ir.y - 50 || r.y > ir.y + ir.height + 50) continue;
                            var dist = Math.abs(r.x + r.width/2 - (ir.x + ir.width)) +
                                       Math.abs(r.y + r.height/2 - (ir.y + ir.height/2));
                            if (dist < bestScore) { bestScore = dist; best = candidates[i]; }
                        }
                        if (!best) return null;
                        best.click();
                        return {x: best.getBoundingClientRect().x + best.getBoundingClientRect().width/2,
                                y: best.getBoundingClientRect().y + best.getBoundingClientRect().height/2};
                    })();
                """)
                if auto_send:
                    self._cmt_click_at(auto_send["x"], auto_send["y"])
                    self.L(f"📤 自动检测发送 @ ({auto_send['x']:.0f},{auto_send['y']:.0f})", "white")
                    clicked = True
                else:
                    # 策略B: 录制坐标兜底
                    p_send = pos.get("7_发送按钮") if pos else None
                    if p_send:
                        btn_clicked = self._cmt_js(f"""
                            var el = document.elementFromPoint({p_send['x']}, {p_send['y']});
                            if (!el) return false;
                            for (var i = 0; i < 5; i++) {{
                                var tag = (el.tagName || '').toLowerCase();
                                var cls = (el.className || '').toString().toLowerCase();
                                if (tag === 'button' || tag === 'svg' || cls.indexOf('send') >= 0 || cls.indexOf('submit') >= 0) {{
                                    el.click(); return true;
                                }}
                                if (el.parentElement) el = el.parentElement;
                            }}
                            el.click(); return true;
                        """)
                        if btn_clicked:
                            self.L("📤 录制坐标发送", "white")
                        else:
                            self._cmt_click_at(p_send["x"], p_send["y"])
                            self.L("📤 坐标点击发送", "white")
                        clicked = True
                    else:
                        break

                time.sleep(1.5)
                # 验证：输入框被清空 = 发送成功
                verify = self._cmt_js("""
                    var el = document.querySelector('[contenteditable="true"]');
                    if (!el) return true;
                    return (el.textContent || '').trim().length === 0;
                """)
                if verify:
                    self.L("  ✓ 发送成功", "green")
                    break
                if clicked:
                    self.L(f"  ⚠ 重试发送 {attempt+2}/3...", "yellow")

            if not clicked:
                self.L("⚠ 未找到发送按钮", "yellow")

            # 提取评论昵称
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
            self.L(f"✅ 评论已回复 | 累计: {self._cmt_n}", "green")

            self._d.get(DY_HOME)
            time.sleep(3)

        except WebDriverException:
            pass
        except Exception as e:
            self.L(f"⚠ 评论异常: {e}", "yellow")
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

            self._login_ok.wait()
            if not self._run: return

            self.status.emit(self.name, "登录确认中...")
            self.L("⏳ 正在打开私信页面...", "white")
            self._open_pm_tab()
            self._switch_tab(TAB_HOME)
            self.status.emit(self.name, "已就绪")
            self.L(f"✅ 就绪 | 轮换模式: {CMT_PHASE}s评论→{PM_PHASE}s私信→{REST_PHASE}s休息", "green")

            # ── 侦察兵：精准定位通知按钮 ──
            if self.cmt_on:
                self._calibrate_notify()
                # 校准完后回到首页
                self._switch_tab(TAB_HOME)
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
                    self._calibrate_notify()
                    ok = self._notify_coord is not None
                    self.recal_done.emit(self.name, ok)
                    if ok:
                        self.L("✅ 重新校准成功", "green")
                        self._switch_tab(TAB_HOME)
                        if "www.douyin.com" not in (self._d.current_url or ""):
                            self._d.get(DY_HOME)
                            time.sleep(3)
                    else:
                        self.L("⚠ 重新校准失败，继续使用旧坐标", "yellow")

        except Exception as e:
            self.L(f"❌ 异常: {e}", "red")
            traceback.print_exc()
        finally:
            try: self._d.quit()
            except: pass
            self.status.emit(self.name, "已停止")
            self.stopped.emit(self.name)
