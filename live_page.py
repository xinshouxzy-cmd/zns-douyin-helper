# -*- coding: utf-8 -*-
"""
遵农商·抖音AI工作台 — 直播助手页面
直播评论实时监控 + Coze AI 生成回复话术
（整合自原 live_assistant.py，独立页面，可独立启停）
"""
import os, json, time, threading, traceback

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QLineEdit, QFrame, QMessageBox, QGroupBox, QFormLayout,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_CFG_FILE = os.path.join(BASE_DIR, "live_config.json")

DEFAULT_CFG = {
    "coze_api_url": "https://zdn5vj865c.coze.site/stream_run",
    "coze_token": "",
    "creator_url": "https://creator.douyin.com/creator-micro/live/manage",
    "comment_selector": ".comment-item",
    "poll_interval": 3,
}

ACCENT = "#07C160"
ACCENT_DIM = "#06AD56"
CARD_BG = "#FFFFFF"
C_TEXT_PRIMARY = "#1A1A1A"
C_TEXT_SECONDARY = "#888888"
C_BORDER = "#E5E5E5"
C_RED = "#FA5151"
C_YELLOW = "#E6A23C"


def load_live_cfg():
    if os.path.exists(LIVE_CFG_FILE):
        try:
            with open(LIVE_CFG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CFG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CFG)


def save_live_cfg(cfg):
    with open(LIVE_CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_ai_reply(api_url, token, comment_text):
    """调用扣子智能体获取回复建议"""
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        data = {"messages": [{"role": "user", "content": comment_text}]}
        resp = requests.post(api_url, headers=headers, json=data, timeout=10)
        result = resp.json()
        return result.get("data", {}).get("content", "AI分析中...")
    except Exception as e:
        return f"AI连接失败: {str(e)}"


class LiveMonitor(threading.Thread):
    """评论监控线程（Playwright）"""
    log = pyqtSignal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.daemon = True
        self.running = False
        self.processed = set()

    def run(self):
        self.running = True
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.log.emit("[red]缺少 playwright 库，请执行: pip install playwright && playwright install chromium")
            self.running = False
            return

        try:
            with sync_playwright() as p:
                self.log.emit("[green]正在启动浏览器...")
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()
                self.log.emit(f"[white]打开直播后台: {self.cfg['creator_url']}")
                page.goto(self.cfg["creator_url"])
                self.log.emit("[yellow]请在浏览器中手动扫码登录，登录后等待监控开始...")
                time.sleep(10)

                # 等待页面加载
                for _ in range(20):
                    if not self.running:
                        break
                    time.sleep(2)
                    try:
                        page.wait_for_selector(self.cfg["comment_selector"], timeout=1000)
                        self.log.emit("[green]已检测到评论区，开始监控...")
                        break
                    except Exception:
                        continue

                while self.running:
                    try:
                        comments = page.query_selector_all(self.cfg["comment_selector"])
                        for c in comments:
                            cid = (c.get_attribute("data-id") or "") or (c.text_content() or "")[:20]
                            if cid and cid not in self.processed:
                                self.processed.add(cid)
                                text = (c.text_content() or "").strip()
                                if not text:
                                    continue
                                self.log.emit(f"[white]收到评论: {text}")
                                ai = get_ai_reply(self.cfg["coze_api_url"], self.cfg["coze_token"], text)
                                self.log.emit(f"[yellow]AI建议: {ai}")
                                self.log.emit("── " * 12)
                    except Exception as e:
                        self.log.emit(f"[red]监控异常: {e}")
                    time.sleep(float(self.cfg.get("poll_interval", 3)))
        except Exception as e:
            self.log.emit(f"[red]直播助手异常: {e}")
            traceback.print_exc()
        finally:
            self.log.emit("[white]直播助手已停止")
            self.running = False

    def stop(self):
        self.running = False


class LivePage(QWidget):
    """直播助手页面"""
    def __init__(self, main_win=None):
        super().__init__()
        self.main = main_win
        self.monitor = None
        self.cfg = load_live_cfg()
        self._build()
        self._load_cfg_to_ui()

    # ── UI ──
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        # 标题行
        title_row = QHBoxLayout()
        lbl_title = QLabel("🎥 直播助手 — 直播评论 AI 实时回复")
        lbl_title.setStyleSheet("font-size:20px; font-weight:bold; color:%s;" % C_TEXT_PRIMARY)
        title_row.addWidget(lbl_title)
        title_row.addStretch()

        self.btn_back = QPushButton("← 返回首页")
        self.btn_back.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{C_TEXT_SECONDARY};
                border:1px solid {C_BORDER}; border-radius:6px;
                padding:8px 16px; font-size:13px; }}
            QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}
        """)
        self.btn_back.clicked.connect(self._go_home)
        title_row.addWidget(self.btn_back)

        self.lb_status = QLabel("⏸ 未启动")
        self.lb_status.setStyleSheet(f"""
            background: #F0F0F0; color: {C_TEXT_SECONDARY};
            padding: 4px 14px; border-radius: 12px; font-size: 13px;
        """)
        title_row.addWidget(self.lb_status)
        lay.addLayout(title_row)

        # 配置卡片
        cfg_box = QGroupBox("⚙️ AI 配置（扣子 Coze）")
        cfg_box.setStyleSheet(f"""
            QGroupBox {{ border:1px solid {C_BORDER}; border-radius:8px; margin-top:14px; padding-top:8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color:{C_TEXT_PRIMARY}; font-weight:bold; }}
        """)
        form = QFormLayout(cfg_box)
        form.setSpacing(10)

        self.le_url = QLineEdit()
        self.le_url.setPlaceholderText("Coze 工作流 API 地址")
        form.addRow("API 地址：", self.le_url)

        self.le_token = QLineEdit()
        self.le_token.setPlaceholderText("Bearer Token")
        self.le_token.setEchoMode(QLineEdit.Password)
        form.addRow("Token：", self.le_token)

        self.le_selector = QLineEdit()
        self.le_selector.setPlaceholderText("评论元素选择器，默认 .comment-item")
        form.addRow("评论选择器：", self.le_selector)
        lay.addWidget(cfg_box)

        # 控制按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_start = QPushButton("▶ 开始直播监控")
        self.btn_start.setStyleSheet(f"""
            QPushButton {{ background:{ACCENT}; color:white; font-weight:bold;
                border-radius:6px; padding:10px 24px; font-size:14px; }}
            QPushButton:hover {{ background:{ACCENT_DIM}; }}
            QPushButton:disabled {{ background:#C0C0C0; color:#FFF; }}
        """)
        self.btn_start.clicked.connect(self._toggle)
        btn_row.addWidget(self.btn_start)

        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{C_TEXT_SECONDARY};
                border:1px solid {C_BORDER}; border-radius:6px;
                padding:10px 18px; font-size:13px; }}
            QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}
        """)
        self.btn_save.clicked.connect(self._save_cfg)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # 日志区
        log_lbl = QLabel("📋 直播监控日志")
        log_lbl.setStyleSheet("color:%s; font-weight:bold;" % C_TEXT_PRIMARY)
        lay.addWidget(log_lbl)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("评论与 AI 建议将显示在这里...")
        lay.addWidget(self.log_box, 1)

    # ── 逻辑 ──
    def _load_cfg_to_ui(self):
        self.le_url.setText(self.cfg.get("coze_api_url", ""))
        self.le_token.setText(self.cfg.get("coze_token", ""))
        self.le_selector.setText(self.cfg.get("comment_selector", DEFAULT_CFG["comment_selector"]))

    def _save_cfg(self):
        self.cfg["coze_api_url"] = self.le_url.text().strip()
        self.cfg["coze_token"] = self.le_token.text().strip()
        self.cfg["comment_selector"] = self.le_selector.text().strip() or DEFAULT_CFG["comment_selector"]
        save_live_cfg(self.cfg)
        QMessageBox.information(self, "已保存", "AI 配置已保存，下次启动自动生效。")

    def _toggle(self):
        if self.monitor and self.monitor.is_alive() and self.monitor.running:
            self.monitor.stop()
            self.monitor.join(timeout=3)
            self.monitor = None
            self._set_running(False)
            return
        if not self.le_token.text().strip():
            QMessageBox.warning(self, "缺少配置", "请先填写 Coze Token 再启动。")
            return
        self._save_cfg()
        self.cfg = load_live_cfg()
        self.monitor = LiveMonitor(self.cfg)
        self.monitor.log.connect(self._append_log)
        self.monitor.start()
        self._set_running(True)
        self._append_log("[green]直播助手已启动，浏览器将自动打开...")

    def _set_running(self, running):
        if running:
            self.lb_status.setText("🟢 监控中")
            self.lb_status.setStyleSheet(f"""
                background:#E6F9EE; color:{ACCENT};
                padding:4px 14px; border-radius:12px; font-size:13px;
            """)
            self.btn_start.setText("⏹ 停止监控")
            self.btn_start.setStyleSheet(f"""
                QPushButton {{ background:{C_RED}; color:white; font-weight:bold;
                    border-radius:6px; padding:10px 24px; font-size:14px; }}
                QPushButton:hover {{ background:#D43D3D; }}
            """)
        else:
            self.lb_status.setText("⏸ 未启动")
            self.lb_status.setStyleSheet(f"""
                background:#F0F0F0; color:{C_TEXT_SECONDARY};
                padding:4px 14px; border-radius:12px; font-size:13px;
            """)
            self.btn_start.setText("▶ 开始直播监控")
            self.btn_start.setStyleSheet(f"""
                QPushButton {{ background:{ACCENT}; color:white; font-weight:bold;
                    border-radius:6px; padding:10px 24px; font-size:14px; }}
                QPushButton:hover {{ background:{ACCENT_DIM}; }}
            """)

    def _append_log(self, msg):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        color = C_TEXT_PRIMARY
        text = msg
        if msg.startswith("[green]"):
            color = ACCENT; text = msg[7:]
        elif msg.startswith("[yellow]"):
            color = C_YELLOW; text = msg[8:]
        elif msg.startswith("[red]"):
            color = C_RED; text = msg[5:]
        elif msg.startswith("[white]"):
            color = C_TEXT_SECONDARY; text = msg[7:]
        html = f'<span style="color:#888;">{ts}</span> <span style="color:{color};">{text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</span>'
        self.log_box.append(html)
        from PyQt5.QtGui import QTextCursor
        self.log_box.moveCursor(QTextCursor.End)

    def _stop_if_running(self):
        """停止直播监控（从启动页切换离开时调用）"""
        if self.monitor and self.monitor.is_alive() and self.monitor.running:
            self.monitor.stop()
            self.monitor.join(timeout=3)
            self.monitor = None
            self._set_running(False)

    def _go_home(self):
        self._stop_if_running()
        if self.main:
            self.main.go_home()

    def closeEvent(self, ev):
        if self.monitor and self.monitor.is_alive() and self.monitor.running:
            self.monitor.stop()
        super().closeEvent(ev)
