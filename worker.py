# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手 — 工作线程
双标签页：抖音首页(评论) + 私信页(私信)
- 评论回复：CDP 鼠标事件（Playwright 同款底层）+ 全页面 JS 找坐标
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
                    _pattern = os.path.join(os.path.expanduser("~"), ".wdm", "drivers", "chromedriver", _pf_dir, "*", "chromedriver*")
                    _matches = sorted(_g.glob(_pattern), reverse=True)
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

    # ═══════════ 评论回复（Selenium ActionChains = 真实鼠标点击） ═══════════

    def _cmt_click_at(self, x, y, retries=3):
        """用 ActionChains 模拟真实鼠标点击（视口绝对坐标）"""
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

    def _cmt_js(self, code):
        try:
            return self._d.execute_script(code)
        except:
            return None

    def _cmt_load_positions(self):
        """加载录制的坐标文件，按当前视口缩放"""
        pos_file = os.path.join(BASE_DIR, "comment_data", "positions.json")
        if not os.path.exists(pos_file):
            self.L("⚠ 未找到坐标文件 comment_data/positions.json", "yellow")
            return None
        try:
            with open(pos_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            vp = self._d.execute_script("return {w: window.innerWidth, h: window.innerHeight};")
            vw, vh = vp["w"], vp["h"]
            positions = {}
            for name, p in data.items():
                if name.startswith("_"):
                    continue
                if "x_pct" in p and p["x_pct"] > 0:
                    positions[name] = {"x": int(p["x_pct"] * vw), "y": int(p["y_pct"] * vh)}
                else:
                    # 兼容旧格式：标清录制分辨率 1084x705
                    positions[name] = {"x": int(p.get("x", 0) * vw / 1084), "y": int(p.get("y", 0) * vh / 705)}
            return positions
        except Exception as e:
            self.L(f"⚠ 坐标文件读取失败: {e}", "yellow")
            return None

    def _cmt_cycle(self):
        """一轮评论检测+回复（坐标优先 → JS动态兜底）"""
        try:
            self._switch_tab(TAB_HOME)
            if "www.douyin.com" not in (self._d.current_url or ""):
                self._d.get(DY_HOME)
                self.L("⏳ 加载抖音首页...", "white")
                time.sleep(5)

            # 加载录制的坐标（每次运行时做一次缩放）
            pos = self._cmt_load_positions()

            # ====== 1. 点击通知图标（坐标优先） ======
            self.L("🔔 点击通知...", "white")
            p = pos.get("1_通知图标") if pos else None
            clicked = False
            if p:
                clicked = self._cmt_click_at(p["x"], p["y"])
            if not clicked:
                # JS 兜底
                found = self._cmt_js("""
                    var icons = document.querySelectorAll('header [class*="icon"]');
                    var best = null, bx = -1;
                    for (var i = 0; i < icons.length; i++) {
                        var r = icons[i].getBoundingClientRect();
                        if (r.width >= 16 && r.width <= 70 && r.height >= 16 && r.height <= 70
                            && r.x > window.innerWidth * 0.5 && r.x > bx && r.y < 100) {
                            best = icons[i]; bx = r.x;
                        }
                    }
                    if (!best) return null;
                    var r = best.getBoundingClientRect();
                    return {x: r.x + r.width/2, y: r.y + r.height/2};
                """)
                if found:
                    self._cmt_click_at(found["x"], found["y"])
                else:
                    self.L("⚠ 未找到通知图标", "yellow")
                    return
            time.sleep(3)

            # ====== 2. 点击「全部消息」（坐标优先） ======
            self.L("📋 点击「全部消息」...", "white")
            p = pos.get("2_全部消息") if pos else None
            if p:
                self._cmt_click_at(p["x"], p["y"])
            else:
                found = self._cmt_js("""
                    var els = document.querySelectorAll('span,div,button,a');
                    for (var i = 0; i < els.length; i++) {
                        var t = (els[i].textContent || '').trim();
                        if (t.indexOf('全部消息') >= 0 || t.indexOf('查看全部') >= 0) {
                            var r = els[i].getBoundingClientRect();
                            if (r.width > 30 && r.height > 10)
                                return {x: r.x + r.width/2, y: r.y + r.height/2};
                        }
                    }
                    return null;
                """)
                if found:
                    self._cmt_click_at(found["x"], found["y"])
            time.sleep(1.5)

            # ====== 3. 点击「评论」筛选（坐标优先 → JS兜底） ======
            self.L("💬 找「评论」筛选...", "white")
            p = pos.get("3_评论筛选") if pos else None
            found = self._cmt_js("""
                var all = document.querySelectorAll('span, div, a, button');
                for (var i = 0; i < all.length; i++) {
                    var t = (all[i].textContent || '').trim();
                    if (t === '评论') {
                        var r = all[i].getBoundingClientRect();
                        if (r.width > 0 && r.height > 0 && r.width < 200)
                            return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)};
                    }
                }
                return null;
            """)
            if found:
                self.L(f"  JS找到「评论」@ ({found['x']}, {found['y']})", "white")
                self._cmt_click_at(found["x"], found["y"])
            elif p:
                self.L(f"  用录制坐标兜底 ({p['x']}, {p['y']})", "white")
                self._cmt_click_at(p["x"], p["y"])
            else:
                self.L("⚠ 未找到「评论」标签", "yellow")
                self._d.get(DY_HOME); time.sleep(3); return
            time.sleep(2)

            # ====== 4. 提取第一条评论 ======
            self.L("🔍 提取第一条评论...", "white")
            p_item = pos.get("4_第一条评论") if pos else None
            ct = None

            # 策略A：用录制坐标 + elementFromPoint（最可靠，和 comment_auto_reply.py 一致）
            if p_item:
                ct = self._cmt_js(f"""
                    var el = document.elementFromPoint({p_item['x']}, {p_item['y']});
                    if (!el) return '';
                    var target = el;
                    for (var i = 0; i < 5; i++) {{
                        if (target.parentElement) target = target.parentElement;
                        if ((target.textContent || '').trim().length > 20) break;
                    }}
                    var text = (target.textContent || '').trim().substring(0, 120);
                    if (text) target.setAttribute('data-cmt-first', '1');
                    return text;
                """)
                if ct:
                    self.L(f"  坐标定位到评论项 ({p_item['x']}, {p_item['y']})", "white")

            # 策略B：CSS class 兜底（抖音类名常为随机 hash，可能无效）
            if not ct:
                ct = self._cmt_js("""
                    var items = document.querySelectorAll('[class*="message-item"],[class*="conversation-item"],[class*="msgItem"],[class*="notice-item"],[class*="list-item"],[class*="comment-item"]');
                    for (var i = 0; i < items.length; i++) {
                        var r = items[i].getBoundingClientRect();
                        if (r.width > 120 && r.height > 30 && r.y > 60 && r.y < window.innerHeight * 0.85) {
                            items[i].setAttribute('data-cmt-first', '1');
                            return (items[i].textContent||'').trim().substring(0, 120);
                        }
                    }
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

            # ====== 6. 找「回复」按钮（JS候选 + 验证） ======
            self.L("✏️ 找「回复」按钮...", "white")
            candidates = self._cmt_js("""
                var results = [];
                var all = document.querySelectorAll('span, button, div, a');
                for (var i = 0; i < all.length; i++) {
                    var t = (all[i].textContent || '').trim();
                    if (t === '回复') {
                        var r = all[i].getBoundingClientRect();
                        if (r.width > 0 && r.height > 0 && r.width < 200 && r.y > 80) {
                            results.push({x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)});
                        }
                    }
                }
                return results;
            """)
            reply_ok = False
            # 先尝试 JS 候选，再用录制坐标兜底
            all_candidates = list(candidates or [])
            p_reply = pos.get("5_回复按钮") if pos else None
            if p_reply and not all_candidates:
                all_candidates.append(p_reply)
            for c in all_candidates:
                self._cmt_click_at(c["x"], c["y"])
                time.sleep(1.5)
                v = self._cmt_js("""
                    var spans = document.querySelectorAll('span');
                    for (var i = 0; i < spans.length; i++) {
                        if ((spans[i].textContent || '').trim() === '回复中') return true;
                    }
                    var inputs = document.querySelectorAll('[contenteditable="true"], input, textarea');
                    for (var i = 0; i < inputs.length; i++) {
                        var txt = (inputs[i].textContent || inputs[i].value || '').trim();
                        if (txt.indexOf('回复 @') >= 0 || txt.indexOf('回复中') >= 0) return true;
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

            # ====== 8. 发送（红色箭头图标按钮，无文字，输入后才出现）=====
            p_send = pos.get("7_发送按钮") if pos else None
            clicked = False
            for attempt in range(3):
                # 等待发送按钮渲染（输入内容后才会出现）
                time.sleep(0.8)
                # 策略A：elementFromPoint + JS click（图标按钮无文字，JS textContent搜不到）
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
                        el.click();
                        return true;
                    """)
                    if btn_clicked:
                        self.L("📤 elementFromPoint 点击发送", "white")
                        clicked = True
                    else:
                        self.L("📤 坐标点击发送...", "white")
                        self._cmt_click_at(p_send["x"], p_send["y"])
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
                    break
                self.L(f"⚠ 未验证到发送成功，重试 {attempt+2}/3...", "yellow")

            if not clicked:
                self.L("⚠ 未找到发送按钮", "yellow")

            rec["cmt_fps"].append(fk)
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
