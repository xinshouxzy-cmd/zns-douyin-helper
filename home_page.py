# -*- coding: utf-8 -*-
"""
遵农商·抖音AI工作台 — 启动门户页（高级炫酷版）
渐变品牌标题 + 星云粒子连线 + 流动光带 + 卡片悬停发光脉冲
"""
import random, math

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt5.QtGui import (
    QPainter, QLinearGradient, QRadialGradient, QColor,
    QFont, QPen, QBrush,
)
from PyQt5.QtWidgets import (
    QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QSpacerItem,
    QSizePolicy, QGraphicsDropShadowEffect,
)

C_BG0 = QColor("#0a0e1a")
C_ACC1 = QColor("#3d8bff")
C_ACC2 = QColor("#00d2ff")
C_ACC3 = QColor("#9b59ff")
C_GREEN = QColor("#2ecc71")
C_TEXT = "#eaf2ff"
C_SUB = "#93a4c8"
C_CARD = QColor(22, 27, 38, 235)
C_BORDER = QColor(38, 48, 64, 200)


class GradientTitle(QLabel):
    """渐变品牌标题（青→蓝→紫，随角度流动）"""

    def __init__(self, text, point_size=32, parent=None):
        super().__init__(text, parent)
        f = QFont()
        f.setPointSize(point_size)
        f.setBold(True)
        self.setFont(f)
        self.setAlignment(Qt.AlignCenter)
        self._phase = 0.0
        tm = QTimer(self)
        tm.timeout.connect(self._shift)
        tm.start(60)

    def _shift(self):
        self._phase += 0.02
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w = max(self.width(), 1)
        g = QLinearGradient(self._phase * 60 - 80, 0, self._phase * 60 + w + 80, 0)
        g.setColorAt(0.0, QColor("#5a9dff"))
        g.setColorAt(0.45, QColor("#00d2ff"))
        g.setColorAt(1.0, QColor("#9b59ff"))
        p.setPen(QPen(QBrush(g), 1))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
        p.end()


class CardWidget(QFrame):
    """发光悬停卡片（hover 时图标脉冲 + 发光增强 + 渐变描边）"""
    clicked = pyqtSignal()

    def __init__(self, icon, title, desc, accent, enabled=True, parent=None):
        super().__init__(parent)
        self._enabled = enabled
        self._accent = accent
        self._hover = False
        self._pulse = 0.0
        self._base_icon_size = 42
        self.setFixedSize(256, 190)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ForbiddenCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 14)
        lay.setSpacing(8)
        self.lb_icon = QLabel(icon)
        self.lb_icon.setStyleSheet("background: transparent; font-size: 42px;")
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
        # 底部渐变装饰条
        self.bar = QFrame()
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"stop:0 {accent.name()}, stop:0.5 {QColor('#00d2ff').name()}, stop:1 {accent.name()});")
        lay.addWidget(self.bar)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(24)
        self._shadow.setOffset(0, 6)
        self._shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(self._shadow)
        self._refresh()
        # hover 脉冲计时器
        self._ptimer = QTimer(self)
        self._ptimer.timeout.connect(self._pulse_tick)
        self._ptimer.start(33)

    def _pulse_tick(self):
        if self._hover and self._enabled:
            self._pulse += 0.15
            size = self._base_icon_size + int(5 * math.sin(self._pulse))
            self.lb_icon.setStyleSheet(
                f"background: transparent; font-size: {size}px; color: {self._accent.name()};")
            self.update()

    def _refresh(self):
        if self._hover and self._enabled:
            glow = self._accent
            self._shadow.setColor(QColor(glow.red(), glow.green(), glow.blue(), 180))
            self._shadow.setBlurRadius(46)
            self.setStyleSheet(
                f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, "
                f"stop:0 {QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 46).name(QColor.HexArgb)}, "
                f"stop:0.5 {C_CARD.name()}, "
                f"stop:1 {QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 60).name(QColor.HexArgb)}); "
                f"border: 2px solid {self._accent.name()}; border-radius: 18px; }}")
            self.lb_title.setStyleSheet(f"background: transparent; color: {self._accent.name()};")
            self.lb_desc.setStyleSheet("background: transparent; color: " + C_SUB + ";")
            self.bar.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
                f"stop:0 {self._accent.name()}, stop:0.5 {QColor('#00d2ff').name()}, stop:1 {self._accent.name()});")
        else:
            self._pulse = 0.0
            self._shadow.setColor(QColor(0, 0, 0, 120))
            self._shadow.setBlurRadius(24)
            self.setStyleSheet(
                f"QFrame {{ background: {C_CARD.name()}; border: 1px solid {C_BORDER.name()}; border-radius: 18px; }}")
            self.lb_title.setStyleSheet("background: transparent; color: " + C_TEXT + ";")
            self.lb_desc.setStyleSheet("background: transparent; color: " + C_SUB + ";")
            self.lb_icon.setStyleSheet("background: transparent; font-size: 42px;")
            self.bar.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
                f"stop:0 {self._accent.name()}, stop:0.5 {QColor('#00d2ff').name()}, stop:1 {self._accent.name()});")

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
    """启动门户页：品牌标题 + 三个工具入口卡片"""
    enter_dm = pyqtSignal()
    enter_live = pyqtSignal()
    enter_downloader = pyqtSignal()

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
        for _ in range(52):
            pts.append({
                "x": random.random(), "y": random.random(),
                "r": random.uniform(1.0, 2.6),
                "vy": random.uniform(0.0006, 0.0022),
                "vx": random.uniform(-0.0004, 0.0004),
                "a": random.uniform(0.08, 0.5),
                "c": random.choice([C_ACC1, C_ACC2, C_ACC3, C_GREEN]),
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
        t = self._t / 300.0
        # 动态渐变背景
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0.0, QColor(10, 14, 26))
        g.setColorAt(0.5, QColor(16, 26, 51))
        g.setColorAt(1.0, QColor(8, 12, 24))
        p.fillRect(self.rect(), g)
        # 右上角青色光晕
        rg = QRadialGradient(w * 0.92, h * 0.08, min(w, h) * 0.55)
        rg.setColorAt(0.0, QColor(C_ACC2.red(), C_ACC2.green(), C_ACC2.blue(), 30))
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(rg))
        # 左下角紫色光晕
        rg2 = QRadialGradient(w * 0.06, h * 0.92, min(w, h) * 0.6)
        rg2.setColorAt(0.0, QColor(C_ACC3.red(), C_ACC3.green(), C_ACC3.blue(), 26))
        rg2.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(rg2))
        # 中部蓝色氛围光
        rg3 = QRadialGradient(w * 0.5, h * 0.42, min(w, h) * 0.7)
        rg3.setColorAt(0.0, QColor(C_ACC1.red(), C_ACC1.green(), C_ACC1.blue(), 14))
        rg3.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(rg3))
        # 斜向流动光带（两条，缓慢漂移）
        for k in range(2):
            tt = (t * 0.55 + k * 0.47) % 1.0
            x0 = -0.25 * w + tt * 1.5 * w
            y0 = h * (0.22 + 0.35 * k + 0.18 * math.sin(t * 1.3 + k * 2.1))
            lg = QLinearGradient(x0 - 240, y0, x0 + 240, y0)
            col = C_ACC2 if k == 0 else C_ACC3
            lg.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(), 0))
            lg.setColorAt(0.5, QColor(col.red(), col.green(), col.blue(), 36))
            lg.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(lg)
            p.drawEllipse(QRectF(x0 - 250, y0 - 7, 500, 14))
        # 粒子 + 连线星云
        pts = self.particles
        n = len(pts)
        xs = [pt["x"] * w for pt in pts]
        ys = [pt["y"] * h for pt in pts]
        link_r = min(w, h) * 0.16
        for i in range(n):
            for j in range(i + 1, n):
                dx = xs[i] - xs[j]
                dy = ys[i] - ys[j]
                d2 = dx * dx + dy * dy
                if d2 < link_r * link_r:
                    d = math.sqrt(d2)
                    alpha = int(70 * (1 - d / link_r))
                    p.setPen(QPen(QColor(120, 170, 255, alpha), 1))
                    p.drawLine(xs[i], ys[i], xs[j], ys[j])
        # 粒子
        for pt in pts:
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
        outer.addSpacerItem(QSpacerItem(1, 54, QSizePolicy.Minimum, QSizePolicy.Expanding))
        # 品牌渐变标题
        self.lb_title = GradientTitle("遵农商 · 抖音AI工作台", 32)
        outer.addWidget(self.lb_title)
        outer.addSpacing(4)
        # 副标题
        self.lb_sub = QLabel("抖音新媒体运营 · AI 数字营销一站式工作台")
        fs = QFont()
        fs.setPointSize(13)
        self.lb_sub.setFont(fs)
        self.lb_sub.setAlignment(Qt.AlignCenter)
        self.lb_sub.setStyleSheet("background: transparent; color: " + C_SUB + "; letter-spacing: 2px;")
        outer.addWidget(self.lb_sub)
        outer.addSpacing(14)
        # 品牌发光装饰线
        line = QFrame()
        line.setFixedSize(260, 3)
        line.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 transparent, stop:0.5 #00d2ff, stop:1 transparent);")
        hline = QHBoxLayout()
        hline.addStretch(1)
        hline.addWidget(line)
        hline.addStretch(1)
        outer.addLayout(hline)
        outer.addSpacing(30)
        # 工具卡片（三个）
        cards = QHBoxLayout()
        cards.setSpacing(26)
        cards.addStretch(1)
        c_dm = CardWidget("💬", "评论私信助手", "抖音评论 + 私信多账号自动回复\nAI 话术 · 多账号并行", QColor("#3d8bff"))
        c_dm.clicked.connect(self.enter_dm.emit)
        cards.addWidget(c_dm)
        c_live = CardWidget("🎥", "直播助手", "评论关键词触发场景特效\n知识库问答 · 自动播报", QColor("#00d2ff"))
        c_live.clicked.connect(self.enter_live.emit)
        cards.addWidget(c_live)
        c_dl = CardWidget("📥", "无水印下载器", "粘贴抖音链接解析无水印原视频\n高清下载 · 即贴即下", QColor("#2ecc71"))
        c_dl.clicked.connect(self.enter_downloader.emit)
        cards.addWidget(c_dl)
        cards.addStretch(1)
        outer.addLayout(cards)
        outer.addSpacerItem(QSpacerItem(1, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        # 底部版本徽章
        self.lb_footer = QLabel()
        ff = QFont()
        ff.setPointSize(10)
        self.lb_footer.setFont(ff)
        self.lb_footer.setAlignment(Qt.AlignCenter)
        self.lb_footer.setStyleSheet(
            "background: rgba(22,27,38,140); color: #5b6b8c; "
            "border: 1px solid rgba(38,48,64,160); border-radius: 12px; padding: 4px 16px;")
        outer.addWidget(self.lb_footer)
        outer.addSpacing(20)

    def set_version(self, v):
        self.version = v
        self.lb_footer.setText(f"© 2026 遵义农商银行 · AI 数字营销工作台   {v}")
