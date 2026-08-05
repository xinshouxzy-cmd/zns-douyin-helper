# -*- coding: utf-8 -*-
"""
遵农商·智媒工作台 — 智鉴助手（第3个工具）
功能：粘贴抖音分享链接 → 下载无水印视频 + AI 拆解爆款
（语音转写文案 / GLM 画面理解 / DeepSeek 爆款分析报告 + 手机版 APK 导出）
"""

import os, re, json, time, shutil, tempfile, html as _html
import requests
import zns_analyze
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
# 完整浏览器请求头（关键！缺头会被抖音风控返回空数据，安卓端正是带了 Accept 才能解析成功）
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.douyin.com/",
    "Connection": "keep-alive",
}


# ── 核心解析逻辑（移植自 UniApp 无水印下载器） ──────────
def extract_video_id(text):
    """从分享链接/口令中提取视频ID，支持完整链接和 v.douyin.com 短链"""
    # 1) 直接匹配数字 ID 格式
    for pat in (r"/share/video/(\d+)", r"/video/(\d+)",
                r"video_id=(\d+)", r"aweme_id=(\d+)", r"modal_id=(\d+)"):
        m = re.search(pat, text)
        if m:
            return m.group(1)
    # 2) v.douyin.com 短链 → 返回短链，由 parse_douyin 跳转解析
    m = re.search(r"https?://v\.douyin\.com/[A-Za-z0-9_\-]+", text)
    if m:
        return "short:" + m.group(0)
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


def _resolve_short_url(short_url):
    """解析 v.douyin.com 短链 → 返回真实视频ID或None"""
    try:
        r = requests.get(short_url, headers=HEADERS, timeout=15,
                         allow_redirects=True)
        vid = extract_video_id(r.url)
        if vid and not vid.startswith("short:"):
            return vid
        # 跳转后页面 HTML 里也可能带 ID
        vid = extract_video_id(r.text)
        if vid and not vid.startswith("short:"):
            return vid
    except Exception:
        pass
    return None


def parse_douyin(url):
    """解析抖音分享链接，返回视频信息 dict 或抛异常"""
    vid = extract_video_id(url)
    if not vid:
        raise ValueError("未能从链接中识别出视频ID，请检查分享链接是否完整")
    # v.douyin.com 短链 → 先跳转解析真实 ID
    if vid.startswith("short:"):
        real_vid = _resolve_short_url(vid[6:])
        if not real_vid:
            raise ValueError("短链接解析失败：无法获取视频ID，请用视频详情页链接重试")
        vid = real_vid
    r = requests.get(f"https://www.iesdouyin.com/share/video/{vid}",
                     headers=HEADERS, timeout=15)
    r.raise_for_status()
    router = extract_router_data(r.text)
    item = find_video_info(router)
    if not item:
        raise ValueError("解析失败：视频可能已被删除，或页面结构已更新，请稍后再试")
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
        "collect": stats.get("collect_count") or 0,
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


# ── 智能分析线程（下载 → 转写 → 画面理解 → 爆款报告） ──
class AnalyzeWorker(QThread):
    step = pyqtSignal(str, int)   # (消息, 进度0-100)
    ok = pyqtSignal(dict)         # {desc, author, stats, transcript, report}
    fail = pyqtSignal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            self.step.emit("解析视频信息…", 5)
            info = parse_douyin(self.url)
            self.play_url = info["play"]
            tmp = tempfile.mkdtemp(prefix="zns_analyze_")
            video = os.path.join(tmp, "video.mp4")
            self.step.emit("下载无水印视频…", 20)
            hdr = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
            r = requests.get(info["play"], headers=hdr, stream=True, timeout=120)
            r.raise_for_status()
            with open(video, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
            if os.path.getsize(video) < 10000:
                raise RuntimeError("视频下载异常（文件过小）")
            self.step.emit("提取音频…", 45)
            wav = os.path.join(tmp, "audio.wav")
            zns_analyze.extract_audio(video, wav)
            self.step.emit("语音转写文案…", 60)
            transcript, got = zns_analyze.baidu_asr(wav)
            self.step.emit("AI 理解画面…", 72)
            vis = zns_analyze.glm_understand_frames(video, tmp)
            self.step.emit("获取评论区与互动数据…", 82)
            comments = []
            try:
                cj = zns_analyze.fetch_comments(self.url)
                comments = cj.get("comments") or []
                if cj.get("stats"):
                    info = dict(info)
                    info["digg"] = cj["stats"].get("likes", info.get("digg", 0))
                    info["comment"] = cj["stats"].get("comments", info.get("comment", 0))
                    info["share"] = cj["stats"].get("shares", info.get("share", 0))
                    info["collect"] = cj["stats"].get("favorites", info.get("collect", 0))
            except Exception:
                comments = []
            self.step.emit("生成爆款分析报告…", 90)
            meta = json.dumps({
                "desc": info.get("desc", ""),
                "stats": {"likes": info.get("digg", 0), "comments": info.get("comment", 0),
                          "collects": info.get("collect", 0), "shares": info.get("share", 0)},
            }, ensure_ascii=False)
            report = zns_analyze.deepseek_report(meta, transcript, "", vis, comments)
            self.ok.emit({
                "desc": info.get("desc", ""), "author": info.get("author", ""),
                "stats": info, "transcript": transcript if got else "",
                "no_speech": not got, "report": report, "video_path": video,
                "comments": comments,
            })
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

        title = QLabel("🔍 智鉴助手")
        title.setStyleSheet(f"color:{C_TEXT}; font-size:19px; font-weight:bold;")
        top.addWidget(title)
        sub = QLabel("粘贴抖音分享链接：下载无水印视频 + AI 拆解爆款（文案/画面/报告）")
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
        self.btn_parse = QPushButton("🔍 解析并分析")
        self.btn_parse.setStyleSheet(
            f"QPushButton {{ background:{C_ACCENT}; color:white; border:none; border-radius:8px;"
            f" padding:12px 26px; font-size:14px; font-weight:bold; }}"
            f"QPushButton:hover {{ background:#5a9dff; }}"
            f"QPushButton:disabled {{ background:{C_BORDER}; color:#556; }}")
        self.btn_parse.clicked.connect(self._on_parse)
        row.addWidget(self.btn_parse)
        in_lay.addLayout(row)

        tip = QLabel("💡 支持：分享口令 / 分享链接 / 视频详情页地址。点击【解析并分析】自动完成：下载 → 转写文案 → AI 看画面 → 爆款分析报告")
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

        # ── 分析报告卡片 ──
        self.card_report = QFrame()
        self.card_report.setStyleSheet(
            f"QFrame {{ background:{C_CARD}; border:1px solid {C_BORDER}; border-radius:12px; }}")
        self.card_report.setVisible(False)
        rep_lay = QVBoxLayout(self.card_report)
        rep_lay.setContentsMargins(18, 16, 18, 16)
        rep_lay.setSpacing(10)
        rep_title = QLabel("📄 分析结果（文案 + 爆款解读）")
        rep_title.setStyleSheet(f"color:{C_TEXT}; font-size:14px; font-weight:bold;")
        rep_lay.addWidget(rep_title)
        self.txt_report = QTextEdit()
        self.txt_report.setReadOnly(True)
        self.txt_report.setStyleSheet(
            f"QTextEdit {{ background:{C_BG}; color:{C_TEXT}; border:1px solid {C_BORDER};"
            f" border-radius:8px; padding:10px 14px; font-size:13px; }}")
        rep_lay.addWidget(self.txt_report)
        body.addWidget(self.card_report)

        # ── 下载进度 ──
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background:{C_BG}; border:1px solid {C_BORDER}; border-radius:6px;"
            f" text-align:center; color:{C_TEXT}; font-size:12px; height:18px; }}"
            f"QProgressBar::chunk {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {C_ACCENT}, stop:1 {C_CYAN}); border-radius:5px; }}")
        body.addWidget(self.progress)
        self.lbl_step = QLabel("")
        self.lbl_step.setStyleSheet(
            f"color:{C_CYAN}; font-size:13px; font-weight:bold; padding:2px 4px;")
        body.addWidget(self.lbl_step)

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
        lbl = QLabel(f"遵农商·智媒工作台 · 智鉴助手 · 保存目录：{self.save_dir}")
        lbl.setStyleSheet(f"color:#4a5568; font-size:11px;")
        foot.addWidget(lbl)
        foot.addStretch()
        self.btn_apk = QPushButton("📱 下载手机版（APK）")
        self.btn_apk.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_CYAN}; border:1px solid {C_BORDER};"
            f" border-radius:8px; padding:6px 14px; font-size:12px; }}"
            f"QPushButton:hover {{ color:{C_ACCENT}; border-color:{C_ACCENT}; }}")
        self.btn_apk.clicked.connect(self._export_apk)
        foot.addWidget(self.btn_apk)
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
        if getattr(self, "analyze_worker", None) and self.analyze_worker.isRunning():
            return
        # 用户主动点击「解析并分析」→ 第一步立即上报（静默）
        try:
            import updater
            updater.report_action(os.path.join(BASE_DIR, "config.json"), "zhijian-exe", "video_analyze")
        except Exception:
            pass
        # 一条龙：解析 + 下载 + 转写 + 画面理解 + 爆款报告
        self.btn_parse.setEnabled(False)
        self.btn_parse.setText("⏳ 分析中…")
        self.card_result.setVisible(False)
        self.card_report.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setValue(2)
        self.txt_report.clear()
        self._log("开始智能分析：下载视频 → 转写文案 → AI 看画面 → 爆款报告", C_CYAN)
        self.analyze_worker = AnalyzeWorker(url)
        self.analyze_worker.step.connect(self._on_analyze_step)
        self.analyze_worker.ok.connect(self._on_analyze_ok)
        self.analyze_worker.fail.connect(self._on_analyze_fail)
        self.analyze_worker.start()

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
        self.btn_parse.setText("🔍 解析并分析")
        self._log(f"解析失败：{err}", C_RED)
        QMessageBox.warning(self, "解析失败", f"无法解析该视频：\n{err}")

    def _on_analyze_step(self, msg, pct):
        self.progress.setValue(pct)
        self.lbl_step.setText(f"⏳ {msg}　{pct}%")
        self._log(msg, C_SUB)

    def _on_analyze_ok(self, res):
        self.btn_parse.setEnabled(True)
        self.btn_parse.setText("🔍 解析并分析")
        self.progress.setValue(100)
        self.progress.setVisible(False)
        self.lbl_step.setText("✅ 分析完成！")
        st = res.get("stats") or {}
        self._info = {
            "play": getattr(self.analyze_worker, "play_url", "") or "",
            "desc": res.get("desc", ""), "author": res.get("author", ""),
            "digg": st.get("digg", 0), "comment": st.get("comment", 0),
            "share": st.get("share", 0),
        }
        self.lbl_desc.setText(f"📝 {str(res.get('desc', ''))[:60]}")
        self.lbl_author.setText(f"👤 作者：{res.get('author', '')}")
        self.lbl_stats.setText(
            f"👍 点赞 {_fmt_count(st.get('digg', 0))}    💬 评论 {_fmt_count(st.get('comment', 0))}    "
            f"🔄 分享 {_fmt_count(st.get('share', 0))}")
        self.card_result.setVisible(True)
        self.card_report.setVisible(True)
        st = res.get("stats") or {}
        base = (f"【📊 视频基础数据】\n"
                f"👍 点赞 {_fmt_count(st.get('digg', 0))}　💬 评论 {_fmt_count(st.get('comment', 0))}\n"
                f"⭐ 收藏 {_fmt_count(st.get('collect', 0))}　🔄 转发 {_fmt_count(st.get('share', 0))}\n")
        cmts = res.get("comments") or []
        cmt_part = ""
        if cmts:
            cmt_lines = []
            for c in cmts[:15]:
                cmt_lines.append(f"　{c.get('user', '?')}：{c.get('text', '')}"
                                 + (f"（赞{c.get('digg')}）" if c.get("digg") else ""))
            cmt_part = "【💬 评论区热评（真实抓取）】\n" + "\n".join(cmt_lines) + "\n"
        parts = [base]
        if res.get("no_speech"):
            parts.append("（未识别到口播语音：纯音乐/无人声视频，已用 AI 画面理解分析）")
        elif res.get("transcript"):
            parts.append("【🎙 音频转写文案（本视频语音识别）】\n" + res["transcript"])
        if cmt_part:
            parts.append(cmt_part.rstrip())
        else:
            parts.append("⚠️ 本次未获取到评论区内容")
        parts.append("【📋 爆款分析报告】\n" + res.get("report", ""))
        self.txt_report.setPlainText("\n\n".join(parts))
        self._log("✅ 智能分析完成！可点击【下载无水印视频】保存原视频", C_GREEN)

    def _on_analyze_fail(self, err):
        self.btn_parse.setEnabled(True)
        self.btn_parse.setText("🔍 解析并分析")
        self.progress.setVisible(False)
        self.lbl_step.setText(f"❌ 分析失败：{err[:60]}")
        self._log(f"分析失败：{err}", C_RED)
        QMessageBox.warning(self, "分析失败", f"智能分析失败：\n{err}")

    def _export_apk(self):
        """把内置的手机版 APK 导出到用户选择的位置"""
        base = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base, "apk", "智鉴助手_v1.0.33.apk"),
            os.path.join(base, "runtime", "智鉴助手_v1.0.33.apk"),
        ]
        src = next((p for p in candidates if os.path.exists(p)), None)
        if not src:
            QMessageBox.information(
                self, "提示",
                "手机版 APK 未随本工具携带。\n请向开发者索取 智鉴助手_v1.0.33.apk，或用手机直接安装。")
            return
        d, _ = QFileDialog.getSaveFileName(
            self, "保存手机版 APK", os.path.join(self.save_dir, "智鉴助手_v1.0.33.apk"), "APK (*.apk)")
        if d:
            try:
                shutil.copy(src, d)
                self._log(f"✅ 手机版 APK 已导出：{d}（发送到手机安装即可）", C_GREEN)
                QMessageBox.information(self, "导出成功",
                                        f"APK 已保存到：\n{d}\n\n发送到手机安装即可使用「智鉴助手·手机版」")
            except Exception as e:
                self._log(f"导出 APK 失败：{e}", C_RED)

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
