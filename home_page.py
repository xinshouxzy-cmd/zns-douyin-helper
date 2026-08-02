# -*- coding: utf-8 -*-
"""
遵农商·抖音AI工作台 — 启动门户页（炫酷版）
动态渐变背景 + 漂浮粒子动画 + 卡片发光悬停 + 渐变品牌标题
"""
import random

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt5.QtGui import (
    QPainter, QPainterPath, QLinearGradient, QRadialGradient, QColor,
    QFont, QPen, QBrush,
)
from PyQt5.QtWidgets import (
    QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QSpacerItem,
    QSizePolicy, QGraphicsDropShadowEffect,
)

C_BG0 = QColor("#0a0e1a")
C_BG1 = QColor("#101a33")
C_ACC1 = QColor("#3d8bff")
C_ACC2 = QColor("#00d2ff")
C_ACC3 = QColor("#9b59ff")
C_TEXT = "#eaf2ff"
C_SUB = "#93a4c8"
C_CARD = QColor(22, 27, 38, 235)
C_BORDER = QColor(38, 48, 64, 200)


class CardWidget(QFrame):
    """发光悬停卡片"""
    clicked = pyqtSignal()

    def __init__(self, icon, title, desc, accent, enabled=True, parent=None):
        super().__init__(parent)
        self._enabled = enabled
        self._accent = accent
        self._hover = False
        self.setFixedSize(250, 180)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ForbiddenCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 14)
        lay.setSpacing(8)
        self.lb_icon = QLabel(icon)
        self.lb_icon.setStyleSheet("background: transparent; font-size: 40px;")
        self.lb_title = QLabel(title)
        ft = QFont()
        ft.setPointSize(16)
        ft.setBold(True)
        self.lb_title.setFont(ft)
        self.lb_title.setStyleSheet("background: transparent;")
        self.lb_desc = QLabel(desc)
        ft2 = QFont()
        ft2.setPointSize(11)
        self.lb_desc.setFont(ft2)
        self.lb_desc.setWordWrap(True)
        self.lb_desc.setStyleSheet("background: transparent;")
        lay.addWidget(self.lb_icon)
        lay.addWidget(self.lb_title)
        lay.addWidget(self.lb_desc)
        lay.addStretch(1)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(24)
        self._shadow.setOffset(0, 6)
        self._shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(self._shadow)
        self._refresh()

    def _refresh(self):
        if self._hover and self._enabled:
            glow = self._accent
            shadow_c = QColor(glow.red(), glow.green(), glow.blue(), 160)
            self._shadow.setColor(shadow_c)
            self._shadow.setBlurRadius(40)
            self.setStyleSheet(
                f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {C_ACC1.name()+'26'}, "
                f"stop:0.5 {C_CARD.name()}, stop:1 {self._accent.name()+'33'}); "
                f"border: 2px solid {self._accent.name()}; border-radius: 16px; }}")
            self.lb_title.setStyleSheet(f"background: transparent; color: {self._accent.name()};")
            self.lb_desc.setStyleSheet("background: transparent; color: " + C_SUB + ";")
            self.lb_icon.setStyleSheet("background: transparent;")
        else:
            self._shadow.setColor(QColor(0, 0, 0, 120))
            self._shadow.setBlurRadius(24)
            self.setStyleSheet(
                f"QFrame {{ background: {C_CARD.name()}; border: 1px solid {C_BORDER.name()}; border-radius: 16px; }}")
            self.lb_title.setStyleSheet("background: transparent; color: " + C_TEXT + ";")
            self.lb_desc.setStyleSheet("background: transparent; color: " + C_SUB + ";")
            self.lb_icon.setStyleSheet("background: transparent;")

    def enterEvent(self, e):
        if self._enabled:
            self._hover = True
            self._refresh()

    def leaveEvent(self, e):
        self._hover = False
        self._refresh()

    def mousePressEvent(self, e):
        if self._enabled and e.button() == Qt.LeftButton:
            self.clicked.emit()


class HomePage(QWidget):
    """启动门户页：品牌标题 + 工具入口卡片"""
    enter_dm = pyqtSignal()
    enter_live = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0
        self.version = ""
        self.particles = self._init_particles()
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)  # ~30fps

    # ── 粒子系统 ──
    def _init_particles(self):
        pts = []
        for _ in range(46):
            pts.append({
                "x": random.random(), "y": random.random(),
                "r": random.uniform(1.0, 2.6),
                "vy": random.uniform(0.0006, 0.0022),
                "vx": random.uniform(-0.0004, 0.0004),
                "a": random.uniform(0.08, 0.5),
                "c": random.choice([C_ACC1, C_ACC2, C_ACC3]),
            })
        return pts

    def _tick(self):
        self._t += 1
        w, h = max(self.width(), 1), max(self.height(), 1)
        for p in self.particles:
            p["y"] -= p["vy"]
            p["x"] += p["vx"]
            if p["y"] < -0.02:
                p["y"] = 1.02
                p["x"] = random.random()
            if p["x"] < -0.02:
                p["x"] = 1.02
            if p["x"] > 1.02:
                p["x"] = -0.02
        self.update()

    # ── 自绘背景 ──
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # 动态渐变背景（颜色随时间缓慢流动）
        t = self._t / 300.0
        shift = 0.15 * (t % 1.0)
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0.0, QColor(int(10 + 8 * t % 1 * 6), 14, 26))
        g.setColorAt(0.35 + shift * 0.1, QColor(16, 26, 51))
        g.setColorAt(1.0, QColor(8, 12, 24))
        p.fillRect(self.rect(), g)
        # 右上角青色光晕
        rg = QRadialGradient(w * 0.92, h * 0.08, min(w, h) * 0.5)
        rg.setColorAt(0.0, QColor(C_ACC2.red(), C_ACC2.green(), C_ACC2.blue(), 26))
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(rg))
        # 左下角紫色光晕
        rg2 = QRadialGradient(w * 0.06, h * 0.92, min(w, h) * 0.55)
        rg2.setColorAt(0.0, QColor(C_ACC3.red(), C_ACC3.green(), C_ACC3.blue(), 22))
        rg2.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(rg2))
        # 漂浮粒子
        for pt in self.particles:
            col = pt["c"]
            col.setAlphaF(pt["a"])
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QRectF(pt["x"] * w, pt["y"] * h, pt["r"] * 2, pt["r"] * 2))
        p.end()

    # ── UI ──
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addSpacerItem(QSpacerItem(1, 60, QSizePolicy.Minimum, QSizePolicy.Expanding))
        # 品牌标题
        title_box = QVBoxLayout()
        title_box.setSpacing(6)
        self.lb_title = QLabel()
        self.lb_title.setAlignment(Qt.AlignCenter)
        f = QFont()
        f.setPointSize(30)
        f.setBold(True)
        self.lb_title.setFont(f)
        self.lb_title.setStyleSheet("background: transparent; color: " + C_TEXT + ";")
        self.lb_sub = QLabel("抖音新媒体运营 · AI 数字营销一站式工作台")
        fs = QFont()
        fs.setPointSize(13)
        self.lb_sub.setFont(fs)
        self.lb_sub.setAlignment(Qt.AlignCenter)
        self.lb_sub.setStyleSheet("background: transparent; color: " + C_SUB + ";")
        title_box.addWidget(self.lb_title)
        title_box.addWidget(self.lb_sub)
        outer.addLayout(title_box)
        outer.addSpacing(10)
        # 渐变装饰线（中间亮两边淡）
        line = QFrame()
        line.setFixedHeight(3)
        line.setStyleSheet("background: transparent;")
        outer.addWidget(line)
        outer.addSpacing(28)
        # 工具卡片
        cards = QHBoxLayout()
        cards.setSpacing(26)
        cards.addStretch(1)
        c_dm = CardWidget("💬", "评论私信助手", "抖音评论 + 私信多账号自动回复\nAI 话术 · 多账号并行", QColor("#3d8bff"))
        c_dm.clicked.connect(self.enter_dm.emit)
        cards.addWidget(c_dm)
        c_live = CardWidget("🎥", "直播助手", "评论关键词触发场景特效\n知识库问答 · 自动播报", QColor("#00d2ff"))
        c_live.clicked.connect(self.enter_live.emit)
        cards.addWidget(c_live)
        c_more = CardWidget("🔧", "更多工具", "更多能力持续集成中\n敬请期待", QColor("#9b59ff"), enabled=False)
        cards.addWidget(c_more)
        cards.addStretch(1)
        outer.addLayout(cards)
        outer.addSpacerItem(QSpacerItem(1, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        # 底部低调版权
        self.lb_footer = QLabel()
        ff = QFont()
        ff.setPointSize(10)
        self.lb_footer.setFont(ff)
        self.lb_footer.setAlignment(Qt.AlignCenter)
        self.lb_footer.setStyleSheet("background: transparent; color: #5b6b8c;")
        outer.addWidget(self.lb_footer)
        outer.addSpacing(20)

    def set_version(self, v):
        self.version = v
        self.lb_title.setText("遵农商 · 抖音AI工作台")
        self.lb_footer.setText(f"© 2026 遵义农商银行 · AI 数字营销工作台  {v}")
