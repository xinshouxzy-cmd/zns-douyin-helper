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
    QInputDialog, QListWidget, QListWidgetItem, QStackedWidget, QSizePolicy,
    QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QPalette, QTextCursor, QIcon, QPixmap, QPainter

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


# ── 微信风格配色 ───────────────────────────────────
C_SIDEBAR_BG = "#2C2C2C"
C_SIDEBAR_HOVER = "#3A3A3A"
C_SIDEBAR_ACTIVE = "#3A3A3A"
C_MAIN_BG = "#F0F0F0"
C_CARD_BG = "#FFFFFF"
C_TEXT_PRIMARY = "#1A1A1A"
C_TEXT_SECONDARY = "#888888"
C_TEXT_SIDEBAR = "#CCCCCC"
C_TEXT_SIDEBAR_ACTIVE = "#FFFFFF"
C_ACCENT = "#07C160"
C_ACCENT_HOVER = "#06AD56"
C_RED = "#FA5151"
C_BORDER = "#E5E5E5"
C_STATUS_RUNNING = "#07C160"
C_STATUS_STOPPED = "#B0B0B0"
C_LOG_BG = "#F8F8F8"
C_BTN_DISABLED = "#C0C0C0"

# 兼容旧引用
C_GREEN = C_ACCENT
C_YELLOW = "#E6A23C"
C_TEXT = C_TEXT_PRIMARY
C_BG = C_MAIN_BG
C_PANEL = C_CARD_BG
C_INPUT = C_CARD_BG

STYLE = f"""
QMainWindow {{ background: {C_MAIN_BG}; }}
QWidget {{
    font-size: 14px;
    font-family: "PingFang SC", "Microsoft YaHei", "SF Pro Display", sans-serif;
}}
QLineEdit {{
    background: {C_CARD_BG}; color: {C_TEXT_PRIMARY};
    border: 1px solid {C_BORDER}; border-radius: 6px;
    padding: 10px 14px; font-size: 14px;
}}
QLineEdit:focus {{ border-color: {C_ACCENT}; background: #F0FFF5; }}
QLineEdit:disabled {{ background: #F5F5F5; color: #BBB; }}
QTextEdit {{
    background: {C_LOG_BG}; color: {C_TEXT_SECONDARY};
    border: 1px solid {C_BORDER}; border-radius: 6px;
    padding: 8px 12px; font-size: 12px;
    font-family: "SF Mono", "Menlo", "Consolas", "Courier New", monospace;
}}
QScrollArea {{ border: none; background: transparent; }}
QCheckBox {{
    color: {C_TEXT_PRIMARY}; spacing: 8px; font-size: 14px;
}}
QCheckBox::indicator {{
    width: 20px; height: 20px;
    border: 2px solid {C_BORDER}; border-radius: 4px;
    background: {C_CARD_BG};
}}
QCheckBox::indicator:checked {{
    background: {C_ACCENT}; border-color: {C_ACCENT};
}}
QLabel {{ color: {C_TEXT_PRIMARY}; }}
QScrollBar:vertical {{
    background: transparent; width: 6px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #CCC; border-radius: 3px; min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 6px;
}}
QScrollBar::handle:horizontal {{
    background: #CCC; border-radius: 3px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


def _btn_primary():
    """微信绿主按钮"""
    return f"""
        QPushButton {{
            background: {C_ACCENT}; color: white; border: none;
            border-radius: 6px; padding: 10px 24px;
            font-size: 14px; font-weight: bold;
        }}
        QPushButton:hover {{ background: {C_ACCENT_HOVER}; }}
        QPushButton:pressed {{ background: #05944A; }}
        QPushButton:disabled {{ background: {C_BTN_DISABLED}; color: #999; }}
    """


def _btn_danger():
    """红色按钮（停止）"""
    return f"""
        QPushButton {{
            background: {C_RED}; color: white; border: none;
            border-radius: 6px; padding: 10px 24px;
            font-size: 14px; font-weight: bold;
        }}
        QPushButton:hover {{ background: #E04848; }}
        QPushButton:pressed {{ background: #C73E3E; }}
        QPushButton:disabled {{ background: {C_BTN_DISABLED}; color: #999; }}
    """


def _btn_default():
    """灰色次要按钮"""
    return f"""
        QPushButton {{
            background: #E5E5E5; color: {C_TEXT_PRIMARY}; border: none;
            border-radius: 6px; padding: 10px 24px;
            font-size: 14px;
        }}
        QPushButton:hover {{ background: #D5D5D5; }}
        QPushButton:pressed {{ background: #C5C5C5; }}
        QPushButton:disabled {{ background: #F0F0F0; color: #BBB; }}
    """


# 兼容旧 _btn() 调用
def _btn(color, text_color="white"):
    return f"""
        QPushButton {{
            background: {color}; color: {text_color}; border: none;
            border-radius: 6px; padding: 10px 24px;
            font-size: 14px; font-weight: bold;
        }}
        QPushButton:hover {{ opacity: 0.85; }}
        QPushButton:pressed {{ background: #333; }}
        QPushButton:disabled {{ background: #555; color: #888; }}
    """


class Card(QFrame):
    """白色圆角卡片"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"""
            #card {{
                background: {C_CARD_BG};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)


class SidebarItem(QWidget):
    """侧边栏账号项"""
    clicked = pyqtSignal(int)
    remove_requested = pyqtSignal(int)

    def __init__(self, idx, name, parent=None):
        super().__init__(parent)
        self.idx = idx
        self._name = name
        self._active = False
        self._is_running = False
        self.setFixedHeight(64)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self._update_dot()
        lay.addWidget(self.dot)

        tv = QVBoxLayout()
        tv.setSpacing(2)
        self.lbl_name = QLabel(self._name)
        self.lbl_name.setStyleSheet(f"color:{C_TEXT_SIDEBAR};font-size:14px;font-weight:500;")
        tv.addWidget(self.lbl_name)
        self.lbl_status = QLabel("已停止")
        self.lbl_status.setStyleSheet("color:#888;font-size:11px;")
        tv.addWidget(self.lbl_status)
        lay.addLayout(tv, 1)

        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(20, 20)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{ background:transparent;color:#888;border:none;font-size:16px;font-weight:bold;padding:0; }}
            QPushButton:hover {{ color:{C_RED};background:rgba(255,255,255,0.1);border-radius:10px; }}
        """)
        self.btn_close.clicked.connect(lambda: self.remove_requested.emit(self.idx))
        self.btn_close.setVisible(False)
        lay.addWidget(self.btn_close)

    def _update_dot(self):
        color = C_STATUS_RUNNING if self._is_running else C_STATUS_STOPPED
        r = 5
        pix = QPixmap(r * 2 + 2, r * 2 + 2)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, r * 2, r * 2)
        p.end()
        self.dot.setPixmap(pix)

    def set_status(self, is_running, text):
        self._is_running = is_running
        self._update_dot()
        self.lbl_status.setText(text)
        if is_running:
            self.lbl_status.setStyleSheet(f"color:{C_STATUS_RUNNING};font-size:11px;")
        else:
            self.lbl_status.setStyleSheet("color:#888;font-size:11px;")

    def set_name(self, name):
        self._name = name
        self.lbl_name.setText(name)

    def set_active(self, active):
        self._active = active
        if active:
            self.setStyleSheet(f"""
                SidebarItem {{
                    background: {C_SIDEBAR_ACTIVE};
                    border-left: 3px solid {C_ACCENT};
                }}
            """)
            self.lbl_name.setStyleSheet(f"color:{C_TEXT_SIDEBAR_ACTIVE};font-size:14px;font-weight:500;")
        else:
            self.setStyleSheet("SidebarItem { border-left: 3px solid transparent; }")
            self.lbl_name.setStyleSheet(f"color:{C_TEXT_SIDEBAR};font-size:14px;font-weight:400;")

    def enterEvent(self, event):
        if not self._active:
            self.setStyleSheet(f"SidebarItem {{ background: {C_SIDEBAR_HOVER}; border-left: 3px solid transparent; }}")
        self.btn_close.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._active:
            self.setStyleSheet("SidebarItem { border-left: 3px solid transparent; }")
        self.btn_close.setVisible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.idx)
        super().mousePressEvent(event)


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
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        # ── 标题行：名称 + 状态徽章 ──
        title_row = QHBoxLayout()
        lbl_title = QLabel("⚙️ 账号设置")
        lbl_title.setStyleSheet(f"font-size:20px; font-weight:bold; color:{C_TEXT_PRIMARY};")
        title_row.addWidget(lbl_title)
        title_row.addStretch()
        self.lb_status = QLabel("⏸ 未启动")
        self.lb_status.setStyleSheet(f"""
            background: #F0F0F0; color: {C_TEXT_SECONDARY};
            padding: 4px 14px; border-radius: 12px; font-size: 13px;
        """)
        title_row.addWidget(self.lb_status)
        lay.addLayout(title_row)

        # ── 账号名称卡片 ──
        card_name = Card()
        cn_lay = QVBoxLayout(card_name)
        cn_lay.setContentsMargins(20, 16, 20, 16)
        cn_lay.setSpacing(8)
        lbl_n = QLabel("🏷 账号名称")
        lbl_n.setStyleSheet(f"font-weight:bold; color:{C_TEXT_PRIMARY}; font-size:14px;")
        cn_lay.addWidget(lbl_n)
        self.le_name = QLineEdit(self.cfg.get("name", ""))
        self.le_name.setPlaceholderText("输入账号名称（侧边栏将自动更新）")
        self.le_name.textChanged.connect(self._on_name_changed)
        cn_lay.addWidget(self.le_name)
        lay.addWidget(card_name)

        # ── 确认登录按钮 ──
        self.btn_login = QPushButton("✓ 确认已扫码登录")
        self.btn_login.setStyleSheet(_btn_primary())
        self.btn_login.clicked.connect(self._confirm_login)
        self.btn_login.setVisible(False)
        self.btn_login.setFixedHeight(42)
        lay.addWidget(self.btn_login)

        # ── 私信回复卡片 ──
        card_pm = Card()
        cp_lay = QVBoxLayout(card_pm)
        cp_lay.setContentsMargins(20, 16, 20, 16)
        cp_lay.setSpacing(10)
        pm_hdr = QHBoxLayout()
        lbl_pm = QLabel("💬 私信自动回复")
        lbl_pm.setStyleSheet(f"font-weight:bold; color:{C_TEXT_PRIMARY}; font-size:14px;")
        pm_hdr.addWidget(lbl_pm)
        pm_hdr.addStretch()
        self.cb_pm = QCheckBox("启用")
        self.cb_pm.setChecked(self.cfg.get("pm_enabled", True))
        self.cb_pm.toggled.connect(self._save)
        pm_hdr.addWidget(self.cb_pm)
        cp_lay.addLayout(pm_hdr)
        lbl_tip = QLabel("回复话术：")
        lbl_tip.setStyleSheet(f"color:{C_TEXT_SECONDARY}; font-size:12px;")
        cp_lay.addWidget(lbl_tip)
        self.le_pm = QLineEdit(self.cfg.get("pm_reply", DEFAULT_PM_REPLY))
        self.le_pm.setPlaceholderText("私信回复话术...")
        self.le_pm.textChanged.connect(self._save)
        cp_lay.addWidget(self.le_pm)
        lay.addWidget(card_pm)

        # ── 评论回复卡片 ──
        card_cmt = Card()
        cc_lay = QVBoxLayout(card_cmt)
        cc_lay.setContentsMargins(20, 16, 20, 16)
        cc_lay.setSpacing(10)
        cmt_hdr = QHBoxLayout()
        lbl_cmt = QLabel("📝 评论自动回复")
        lbl_cmt.setStyleSheet(f"font-weight:bold; color:{C_TEXT_PRIMARY}; font-size:14px;")
        cmt_hdr.addWidget(lbl_cmt)
        cmt_hdr.addStretch()
        self.cb_cmt = QCheckBox("启用")
        self.cb_cmt.setChecked(self.cfg.get("comment_enabled", True))
        self.cb_cmt.toggled.connect(self._save)
        cmt_hdr.addWidget(self.cb_cmt)
        cc_lay.addLayout(cmt_hdr)
        lbl_tip2 = QLabel("回复话术：")
        lbl_tip2.setStyleSheet(f"color:{C_TEXT_SECONDARY}; font-size:12px;")
        cc_lay.addWidget(lbl_tip2)
        self.le_cmt = QLineEdit(self.cfg.get("comment_reply", DEFAULT_CMT_REPLY))
        self.le_cmt.setPlaceholderText("评论回复话术...")
        self.le_cmt.textChanged.connect(self._save)
        cc_lay.addWidget(self.le_cmt)
        lay.addWidget(card_cmt)

        lay.addStretch()

        # ── 操作按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.btn_start = QPushButton("▶ 启动")
        self.btn_start.setStyleSheet(_btn_primary())
        self.btn_start.setFixedHeight(42)
        self.btn_start.clicked.connect(self._toggle)
        self.btn_export = QPushButton("📊 导出数据")
        self.btn_export.setStyleSheet(_btn_default())
        self.btn_export.setFixedHeight(42)
        self.btn_export.clicked.connect(self._export_one)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_export)
        lay.addLayout(btn_row)

    def _on_name_changed(self, txt):
        self._save()
        self.main._update_sidebar_name(self.idx, txt.strip() or f"账号{self.idx+1}")

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

    def _set_status_ui(self, text, color, is_running=False, status_text=""):
        self.lb_status.setText(text)
        self.lb_status.setStyleSheet(f"""
            background: {color}20; color: {color};
            padding: 4px 14px; border-radius: 12px;
            font-size: 13px; font-weight: bold;
        """)
        if status_text:
            self.main._update_sidebar_status(self.idx, is_running, status_text)

    def _confirm_login(self):
        """用户点击「确认已登录」"""
        if self.worker:
            self.worker.confirm_login()
            self.btn_login.setVisible(False)
            self._set_status_ui("登录确认中...", C_ACCENT, True, "登录确认中...")

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
            self.btn_start.setStyleSheet(_btn_danger())
            self._set_status_ui("启动中...", C_ACCENT, True, "启动中...")

    def _on_waiting_login(self, name):
        if name == self.cfg.get("name"):
            self._in_login_wait = True
            self.btn_login.setVisible(True)
            self._set_status_ui("📱 请扫码登录", C_YELLOW, True, "等待扫码登录")

    def _on_status(self, name, s):
        if name == self.cfg.get("name"):
            self._set_status_ui(s, C_ACCENT, True, s)

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
            self.btn_start.setStyleSheet(_btn_primary())
            self.btn_start.setEnabled(True)
            self.btn_login.setVisible(False)
            self._in_login_wait = False
            self._set_status_ui("⏸ 已停止", C_TEXT_SECONDARY, False, "已停止")

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
            self._set_status_ui("⏸ 正在暂停...", C_YELLOW, False, "导出暂停中")
            QApplication.processEvents()
            worker_ref.wait(15000)
            # 手动清理（_on_stopped 被断开，需要自己处理）
            self.worker = None
            self.btn_start.setText("▶ 启动")
            self.btn_start.setStyleSheet(_btn_primary())
            self.btn_start.setEnabled(True)
            self.btn_login.setVisible(False)
            self._in_login_wait = False

        # ── 导出（参照 v42.1 格式）──
        self._set_status_ui("📊 导出中...", "#409EFF", False, "导出中")
        QApplication.processEvents()

        wb = Workbook()
        header_fill = PatternFill(start_color="07C160", end_color="07C160", fill_type="solid")
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
            self._set_status_ui("✅ 导出完成，恢复中...", C_ACCENT, True, "恢复运行中")
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
        self.resize(960, 720)
        self.setMinimumSize(780, 560)
        self.setStyleSheet(STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ═══════════ 左侧边栏 ═══════════
        sidebar_frame = QFrame()
        sidebar_frame.setFixedWidth(220)
        sidebar_frame.setStyleSheet(f"background:{C_SIDEBAR_BG}; border:none;")
        sbl = QVBoxLayout(sidebar_frame)
        sbl.setContentsMargins(0, 0, 0, 0)
        sbl.setSpacing(0)

        sb_title = QLabel("📋 账号列表")
        sb_title.setStyleSheet(f"color:{C_TEXT_SIDEBAR}; font-size:13px; font-weight:bold; padding:16px 16px 12px 16px;")
        sbl.addWidget(sb_title)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color:#444;margin:0 12px;")
        sbl.addWidget(div)

        self.sidebar_items_layout = QVBoxLayout()
        self.sidebar_items_layout.setSpacing(0)
        sbl.addLayout(self.sidebar_items_layout)
        sbl.addStretch()

        btn_add_sidebar = QPushButton("＋ 新增账号")
        btn_add_sidebar.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C_ACCENT};
                border: 1px solid {C_ACCENT}; border-radius: 6px;
                padding: 8px 16px; font-size: 13px; margin: 10px 12px;
            }}
            QPushButton:hover {{ background: {C_ACCENT}; color: white; }}
        """)
        btn_add_sidebar.clicked.connect(self._add_account)
        sbl.addWidget(btn_add_sidebar)

        ver_lbl = QLabel(f"  {VERSION}")
        ver_lbl.setStyleSheet("color:#555;font-size:11px;padding:4px 16px 8px 16px;")
        sbl.addWidget(ver_lbl)

        root.addWidget(sidebar_frame)

        # ═══════════ 右侧主区域 ═══════════
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{C_MAIN_BG};")
        right.addWidget(self.stack, 1)

        # ── 日志区域 ──
        log_frame = QFrame()
        log_frame.setStyleSheet(f"background:{C_CARD_BG};border-top:1px solid {C_BORDER};")
        lfl = QVBoxLayout(log_frame)
        lfl.setContentsMargins(16, 8, 16, 10)
        lfl.setSpacing(4)
        log_hdr = QHBoxLayout()
        log_hdr.addWidget(QLabel("📋 运行日志"))
        log_hdr.addStretch()
        btn_clear_log = QPushButton("清空")
        btn_clear_log.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{C_TEXT_SECONDARY}; border:none; font-size:12px; }}
            QPushButton:hover {{ color:{C_RED}; }}
        """)
        btn_clear_log.clicked.connect(lambda: self.log_box.clear())
        log_hdr.addWidget(btn_clear_log)
        lfl.addLayout(log_hdr)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(140)
        lfl.addWidget(self.log_box)
        right.addWidget(log_frame)

        # ── 底部按钮栏 ──
        btm = QHBoxLayout()
        btm.setContentsMargins(20, 8, 20, 10)
        btm.setSpacing(12)
        btm.addStretch()
        btn_all = QPushButton("▶ 全部启动")
        btn_all.setStyleSheet(_btn_primary())
        btn_all.clicked.connect(lambda: self._all_toggle(True))
        btm.addWidget(btn_all)
        btn_stop = QPushButton("⏹ 全部停止")
        btn_stop.setStyleSheet(_btn_danger())
        btn_stop.clicked.connect(lambda: self._all_toggle(False))
        btm.addWidget(btn_stop)
        right.addLayout(btm)

        root.addLayout(right, 1)

        self._pages = []       # AccountPage 列表
        self._sidebar_items = []  # QWidget (sidebar item) 列表
        self._load_accounts()
        if len(self._pages) == 0:
            QTimer.singleShot(300, self._show_new_account_wizard)

    # ── 侧边栏操作 ──
    def _update_sidebar_name(self, idx, name):
        if 0 <= idx < len(self._sidebar_items):
            self._sidebar_items[idx].set_name(name)

    def _update_sidebar_status(self, idx, is_running, text):
        if 0 <= idx < len(self._sidebar_items):
            self._sidebar_items[idx].set_status(is_running, text)

    def _on_sidebar_click(self, idx):
        if 0 <= idx < len(self._pages):
            # 高亮选中的侧边栏项
            for i, item in enumerate(self._sidebar_items):
                item.set_active(i == idx)
            self.stack.setCurrentIndex(idx)

    def _on_sidebar_remove(self, idx):
        self._close_account(idx)

    # ── 账号管理 ──
    def _load_accounts(self):
        cfg = load_config()
        for i, ac in enumerate(cfg.get("accounts", [])):
            self._add_page(i, ac)

    def _add_page(self, idx, ac):
        page = AccountPage(idx, ac, self)
        name = ac.get("name") or f"账号{idx+1}"
        self._pages.append(page)
        self.stack.addWidget(page)

        # 创建侧边栏项
        item = SidebarItem(idx, name)
        item.clicked.connect(self._on_sidebar_click)
        item.remove_requested.connect(self._on_sidebar_remove)
        self.sidebar_items_layout.addWidget(item)
        self._sidebar_items.append(item)

        # 默认选中第一项
        if idx == 0:
            self._on_sidebar_click(0)

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

    def _close_account(self, index):
        if index < 0 or index >= len(self._pages):
            return
        page = self._pages[index]
        if page.worker and page.worker.isRunning():
            page.worker.stop()
            page.worker.wait(2000)

        cfg = load_config()
        if index < len(cfg.get("accounts", [])):
            cfg["accounts"].pop(index)
            save_config(cfg)

        # 移除侧边栏项
        if index < len(self._sidebar_items):
            item = self._sidebar_items.pop(index)
            self.sidebar_items_layout.removeWidget(item)
            item.deleteLater()

        # 移除页面
        self._pages.pop(index)
        self.stack.removeWidget(page)
        page.deleteLater()

        # 更新索引
        for i, p in enumerate(self._pages):
            p.idx = i
            p._save()
        for i, item in enumerate(self._sidebar_items):
            item.idx = i

        # 选中下一个
        if self._pages:
            self._on_sidebar_click(min(index, len(self._pages) - 1))

    def _all_toggle(self, start):
        for page in self._pages:
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
