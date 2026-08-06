# -*- coding: utf-8 -*-
"""比赛附件：渲染智媒工作台各页面并截图（真实 UI 源码）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout
from PyQt5.QtCore import Qt, QTimer

OUT = "/Users/lws/Desktop/比赛方案_附件/界面截图"
os.makedirs(OUT, exist_ok=True)


class StubMain:
    def _update_sidebar_name(self, *a, **k):
        pass
    def _update_sidebar_status(self, *a, **k):
        pass
    def _append_log(self, *a, **k):
        pass


def shoot(widget, name, w, h, settle=1600):
    win = QMainWindow()
    win.setCentralWidget(widget)
    win.resize(w, h)
    win.setWindowTitle(name)
    win.show()
    app.processEvents()
    loop = QTimer()
    loop.setSingleShot(True)
    done = {}

    def grab():
        pix = widget.grab()
        path = os.path.join(OUT, name + ".png")
        pix.save(path)
        print("已保存:", path)
        done["ok"] = True
        win.close()

    loop.timeout.connect(grab)
    loop.start(settle)
    while not done:
        app.processEvents()
        QTimer().singleShot(50, lambda: None)
        app.processEvents()


def main():
    global app
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from home_page import HomePage
    from live_page import LivePage
    from downloader_page import DownloaderPage
    from main import AccountPage, load_config

    cfg = load_config()
    accounts = cfg.get("accounts") or [{}]

    hp = HomePage()
    hp.version = "v2.1.3"
    shoot(hp, "01_启动门户_智媒工作台", 1280, 820, settle=2600)

    ap = AccountPage(0, dict(accounts[0]), StubMain())
    shoot(ap, "02_智联助手_私信评论回复", 1280, 820, settle=1000)

    lp = LivePage()
    shoot(lp, "03_智播助手_直播监控特效", 1280, 900, settle=1200)

    dp = DownloaderPage()
    shoot(dp, "04_智鉴助手_电脑版视频解析", 1280, 900, settle=1200)


if __name__ == "__main__":
    main()
