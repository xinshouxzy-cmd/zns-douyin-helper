# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手 — 工作线程
单浏览器双标签页：首页(评论) + 私信页(私信)
私信逻辑完全基于 v42.1 成熟方案
"""

import os, sys, json, time, re, subprocess, traceback
from threading import Event
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, WebDriverException
)

from PyQt5.QtCore import QThread, pyqtSignal

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPLIED_DIR = os.path.join(BASE_DIR, "replied_records")
os.makedirs(REPLIED_DIR, exist_ok=True)

DY_HOME = "https://www.douyin.com"
PM_URL = "https://www.douyin.com/chat?isPopup=1"   # ← v42.1 的正确私信URL
DEFAULT_COORDS = os.path.join(BASE_DIR, "comment_data", "positions.json")

TAB_HOME = 0  # 首页 tab 索引（评论用）
TAB_PM = 1    # 私信 tab 索引（私信用）


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
    safe = name.replace("/", "_").replace("\\", "_")
    return os.path.join(REPLIED_DIR, f"{safe}.json")


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
        self.pm_poll = pm_poll
        self.cmt_poll = cmt_poll
        self._run = True
        self._d = None
        self._pm_n = 0
        self._cmt_n = 0
        self._coords = None
        self._login_ok = Event()
        self._last_reply_time = {}  # 防重复回复

    def L(self, msg, tag="white"):
        self.log.emit(self.name, f"[{tag}]{msg}")

    def stop(self):
        self._run = False
        self._login_ok.set()

    def confirm_login(self):
        self._login_ok.set()

    # ── 浏览器启动 ──
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
            handles = self._d.window_handles
            if idx < len(handles):
                self._d.switch_to.window(handles[idx])
        except:
            pass

    def _open_pm_tab(self):
        """在新标签页打开私信页面"""
        self._d.execute_script(f"window.open('{PM_URL}','_blank');")
        time.sleep(4)
        self._switch_tab(TAB_PM)
        time.sleep(3)
        self.L("等待10秒后刷新私信页面...", "white")
        time.sleep(10)
        self._d.refresh()
        time.sleep(3)

    # ── 辅助方法 ──
    def _js(self, code):
        try:
            return self._d.execute_script(code)
        except:
            return None

    def _clk(self, x, y):
        try:
            self._d.execute_script(f"document.elementFromPoint({x},{y}).click();")
        except:
            pass

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
        """去掉时间后缀"""
        return re.sub(
            r'(刚刚|\d+分钟前|\d+小时前|昨天|\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日|\d{2}/\d{2})$',
            '', raw
        ).strip()

    # ── 私信回复（基于 v42.1 成熟逻辑）──
    def _enter_stranger(self):
        """点击陌生人入口 → True=已进入"""
        found = self._js("""
            let row = document.querySelector('[class*="conversationStrangerBoxrowArea2"]');
            if (!row) row = document.querySelector('[class*="StrangerBoxwrapper"]');
            if (row) {
                row.setAttribute('data-stranger-click', '1');
                return true;
            }
            return false;
        """)
        if not found:
            return False
        try:
            el = self._d.find_element(By.CSS_SELECTOR, '[data-stranger-click="1"]')
            ActionChains(self._d).move_to_element(el).click().perform()
            time.sleep(4)
            return True
        except:
            return False

    def _back_to_list(self):
        """返回消息列表"""
        self._js("""
            let back=document.querySelector('[class*="back"], [class*="return"], [class*="arrow"]');
            if(back){back.closest('div,button,span').click();return;}
            let tabs=document.querySelectorAll('[class*="tab"] span, [class*="nav"] div');
            for(let t of tabs){if(/消息/.test(t.textContent)){t.click();return;}}
        """)

    def _send_pm_reply(self, text):
        """在私信输入框输入并发送"""
        found = self._js("""
            let inp = document.querySelector('[class*="zone-container"][class*="editor-kit-container"]');
            if (inp) { inp.focus(); inp.click(); return true; }
            let all=document.querySelectorAll('div[contenteditable="true"], textarea');
            for(let el of all){
                let r=el.getBoundingClientRect();
                if(r.height>20&&r.height<200&&r.top>window.innerHeight*0.35){inp=el;break;}
            }
            if(!inp)inp=document.querySelector('div[data-placeholder]')||document.querySelector('div[class*="rich-input"]');
            if(inp){inp.focus();inp.click();}
            return !!inp;
        """)
        if not found:
            return False
        time.sleep(0.3)
        actions = ActionChains(self._d)
        for ch in text:
            actions.send_keys(ch)
        actions.pause(0.3).send_keys(Keys.ENTER).perform()
        return True

    def _pm_cycle(self):
        """一轮私信检测+回复（在 tab 1 私信页执行）- v42.1 逻辑"""
        try:
            self._switch_tab(TAB_PM)

            # 验证是否还在陌生人列表内
            still_in = self._js("""
                let list = document.querySelector('[class*="conversationStrangerConversationListlist"]');
                if (!list) return false;
                let items = list.querySelectorAll('[class*="conversationConversationItemwrapper"]');
                return items.length > 0;
            """)

            if not still_in:
                # 尝试进入陌生人列表
                if self._enter_stranger():
                    self.L("已进入陌生人消息", "white")
                    self._last_reply_time = {}
                return

            # 在陌生人列表内，找第一个陌生人并回复
            clicked = self._js("""
                let list = document.querySelector('[class*="conversationStrangerConversationListlist"]');
                if (!list) return '';
                let items = list.querySelectorAll('[class*="conversationConversationItemwrapper"]');
                if (items.length === 0) return '';
                let first = items[0];
                let title = first.querySelector('[class*="conversationConversationItemtitle"]');
                let name = title ? title.textContent.trim() : '';
                first.focus();
                ['mousedown','mouseup','click'].forEach(e =>
                    first.dispatchEvent(new MouseEvent(e,{bubbles:true,cancelable:true}))
                );
                return name;
            """)

            if not clicked:
                return

            first_name = self._clean_name(clicked)
            if not first_name:
                return

            # 防重复：同一人30秒内不重复回复
            now = time.time()
            if first_name in self._last_reply_time and now - self._last_reply_time[first_name] < 30:
                return

            # 检查是否已回复过
            rec = load_replied(self.name)
            if first_name in rec.get("pm_fps", []):
                return

            self.L(f'💬 新私信: "{first_name}"', "white")
            time.sleep(2)

            if self.pm_text and self._send_pm_reply(self.pm_text):
                self._last_reply_time[first_name] = time.time()
                rec["pm_fps"].append(first_name)
                save_replied(self.name, rec)
                self._pm_n += 1
                self.pm_cnt.emit(self.name, self._pm_n)
                self.L(f"✅ 私信已回复: {first_name} | 累计: {self._pm_n}", "green")
            else:
                self.L(f"⚠ 私信回复失败: {first_name}", "yellow")

            self._back_to_list()
            time.sleep(1)

        except WebDriverException:
            pass
        except Exception as e:
            self.L(f"⚠ 私信异常: {e}", "yellow")

    # ── 评论回复（坐标式，在 tab 0 首页执行）──
    def _load_coords(self):
        if not os.path.exists(DEFAULT_COORDS):
            self.L("⚠️ 评论坐标文件未找到，评论回复将跳过", "yellow")
            self.cmt_on = False
            return False
        try:
            with open(DEFAULT_COORDS, "r", encoding="utf-8") as f:
                self._coords = json.load(f)
            self.L(f"✅ 评论坐标已加载 ({len(self._coords)-2}步)", "green")
            return True
        except Exception as e:
            self.L(f"⚠️ 坐标加载失败: {e}", "yellow")
            self.cmt_on = False
            return False

    def _cmt_cycle(self):
        """一轮评论检测+回复（在 tab 0 首页执行）"""
        if not self._coords:
            return

        c = self._coords
        try:
            self._switch_tab(TAB_HOME)

            # 确保在抖音首页
            current = self._d.current_url
            if "www.douyin.com" not in current:
                self._d.get(DY_HOME)
                time.sleep(3)

            # 步骤1：点击通知
            self._clk(c["1_click_notification"]["x"], c["1_click_notification"]["y"])
            time.sleep(2.5)

            # 步骤2：点击全部消息
            self._clk(c["2_click_all_messages"]["x"], c["2_click_all_messages"]["y"])
            time.sleep(1.5)

            # 步骤3：点击评论筛选
            if "3_click_comment_filter" in c:
                self._clk(c["3_click_comment_filter"]["x"], c["3_click_comment_filter"]["y"])
                time.sleep(2)

            # 步骤4：获取第一条评论
            p4 = c["4_click_first_conversation"]
            fp = self._js(f"""let el=document.elementFromPoint({p4['x']},{p4['y']});
                if(!el)return null;
                let t=el;
                for(let i=0;i<5;i++){{if(t.parentElement)t=t.parentElement;
                if((t.textContent||'').trim().length>20)break;}}
                var tx=(t.textContent||'').trim();
                return tx?{{text:tx.slice(0,120)}}:null;""")

            if not fp:
                return

            comment_text = fp.get("text", "")[:80]
            fk = comment_text[:40]

            rec = load_replied(self.name)
            if fk in rec.get("cmt_fps", []):
                return

            self.L(f"💬 新评论: \"{comment_text}\"", "white")

            # 步骤5：点击评论
            self._clk(p4["x"], p4["y"])
            time.sleep(2.5)

            # 步骤6：找「回复」按钮
            reply_ok = False
            cands = self._js("""var r=[];var a=document.querySelectorAll('span,button,div,a');
                for(var i=0;i<a.length;i++){var e=a[i],t=(e.textContent||'').trim();
                if(t==='回复'){var b=e.getBoundingClientRect();
                if(b.width>0&&b.height>0&&b.width<200&&b.y>80)
                r.push({x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)});}}
                return r.sort(function(a,b){return Math.abs(a.y-500)-Math.abs(b.y-500)});""") or []

            for cand in (cands or []):
                self._clk(cand["x"], cand["y"])
                time.sleep(1.5)
                v = self._js("""var a=document.querySelectorAll('span');
                    for(var i=0;i<a.length;i++){if((a[i].textContent||'').trim()==='回复中')return true;}
                    var ins=document.querySelectorAll('[contenteditable="true"],input,textarea');
                    for(var i=0;i<ins.length;i++){var t=ins[i].getAttribute('placeholder')||'';
                    if(t.indexOf('回复')>-1||t.indexOf('@')>-1)return true;
                    if((ins[i].textContent||'').indexOf('回复 @')>-1)return true;}return false;""")
                if v:
                    reply_ok = True
                    break

            if not reply_ok and "5_click_reply_button" in c:
                self._clk(c["5_click_reply_button"]["x"], c["5_click_reply_button"]["y"])
                time.sleep(1.5)

            # 步骤7：输入回复
            try:
                self._d.execute_script(
                    "var e=document.querySelector('[contenteditable=\"true\"]');if(e)e.click();")
                time.sleep(0.5)
                edt = self._d.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                if edt:
                    self._paste(self.cmt_text, edt[0])
                time.sleep(1)
            except Exception as ex:
                self.L(f"⚠ 评论输入异常: {ex}", "yellow")

            # 步骤8：发送
            sent = self._js("""var a=document.querySelectorAll('span,button,div');
                for(var i=0;i<a.length;i++){if((a[i].textContent||'').trim()==='发送'){
                var r=a[i].getBoundingClientRect();if(r.width>0){a[i].click();return true;}}}return false;""")
            if not sent and "7_send_button" in c:
                self._clk(c["7_send_button"]["x"], c["7_send_button"]["y"])
            time.sleep(2)

            rec["cmt_fps"].append(fk)
            save_replied(self.name, rec)
            self._cmt_n += 1
            self.cmt_cnt.emit(self.name, self._cmt_n)
            self.L(f"✅ 评论已回复 | 累计: {self._cmt_n}", "green")

            # 回到首页
            self._d.get(DY_HOME)
            time.sleep(3)

        except WebDriverException:
            pass
        except Exception as e:
            self.L(f"⚠ 评论异常: {e}", "yellow")

    # ── 主循环 ──
    def run(self):
        self.status.emit(self.name, "启动中...")
        self.L(f"▶ 启动 | 私信:{'开' if self.pm_on else '关'} 评论:{'开' if self.cmt_on else '关'}", "white")

        if self.cmt_on:
            self._load_coords()

        try:
            # 打开浏览器（首页 tab）
            self._d = self._start_browser()
            self.status.emit(self.name, "📱 请扫码登录后点击确认")
            self.waiting_login.emit(self.name)
            self.L("📱 请扫码登录，完成后点击「确认已登录」", "white")

            # 等待用户点击确认
            self._login_ok.wait()
            if not self._run:
                return

            self.status.emit(self.name, "登录确认中...")
            self.L("⏳ 正在打开私信页面...", "white")

            # 在新标签页打开私信页面
            self._open_pm_tab()

            # 切回首页 tab
            self._switch_tab(TAB_HOME)

            self.status.emit(self.name, "已就绪，开始监控")
            self.L("✅ 就绪 | 首页Tab(评论) + 私信Tab(私信)", "green")

            pt = 0
            ct = 0

            while self._run:
                try:
                    # 私信轮询
                    if self.pm_on and pt >= self.pm_poll:
                        pt = 0
                        self._pm_cycle()

                    # 评论轮询
                    if self.cmt_on and ct >= self.cmt_poll:
                        ct = 0
                        self._cmt_cycle()

                    self.status.emit(self.name,
                        f"监控中 | PM:{self._pm_n} CMT:{self._cmt_n}")
                    time.sleep(1)
                    pt += 1
                    ct += 1

                except WebDriverException:
                    if not self._run:
                        break
                    time.sleep(5)
                except Exception:
                    if not self._run:
                        break
                    traceback.print_exc()
                    time.sleep(5)

        except Exception as e:
            self.L(f"❌ 浏览器异常: {e}", "red")
            traceback.print_exc()
        finally:
            try:
                self._d.quit()
            except:
                pass
            self.status.emit(self.name, "已停止")
            self.stopped.emit(self.name)
