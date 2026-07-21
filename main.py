# -*- coding: utf-8 -*-
"""
遵农商·抖音客服助手 v1.0 — GUI 界面
"""
import os, sys, json, csv
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QTextEdit, QLineEdit,
    QCheckBox, QGroupBox, QFileDialog, QMessageBox, QFrame,
    QScrollArea, QGridLayout
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QPalette, QTextCursor

from worker import AccountWorker, BASE_DIR

# ── 配色 ──────────────────────────────────────────
C_DARK  = "#1B2A1E"
C_PRIM  = "#2D7A3E"
C_GOLD  = "#D4AF37"
C_BG    = "#212922"
C_TEXT  = "#E8ECDF"
C_LOG   = "#161C17"
C_LINK  = "#5CB8FF"
C_SUCC  = "#4CAF50"
C_WARN  = "#FFC107"
C_ERR   = "#F44336"

APP_TITLE = "遵农商·抖音客服助手 v1.0"

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"accounts": [], "settings": {}}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── 样式 ──────────────────────────────────────────
def btn_style(color=C_PRIM):
    return f"""
        QPushButton {{
            background: {color}; color: white; border: none;
            border-radius: 5px; padding: 6px 16px; font-size: 12px; font-weight: bold;
        }}
        QPushButton:hover {{ background: #3D9A50; }}
        QPushButton:pressed {{ background: #1E5A2A; }}
        QPushButton:disabled {{ background: #444; color: #777; }}
    """


def accent_btn():
    return f"""
        QPushButton {{
            background: {C_GOLD}; color: {C_DARK}; border: none;
            border-radius: 5px; padding: 6px 16px; font-size: 12px; font-weight: bold;
        }}
        QPushButton:hover {{ background: #E6C84F; }}
        QPushButton:pressed {{ background: #B8960F; }}
        QPushButton:disabled {{ background: #444; color: #777; }}
    """


def danger_btn():
    return f"""
        QPushButton {{
            background: {C_ERR}; color: white; border: none;
            border-radius: 5px; padding: 6px 16px; font-size: 12px; font-weight: bold;
        }}
        QPushButton:hover {{ background: #E57373; }}
        QPushButton:pressed {{ background: #C62828; }}
        QPushButton:disabled {{ background: #444; color: #777; }}
    """


def input_style():
    return f"""
        QLineEdit, QTextEdit {{
            background: {C_LOG}; color: {C_TEXT};
            border: 1px solid #3A4A3E; border-radius: 4px;
            padding: 6px 8px; font-size: 12px;
        }}
        QLineEdit:focus, QTextEdit:focus {{ border-color: {C_PRIM}; }}
    """


# ── 一个账号的控件 ────────────────────────────────
class AccountWidget(QWidget):
    def __init__(self, idx, cfg, main_win):
        super().__init__()
        self.idx = idx
        self.cfg = cfg
        self.main = main_win
        self.worker = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # ── 标题行 ──
        hr = QHBoxLayout()
        self.cb_on = QCheckBox("启用")
        self.cb_on.setChecked(self.cfg.get("enabled", True))
        self.cb_on.setStyleSheet(f"color:{C_TEXT};font-weight:bold;")
        self.cb_on.toggled.connect(self._save)

        self.lb_name = QLabel(f"📱  {self.cfg.get('name','未命名')}")
        self.lb_name.setStyleSheet(f"color:{C_GOLD};font-size:15px;font-weight:bold;")

        self.lb_status = QLabel("⏸ 未启动")
        self.lb_status.setStyleSheet(f"color:#888;font-size:12px;")

        self.btn_start = QPushButton("▶ 启动")
        self.btn_start.setStyleSheet(btn_style())
        self.btn_start.clicked.connect(self._toggle)

        hr.addWidget(self.cb_on)
        hr.addWidget(self.lb_name)
        hr.addStretch()
        hr.addWidget(self.lb_status)
        hr.addWidget(self.btn_start)
        lay.addLayout(hr)

        # ── 私信配置 ──
        g1 = QGroupBox("💬 私信自动回复")
        g1.setStyleSheet(f"""
            QGroupBox {{ color:{C_GOLD}; font-weight:bold; border:1px solid #3A4A3E;
                border-radius:6px; margin-top:10px; padding-top:14px; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 6px; }}
        """)
        g1l = QVBoxLayout(g1)
        self.cb_pm = QCheckBox("开启私信回复")
        self.cb_pm.setChecked(self.cfg.get("pm_enabled", True))
        self.cb_pm.setStyleSheet(f"color:{C_TEXT};")
        self.cb_pm.toggled.connect(self._save)

        self.le_pm = QLineEdit()
        self.le_pm.setText(self.cfg.get("pm_reply", ""))
        self.le_pm.setPlaceholderText("输入私信回复话术...")
        self.le_pm.setStyleSheet(input_style())
        self.le_pm.textChanged.connect(self._save)

        g1l.addWidget(self.cb_pm)
        g1l.addWidget(QLabel("回复内容:"))
        g1l.addWidget(self.le_pm)
        lay.addWidget(g1)

        # ── 评论配置 ──
        g2 = QGroupBox("📝 评论自动回复")
        g2.setStyleSheet(f"""
            QGroupBox {{ color:{C_GOLD}; font-weight:bold; border:1px solid #3A4A3E;
                border-radius:6px; margin-top:10px; padding-top:14px; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 6px; }}
        """)
        g2l = QVBoxLayout(g2)
        self.cb_cmt = QCheckBox("开启评论回复")
        self.cb_cmt.setChecked(self.cfg.get("comment_enabled", True))
        self.cb_cmt.setStyleSheet(f"color:{C_TEXT};")
        self.cb_cmt.toggled.connect(self._save)

        self.le_cmt = QLineEdit()
        self.le_cmt.setText(self.cfg.get("comment_reply", ""))
        self.le_cmt.setPlaceholderText("输入评论回复话术...")
        self.le_cmt.setStyleSheet(input_style())
        self.le_cmt.textChanged.connect(self._save)

        # 坐标文件选择
        cfr = QHBoxLayout()
        self.le_coords = QLineEdit()
        self.le_coords.setText(self.cfg.get("comment_coords_file", ""))
        self.le_coords.setPlaceholderText("坐标文件路径...")
        self.le_coords.setStyleSheet(input_style())
        self.le_coords.textChanged.connect(self._save)
        btn_cf = QPushButton("📁 选择")
        btn_cf.setStyleSheet(btn_style())
        btn_cf.clicked.connect(self._sel_coords)
        cfr.addWidget(QLabel("坐标文件:"))
        cfr.addWidget(self.le_coords)
        cfr.addWidget(btn_cf)

        g2l.addWidget(self.cb_cmt)
        g2l.addWidget(QLabel("回复内容:"))
        g2l.addWidget(self.le_cmt)
        g2l.addLayout(cfr)
        lay.addWidget(g2)

    def _sel_coords(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择评论坐标文件", BASE_DIR, "JSON (*.json)")
        if f:
            self.le_coords.setText(os.path.relpath(f, BASE_DIR) if f.startswith(BASE_DIR) else f)
            self._save()

    def _save(self):
        self.cfg["enabled"] = self.cb_on.isChecked()
        self.cfg["pm_enabled"] = self.cb_pm.isChecked()
        self.cfg["pm_reply"] = self.le_pm.text()
        self.cfg["comment_enabled"] = self.cb_cmt.isChecked()
        self.cfg["comment_reply"] = self.le_cmt.text()
        self.cfg["comment_coords_file"] = self.le_coords.text()
        config = load_config()
        if self.idx < len(config["accounts"]):
            config["accounts"][self.idx] = self.cfg
            save_config(config)

    def _toggle(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.btn_start.setText("⏳ 停止中...")
            self.btn_start.setEnabled(False)
        else:
            # 检查坐标
            if self.cfg.get("comment_enabled") and not self.le_coords.text():
                QMessageBox.warning(self, "提示", "评论回复已开启但未配置坐标文件！\n评论功能将跳过。")

            cfg = dict(self.cfg)
            cfg["pm_reply"] = self.le_pm.text() or "你好，请问需要办理什么业务？"
            cfg["comment_reply"] = self.le_cmt.text() or "感谢您的关注与支持！"

            self.worker = AccountWorker(cfg)
            self.worker.log.connect(self.main.append_log)
            self.worker.status.connect(self._on_status)
            self.worker.stopped.connect(self._on_stopped)
            self.worker.start()
            self.btn_start.setText("⏹ 停止")
            self.btn_start.setStyleSheet(danger_btn())
            self.lb_status.setStyleSheet(f"color:{C_PRIM};font-size:12px;")

    def _on_status(self, name, s):
        if name == self.cfg.get("name"):
            self.lb_status.setText(s)

    def _on_stopped(self, name):
        if name == self.cfg.get("name"):
            self.worker = None
            self.btn_start.setText("▶ 启动")
            self.btn_start.setStyleSheet(btn_style())
            self.btn_start.setEnabled(True)
            self.lb_status.setText("⏸ 已停止")
            self.lb_status.setStyleSheet("color:#888;font-size:12px;")


# ── 主窗口 ────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(900, 700)

        # 暗色主题
        self.setStyleSheet(f"""
            QMainWindow {{ background: {C_DARK}; }}
            QWidget {{ color: {C_TEXT}; font-size: 12px; }}
            QLabel {{ color: {C_TEXT}; }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: {C_DARK}; width: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #3A4A3E; border-radius: 4px; min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(14, 10, 14, 10)
        ml.setSpacing(8)

        # ── 顶部标题 ──
        title = QLabel(f"🏦  {APP_TITLE}")
        title.setStyleSheet(f"color:{C_GOLD};font-size:20px;font-weight:bold;padding:4px 0;")
        ml.addWidget(title)

        # ── 设置行 ──
        srow = QHBoxLayout()
        srow.addWidget(QLabel("私信间隔(秒):"))
        self.le_pm_int = QLineEdit("8")
        self.le_pm_int.setFixedWidth(50)
        self.le_pm_int.setStyleSheet(input_style())
        srow.addWidget(self.le_pm_int)
        srow.addWidget(QLabel("评论间隔(秒):"))
        self.le_cmt_int = QLineEdit("30")
        self.le_cmt_int.setFixedWidth(50)
        self.le_cmt_int.setStyleSheet(input_style())
        srow.addWidget(self.le_cmt_int)
        srow.addStretch()

        self.btn_add = QPushButton("➕ 添加账号")
        self.btn_add.setStyleSheet(accent_btn())
        self.btn_add.clicked.connect(self._add_account)
        srow.addWidget(self.btn_add)
        ml.addLayout(srow)

        # ── 账号列表滚动区 ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.accts_w = QWidget()
        self.accts_l = QVBoxLayout(self.accts_w)
        self.accts_l.setSpacing(10)
        self.accts_l.setContentsMargins(0, 0, 0, 0)
        self.accts_l.addStretch()
        self.scroll.setWidget(self.accts_w)
        ml.addWidget(self.scroll, 1)

        # ── 日志区 ──
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        self.log_box.setStyleSheet(f"""
            QTextEdit {{
                background: {C_LOG}; color: {C_TEXT};
                border: 1px solid #3A4A3E; border-radius: 4px;
                padding: 6px; font-size: 11px; font-family: "Consolas","Menlo",monospace;
            }}
        """)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("📋 运行日志"))
        hdr.addStretch()
        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.setStyleSheet(btn_style())
        self.btn_clear_log.clicked.connect(lambda: self.log_box.clear())
        hdr.addWidget(self.btn_clear_log)
        ml.addLayout(hdr)
        ml.addWidget(self.log_box)

        # ── 底部按钮 ──
        br = QHBoxLayout()
        br.addStretch()
        btn_all = QPushButton("▶ 全部启动")
        btn_all.setStyleSheet(btn_style())
        btn_all.clicked.connect(lambda: self._all_toggle(True))
        br.addWidget(btn_all)
        btn_stop_all = QPushButton("⏹ 全部停止")
        btn_stop_all.setStyleSheet(danger_btn())
        btn_stop_all.clicked.connect(lambda: self._all_toggle(False))
        br.addWidget(btn_stop_all)
        btn_export = QPushButton("📊 导出报表")
        btn_export.setStyleSheet(accent_btn())
        btn_export.clicked.connect(self._export_csv)
        br.addWidget(btn_export)
        ml.addLayout(br)

        self._widgets = []  # AccountWidget 列表
        self._load_accounts()

    # ── 账号管理 ──
    def _load_accounts(self):
        cfg = load_config()
        for i, ac in enumerate(cfg.get("accounts", [])):
            self._add_widget(i, ac)

    def _add_widget(self, idx, ac):
        w = AccountWidget(idx, ac, self)
        # 插入到 stretch 之前
        self.accts_l.insertWidget(self.accts_l.count() - 1, w)
        self._widgets.append(w)

    def _add_account(self):
        cfg = load_config()
        idx = len(cfg["accounts"])
        new_ac = {
            "name": f"账号_{idx+1}",
            "enabled": True,
            "pm_enabled": True,
            "pm_reply": "你好，请问需要办理什么业务？",
            "comment_enabled": True,
            "comment_reply": "感谢您的关注与支持！",
            "comment_coords_file": "",
            "chrome_profile": f"chrome_profiles/account_{idx+1}"
        }
        cfg["accounts"].append(new_ac)
        save_config(cfg)
        self._add_widget(idx, new_ac)

    def _all_toggle(self, start):
        for w in self._widgets:
            running = w.worker and w.worker.isRunning()
            if start and not running:
                w._toggle()
            elif not start and running:
                w._toggle()

    def _export_csv(self):
        f, _ = QFileDialog.getSaveFileName(self, "导出报表", f"抖应报表_{datetime.now().strftime('%m%d')}.csv", "CSV (*.csv)")
        if not f:
            return
        with open(f, "w", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            w.writerow(["账号", "启动", "私信回复", "评论回复", "私信累计", "评论累计", "最后更新"])
            for wd in self._widgets:
                running = wd.worker and wd.worker.isRunning()
                w.writerow([
                    wd.cfg.get("name", ""),
                    "是" if running else "否",
                    "开" if wd.cb_pm.isChecked() else "关",
                    "开" if wd.cb_cmt.isChecked() else "关",
                    wd.worker._pm_n if wd.worker else 0,
                    wd.worker._cmt_n if wd.worker else 0,
                    datetime.now().strftime("%H:%M:%S")
                ])
        QMessageBox.information(self, "导出完成", f"已导出至:\n{f}")

    # ── 日志 ──
    def append_log(self, name, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        if msg.startswith("[green]"):
            color = C_SUCC
            text = msg[7:]
        elif msg.startswith("[#FFC107]"):
            color = C_WARN
            text = msg[8:]
        elif msg.startswith("[red]"):
            color = C_ERR
            text = msg[5:]
        elif msg.startswith("[white]"):
            color = C_TEXT
            text = msg[7:]
        else:
            color = C_TEXT
            text = msg

        html = f'<span style="color:#888;">{ts}</span> <span style="color:{C_GOLD};">[{name}]</span> <span style="color:{color};">{text}</span>'
        self.log_box.append(html)
        # 自动滚动到底部
        self.log_box.moveCursor(QTextCursor.End)

        # 限制行数
        if self.log_box.document().blockCount() > 500:
            self.log_box.clear()
            self.log_box.append('<span style="color:#888;">[日志已自动清理]</span>')


# ═══════════════════════════════════════════════════
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    # macOS 适配
    if sys.platform == "darwin":
        app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
