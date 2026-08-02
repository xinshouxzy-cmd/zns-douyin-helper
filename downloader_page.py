# -*- coding: utf-8 -*-
"""
遵农商·抖音AI工作台 — 无水印视频下载器（第3个工具）
功能：粘贴抖音分享链接 → 解析视频信息 → 一键下载高清无水印视频
核心解析逻辑整合自《抖音无水印下载》UniApp 源码
"""

import os, re, json, time, html as _html
import requests
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QFrame, QProgressBar, QTextEdit, QFileDialog, QMessageBox,
)

# ── 深色科技风配色（与直播助手/评论私信统一） ──────────
C_BG = "#0d1117"; C_CARD = "#161b26"; C_CARD2 = "#1c2333"; C_BORDER = "#263040"
C_TEXT = "#e8eef7"; C_SUB = "#8b98ad"; C_ACCENT = "#3d8bff"
C_GREEN = "#2ecc71"; C_RED = "#e74c3c"; C_YELLOW = "#f1c40f"; C_CYAN = "#00d2ff"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, "无水印视频下载")
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")


# ── 核心解析逻辑（移植自 UniApp 无水印下载器） ──────────
def extract_video_id(text):
    """从分享链接/口令中提取视频ID"""
    for pat in (r"/share/video/(\d+)", r"/video/(\d+)",
                r"video_id=(\d+)", r"aweme_id=(\d+)", r"modal_id=(\d+)"):
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def extract_router_data(html):
    """括号配对提取 window._ROUTER_DATA JSON"""
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{)", html)
    if not m:
        return None
    text = html[m.start(1):]
    depth, start, i = 0, 0, 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


def find_video_info(router):
    """递归查找 videoInfoRes.item_list[0]"""
    def walk(obj):
        if isinstance(obj, dict):
            if "videoInfoRes" in obj:
                return obj["videoInfoRes"]
            for v in obj.values():
                r = walk(v)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = walk(v)
                if r:
                    return r
        return None
    res = walk(router) if isinstance(router, dict) else None
    if not res:
        return None
    items = res.get("item_list") or []
    return items[0] if items else None


def parse_douyin(url):
    """解析抖音分享链接，返回视频信息 dict 或抛异常"""
    vid = extract_video_id(url)
    if not vid:
        raise ValueError("未能从链接中识别出视频ID，请检查分享链接是否完整")
    r = requests.get(f"https://www.iesdouyin.com/share/video/{vid}",
                     headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    router = extract_router_data(r.text)
    item = find_video_info(router)
    if not item:
        raise ValueError("解析失败：页面结构可能已更新，请稍后再试")
    v = item.get("video") or {}
    play_list = (v.get("play_addr") or {}).get("url_list") or []
    if not play_list:
        raise ValueError("解析失败：未找到视频播放地址")
    play = play_list[0].replace("playwm", "play")
    author = item.get("author") or {}
    stats = item.get("statistics") or {}
    cover_list = (v.get("cover") or {}).get("url_list") or []
    return {
        "video_id": vid,
        "desc": item.get("desc") or "（无描述）",
        "author": author.get("nickname") or "未知作者",
        "digg": stats.get("digg_count") or 0,
        "comment": stats.get("comment_count") or 0,
        "share": stats.get("share_count") or 0,
        "play": play,
        "cover": cover_list[0] if cover_list else None,
    }


def _fmt_count(n):
    return f"{int(n):,}"


# ── 解析线程 ────────────────────────────────────────
class ParseWorker(QThread):
    ok = pyqtSignal(dict)
    fail = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            info = parse_douyin(self.url)
            # 顺带把封面图下载成 bytes，避免主线程卡顿
            cover_bytes = None
            if info.get("cover"):
                try:
                    cover_bytes = requests.get(
                        info["cover"].replace("http://", "https://"),
                        headers={"User-Agent": UA}, timeout=10).content
                except Exception:
                    cover_bytes = None
            info["cover_bytes"] = cover_bytes
            self.ok.emit(info)
        except Exception as e:
            self.fail.emit(str(e))


# ── 下载线程 ────────────────────────────────────────
class DownloadWorker(QThread):
    progress = pyqtSignal(int, int)   # done, total
    ok = pyqtSignal(str)              # 保存路径
    fail = pyqtSignal(str)

    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path

    def run(self):
        try:
            hdr = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
            r = requests.get(self.url, headers=hdr, stream=True, timeout=60)
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(self.save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    self.progress.emit(done, total)
            self.ok.emit(self.save_path)
        except Exception as e:
            self.fail.emit(str(e))


# ── 页面 ────────────────────────────────────────────
class DownloaderPage(QWidget):
    go_home = pyqtSignal()
    check_update = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_BG};")
        self.parse_worker = None
        self.dl_worker = None
        self.save_dir = SAVE_DIR
        self._build_ui()

    # ─────────── UI ───────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(self._build_topbar())
        outer.addLayout(self._build_body(), 1)
        outer.addWidget(self._build_footer())

    def _build_topbar(self):
        top = QHBoxLayout()
        top.setContentsMargins(18, 14, 18, 12)
        top.setSpacing(12)
        btn_back = QPushButton("← 返回首页")
        btn_back.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {C_SUB}; border: 1px solid {C_BORDER};"
            f" border-radius: 8px; padding: 7px 14px; font-size: 13px; }}"
            f"QPushButton:hover {{ color: {C_ACCENT}; border-color: {C_ACCENT}; }}")
        btn_back.clicked.connect(self.go_home)
        top.addWidget(btn_back)

        title = QLabel("🎬 无水印视频下载器")
        title.setStyleSheet(f"color:{C_TEXT}; font-size:19px; font-weight:bold;")
        top.addWidget(title)
        sub = QLabel("粘贴抖音分享链接，一键下载高清无水印视频")
        sub.setStyleSheet(f"color:{C_SUB}; font-size:12px;")
        top.addWidget(sub)
        top.addStretch()

        self.btn_check = QPushButton("🔄 检查更新")
        self.btn_check.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {C_SUB}; border: 1px solid {C_BORDER};"
            f" border-radius: 8px; padding: 7px 14px; font-size: 13px; }}"
            f"QPushButton:hover {{ color: {C_ACCENT}; border-color: {C_ACCENT}; }}")
        self.btn_check.clicked.connect(self.check_update)
        top.addWidget(self.btn_check)
        return top

    def _build_body(self):
        body = QVBoxLayout()
        body.setContentsMargins(24, 8, 24, 8)
        body.setSpacing(14)

        # ── 链接输入卡片 ──
        card_in = QFrame()
        card_in.setStyleSheet(
            f"QFrame {{ background:{C_CARD}; border:1px solid {C_BORDER}; border-radius:12px; }}")
        in_lay = QVBoxLayout(card_in)
        in_lay.setContentsMargins(18, 16, 18, 16)
        in_lay.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.le_url = QLineEdit()
        self.le_url.setPlaceholderText("粘贴抖音分享链接，如 https://v.douyin.com/xxxxxx/ 或视频页面地址…")
        self.le_url.setStyleSheet(
            f"QLineEdit {{ background:{C_BG}; color:{C_TEXT}; border:1px solid {C_BORDER};"
            f" border-radius:8px; padding:12px 16px; font-size:14px; }}"
            f"QLineEdit:focus {{ border-color:{C_ACCENT}; }}")
        self.le_url.returnPressed.connect(self._on_parse)
        row.addWidget(self.le_url, 1)
        self.btn_parse = QPushButton("🚀 解析视频")
        self.btn_parse.setStyleSheet(
            f"QPushButton {{ background:{C_ACCENT}; color:white; border:none; border-radius:8px;"
            f" padding:12px 26px; font-size:14px; font-weight:bold; }}"
            f"QPushButton:hover {{ background:#5a9dff; }}"
            f"QPushButton:disabled {{ background:{C_BORDER}; color:#556; }}")
        self.btn_parse.clicked.connect(self._on_parse)
        row.addWidget(self.btn_parse)
        in_lay.addLayout(row)

        tip = QLabel("💡 支持：视频分享口令 / 分享链接 / 视频详情页地址，解析成功后即可预览并下载无水印原视频")
        tip.setStyleSheet(f"color:{C_SUB}; font-size:12px;")
        in_lay.addWidget(tip)
        body.addWidget(card_in)

        # ── 结果卡片 ──
        self.card_result = QFrame()
        self.card_result.setStyleSheet(
            f"QFrame {{ background:{C_CARD2}; border:1px solid {C_BORDER}; border-radius:12px; }}")
        self.card_result.setVisible(False)
        res_lay = QHBoxLayout(self.card_result)
        res_lay.setContentsMargins(18, 16, 18, 16)
        res_lay.setSpacing(18)

        self.lbl_cover = QLabel("封面")
        self.lbl_cover.setFixedSize(180, 100)
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.setStyleSheet(
            f"background:{C_BG}; color:{C_SUB}; border:1px solid {C_BORDER}; border-radius:8px; font-size:12px;")
        res_lay.addWidget(self.lbl_cover)

        info = QVBoxLayout()
        info.setSpacing(8)
        self.lbl_desc = QLabel()
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet(f"color:{C_TEXT}; font-size:15px; font-weight:bold;")
        info.addWidget(self.lbl_desc)
        self.lbl_author = QLabel()
        self.lbl_author.setStyleSheet(f"color:{C_CYAN}; font-size:13px;")
        info.addWidget(self.lbl_author)
        self.lbl_stats = QLabel()
        self.lbl_stats.setStyleSheet(f"color:{C_SUB}; font-size:12px;")
        info.addWidget(self.lbl_stats)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.btn_dl = QPushButton("⬇️ 下载无水印视频")
        self.btn_dl.setStyleSheet(
            f"QPushButton {{ background:{C_GREEN}; color:#0b0f14; border:none; border-radius:8px;"
            f" padding:10px 22px; font-size:14px; font-weight:bold; }}"
            f"QPushButton:hover {{ background:#3ddc84; }}"
            f"QPushButton:disabled {{ background:{C_BORDER}; color:#556; }}")
        self.btn_dl.clicked.connect(self._on_download)
        btns.addWidget(self.btn_dl)
        self.btn_dir = QPushButton("📁 选择保存位置")
        self.btn_dir.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_SUB}; border:1px solid {C_BORDER};"
            f" border-radius:8px; padding:10px 16px; font-size:13px; }}"
            f"QPushButton:hover {{ color:{C_ACCENT}; border-color:{C_ACCENT}; }}")
        self.btn_dir.clicked.connect(self._choose_dir)
        btns.addWidget(self.btn_dir)
        btns.addStretch()
        info.addLayout(btns)
        res_lay.addLayout(info, 1)
        body.addWidget(self.card_result)

        # ── 下载进度 ──
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background:{C_BG}; border:1px solid {C_BORDER}; border-radius:6px;"
            f" text-align:center; color:{C_TEXT}; font-size:12px; height:16px; }}"
            f"QProgressBar::chunk {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {C_ACCENT}, stop:1 {C_CYAN}); border-radius:5px; }}")
        body.addWidget(self.progress)

        # ── 下载历史 ──
        lbl_his = QLabel("📂 下载历史")
        lbl_his.setStyleSheet(f"color:{C_SUB}; font-size:12px; font-weight:bold;")
        body.addWidget(lbl_his)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(110)
        self.txt_log.setStyleSheet(
            f"QTextEdit {{ background:{C_CARD}; color:{C_SUB}; border:1px solid {C_BORDER};"
            f" border-radius:8px; padding:8px 12px; font-size:12px; }}")
        body.addWidget(self.txt_log)
        body.addStretch()
        return body

    def _build_footer(self):
        foot = QHBoxLayout()
        foot.setContentsMargins(24, 4, 24, 10)
        lbl = QLabel(f"遵农商·抖音AI工作台 · 无水印视频下载器 · 保存目录：{self.save_dir}")
        lbl.setStyleSheet(f"color:#4a5568; font-size:11px;")
        foot.addWidget(lbl)
        foot.addStretch()
        w = QWidget()
        w.setLayout(foot)
        return w

    # ─────────── 逻辑 ───────────
    def _log(self, msg, color=C_SUB):
        t = time.strftime("%H:%M:%S")
        self.txt_log.append(f'<span style="color:#4a5568;">[{t}]</span> '
                            f'<span style="color:{color};">{_html.escape(str(msg))}</span>')

    def _on_parse(self):
        url = self.le_url.text().strip()
        if not url:
            QMessageBox.information(self, "提示", "请先粘贴抖音分享链接")
            return
        self.btn_parse.setEnabled(False)
        self.btn_parse.setText("⏳ 解析中…")
        self.card_result.setVisible(False)
        self.progress.setVisible(False)
        self._log("开始解析…", C_YELLOW)
        self.parse_worker = ParseWorker(url)
        self.parse_worker.ok.connect(self._on_parsed)
        self.parse_worker.fail.connect(self._on_parse_fail)
        self.parse_worker.start()

    def _on_parsed(self, info):
        self.btn_parse.setEnabled(True)
        self.btn_parse.setText("🚀 解析视频")
        self._info = info
        if info.get("cover_bytes"):
            pix = QPixmap()
            if pix.loadFromData(info["cover_bytes"]):
                pix = pix.scaled(180, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_cover.setPixmap(pix)
            else:
                self.lbl_cover.setText("封面")
        else:
            self.lbl_cover.setText("封面")
        self.lbl_desc.setText(f"📝 {info['desc'][:60]}")
        self.lbl_author.setText(f"👤 作者：{info['author']}")
        self.lbl_stats.setText(
            f"👍 点赞 {_fmt_count(info['digg'])}    💬 评论 {_fmt_count(info['comment'])}    "
            f"🔄 分享 {_fmt_count(info['share'])}")
        self.card_result.setVisible(True)
        self._log(f"解析成功：{info['author']} 的「{info['desc'][:30]}…」", C_GREEN)

    def _on_parse_fail(self, err):
        self.btn_parse.setEnabled(True)
        self.btn_parse.setText("🚀 解析视频")
        self._log(f"解析失败：{err}", C_RED)
        QMessageBox.warning(self, "解析失败", f"无法解析该视频：\n{err}")

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择视频保存目录", self.save_dir)
        if d:
            self.save_dir = d
            self._log(f"保存目录已切换：{d}")

    def _safe_name(self, desc):
        name = re.sub(r'[\\/:*?"<>|\n\r]', "", desc)[:40].strip()
        return name or f"douyin_{int(time.time())}"

    def _on_download(self):
        info = getattr(self, "_info", None)
        if not info:
            return
        os.makedirs(self.save_dir, exist_ok=True)
        path = os.path.join(self.save_dir, f"{self._safe_name(info['desc'])}.mp4")
        if os.path.exists(path):
            path = os.path.join(self.save_dir,
                                f"{self._safe_name(info['desc'])}_{int(time.time())}.mp4")
        self.btn_dl.setEnabled(False)
        self.btn_dl.setText("⏳ 下载中…")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self._log("开始下载无水印视频…", C_YELLOW)
        self.dl_worker = DownloadWorker(info["play"], path)
        self.dl_worker.progress.connect(self._on_dl_progress)
        self.dl_worker.ok.connect(self._on_dl_done)
        self.dl_worker.fail.connect(self._on_dl_fail)
        self.dl_worker.start()

    def _on_dl_progress(self, done, total):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(done)
            pct = int(done * 100 / total)
            self.progress.setFormat(f"下载中 {pct}% · {done // 1048576}MB / {max(total, 1) // 1048576}MB")
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat(f"下载中… {done // 1048576}MB")

    def _on_dl_done(self, path):
        self.btn_dl.setEnabled(True)
        self.btn_dl.setText("⬇️ 下载无水印视频")
        self.progress.setVisible(False)
        self._log(f"✅ 下载完成：{path}", C_GREEN)
        QMessageBox.information(self, "下载完成", f"视频已保存到：\n{path}")

    def _on_dl_fail(self, err):
        self.btn_dl.setEnabled(True)
        self.btn_dl.setText("⬇️ 下载无水印视频")
        self.progress.setVisible(False)
        self._log(f"下载失败：{err}", C_RED)
        QMessageBox.warning(self, "下载失败", f"下载出错：\n{err}")

    def _stop_if_running(self):
        """返回首页时调用"""
        pass
