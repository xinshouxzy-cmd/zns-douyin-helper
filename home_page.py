# -*- coding: utf-8 -*-
"""
遵农商·抖音AI工作台 — 启动页（门户页）
打开软件首先展示的工具集合首页，卡片式入口：
  - 评论私信助手（多账号私信+评论自动回复）
  - 直播助手（直播评论 AI 实时回复）
  - 更多工具（预留扩展位）
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QGraphicsDropShadowEffect, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPainter, QLinearGradient, QColor

from _version import VERSION


# ── 品牌渐变配色（深色高端风） ─────────────────────
BG_TOP = "#0F2027"
BG_MID = "#203A43"
BG_BOT = "#2C5364"
ACCENT = "#07C160"
ACCENT_DIM = "#05A04F"
TEXT_WHITE = "#FFFFFF"
TEXT_MUTED = "#B8C6CC"
CARD_BG = "rgba(255,255,255,0.06)"
CARD_HOVER = "rgba(255,255,255,0.12)"
CARD_BORDER = "rgba(255,255,255,0.14)"


class ToolCard(QFrame):
    """工具入口卡片"""
    clicked = pyqtSignal()

    def __init__(self, icon, title, desc, tag="", parent=None):
        super().__init__(parent)
        self.setFixedSize(280, 190)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            ToolCard {{
                background: {CARD_BG};
                border: 1px solid {CARD_BORDER};
                border-radius: 16px;
            }}
            ToolCard:hover {{
                background: {CARD_HOVER};
                border: 1px solid {ACCENT};
            }}
        """)
        # 阴影
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(24)
        sh.setOffset(0, 4)
        sh.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(sh)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("PingFang SC", 34))
        lay.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color:{TEXT_WHITE}; font-size:17px; font-weight:bold; border:none; background:transparent;"
        )
        lay.addWidget(title_lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(
            f"color:{TEXT_MUTED}; font-size:12px; border:none; background:transparent;"
        )
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl)
        lay.addStretch()

        if tag:
            row = QHBoxLayout()
            tag_lbl = QLabel(tag)
            tag_lbl.setStyleSheet(f"""
                background: {ACCENT}; color: white; font-size:11px;
                padding: 3px 10px; border-radius: 10px; border:none;
            """)
            row.addWidget(tag_lbl)
            row.addStretch()
            lay.addLayout(row)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


class HomePage(QWidget):
    """启动页：工具集合门户"""
    enter_dm = pyqtSignal()    # 进入 评论私信助手
    enter_live = pyqtSignal()  # 进入 直播助手

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def paintEvent(self, ev):
        """深色渐变背景"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0.0, QColor(BG_TOP))
        grad.setColorAt(0.55, QColor(BG_MID))
        grad.setColorAt(1.0, QColor(BG_BOT))
        p.fillRect(self.rect(), grad)
        super().paintEvent(ev)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 36, 40, 32)
        outer.setSpacing(0)

        outer.addStretch(2)

        # ── 品牌标题 ──
        title = QLabel("遵农商 · 抖音AI工作台")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color:{TEXT_WHITE}; font-size:34px; font-weight:bold; background:transparent;"
        )
        outer.addWidget(title)

        sub = QLabel(f"多账号评论私信 · 直播互动  · 一站式智能客服工具集  {VERSION}")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(
            f"color:{TEXT_MUTED}; font-size:13px; background:transparent;"
        )
        outer.addSpacing(8)
        outer.addWidget(sub)

        outer.addSpacing(44)

        # ── 工具卡片网格 ──
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(24)
        grid.setAlignment(Qt.AlignCenter)

        card_dm = ToolCard("💬", "评论私信助手", "多账号同时运行\n抖音私信 + 评论 自动回复", "已就绪")
        card_live = ToolCard("🎥", "直播助手", "直播评论实时监控\nAI 智能生成回复话术", "已就绪")
        card_more = ToolCard("🧩", "更多工具", "下载器 / 素材库等\n敬请期待", "规划中")

        card_dm.clicked.connect(self.enter_dm.emit)
        card_live.clicked.connect(self.enter_live.emit)

        grid.addWidget(card_dm, 0, 0)
        grid.addWidget(card_live, 0, 1)
        grid.addWidget(card_more, 1, 0, 1, 2)

        outer.addLayout(grid)

        outer.addStretch(3)

        # ── 底部信息 ──
        footer = QLabel("遵义农商银行 出品 · 辛振宇  ·  任何 Windows 电脑即开即用")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(
            f"color:{TEXT_MUTED}; font-size:12px; background:transparent;"
        )
        outer.addWidget(footer)

        self.setStyleSheet(f"HomePage {{ background: transparent; }}")
