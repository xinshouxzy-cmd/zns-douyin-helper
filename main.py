# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手
多账号抖音私信+评论自动回复工具
基于 PyQt5 + Selenium
"""

import os, sys, json, csv, traceback
from datetime import datetime
from threading import Event

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QTextEdit, QLineEdit, QTabBar,
    QCheckBox, QGroupBox, QScrollArea, QMessageBox, QFileDialog, QFrame,
    QInputDialog
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette, QTextCursor

from worker import AccountWorker, BASE_DIR

try:
    from _version import VERSION
except Exception:
    VERSION = "v2.0"

# ── 配置 ──────────────────────────────────────────
APP_TITLE = f"遵农商·抖音客服助手 {VERSION} — 辛振宇"
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DEFAULT_PM_REPLY = "请问您需要办理什么业务呢？如需帮助请留下联系电话～"
DEFAULT_CMT_REPLY = "感谢您的关注与支持！如有业务需求欢迎私信咨询～"
PM_POLL = 5
CMT_POLL = 30


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"accounts": []}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── 暗色主题样式 ───────────────────────────────────
C_BG = "#1E1E1E"
C_PANEL = "#252526"
C_BORDER = "#3C3C3C"
C_TEXT = "#CCCCCC"
C_ACCENT = "#0E639C"
C_GREEN = "#4EC9B0"
C_YELLOW = "#DCDCAA"
C_RED = "#F44747"
C_INPUT = "#3C3C3C"

STYLE = f"""
QMainWindow {{ background: {C_BG}; }}
QWidget {{ color: {C_TEXT}; font-size: 13px; font-family: "Microsoft YaHei", "PingFang SC", sans-serif; }}
QTabWidget::pane {{ border: 1px solid {C_BORDER}; background: {C_PANEL}; border-radius: 4px; }}
QTabBar::tab {{
    background: {C_PANEL}; color: {C_TEXT}; padding: 8px 20px;
    border: 1px solid {C_BORDER}; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {C_BG}; color: {C_GREEN}; font-weight: bold; }}
QTabBar::tab:hover {{ background: #2D2D2D; }}
QLineEdit, QTextEdit {{
    background: {C_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px 10px;
}}
QLineEdit:focus, QTextEdit:focus {{ border-color: {C_ACCENT}; }}
QScrollArea {{ border: none; background: transparent; }}
QGroupBox {{
    color: {C_GREEN}; font-weight: bold; border: 1px solid {C_BORDER};
    border-radius: 6px; margin-top: 12px; padding-top: 16px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
"""


def _btn(color, text_color="white"):
    return f"""
        QPushButton {{
            background: {color}; color: {text_color}; border: none;
            border-radius: 4px; padding: 7px 18px; font-size: 13px; font-weight: bold;
        }}
        QPushButton:hover {{ opacity: 0.85; }}
        QPushButton:pressed {{ background: #333; }}
        QPushButton:disabled {{ background: #555; color: #888; }}
    """


# ── 每个账号的页面 ─────────────────────────────────
class AccountPage(QWidget):
    def __init__(self, idx, cfg, main_win):
        super().__init__()
        self.idx = idx
        self.cfg = cfg
        self.main = main_win
        self.worker = None
        self._pm_count = 0
        self._cmt_count = 0
        self._in_login_wait = False
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # ── 名称 + 状态 ──
        row1 = QHBoxLayout()
        lbl = QLabel("🏷 名称:")
        lbl.setFixedWidth(55)
        self.le_name = QLineEdit(self.cfg.get("name", ""))
        self.le_name.setPlaceholderText("输入账号名称（标签页将自动更新）")
        self.le_name.textChanged.connect(self._on_name_changed)
        self.lb_status = QLabel("⏸ 未启动")
        self.lb_status.setStyleSheet(f"color:#888;")
        row1.addWidget(lbl)
        row1.addWidget(self.le_name, 1)
        row1.addWidget(self.lb_status)
        lay.addLayout(row1)

        # ── 确认登录按钮（初始隐藏）──
        self.btn_login = QPushButton("✓ 确认已登录")
        self.btn_login.setStyleSheet(_btn(C_GREEN, "black"))
        self.btn_login.clicked.connect(self._confirm_login)
        self.btn_login.setVisible(False)
        lay.addWidget(self.btn_login)

        # ── 私信回复 ──
        g_pm = QGroupBox("💬 私信自动回复")
        g_pm_lay = QVBoxLayout(g_pm)
        self.cb_pm = QCheckBox("启用私信回复")
        self.cb_pm.setChecked(self.cfg.get("pm_enabled", True))
        self.cb_pm.toggled.connect(self._save)
        self.le_pm = QLineEdit(self.cfg.get("pm_reply", DEFAULT_PM_REPLY))
        self.le_pm.setPlaceholderText("私信回复话术...")
        self.le_pm.textChanged.connect(self._save)
        g_pm_lay.addWidget(self.cb_pm)
        g_pm_lay.addWidget(QLabel("话术:"))
        g_pm_lay.addWidget(self.le_pm)
        lay.addWidget(g_pm)

        # ── 评论回复 ──
        g_cmt = QGroupBox("📝 评论自动回复")
        g_cmt_lay = QVBoxLayout(g_cmt)
        self.cb_cmt = QCheckBox("启用评论回复")
        self.cb_cmt.setChecked(self.cfg.get("comment_enabled", True))
        self.cb_cmt.toggled.connect(self._save)
        self.le_cmt = QLineEdit(self.cfg.get("comment_reply", DEFAULT_CMT_REPLY))
        self.le_cmt.setPlaceholderText("评论回复话术...")
        self.le_cmt.textChanged.connect(self._save)
        g_cmt_lay.addWidget(self.cb_cmt)
        g_cmt_lay.addWidget(QLabel("话术:"))
        g_cmt_lay.addWidget(self.le_cmt)
        lay.addWidget(g_cmt)

        # ── 操作按钮 ──
        lay.addStretch()
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("▶ 启动")
        self.btn_start.setStyleSheet(_btn("#0E639C"))
        self.btn_start.clicked.connect(self._toggle)
        self.btn_export = QPushButton("📊 导出数据")
        self.btn_export.setStyleSheet(_btn("#555"))
        self.btn_export.clicked.connect(self._export_one)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_export)
        lay.addLayout(btn_row)

    def _on_name_changed(self, txt):
        self._save()
        parent = self.main.tabs
        for i in range(parent.count()):
            if parent.widget(i) == self:
                name = txt.strip() or f"账号{self.idx+1}"
                parent.setTabText(i, name)
                break

    def _save(self):
        self.cfg["name"] = self.le_name.text().strip() or f"账号{self.idx+1}"
        self.cfg["pm_enabled"] = self.cb_pm.isChecked()
        self.cfg["pm_reply"] = self.le_pm.text()
        self.cfg["comment_enabled"] = self.cb_cmt.isChecked()
        self.cfg["comment_reply"] = self.le_cmt.text()
        cfg = load_config()
        if self.idx < len(cfg.get("accounts", [])):
            cfg["accounts"][self.idx] = self.cfg
            save_config(cfg)

    def _confirm_login(self):
        """用户点击「确认已登录」"""
        if self.worker:
            self.worker.confirm_login()
            self.btn_login.setVisible(False)
            self.lb_status.setText("登录确认中...")
            self.lb_status.setStyleSheet(f"color:{C_GREEN};")

    def _toggle(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.btn_start.setText("⏳ 停止中...")
            self.btn_start.setEnabled(False)
        else:
            self._save()
            self.worker = AccountWorker(self.cfg, PM_POLL, CMT_POLL)
            self.worker.log.connect(self.main._append_log)
            self.worker.status.connect(self._on_status)
            self.worker.waiting_login.connect(self._on_waiting_login)
            self.worker.pm_cnt.connect(self._on_pm_cnt)
            self.worker.cmt_cnt.connect(self._on_cmt_cnt)
            self.worker.stopped.connect(self._on_stopped)
            self.worker.start()
            self.btn_start.setText("⏹ 停止")
            self.btn_start.setStyleSheet(_btn(C_RED))
            self.lb_status.setText("⏳ 启动中...")
            self.lb_status.setStyleSheet(f"color:{C_GREEN};")

    def _on_waiting_login(self, name):
        """Worker 进入等待登录状态，显示确认按钮"""
        if name == self.cfg.get("name"):
            self._in_login_wait = True
            self.btn_login.setVisible(True)
            self.lb_status.setText("📱 请扫码登录后点击确认")
            self.lb_status.setStyleSheet(f"color:{C_YELLOW};")

    def _on_status(self, name, s):
        if name == self.cfg.get("name"):
            self.lb_status.setText(s)
            self.lb_status.setStyleSheet(f"color:{C_GREEN};")

    def _on_pm_cnt(self, name, n):
        if name == self.cfg.get("name"):
            self._pm_count = n

    def _on_cmt_cnt(self, name, n):
        if name == self.cfg.get("name"):
            self._cmt_count = n

    def _on_stopped(self, name):
        if name == self.cfg.get("name"):
            self.worker = None
            self.btn_start.setText("▶ 启动")
            self.btn_start.setStyleSheet(_btn("#0E639C"))
            self.btn_start.setEnabled(True)
            self.btn_login.setVisible(False)
            self._in_login_wait = False
            self.lb_status.setText("⏸ 已停止")
            self.lb_status.setStyleSheet("color:#888;")

    def _export_one(self):
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
        from worker import load_replied

        f, _ = QFileDialog.getSaveFileName(self, "导出数据",
            f"{self.cfg.get('name','账号')}_{datetime.now().strftime('%m%d')}.xlsx",
            "Excel (*.xlsx)")
        if not f:
            return

        # ── 暂停 worker（参照 v42.1：导出时停止监控，完成后恢复）──
        was_running = self.worker and self.worker.isRunning()
        worker_ref = self.worker
        if was_running:
            # 断开 stopped 信号，防止 _on_stopped 干扰恢复流程
            try:
                worker_ref.stopped.disconnect(self._on_stopped)
            except TypeError:
                pass
            worker_ref.stop()
            self.lb_status.setText("⏸ 正在暂停...")
            self.lb_status.setStyleSheet(f"color:{C_YELLOW};")
            QApplication.processEvents()
            worker_ref.wait(15000)
            # 手动清理（_on_stopped 被断开，需要自己处理）
            self.worker = None
            self.btn_start.setText("▶ 启动")
            self.btn_start.setStyleSheet(_btn("#0E639C"))
            self.btn_start.setEnabled(True)
            self.btn_login.setVisible(False)
            self._in_login_wait = False

        # ── 导出（参照 v42.1 格式）──
        self.lb_status.setText("📊 导出中...")
        self.lb_status.setStyleSheet(f"color:{C_YELLOW};")
        QApplication.processEvents()

        wb = Workbook()
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font_w = Font(bold=True, size=11, color="FFFFFF")

        records = load_replied(self.cfg.get("name", "账号1"))

        # ── Sheet 1: 私信记录（v42.1 7列格式）──
        ws1 = wb.active
        ws1.title = "私信回复记录"
        ws1.append(["序号", "陌生人昵称", "联系时间", "对方消息", "我方回复", "对方后续回复", "用户手机号码"])
        for col in range(1, 8):
            cell = ws1.cell(row=1, column=col)
            cell.font = header_font_w
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        pm_history = records.get("pm_records", [])
        if pm_history:
            for i, r in enumerate(pm_history, 1):
                ws1.append([
                    i,
                    r.get("nickname", ""),
                    r.get("contact_time", r.get("time", "")),
                    r.get("first_msg", ""),
                    r.get("reply_text", ""),
                    r.get("follow_up", ""),
                    r.get("phone", "")
                ])
        else:
            ws1.append(["", "", "", "暂无记录", "", "", ""])
        ws1.column_dimensions["A"].width = 8
        ws1.column_dimensions["B"].width = 16
        ws1.column_dimensions["C"].width = 20
        ws1.column_dimensions["D"].width = 40
        ws1.column_dimensions["E"].width = 45
        ws1.column_dimensions["F"].width = 35
        ws1.column_dimensions["G"].width = 18

        # ── Sheet 2: 评论回复记录 ──
        ws2 = wb.create_sheet("评论回复记录")
        ws2.append(["序号", "回复时间", "评论昵称", "回复内容"])
        for col in range(1, 5):
            cell = ws2.cell(row=1, column=col)
            cell.font = header_font_w
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        cmt_history = records.get("cmt_records", [])
        if cmt_history:
            for i, r in enumerate(cmt_history, 1):
                ws2.append([i, r.get("time", ""), r.get("nickname", ""), r.get("reply_text", "")])
        else:
            ws2.append(["", "", "暂无记录", ""])
        ws2.column_dimensions["A"].width = 8
        ws2.column_dimensions["B"].width = 20
        ws2.column_dimensions["C"].width = 18
        ws2.column_dimensions["D"].width = 50

        wb.save(f)

        # ── 恢复运行 ──
        if was_running:
            self.lb_status.setText("✅ 导出完成，正在恢复...")
            self.lb_status.setStyleSheet(f"color:{C_GREEN};")
            # 延迟恢复，确保 UI 更新
            QTimer.singleShot(300, self._toggle)

        QMessageBox.information(self, "完成",
            f"已导出至:\n{f}\n\n工作簿包含 2 张表：\n"
            f"  ① 私信回复记录（7列）\n  ② 评论回复记录\n"
            + ("\n功能已自动恢复运行。" if was_running else ""))


# ── 主窗口 ────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(880, 680)
        self.setStyleSheet(STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(12, 10, 12, 10)
        ml.setSpacing(8)

        # ── 顶部标题 ──
        title = QLabel(f"🏦  {APP_TITLE}")
        title.setStyleSheet(f"color:{C_GREEN}; font-size:18px; font-weight:bold; padding:4px 0;")
        ml.addWidget(title)

        # ── 标签页 ──
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        ml.addWidget(self.tabs, 1)

        # ── 底部日志 ──
        ml.addWidget(QLabel("📋 运行日志"))

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(140)
        self.log_box.setStyleSheet(f"""
            QTextEdit {{
                background: #111; color: {C_TEXT}; border: 1px solid {C_BORDER};
                border-radius: 4px; padding: 6px; font-size: 11px;
                font-family: "Consolas", "Menlo", "Courier New", monospace;
            }}
        """)
        ml.addWidget(self.log_box)

        # ── 底部按钮栏 ──
        btm = QHBoxLayout()
        btm.addStretch()
        btn_all = QPushButton("▶ 全部启动")
        btn_all.setStyleSheet(_btn("#0E639C"))
        btn_all.clicked.connect(lambda: self._all_toggle(True))
        btm.addWidget(btn_all)
        btn_stop = QPushButton("⏹ 全部停止")
        btn_stop.setStyleSheet(_btn(C_RED))
        btn_stop.clicked.connect(lambda: self._all_toggle(False))
        btm.addWidget(btn_stop)
        btn_add = QPushButton("➕ 新增账号")
        btn_add.setStyleSheet(_btn("#555"))
        btn_add.clicked.connect(self._add_account)
        btm.addWidget(btn_add)
        ml.addLayout(btm)

        self._pages = []
        self._load_accounts()
        # 首次使用：无账号时自动弹出引导向导
        if len(self._pages) == 0:
            QTimer.singleShot(300, self._show_new_account_wizard)

    def _load_accounts(self):
        cfg = load_config()
        for i, ac in enumerate(cfg.get("accounts", [])):
            self._add_page(i, ac)

    def _add_page(self, idx, ac):
        page = AccountPage(idx, ac, self)
        name = ac.get("name") or f"账号{idx+1}"
        self.tabs.addTab(page, name)
        self._pages.append(page)
        self.tabs.setCurrentWidget(page)

    def _add_account(self):
        self._show_new_account_wizard()

    def _show_new_account_wizard(self):
        """三步引导式新建账号向导"""
        # ── 欢迎 ──
        QMessageBox.information(
            self, "添加账号",
            "接下来将引导您创建一个新的抖音客服账号。\n\n"
            "请依次填写以下 3 项必填信息：\n"
            "  ① 抖音昵称\n"
            "  ② 私信自动回复话术\n"
            "  ③ 评论自动回复话术\n\n"
            "点击「确定」开始 👇"
        )

        DIALOG_STYLE = """
            QInputDialog { background: #2D2D2D; }
            QLabel { color: #EEEEEE; font-size: 13px; }
            QLineEdit { color: #000000; background: #FFFFFF; font-size: 14px; padding: 6px; }
            QTextEdit, QPlainTextEdit { color: #000000; background: #FFFFFF; font-size: 14px; }
            QPushButton { padding: 6px 20px; font-size: 13px; }
        """

        # ── 第 1 步：抖音昵称 ──
        d1 = QInputDialog(self)
        d1.setWindowTitle("第 1 步 / 3 — 抖音昵称")
        d1.setLabelText("请输入该账号的抖音昵称：\n\n（用于区分不同账号，可自定义）")
        d1.setTextValue("我的抖音账号")
        d1.setInputMode(QInputDialog.TextInput)
        d1.setStyleSheet(DIALOG_STYLE)
        ok1 = d1.exec_() == QInputDialog.Accepted
        name = d1.textValue().strip() if ok1 else ""
        if not ok1 or not name:
            QMessageBox.warning(self, "已取消", "未输入昵称，已取消创建。")
            return

        # ── 第 2 步：私信回复话术 ──
        d2 = QInputDialog(self)
        d2.setWindowTitle("第 2 步 / 3 — 私信回复话术")
        d2.setLabelText("请输入「私信」收到后的自动回复内容：")
        d2.setOption(QInputDialog.UsePlainTextEditForTextInput, True)
        d2.setTextValue(DEFAULT_PM_REPLY)
        d2.setStyleSheet(DIALOG_STYLE)
        d2.resize(550, 350)
        ok2 = d2.exec_() == QInputDialog.Accepted
        pm_text = d2.textValue().strip() if ok2 else ""
        if not ok2 or not pm_text:
            QMessageBox.warning(self, "已取消", "私信话术不能为空，已取消创建。")
            return

        # ── 第 3 步：评论回复话术 ──
        d3 = QInputDialog(self)
        d3.setWindowTitle("第 3 步 / 3 — 评论回复话术")
        d3.setLabelText("请输入「评论」收到后的自动回复内容：")
        d3.setOption(QInputDialog.UsePlainTextEditForTextInput, True)
        d3.setTextValue(DEFAULT_CMT_REPLY)
        d3.setStyleSheet(DIALOG_STYLE)
        d3.resize(550, 350)
        ok3 = d3.exec_() == QInputDialog.Accepted
        cmt_text = d3.textValue().strip() if ok3 else ""
        if not ok3 or not cmt_text:
            QMessageBox.warning(self, "已取消", "评论话术不能为空，已取消创建。")
            return

        # ── 保存 ──
        cfg = load_config()
        idx = len(cfg.get("accounts", []))
        new_ac = {
            "name": name.strip(),
            "enabled": True,
            "pm_enabled": True,
            "pm_reply": pm_text.strip(),
            "comment_enabled": True,
            "comment_reply": cmt_text.strip(),
            "chrome_profile": f"chrome_profiles/account_{idx+1}"
        }
        if "accounts" not in cfg:
            cfg["accounts"] = []
        cfg["accounts"].append(new_ac)
        save_config(cfg)
        self._add_page(idx, new_ac)

        QMessageBox.information(
            self, "创建成功",
            f"「{name.strip()}」已添加！\n\n"
            f"点击「▶ 启动」并扫码登录后即可开始自动回复。"
        )

    def _close_tab(self, index):
        if self.tabs.count() <= 0:
            return
        page = self._pages[index] if index < len(self._pages) else None
        if page and page.worker and page.worker.isRunning():
            page.worker.stop()
            page.worker.wait(2000)

        cfg = load_config()
        if index < len(cfg.get("accounts", [])):
            cfg["accounts"].pop(index)
            save_config(cfg)

        self._pages.pop(index)
        self.tabs.removeTab(index)

        for i, p in enumerate(self._pages):
            p.idx = i
            p._save()

    def _all_toggle(self, start):
        for i in range(self.tabs.count()):
            page = self._pages[i] if i < len(self._pages) else None
            if not page:
                continue
            running = page.worker and page.worker.isRunning()
            if start and not running:
                page._toggle()
            elif not start and running:
                page._toggle()


    def _append_log(self, name, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        if msg.startswith("[green]"):
            color = C_GREEN; text = msg[7:]
        elif msg.startswith("[yellow]"):
            color = C_YELLOW; text = msg[8:]
        elif msg.startswith("[red]"):
            color = C_RED; text = msg[5:]
        elif msg.startswith("[white]"):
            color = C_TEXT; text = msg[7:]
        else:
            color = C_TEXT; text = msg
        html = f'<span style="color:#888;">{ts}</span> <b style="color:{C_GREEN};">[{name}]</b> <span style="color:{color};">{text}</span>'
        self.log_box.append(html)
        self.log_box.moveCursor(QTextCursor.End)
        if self.log_box.document().blockCount() > 500:
            self.log_box.clear()
            self.log_box.append('<span style="color:#888;">[日志自动清理]</span>')


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    if sys.platform == "darwin":
        app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
