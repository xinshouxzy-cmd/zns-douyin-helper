# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手 — 工作线程
单账号同时处理私信+评论自动回复
"""

import os, sys, json, time, re, subprocess, traceback
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
PM_URL = "https://creator.douyin.com/creator-micro/chat?isPopup=1"
DEFAULT_COORDS = os.path.join(BASE_DIR, "comment_data", "positions.json")


def find_chromedriver():
    for c in [
        os.path.join(BASE_DIR, "chromedriver.exe"),
        os.path.join(BASE_DIR, "chromedriver"),
        "chromedriver", "chromedriver.exe",
    ]:
        if os.path.exists(c) or c in ("chromedriver", "chromedriver.exe"):
            return c
    return "chromedriver"


# ── 已回复记录 ──
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
    pm_cnt = pyqtSignal(str, int)
    cmt_cnt = pyqtSignal(str, int)
    stopped = pyqtSignal(str)

    def __init__(self, cfg, pm_poll=5, cmt_poll=30):
        super().__init__()
        self.cfg = cfg
        self.name = cfg.get("name", "?")
        self.pm_on = cfg.get("pm_enabled", True)
        self.pm_text = cfg.get("pm_reply", "你好，请问需要办理什么业务？")
        self.cmt_on = cfg.get("comment_enabled", True)
        self.cmt_text = cfg.get("comment_reply", "感谢关注！")
        self.profile = os.path.join(BASE_DIR, cfg.get("chrome_profile", f"chrome_profiles/{self.name}"))
        self.pm_poll = pm_poll
        self.cmt_poll = cmt_poll
        self._run = True
        self._d = None
        self._pm_n = 0
        self._cmt_n = 0
        self._coords = None

    def L(self, msg, tag="white"):
        self.log.emit(self.name, f"[{tag}]{msg}")

    def stop(self):
        self._run = False

    # ── 浏览器（单标签页）──
    def _start_browser(self):
        opt = Options()
        opt.add_argument("--disable-blink-features=AutomationControlled")
        opt.add_argument(f"--user-data-dir={self.profile}")
        opt.add_experimental_option("excludeSwitches", ["enable-automation"])
        opt.add_experimental_option("useAutomationExtension", False)

        # macOS Keychain 兼容
        if sys.platform == "darwin":
            opt.add_argument("--use-mock-keychain")

        d = webdriver.Chrome(service=Service(find_chromedriver()), options=opt)
        d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})

        # 打开抖音首页，等待扫码登录
        d.get(DY_HOME)
        time.sleep(5)
        return d

    # ── 私信回复 ──
    def _go_pm_page(self):
        """跳转到私信页面"""
        self._d.get(PM_URL)
        time.sleep(3)
        # 关闭可能弹出的引导
        try:
            close_btns = self._d.find_elements(By.XPATH, '//*[contains(@class,"close") or contains(text(),"关闭")]')
            for b in close_btns[:3]:
                try: b.click()
                except: pass
        except: pass

    def _pm_cycle(self):
        """一轮私信检测+回复"""
        try:
            # 确认在私信页面
            current = self._d.current_url
            if "creator-micro/chat" not in current:
                self._go_pm_page()

            # 点击「陌生人」标签
            try:
                xp = '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[2]/div/div/div/div/div/div[last()-1]/div/span'
                tabs = self._d.find_elements(By.XPATH, xp)
                if tabs:
                    tabs[-1].click()
                    time.sleep(0.8)
            except:
                return

            # 获取最新私信内容
            try:
                ctn = self._d.find_element(By.XPATH,
                    '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[2]/div/div/div/div/div/div[2]/div/div/div/div/div[1]/div/div[2]')
                html = ctn.get_attribute("outerHTML")
                m = re.search(r'data-id="([^"]+)"', html)
                cid = m.group(1) if m else "?"
                txt = (ctn.text or "")[:60].replace("\n", " ")
            except:
                return

            rec = load_replied(self.name)
            if cid in rec.get("pm_fps", []):
                return

            self.L(f"💬 新私信: \"{txt}\"", "white")

            # 输入框
            inp = self._d.find_element(By.XPATH,
                '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[2]/div/div/div/div/div/div[3]/div/div[2]/div/div/div')
            inp.click()
            time.sleep(0.2)

            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=self.pm_text.encode("utf-8"))
                inp.send_keys(Keys.COMMAND, 'v')
            else:
                import pyperclip
                pyperclip.copy(self.pm_text)
                inp.send_keys(Keys.CONTROL, 'v')
            time.sleep(0.5)

            # 发送按钮
            btn = self._d.find_element(By.XPATH,
                '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[2]/div/div/div/div/div/div[3]/div/div[3]/div')
            btn.click()
            time.sleep(0.5)

            rec["pm_fps"].append(cid)
            save_replied(self.name, rec)
            self._pm_n += 1
            self.pm_cnt.emit(self.name, self._pm_n)
            self.L(f"✅ 私信已回复 | 累计: {self._pm_n}", "green")

            # 返回列表
            try:
                bk = self._d.find_element(By.XPATH,
                    '//*[@id="douyin-right-menu"]/div[1]/div[2]/div[1]/div/div[1]/div/div[1]/div/div/span')
                bk.click()
                time.sleep(0.5)
            except:
                pass

        except WebDriverException:
            pass
        except Exception as e:
            self.L(f"⚠ 私信异常: {e}", "yellow")

    # ── 评论回复（坐标式）──
    def _load_coords(self):
        """自动加载内置坐标文件"""
        if not os.path.exists(DEFAULT_COORDS):
            self.L("⚠️ 评论坐标文件未找到，评论回复将跳过", "yellow")
            self.L("   请先运行坐标录制工具生成 comment_data/positions.json", "yellow")
            self.cmt_on = False
            return False
        try:
            with open(DEFAULT_COORDS, "r", encoding="utf-8") as f:
                self._coords = json.load(f)
            self.L(f"✅ 评论坐标已加载 ({len(self._coords)}步)", "green")
            return True
        except Exception as e:
            self.L(f"⚠️ 坐标加载失败: {e}", "yellow")
            self.cmt_on = False
            return False

    def _clk(self, x, y):
        """点击指定坐标"""
        try:
            self._d.execute_script(f"document.elementFromPoint({x},{y}).click();")
        except:
            pass

    def _js(self, code):
        try:
            return self._d.execute_script(code)
        except:
            return None

    def _cmt_cycle(self):
        """一轮评论检测+回复"""
        if not self._coords:
            return

        c = self._coords
        try:
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

            # 步骤4：获取第一条评论内容
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

            # 步骤6：找并点击「回复」按钮
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

            # 步骤7：输入回复内容
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

        # 内置加载坐标
        if self.cmt_on:
            self._load_coords()

        try:
            self._d = self._start_browser()
            self.status.emit(self.name, "等待登录...")
            self.L("📱 请扫码登录抖音", "white")

            pt = 0
            ct = 0
            first_login = True

            while self._run:
                try:
                    # 检测是否已登录
                    if first_login:
                        cookies = self._d.get_cookies()
                        logged_in = any(c.get("name") == "sso_uid_tt" for c in cookies)
                        if logged_in:
                            self.status.emit(self.name, "已登录，开始监控...")
                            self.L("✅ 登录成功", "green")
                            first_login = False
                        else:
                            self.status.emit(self.name, "等待扫码登录...")
                            time.sleep(3)
                            continue

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
