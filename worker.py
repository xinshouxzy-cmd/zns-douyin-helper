# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手 — 工作线程
双标签页：创作者中心(评论) + 私信页(私信)
- 评论回复：JS 坐标检测 + ActionChains 真实鼠标点击（浮窗兼容）
- 私信回复：基于 v42.1 成熟方案（不动）
- 分时轮流：30s评论 → 20s私信 → 10s休息
"""

import os, sys, json, time, re, subprocess, traceback
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
CMT_URL = "https://creator.douyin.com"
PM_URL = "https://www.douyin.com/chat?isPopup=1"

TAB_HOME = 0
TAB_PM = 1
CMT_PHASE = 30
PM_PHASE = 20
REST_PHASE = 10


def find_chromedriver():
    for c in [
        os.path.join(BASE_DIR, "chromedriver.exe"),
        os.path.join(BASE_DIR, "chromedriver"),
        "chromedriver", "chromedriver.exe",
    ]:
        if os.path.exists(c) or c in ("chromedriver", "chromedriver.exe"):
            return c
    return "chromedriver"


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

    def L(self, msg, tag="white"):
        self.log.emit(self.name, f"[{tag}]{msg}")

    def stop(self):
        self._run = False
        self._login_ok.set()

    def confirm_login(self):
        self._login_ok.set()

    # ── 浏览器 ──
    def _start_browser(self):
        opt = Options()
        opt.add_argument("--disable-blink-features=AutomationControlled")
        opt.add_argument(f"--user-data-dir={self.profile}")
        opt.add_experimental_option("excludeSwitches", ["enable-automation"])
        opt.add_experimental_option("useAutomationExtension", False)
        opt.add_experimental_option("detach", True)
        if sys.platform == "darwin":
            opt.add_argument("--use-mock-keychain")
        d = webdriver.Chrome(service=Service(find_chromedriver()), options=opt)
        d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
        d.set_window_size(1100, 800)
        d.get(DY_HOME)
        time.sleep(5)
        return d

    def _switch_tab(self, idx):
        try:
            hs = self._d.window_handles
            if idx < len(hs):
                self._d.switch_to.window(hs[idx])
        except:
            pass

    def _open_pm_tab(self):
        self._d.execute_script(f"window.open('{PM_URL}','_blank');")
        time.sleep(4)
        self._switch_tab(TAB_PM)
        time.sleep(5)
        self.L("等待加载...", "white")
        time.sleep(8)
        self._d.refresh()
        time.sleep(3)

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
            time.sleep(2)
            if self.pm_text and self._send_pm_reply(self.pm_text):
                self._last_reply[fn] = now
                rec["pm_fps"].append(fn)
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

    # ═══════════ 评论回复（侦察兵方案：JS坐标 + 真实鼠标点击） ═══════════

    def _ac_click_at(self, x, y):
        """在页面坐标 (x,y) 处执行真实鼠标点击"""
        try:
            body = self._d.find_element(By.TAG_NAME, 'body')
            ActionChains(self._d).move_to_element_with_offset(body, int(x), int(y)).click().perform()
            return True
        except:
            return False

    def _ac_hover_at(self, x, y):
        """在页面坐标 (x,y) 处悬停"""
        try:
            body = self._d.find_element(By.TAG_NAME, 'body')
            ActionChains(self._d).move_to_element_with_offset(body, int(x), int(y)).perform()
            return True
        except:
            return False

    def _cmt_find_visible(self, js_code):
        """用 JS 查找可见元素的坐标，返回 {x, y, w, h, ok}"""
        try:
            return self._d.execute_script(js_code) or {"ok": False}
        except:
            return {"ok": False}

    def _cmt_hover_notification(self):
        """悬停在 header 右侧通知图标上 → 浮窗出现"""
        info = self._cmt_find_visible("""
            var icons = document.querySelectorAll('header [class*="icon"]');
            var best = null, bx = -1;
            for (var i = 0; i < icons.length; i++) {
                var r = icons[i].getBoundingClientRect();
                if (r.width >= 16 && r.width <= 70 && r.height >= 16 && r.height <= 70
                    && r.x > window.innerWidth * 0.5 && r.x > bx && r.y < 100) {
                    best = icons[i]; bx = r.x;
                }
            }
            if (!best) {
                var els = document.querySelectorAll('[class*="notice"],[class*="notify"],[class*="bell"]');
                for (var i = 0; i < els.length; i++) {
                    var r = els[i].getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.width < 80 && r.y < 100
                        && r.x > window.innerWidth * 0.5) {
                        best = els[i]; break;
                    }
                }
            }
            if (!best) return {ok: false};
            var r = best.getBoundingClientRect();
            return {ok: true, x: r.x + r.width/2, y: r.y + r.height/2};
        """)
        if not info.get("ok"):
            self.L("⚠ 未找到通知图标", "yellow")
            return False
        self._ac_hover_at(info["x"], info["y"])
        time.sleep(2)
        # 检查浮窗是否出现
        overlay = self._js("return !!document.querySelector('[class*=\"semi-tabs-pane-motion-overlay\"],[class*=\"notice-overlay\"],[class*=\"notification-panel\"]')")
        if overlay:
            self.L("✓ 浮窗已打开", "white")
        return overlay or True  # 即使没检测到 overlay 也继续尝试

    def _cmt_click_tab_in_overlay(self, tab_name):
        """在浮窗 overlay 内点击指定标签（如「评论」「赞」）"""
        esc = tab_name.replace("\\", "\\\\").replace("'", "\\'")
        info = self._cmt_find_visible(f"""
            var overlay = document.querySelector('[class*="semi-tabs-pane-motion-overlay"],[class*="notice-overlay"],[class*="notification-panel"]');
            if (!overlay) {{
                var tabs = document.querySelectorAll('[class*="semi-tabs-tab"]');
                if (tabs.length) overlay = tabs[0].closest('div');
            }}
            if (!overlay) {{
                var tabs = document.querySelectorAll('[role="tablist"]');
                if (tabs.length) overlay = tabs[0];
            }}
            if (!overlay) return {{ok: false}};
            overlay.setAttribute('data-cmt-overlay', '1');
            var kids = overlay.querySelectorAll('*');
            for (var i = 0; i < kids.length; i++) {{
                var t = (kids[i].textContent || '').trim();
                if (t === '{esc}' || t.indexOf('{esc}') !== -1) {{
                    var r = kids[i].getBoundingClientRect();
                    if (r.width > 10 && r.height > 10) {{
                        kids[i].setAttribute('data-cmt-tab', '1');
                        return {{ok: true, x: r.x + r.width/2, y: r.y + r.height/2, w: r.width, h: r.height}};
                    }}
                }}
            }}
            return {{ok: false}};
        """)
        if not info.get("ok"):
            self.L(f"⚠ 未找到浮窗内「{tab_name}」标签", "yellow")
            return False
        self._ac_click_at(info["x"], info["y"])
        time.sleep(3)
        return True

    def _cmt_click_first_item(self):
        """在消息列表里点击第一条评论"""
        info = self._cmt_find_visible("""
            var items = document.querySelectorAll('[class*="message-item"],[class*="conversation-item"],[class*="msgItem"],[class*="notice-item"]');
            for (var i = 0; i < items.length; i++) {
                var r = items[i].getBoundingClientRect();
                if (r.width > 100 && r.height > 30 && r.y > 60 && r.y < window.innerHeight * 0.85) {
                    items[i].setAttribute('data-cmt-first', '1');
                    return {ok: true, x: r.x + r.width/2, y: r.y + r.height/2, text: (items[i].textContent||'').trim().substring(0, 120)};
                }
            }
            return {ok: false};
        """)
        if not info.get("ok"):
            self.L("⚠ 未找到评论项", "yellow")
            return False, ""
        self._ac_click_at(info["x"], info["y"])
        time.sleep(3)
        return True, info.get("text", "")

    def _cmt_click_text_button(self, text):
        """在当前视图中点击显示指定文字的按钮（用于「回复」「发送」等）"""
        esc = text.replace("\\", "\\\\").replace("'", "\\'")
        info = self._cmt_find_visible(f"""
            var els = document.querySelectorAll('span,button,div,a,li');
            for (var i = 0; i < els.length; i++) {{
                var t = (els[i].textContent || '').trim();
                if (t === '{esc}') {{
                    var r = els[i].getBoundingClientRect();
                    if (r.width > 8 && r.width < 300 && r.height > 8 && r.height < 120) {{
                        els[i].setAttribute('data-cmt-btn', '1');
                        return {{ok: true, x: r.x + r.width/2, y: r.y + r.height/2}};
                    }}
                }}
            }}
            return {{ok: false}};
        """)
        if not info.get("ok"):
            return False
        self._ac_click_at(info["x"], info["y"])
        time.sleep(1.5)
        return True

    def _cmt_focus_and_type(self, text):
        """找到输入框并点击聚焦"""
        info = self._cmt_find_visible("""
            var edts = document.querySelectorAll('[contenteditable="true"]');
            for (var i = 0; i < edts.length; i++) {
                var r = edts[i].getBoundingClientRect();
                if (r.height > 20 && r.height < 300 && r.width > 100 && r.top > window.innerHeight * 0.25) {
                    edts[i].setAttribute('data-cmt-input', '1');
                    return {ok: true, x: r.x + r.width/2, y: r.y + r.height/2};
                }
            }
            var ins = document.querySelectorAll('textarea,input[type="text"]');
            for (var i = 0; i < ins.length; i++) {
                var r = ins[i].getBoundingClientRect();
                if (r.height > 20 && r.width > 100) {
                    ins[i].setAttribute('data-cmt-input', '1');
                    return {ok: true, x: r.x + r.width/2, y: r.y + r.height/2};
                }
            }
            return {ok: false};
        """)
        if not info.get("ok"):
            return False
        self._ac_click_at(info["x"], info["y"])
        time.sleep(0.5)
        # 粘贴文本
        try:
            edt = self._d.find_element(By.CSS_SELECTOR, '[data-cmt-input="1"]')
            self._paste(text, edt)
        except:
            self._paste(text)
        time.sleep(1)
        return True

    def _cmt_cycle(self):
        """一轮评论检测+回复（JS坐标 + ActionChains真实鼠标点击）"""
        try:
            self._switch_tab(TAB_HOME)
            if "creator.douyin.com" not in (self._d.current_url or ""):
                self._d.get(CMT_URL)
                self.L("⏳ 加载创作者中心...", "white")
                time.sleep(5)

            # 1. hover 通知图标 → 浮窗打开
            self.L("🔔 悬停通知图标...", "white")
            if not self._cmt_hover_notification():
                return
            time.sleep(1)

            # 2. 点「评论」tab
            self.L("📋 点击评论标签...", "white")
            if not self._cmt_click_tab_in_overlay("评论"):
                self.L("⚠ 点击评论失败，尝试「互动」...", "yellow")
                if not self._cmt_click_tab_in_overlay("互动"):
                    self._d.get(CMT_URL); time.sleep(3); return

            # 3. 获取第一条评论
            ok, ct = self._cmt_click_first_item()
            if not ok or not ct:
                self._d.get(CMT_URL); time.sleep(3); return

            fk = ct[:40]
            rec = load_replied(self.name)
            if fk in rec.get("cmt_fps", []):
                self._d.get(CMT_URL); time.sleep(3); return

            self.L(f'💬 新评论: "{ct}"', "white")

            # 4. 点「回复」
            if not self._cmt_click_text_button("回复"):
                self._d.get(CMT_URL); time.sleep(3); return

            # 5. 输入 → 发送
            if not self._cmt_focus_and_type(self.cmt_text):
                self.L("⚠ 未找到输入框", "yellow")
                self._d.get(CMT_URL); time.sleep(3); return

            ok = self._cmt_click_text_button("发送")
            if ok:
                rec["cmt_fps"].append(fk)
                save_replied(self.name, rec)
                self._cmt_n += 1
                self.cmt_cnt.emit(self.name, self._cmt_n)
                self.L(f"✅ 评论已回复 | 累计: {self._cmt_n}", "green")
            else:
                self.L("⚠ 未找到发送按钮", "yellow")

            self._d.get(CMT_URL)
            time.sleep(3)

        except WebDriverException:
            pass
        except Exception as e:
            self.L(f"⚠ 评论异常: {e}", "yellow")
            try: self._d.get(CMT_URL)
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

            while self._run:
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

                # ── 休息 (10s) ──
                self.status.emit(self.name, f"⏸ 休息中... ({REST_PHASE}s)")
                for _ in range(REST_PHASE):
                    if not self._run: break
                    time.sleep(1)

        except Exception as e:
            self.L(f"❌ 异常: {e}", "red")
            traceback.print_exc()
        finally:
            try: self._d.quit()
            except: pass
            self.status.emit(self.name, "已停止")
            self.stopped.emit(self.name)
