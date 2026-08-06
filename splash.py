# -*- coding: utf-8 -*-
"""启动画面：品牌 logo 缩放发光 + 标题渐显 + 进度光带，约 2.2 秒后淡出"""
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, QPropertyAnimation, pyqtSignal, QEasingCurve
from PyQt5.QtGui import (QPainter, QColor, QPixmap, QFont, QLinearGradient,
                         QRadialGradient, QPen, QBrush)
from PyQt5.QtWidgets import QWidget

from worker import assets_path


class SplashScreen(QWidget):
    finished = pyqtSignal()

    def __init__(self, version=""):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(620, 400)
        self._t = 0
        self._version = version
        self._closing = False
        self._anim = None
        self._logo = QPixmap(assets_path("icon_main.png"))
        if self._logo.isNull():
            self._logo = QPixmap(256, 256)
            self._logo.fill(Qt.transparent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._t += 1
        if self._t >= 138 and not self._closing:  # 约 2.2 秒
            self._closing = True
            self._timer.stop()
            self._anim = QPropertyAnimation(self, b"windowOpacity", self)
            self._anim.setDuration(450)
            self._anim.setStartValue(1.0)
            self._anim.setEndValue(0.0)
            self._anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._anim.finished.connect(self._done)
            self._anim.start()
        self.update()

    def _done(self):
        self.finished.emit()
        self.close()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        t = min(1.0, self._t / 138.0)
        rect = QRectF(0, 0, w, h)
        # 深空蓝圆角底
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 16, 30, 246))
        p.drawRoundedRect(rect, 24, 24)
        # 蓝青光晕
        glow = QRadialGradient(w / 2, h * 0.42, w * 0.55)
        glow.setColorAt(0, QColor(77, 148, 255, int(60 * t)))
        glow.setColorAt(0.6, QColor(34, 211, 238, int(30 * t)))
        glow.setColorAt(1, QColor(10, 16, 30, 0))
        p.setBrush(glow)
        p.drawRoundedRect(rect, 24, 24)
        # 顶部流光
        line = QLinearGradient(0, 4, w, 4)
        line.setColorAt(0, QColor(77, 148, 255, 0))
        line.setColorAt(0.5, QColor(120, 190, 255, 200))
        line.setColorAt(1, QColor(77, 148, 255, 0))
        p.setBrush(line)
        p.drawRect(0, 4, w, 3)
        # logo 缩放 + 发光
        if not self._logo.isNull():
            scale = 0.6 + 0.4 * min(1.0, t * 1.6)
            base = 168 * scale
            gr = int(base * 1.35)
            g = QRadialGradient(w / 2, h * 0.34, gr)
            g.setColorAt(0, QColor(90, 170, 255, int(90 * t)))
            g.setColorAt(1, QColor(90, 170, 255, 0))
            p.setBrush(g)
            p.drawEllipse(QPointF(w / 2, h * 0.34), gr, gr * 0.8)
            p.drawPixmap(int(w / 2 - base / 2), int(h * 0.34 - base / 2),
                         int(base), int(base), self._logo)
        # 主标题渐显
        alpha = int(255 * min(1.0, max(0.0, (t - 0.25) / 0.45)))
        f = QFont()
        f.setPointSize(26)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(f)
        tg = QLinearGradient(0, 0, w, 0)
        tg.setColorAt(0, QColor(127, 178, 255, alpha))
        tg.setColorAt(0.5, QColor(77, 148, 255, alpha))
        tg.setColorAt(1, QColor(34, 211, 238, alpha))
        p.setPen(QPen(QBrush(tg), 1))
        p.drawText(QRectF(0, h * 0.56, w, 60), Qt.AlignCenter, "遵农商·智媒工作台")
        # 副标题
        f2 = QFont()
        f2.setPointSize(12)
        f2.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        p.setFont(f2)
        p.setPen(QColor(216, 180, 90, alpha))
        p.drawText(QRectF(0, h * 0.70, w, 30), Qt.AlignCenter, "与遵同行 · 助农兴企")
        # 底部进度光带
        pw = int((w * 0.42) * min(1.0, t * 1.2))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(216, 180, 90, 150))
        p.drawRoundedRect(QRectF(w / 2 - pw / 2, h * 0.82, pw, 3), 2, 2)
        # 版本号
        f3 = QFont()
        f3.setPointSize(9)
        p.setFont(f3)
        p.setPen(QColor(140, 160, 200, alpha))
        p.drawText(QRectF(0, h * 0.90, w, 20), Qt.AlignCenter, self._version or "")
        p.end()
