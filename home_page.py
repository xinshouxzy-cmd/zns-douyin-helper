# -*- coding: utf-8 -*-
"""
遵农商·智媒工作台 — 启动门户页（质感版 v2）
渐变品牌标题 + 柔和光晕 + 星云粒子 + 玻璃拟态卡片（平滑过渡/上浮/辉光）
设计语言：深空蓝底 + 蓝青科技色 + 暖金银行点缀，避免"AI 生成感"，追求品牌质感。
"""
import os, random, math

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF
from PyQt5.QtGui import (
    QPainter, QLinearGradient, QRadialGradient, QColor,
    QFont, QPen, QBrush, QPixmap,
)
from PyQt5.QtWidgets import (
    QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QSpacerItem,
    QSizePolicy, QGraphicsDropShadowEffect,
)
from worker import assets_path

C_BG0 = QColor("#070b14")
C_ACC1 = QColor("#4d94ff")
C_ACC2 = QColor("#22d3ee")
C_ACC3 = QColor("#a78bfa")
C_GREEN = QColor("#34d399")
C_GOLD = QColor("#d8b45a")
C_TEXT = "#eaf2ff"
C_SUB = "#8fa1c4"
C_CARD = QColor(21, 27, 40, 230)
C_BORDER = QColor(52, 66, 92, 210)


class GradientTitle(QLabel):
    """品牌标题：多色渐变 + 柔和光晕，流动节奏放缓更显沉稳"""

    def __init__(self, text, point_size=34, parent=None):
        super().__init__(text, parent)
        f = QFont()
        f.setPointSize(point_size)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        self.setFont(f)
        self.setAlignment(Qt.AlignCenter)
        self._phase = 0.0
        tm = QTimer(self)
        tm.timeout.connect(self._shift)
        tm.start(80)

    def _shift(self):
        self._phase += 0.012
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w = max(self.width(), 1)
        # 主渐变：深蓝 → 亮蓝 → 青 → 紫（暖金只做点缀不抢科技感）
        g = QLinearGradient(self._phase * 80 - 120, 0, self._phase * 80 + w + 120, 0)
        g.setColorAt(0.0, QColor("#7fb2ff"))
        g.setColorAt(0.30, QColor("#4d94ff"))
        g.setColorAt(0.55, QColor("#22d3ee"))
        g.setColorAt(0.85, QColor("#8b9dff"))
        g.setColorAt(1.0, QColor("#a78bfa"))
        # 光晕：多层低透明偏移绘制
        glow = QColor(90, 170, 255, 34)
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, 1), (1, -1)]:
            r = self.rect().translated(dx, dy)
            p.setPen(QPen(glow))
            p.setFont(self.font())
            p.drawText(r, Qt.AlignCenter, self.text())
        p.setPen(QPen(QBrush(g), 1))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
        p.end()


class CardWidget(QFrame):
    """玻璃拟态卡片：默认低存在感，悬停平滑过渡到上浮 + 辉光 + 渐变描边"""
    clicked = pyqtSignal()

    def __init__(self, icon, title, desc, accent, enabled=True, parent=None, icon_pix=None):
        super().__init__(parent)
        self._enabled = enabled
        self._accent = QColor(accent) if not isinstance(accent, QColor) else accent
        self._hover = 0.0          # 0.0 ~ 1.0 平滑动画进度
        self._hovering = False
        self._pulse = 0.0
        self._base_icon_size = 40
        self.setFixedSize(268, 196)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ForbiddenCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(7)
        # 图标（带同色柔光）
        self.lb_icon = QLabel(icon)
        self.lb_icon.setAlignment(Qt.AlignCenter)
        self.lb_icon.setFixedHeight(52)
        if icon_pix is not None and not icon_pix.isNull():
            self.lb_icon.setPixmap(
                icon_pix.scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.lb_icon.setStyleSheet("background: transparent;")
        else:
            self.lb_icon.setStyleSheet("background: transparent; font-size: 40px;")
        icon_glow = QGraphicsDropShadowEffect(self)
        icon_glow.setBlurRadius(22)
        icon_glow.setOffset(0, 0)
        icon_glow.setColor(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 150))
        self.lb_icon.setGraphicsEffect(icon_glow)
        lay.addWidget(self.lb_icon)
        self.lb_title = QLabel(title)
        ft = QFont()
        ft.setPointSize(15)
        ft.setBold(True)
        self.lb_title.setFont(ft)
        self.lb_title.setAlignment(Qt.AlignCenter)
        self.lb_title.setStyleSheet("background: transparent;")
        lay.addWidget(self.lb_title)
        self.lb_desc = QLabel(desc)
        ft2 = QFont()
        ft2.setPointSize(10)
        ft2.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
        self.lb_desc.setFont(ft2)
        self.lb_desc.setWordWrap(True)
        self.lb_desc.setAlignment(Qt.AlignCenter)
        self.lb_desc.setStyleSheet("background: transparent;")
        lay.addWidget(self.lb_desc)
        lay.addStretch(1)
        # 底部渐变装饰条
        self.bar = QFrame()
        self.bar.setFixedHeight(3)
        lay.addWidget(self.bar)
        self._shadow = QGraphicsDropShadowEffect(self)
        self.setGraphicsEffect(self._shadow)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(24)
        self._apply(0.0)

    # ── 平滑过渡动画 ──
    def _tick(self):
        target = 1.0 if (self._hovering and self._enabled) else 0.0
        if abs(self._hover - target) < 0.02:
            if self._hover != target:
                self._hover = target
                self._apply(target)
            if self._hovering and self._enabled:
                self._pulse += 0.12
                size = self._base_icon_size + int(4 * math.sin(self._pulse))
                self.lb_icon.setStyleSheet(
                    f"background: transparent; font-size: {size}px; color: {self._accent.name()};")
            return
        self._hover += (target - self._hover) * 0.16
        self._apply(self._hover)
        self.update()

    def _apply(self, t):
        """按进度 t 插值：上浮、辉光、边框、填充"""
        a = self._accent
        lift = int(t * 4)
        blur = int(18 + t * 30)
        shadow_alpha = int(110 + t * 90)
        self._shadow.setBlurRadius(blur)
        self._shadow.setOffset(0, 8 - lift)
        self._shadow.setColor(QColor(a.red(), a.green(), a.blue(), shadow_alpha) if t > 0.3
                              else QColor(0, 0, 0, 110))
        # 填充：暗底 + 渐变，hover 时融入主题色
        fill = QColor(21 + int(a.red() * t * 0.18), 27 + int(a.green() * t * 0.18),
                      40 + int(a.blue() * t * 0.18), 230)
        border = QColor(int(52 + (a.red() - 52) * t), int(66 + (a.green() - 66) * t),
                        int(92 + (a.blue() - 92) * t), 230)
        self.setStyleSheet(
            f"QFrame {{ background: {fill.name(QColor.HexArgb)}; "
            f"border: {1 + int(t)}px solid {border.name()}; border-radius: 20px; }}")
        self.lb_title.setStyleSheet(
            f"background: transparent; color: {C_TEXT if t < 0.5 else a.name()};")
        self.lb_desc.setStyleSheet(f"background: transparent; color: {C_SUB};")
        self.bar.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"stop:0 {QColor(a.red(), a.green(), a.blue(), 40).name(QColor.HexArgb)}, "
            f"stop:0.5 {a.name()}, "
            f"stop:1 {QColor(a.red(), a.green(), a.blue(), 40).name(QColor.HexArgb)}); "
            f"border-radius: 2px;")

    def enterEvent(self, e):
        self._hovering = True

    def leaveEvent(self, e):
        self._hovering = False

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

    def _icon(self, name):
        p = assets_path(name)
        if os.path.exists(p):
            return QPixmap(p)
        return None
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ── 粒子系统 ──
    def _init_particles(self):
        pts = []
        for _ in range(46):
            pts.append({
                "x": random.random(), "y": random.random(),
                "r": random.uniform(0.9, 2.3),
                "vy": random.uniform(0.0005, 0.0018),
                "vx": random.uniform(-0.0004, 0.0004),
                "a": random.uniform(0.07, 0.42),
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
        t = self._t / 400.0
        # 深空渐变底
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0.0, QColor(7, 11, 20))
        g.setColorAt(0.5, QColor(13, 21, 42))
        g.setColorAt(1.0, QColor(6, 9, 18))
        p.fillRect(self.rect(), g)
        # 三处环境光晕（右上青 / 左下紫 / 中下蓝），比旧版更柔
        for cx, cy, r, col, al in [
            (w * 0.92, h * 0.06, min(w, h) * 0.6, C_ACC2, 26),
            (w * 0.05, h * 0.94, min(w, h) * 0.62, C_ACC3, 22),
            (w * 0.5, h * 0.46, min(w, h) * 0.75, C_ACC1, 13),
        ]:
            rg = QRadialGradient(cx, cy, r)
            rg.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(), al))
            rg.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), QBrush(rg))
        # 斜向流动光带（更细更淡，避免廉价感）
        for k in range(2):
            tt = (t * 0.5 + k * 0.5) % 1.0
            x0 = -0.2 * w + tt * 1.4 * w
            y0 = h * (0.25 + 0.32 * k + 0.16 * math.sin(t * 1.1 + k * 2.1))
            lg = QLinearGradient(x0 - 260, y0, x0 + 260, y0)
            col = C_ACC2 if k == 0 else C_ACC3
            lg.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(), 0))
            lg.setColorAt(0.5, QColor(col.red(), col.green(), col.blue(), 26))
            lg.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(lg)
            p.drawEllipse(QRectF(x0 - 270, y0 - 5, 540, 10))
        # 粒子 + 连线星云
        pts = self.particles
        n = len(pts)
        xs = [pt["x"] * w for pt in pts]
        ys = [pt["y"] * h for pt in pts]
        link_r = min(w, h) * 0.15
        for i in range(n):
            for j in range(i + 1, n):
                dx = xs[i] - xs[j]
                dy = ys[i] - ys[j]
                d2 = dx * dx + dy * dy
                if d2 < link_r * link_r:
                    d = math.sqrt(d2)
                    alpha = int(52 * (1 - d / link_r))
                    p.setPen(QPen(QColor(120, 170, 255, alpha), 1))
                    p.drawLine(int(xs[i]), int(ys[i]), int(xs[j]), int(ys[j]))
        for pt in pts:
            col = pt["c"]
            col.setAlphaF(pt["a"])
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QRectF(pt["x"] * w, pt["y"] * h, pt["r"] * 2, pt["r"] * 2))
        # 底部微渐隐（让内容区更聚焦）
        vg = QLinearGradient(0, h * 0.82, 0, h)
        vg.setColorAt(0.0, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(4, 6, 12, 90))
        p.fillRect(QRectF(0, h * 0.82, w, h * 0.18), vg)
        p.end()

    # ── UI ──
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addSpacerItem(QSpacerItem(1, 46, QSizePolicy.Minimum, QSizePolicy.Expanding))
        # 眉题（银行感金色点缀）
        self.lb_eyebrow = QLabel("与 遵 同 行 · 助 农 兴 企")
        fe = QFont()
        fe.setPointSize(10)
        fe.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        self.lb_eyebrow.setFont(fe)
        self.lb_eyebrow.setAlignment(Qt.AlignCenter)
        self.lb_eyebrow.setStyleSheet("background: transparent; color: #d8b45a;")
        outer.addWidget(self.lb_eyebrow)
        outer.addSpacing(6)
        # 品牌渐变标题
        self.lb_title = GradientTitle("遵农商 · 智媒工作台", 34)
        outer.addWidget(self.lb_title)
        outer.addSpacing(6)
        # 副标题
        self.lb_sub = QLabel("抖音新媒体运营 · AI 数字营销一站式工作台")
        fs = QFont()
        fs.setPointSize(12)
        fs.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        self.lb_sub.setFont(fs)
        self.lb_sub.setAlignment(Qt.AlignCenter)
        self.lb_sub.setStyleSheet("background: transparent; color: " + C_SUB + ";")
        outer.addWidget(self.lb_sub)
        outer.addSpacing(16)
        # 品牌发光装饰线
        line = QFrame()
        line.setFixedSize(240, 2)
        line.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 transparent, stop:0.5 #22d3ee, stop:1 transparent);")
        hline = QHBoxLayout()
        hline.addStretch(1)
        hline.addWidget(line)
        hline.addStretch(1)
        outer.addLayout(hline)
        outer.addSpacing(32)
        # 工具卡片（三个）
        cards = QHBoxLayout()
        cards.setSpacing(30)
        cards.addStretch(1)
        c_dm = CardWidget("💬", "智联助手", "评论 + 私信多账号自动回复\n话术模板 · 多账号并行",
                          QColor("#2aa868"), icon_pix=self._icon("icon_zhlian.png"))
        c_dm.clicked.connect(self.enter_dm.emit)
        cards.addWidget(c_dm)
        c_live = CardWidget("🎥", "智播助手", "评论关键词触发场景特效\n知识库问答 · 自动播报",
                            QColor("#22c55e"), icon_pix=self._icon("icon_zhibo.png"))
        c_live.clicked.connect(self.enter_live.emit)
        cards.addWidget(c_live)
        c_dl = CardWidget("🔍", "智鉴助手", "爆款视频智能拆解分析\n下载无水印 · AI 文案 · 爆款报告",
                          QColor("#34d399"), icon_pix=self._icon("icon_zhijian.png"))
        c_dl.clicked.connect(self.enter_downloader.emit)
        cards.addWidget(c_dl)
        cards.addStretch(1)
        outer.addLayout(cards)
        outer.addSpacerItem(QSpacerItem(1, 34, QSizePolicy.Minimum, QSizePolicy.Expanding))
        # 底部版本徽章
        self.lb_footer = QLabel()
        ff = QFont()
        ff.setPointSize(10)
        self.lb_footer.setFont(ff)
        self.lb_footer.setAlignment(Qt.AlignCenter)
        self.lb_footer.setStyleSheet(
            "background: rgba(18,24,36,150); color: #5f7092; "
            "border: 1px solid rgba(52,66,92,150); border-radius: 12px; padding: 4px 16px;")
        outer.addWidget(self.lb_footer)
        outer.addSpacing(18)

    def set_version(self, v):
        self.version = v
        self.lb_footer.setText(f"© 2026 遵义农商银行 · 与遵同行 助农兴企    {v}")
