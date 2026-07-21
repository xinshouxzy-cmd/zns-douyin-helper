# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手 v1.0
=========================
多账号抖音私信+评论自动回复工具
每个账号独立配置回复话术，挂机后台全自动运行

技术栈：Selenium + PyQt5
"""

import os, sys, json, time, re, subprocess, traceback
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

PM_URL = "https://creator.douyin.com/creator-micro/chat?isPopup=1"
DY_HOME = "https://www.douyin.com"


def find_chromedriver():
    for c in [
        os.path.join(BASE_DIR, "chromedriver.exe"),
        os.path.join(BASE_DIR, "chromedriver"),
        "chromedriver", "chromedriver.exe",
    ]:
        if os.path.exists(c) or c in ("chromedriver", "chromedriver.exe"):
            return c
    return "chromedriver"


def load_comment_coords(path):
    full = os.path.join(BASE_DIR, path) if not os.path.isabs(path) else path
    if not os.path.exists(full):
        return None
    with open(full, "r", encoding="utf-8") as f:
        return json.load(f)


def _rpath(name):
    return os.path.join(REPLIED_DIR, f"{name.replace('/','_').replace('\\\\','_')}.json")


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
    """单账号工作线程：同时处理私信+评论"""

    log = pyqtSignal(str, str)
    status = pyqtSignal(str, str)
    pm_cnt = pyqtSignal(str, int)
    cmt_cnt = pyqtSignal(str, int)
    stopped = pyqtSignal(str)

    def __init__(self, cfg, pm_poll=8, cmt_poll=30):
        super().__init__()
        self.cfg = cfg
        self.name = cfg.get("name", "?")
        self.pm_on = cfg.get("pm_enabled", True)
        self.pm_text = cfg.get("pm_reply", "你好，请问需要办理什么业务？")
        self.cmt_on = cfg.get("comment_enabled", True)
        self.cmt_text = cfg.get("comment_reply", "感谢关注！")
        self.cmt_coords_f = cfg.get("comment_coords_file", "")
        self.profile = os.path.join(BASE_DIR, cfg.get("chrome_profile", f"chrome_profiles/{self.name}"))
        self.pm_poll = pm_poll
        self.cmt_poll = cmt_poll
        self._run = True
        self._d = None
        self._pm_tab = None
        self._cmt_tab = None
        self._pm_n = 0
        self._cmt_n = 0
        self._coords = {}

    def L(self, msg, tag="white"):
        self.log.emit(self.name, f"[{tag}]{msg}")

    def stop(self):
        self._run = False

    # ── 浏览器 ──
    def _browser(self):
        opt = Options()
        opt.add_argument("--disable-blink-features=AutomationControlled")
        opt.add_argument(f"--user-data-dir={self.profile}")
        opt.add_experimental_option("excludeSwitches", ["enable-automation"])
        opt.add_experimental_option("useAutomationExtension", False)
        d = webdriver.Chrome(service=Service(find_chromedriver()), options=opt)
        d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
        d.get(PM_URL)
        time.sleep(3)
        self._pm_tab = d.current_window_handle
        d.execute_script("window.open('');")
        time.sleep(0.5)
        d.switch_to.window(d.window_handles[1])
        d.get(DY_HOME)
        time.sleep(3)
        self._cmt_tab = d.current_window_handle
        d.switch_to.window(self._pm_tab)
        return d

    def _sw_pm(self):
        try:
            if self._pm_tab in self._d.window_handles:
                self._d.switch_to.window(self._pm_tab)
        except: pass

    def _sw_cmt(self):
        try:
            if self._cmt_tab in self._d.window_handles:
                self._d.switch_to.window(self._cmt_tab)
        except: pass

    # ── 私信 ──
    def _pm_cycle(self):
        self._sw_pm()
        time.sleep(0.3)
        # 进入陌生人
        try:
            xp = '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[2]/div/div/div/div/div/div[last()-1]/div/span'
            tabs = self._d.find_elements(By.XPATH, xp)
            if tabs: tabs[-1].click(); time.sleep(0.8)
        except: return

        try:
            ctn = self._d.find_element(By.XPATH,
                '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[2]/div/div/div/div/div/div[2]/div/div/div/div/div[1]/div/div[2]')
            html = ctn.get_attribute("outerHTML")
            m = re.search(r'data-id="([^"]+)"', html)
            cid = m.group(1) if m else "?"
            txt = (ctn.text or "")[:60].replace("\n", " ")
        except: return

        rec = load_replied(self.name)
        if cid in rec.get("pm_fps", []): return

        self.L(f"💬 新私信: \"{txt}\"", "white")
        try:
            inp = self._d.find_element(By.XPATH,
                '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[2]/div/div/div/div/div/div[3]/div/div[2]/div/div/div')
            inp.click(); time.sleep(0.2)
            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=self.pm_text.encode("utf-8"))
                inp.send_keys(Keys.COMMAND, 'v')
            else:
                import pyperclip
                pyperclip.copy(self.pm_text)
                inp.send_keys(Keys.CONTROL, 'v')
            time.sleep(0.5)
            btn = self._d.find_element(By.XPATH,
                '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[2]/div/div/div/div/div/div[3]/div/div[3]/div')
            btn.click(); time.sleep(0.5)
            rec["pm_fps"].append(cid)
            save_replied(self.name, rec)
            self._pm_n += 1; self.pm_cnt.emit(self.name, self._pm_n)
            self.L(f"✅ 私信已回 | 累计: {self._pm_n}", "green")
        except Exception as e:
            self.L(f"⚠️ 私信发送失败: {e}", "#FFC107")
        # 返回列表
        try:
            bk = self._d.find_element(By.XPATH,
                '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[1]/div/div[1]/div/div/span')
            bk.click(); time.sleep(0.5)
        except: pass

    # ── 评论 ──
    def _clk(self, x, y):
        self._d.execute_script(f"document.elementFromPoint({x},{y}).click();")

    def _js(self, code):
        try:
            return self._d.execute_script(code)
        except: return None

    def _cmt_cycle(self):
        if not self._coords: return
        self._sw_cmt()
        time.sleep(0.5)

        c = self._coords
        try:
            self._clk(c["1_click_notification"]["x"], c["1_click_notification"]["y"])
            time.sleep(2.5)
            self._clk(c["2_click_all_messages"]["x"], c["2_click_all_messages"]["y"])
            time.sleep(1.5)
            if "3_click_comment_filter" in c:
                self._clk(c["3_click_comment_filter"]["x"], c["3_click_comment_filter"]["y"])
                time.sleep(2)
        except: return

        p4 = c["4_click_first_conversation"]
        fp = self._js(f"""let el=document.elementFromPoint({p4['x']},{p4['y']});if(!el)return null;
            let t=el;for(let i=0;i<5;i++){{if(t.parentElement)t=t.parentElement;
            if((t.textContent||'').trim().length>20)break;}}
            var tx=(t.textContent||'').trim();if(!tx)return null;
            return {{text:tx.slice(0,120)}};""")
        if not fp: return

        comment = fp.get("text", "")[:80]; fk = comment[:40]
        rec = load_replied(self.name)
        if fk in rec.get("cmt_fps", []): return

        self.L(f"💬 新评论: \"{comment}\"", "white")
        self._clk(p4["x"], p4["y"]); time.sleep(2.5)

        # 找回复按钮
        cands = self._js("""var r=[];var a=document.querySelectorAll('span,button,div,a');
            for(var i=0;i<a.length;i++){var e=a[i],t=(e.textContent||'').trim();
            if(t==='回复'){var b=e.getBoundingClientRect();
            if(b.width>0&&b.height>0&&b.width<200&&b.y>80)
            r.push({x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)});}}
            r.sort(function(a,b){return(b.rx||0)-(a.rx||0)-((a.rx||0)-(b.rx||0));});return r;""") or []

        ok = False
        for cand in (cands or []):
            self._clk(cand["x"], cand["y"]); time.sleep(1.5)
            v = self._js("""var a=document.querySelectorAll('span');for(var i=0;i<a.length;i++)
                {if((a[i].textContent||'').trim()==='回复中')return true;}
                var ins=document.querySelectorAll('[contenteditable="true"],input,textarea');
                for(var i=0;i<ins.length;i++){var t=ins[i].getAttribute('placeholder')||'';
                if(t.indexOf('回复')>-1||t.indexOf('@')>-1)return true;
                if((ins[i].textContent||'').indexOf('回复 @')>-1)return true;}return false;""")
            if v: ok = True; self.L("✅ 回复按钮验证通过", "green"); break
            else: self.L("❌ 未通过，试下一个", "#FFC107")

        if not ok and "5_click_reply_button" in c:
            self._clk(c["5_click_reply_button"]["x"], c["5_click_reply_button"]["y"]); time.sleep(1.5)

        # 输入
        try:
            self._d.execute_script("var e=document.querySelector('[contenteditable=\"true\"]');if(e)e.click();")
            time.sleep(0.5)
            edt = self._d.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
            if edt:
                e = edt[0]
                if sys.platform == "darwin":
                    subprocess.run(["pbcopy"], input=self.cmt_text.encode("utf-8"))
                    e.send_keys(Keys.COMMAND, 'v')
                else:
                    import pyperclip
                    pyperclip.copy(self.cmt_text)
                    e.send_keys(Keys.CONTROL, 'v')
            time.sleep(1)
        except Exception as ex:
            self.L(f"⚠️ 输入异常: {ex}", "#FFC107")

        # 发送
        sent = self._js("""var a=document.querySelectorAll('span,button,div');
            for(var i=0;i<a.length;i++){if((a[i].textContent||'').trim()==='发送'){
            var r=a[i].getBoundingClientRect();if(r.width>0){a[i].click();return true;}}}return false;""")
        if not sent and "7_send_button" in c:
            self._clk(c["7_send_button"]["x"], c["7_send_button"]["y"])
        time.sleep(2)

        rec["cmt_fps"].append(fk)
        save_replied(self.name, rec)
        self._cmt_n += 1; self.cmt_cnt.emit(self.name, self._cmt_n)
        self.L(f"✅ 评论已回 | 累计: {self._cmt_n}", "green")

        self._d.get(DY_HOME); time.sleep(3)

    # ── 主循环 ──
    def run(self):
        self.status.emit(self.name, "启动中...")
        self.L(f"▶ 启动 | 私信:{'开' if self.pm_on else '关'} 评论:{'开' if self.cmt_on else '关'}")

        if self.cmt_on and self.cmt_coords_f:
            self._coords = load_comment_coords(self.cmt_coords_f) or {}
            if self._coords:
                self.L(f"✅ 坐标加载 ({len(self._coords)}点)", "green")
            else:
                self.L(f"⚠️ 坐标文件未找到", "#FFC107")
                self.cmt_on = False

        try:
            self._d = self._browser()
            pt, ct = 0, 0
            while self._run:
                try:
                    if self.pm_on and pt >= self.pm_poll:
                        pt = 0; self._pm_cycle()
                    if self.cmt_on and ct >= self.cmt_poll:
                        ct = 0; self._cmt_cycle()
                    self.status.emit(self.name,
                        f"运行中 | 私信:{self._pm_n} 评论:{self._cmt_n}")
                    time.sleep(1); pt += 1; ct += 1
                except WebDriverException:
                    if not self._run: break
                    time.sleep(5)
                except Exception:
                    if not self._run: break
                    traceback.print_exc(); time.sleep(5)
        except Exception as e:
            traceback.print_exc()
        finally:
            try: self._d.quit()
            except: pass
            self.status.emit(self.name, "已停止")
            self.stopped.emit(self.name)
