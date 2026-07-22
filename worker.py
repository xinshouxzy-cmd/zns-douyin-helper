# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手 — 工作线程
双标签页：首页(评论) + 私信页(私信)
- 评论回复：纯 JS 元素检测，不依赖坐标
- 私信回复：基于 v42.1 成熟方案
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
        d.set_window_size(500, 800)
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

    # ═══════════ 评论回复（纯 JS，无坐标） ═══════════

    def _clk_text(self, text):
        """点击页面上显示指定文本的元素"""
        esc = text.replace("\\", "\\\\").replace("'", "\\'")
        return self._js(f"""
            var els=document.querySelectorAll('span,a,div,button,li,p,label');
            for(var i=0;i<els.length;i++){{
                if((els[i].textContent||'').trim()==='{esc}'){{
                    var r=els[i].getBoundingClientRect();
                    if(r.width>0&&r.height>0&&r.height<120){{
                        try{{els[i].click()}}catch(e){{els[i].dispatchEvent(new MouseEvent('click',{{bubbles:true}}))}}
                        return true;
                    }}
                }}
            }}
            return false;
        """)

    def _clk_rightmost_icon(self):
        """点击 header 区域最右侧图标（通知铃铛）"""
        return self._js("""
            var all=document.querySelectorAll('header *');
            var best=null,bx=-1;
            for(var i=0;i<all.length;i++){
                var r=all[i].getBoundingClientRect();
                if(r.width>=16&&r.width<=60&&r.height>=16&&r.height<=60&&r.x>window.innerWidth*.55&&r.x>bx&&r.y<120)
                    {{best=all[i];bx=r.x;}}
            }
            if(!best){{
                var icons=document.querySelectorAll('[class*="notice"],[class*="notify"],[class*="bell"],[class*="-msg"],[class*="message-icon"]');
                for(var i=0;i<icons.length;i++){{
                    var r=icons[i].getBoundingClientRect();
                    if(r.width>0&&r.height>0&&r.width<80){{best=icons[i];break;}}
                }}
            }}
            if(best){{try{{best.click()}}catch(e){{best.dispatchEvent(new MouseEvent('click',{{bubbles:true}}))}}return true;}}
            return false;
        """)

    def _get_first_comment_text(self):
        return self._js("""
            var items=document.querySelectorAll('[class*="message-item"],[class*="conversation-item"],[class*="msgItem"],[class*="notice-item"]');
            for(var i=0;i<items.length;i++){
                var r=items[i].getBoundingClientRect();
                if(r.width>100&&r.height>20&&r.y>60){
                    var t=(items[i].textContent||'').trim();
                    if(t.length>3)return t.substring(0,120);
                }
            }
            return '';
        """)

    def _clk_first_comment_item(self):
        return self._js("""
            var items=document.querySelectorAll('[class*="message-item"],[class*="conversation-item"],[class*="msgItem"],[class*="notice-item"]');
            for(var i=0;i<items.length;i++){
                var r=items[i].getBoundingClientRect();
                if(r.width>100&&r.height>20&&r.y>60){
                    try{{items[i].click()}}catch(e){{items[i].dispatchEvent(new MouseEvent('click',{{bubbles:true}}))}}
                    return true;
                }
            }
            return false;
        """)

    def _clk_reply_btn(self):
        return self._js("""
            var els=document.querySelectorAll('span,button,div,a');
            for(var i=0;i<els.length;i++){
                if((els[i].textContent||'').trim()==='回复'){
                    var r=els[i].getBoundingClientRect();
                    if(r.width>10&&r.width<200&&r.height>10){
                        try{{els[i].click()}}catch(e){{els[i].dispatchEvent(new MouseEvent('click',{{bubbles:true}}))}}
                        return true;
                    }
                }
            }
            return false;
        """)

    def _focus_input(self):
        return self._js("""
            var edts=document.querySelectorAll('[contenteditable="true"]');
            for(var i=0;i<edts.length;i++){
                var r=edts[i].getBoundingClientRect();
                if(r.height>20&&r.height<200&&r.width>100&&r.top>window.innerHeight*.3)
                    {{edts[i].focus();edts[i].click();return true;}}
            }
            var ins=document.querySelectorAll('textarea,input[type="text"]');
            for(var i=0;i<ins.length;i++){
                var r=ins[i].getBoundingClientRect();
                if(r.height>20&&r.width>100){{ins[i].focus();ins[i].click();return true;}}
            }
            return false;
        """)

    def _clk_send_btn(self):
        return self._js("""
            var els=document.querySelectorAll('span,button,div');
            for(var i=0;i<els.length;i++){
                if((els[i].textContent||'').trim()==='发送'){
                    var r=els[i].getBoundingClientRect();
                    if(r.width>10&&r.width<200){
                        try{{els[i].click()}}catch(e){{els[i].dispatchEvent(new MouseEvent('click',{{bubbles:true}}))}}
                        return true;
                    }
                }
            }
            return false;
        """)

    def _cmt_cycle(self):
        """一轮评论检测+回复（纯 JS）"""
        try:
            self._switch_tab(TAB_HOME)
            if "www.douyin.com" not in (self._d.current_url or ""):
                self._d.get(DY_HOME)
                time.sleep(3)

            # 1. 通知铃铛
            if not self._clk_rightmost_icon():
                return
            time.sleep(2.5)

            # 2. 全部消息
            ok = self._clk_text("全部消息") or self._clk_text("查看全部")
            if not ok:
                self._d.get(DY_HOME); time.sleep(2); return
            time.sleep(3)

            # 3. 评论标签
            if not self._clk_text("评论"):
                self._d.get(DY_HOME); time.sleep(2); return
            time.sleep(2)

            # 4. 获取第一条评论内容
            ct = self._get_first_comment_text()
            if not ct: return
            fk = ct[:40]
            rec = load_replied(self.name)
            if fk in rec.get("cmt_fps", []): return

            self.L(f'💬 新评论: "{ct}"', "white")

            # 5. 点击评论项
            if not self._clk_first_comment_item():
                self._d.get(DY_HOME); time.sleep(2); return
            time.sleep(3)

            # 6. 回复按钮
            if not self._clk_reply_btn():
                self._d.get(DY_HOME); time.sleep(2); return
            time.sleep(2)

            # 7. 输入
            if not self._focus_input():
                self._d.get(DY_HOME); time.sleep(2); return
            time.sleep(0.5)
            try:
                edt = self._d.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                if edt:
                    self._paste(self.cmt_text, edt[0])
                else:
                    self._js(f"var e=document.querySelector('[contenteditable=\"true\"]');if(e){{e.textContent='{self.cmt_text}';e.dispatchEvent(new Event('input',{{bubbles:true}}));}}")
                time.sleep(1)
            except Exception as ex:
                self.L(f"⚠ 评论输入异常: {ex}", "yellow")

            # 8. 发送
            ok = self._clk_send_btn()
            time.sleep(2)
            if ok:
                rec["cmt_fps"].append(fk)
                save_replied(self.name, rec)
                self._cmt_n += 1
                self.cmt_cnt.emit(self.name, self._cmt_n)
                self.L(f"✅ 评论已回复 | 累计: {self._cmt_n}", "green")
            else:
                self.L("⚠ 未找到发送按钮", "yellow")

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
