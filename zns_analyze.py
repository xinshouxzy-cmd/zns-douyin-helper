# -*- coding: utf-8 -*-
"""智鉴助手 · 视频智能分析模块（电脑版）
链路：下载视频 → 抽音频转写(百度ASR) → 抽帧画面理解(GLM-4.6V) → 爆款分析报告(DeepSeek)
与手机版「智鉴助手」同一套能力与密钥。
"""

import base64
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

BD_AK = "0DudrZbzoHKhzxNegjbD6HOm"
BD_SK = "seS6h56BpMFzKv5PwnPwh8BXT8BvtlpF"
GLM_KEY = "c16a0e31273d4afcb9245588eea86bc8.mCmMiRdNeVT2qK5e"
DS_KEY = "sk-d2eadfc598494ec188b042b14291489c"
BACKEND_URL = "https://affair-rugs-bend-regulations.trycloudflare.com"  # 云端采集服务（评论/弹幕）


def find_ffmpeg():
    """优先用软件自带的 ffmpeg（runtime/ffmpeg.exe），否则用系统 PATH"""
    base = os.path.dirname(os.path.abspath(__file__))
    for cand in [os.path.join(base, "runtime", "ffmpeg.exe"),
                 os.path.join(base, "ffmpeg.exe"),
                 shutil.which("ffmpeg") or ""]:
        if cand and os.path.exists(cand):
            return cand
    return "ffmpeg"


def extract_audio(video, out_wav):
    """视频 → 16k 单声道 wav（百度 ASR 要求）"""
    ff = find_ffmpeg()
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", video,
                    "-ar", "16000", "-ac", "1", out_wav], check=True, timeout=300)
    return out_wav


def _http_json(url, headers, payload=None, timeout=120):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _baidu_token():
    url = ("https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials"
           f"&client_id={BD_AK}&client_secret={BD_SK}")
    j = _http_json(url, {})
    if "access_token" not in j:
        raise RuntimeError("百度 Token 获取失败：" + str(j)[:200])
    return j["access_token"]


def baidu_asr(wav_path, progress=None):
    """百度短语音识别（≤55 秒一段），返回带时间点的文案"""
    token = _baidu_token()
    import wave
    total = (os.path.getsize(wav_path) - 44) // 2
    chunk = 16000 * 55
    parts = []
    offset = 0
    idx = 0
    got = False
    with wave.open(wav_path, "rb") as w:
        rate = w.getframerate() or 16000
    while offset < total:
        end = min(offset + chunk, total)
        tmp = f"{wav_path}.c{idx}.wav"
        _cut_wav(wav_path, tmp, offset, end - offset)
        with open(tmp, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        j = _http_json(
            "https://vop.baidu.com/server_api",
            {"Content-Type": "application/json", "Content-Length": str(len(json.dumps({
                "format": "wav", "rate": rate, "channel": 1, "cuid": "zns-analyze",
                "token": token, "speech": b64, "len": len(b64)})))},
            {"format": "wav", "rate": rate, "channel": 1, "cuid": "zns-analyze",
             "token": token, "speech": b64, "len": len(b64)}, timeout=120)
        txt = j.get("result") and "".join(j["result"]) or ""
        if txt.strip():
            got = True
            sec = offset // rate
            parts.append(f"[{sec // 60:02d}:{sec % 60:02d}] {txt.strip()}")
        os.remove(tmp)
        offset = end
        idx += 1
        if progress:
            progress(int(offset / total * 100), "语音转写中…")
    return "\n".join(parts), got


def _cut_wav(src, dst, start_frames, frames):
    with open(src, "rb") as f:
        header = f.read(44)
        f.seek(44 + start_frames * 2)
        data = f.read(frames * 2)
    n = len(data)
    bb = bytearray(header)
    bb[40:44] = n.to_bytes(4, "little")
    bb[4:8] = (36 + n).to_bytes(4, "little")
    with open(dst, "wb") as f:
        f.write(bytes(bb))
        f.write(data)


def _extract_frames(video, tmpdir, count=4):
    """用 ffmpeg 抽 count 帧，返回压缩后的 base64 列表"""
    ff = find_ffmpeg()
    dur = None
    out = subprocess.run([ff, "-i", video], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr)
    if m:
        h, mi, s = m.groups()
        dur = int(h) * 3600 + int(mi) * 60 + float(s)
    if not dur or dur <= 0:
        dur = 30.0
    times = [dur * i / count for i in range(count)]
    b64s = []
    for i, t in enumerate(times):
        p = os.path.join(tmpdir, f"f{i}.jpg")
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video,
                        "-frames:v", "1", "-vf", "scale='min(768,iw)':-2", "-q:v", "5", p],
                       check=True, timeout=60)
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            with open(p, "rb") as f:
                b64s.append(base64.b64encode(f.read()).decode())
            os.remove(p)
    return b64s


def glm_understand_frames(video, tmpdir, progress=None):
    """GLM-4.6V 画面理解：抽帧 → 描述画面内容"""
    frames = _extract_frames(video, tmpdir)
    if not frames:
        return ""
    content = [{"type": "text", "text": (
        "你正在观看一段短视频的4个关键画面（按时间顺序）。请用中文如实描述画面内容："
        "1）场景与人物/主体（在做什么）；2）画面上的文字（字幕/标题/贴纸，逐字写出）；"
        "3）关键动作与变化；4）整体氛围。按画面顺序分点输出，只描述看到的，不要猜测画面外的信息。")}]
    for f in frames:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + f}})
    j = _http_json(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        {"Authorization": "Bearer " + GLM_KEY, "Content-Type": "application/json"},
        {"model": "glm-4.6v", "temperature": 0.6, "max_tokens": 1500,
         "messages": [{"role": "user", "content": content}]}, timeout=180)
    try:
        return j["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


def deepseek_report(meta, transcript, frame_text, frame_visual, comments=None, progress=None):
    """DeepSeek 生成面向普通用户的爆款分析报告（含基础数据 + 评论区分析）"""
    sys_prompt = (
        "你是一位短视频内容分析专家，善于读懂视频在讲什么。\n"
        "根据提供的【视频描述】【画面文字识别】【画面理解】【口播文案】"
        "【互动数据（点赞/评论/收藏/转发）】【评论区内容】"
        "，用中文写一份面向普通用户的《视频解读》：\n"
        "0. 视频基础数据：点赞数、评论数、收藏数、转发数（有就写，没有不写）\n"
        "1. 这条视频在讲什么（一两句话概括）\n"
        "2. 画面与文案要点（结合画面理解和口播，按时间顺序讲清楚内容）\n"
        "3. 评论区观众在聊什么（根据实际评论内容总结：观众在讨论什么、什么点引发共鸣或争论，"
        "引用几条有代表性的评论）\n"
        "4. 为什么可能受欢迎（结合互动数据与评论区观众反应分析）\n"
        "5. 可以借鉴的做法（给想拍视频的人的具体建议）\n"
        "要求：只写已经掌握的信息，不要编造数据或细节；"
        "评论区内容如果标记为【未获取到评论区内容】，绝对禁止编造任何评论、"
        "禁止引用不存在的观众发言，第3小节只能写：本次未获取到评论区内容（"
        "可能评论未公开/关闭，或采集受限）；"
        "不要出现'信息不足''缺失''建议补充'等开发术语。")
    cmt_text = ""
    if comments:
        lines = []
        for c in comments[:30]:
            lines.append(f"{c.get('user', '?')}：{c.get('text', '')}"
                         + (f"（赞{c.get('digg')}）" if c.get("digg") else ""))
        cmt_text = "\n".join(lines)
    user = (f"视频信息：{meta}\n\n画面文字识别：{frame_text or '（无）'}\n\n"
            f"画面理解：{frame_visual or '（无）'}\n\n完整文案（含时间点）：\n{transcript or '（无口播）'}"
            f"\n\n评论区内容（前30条）：\n{cmt_text or '【未获取到评论区内容】'}")
    j = _http_json(
        "https://api.deepseek.com/chat/completions",
        {"Authorization": "Bearer " + DS_KEY, "Content-Type": "application/json"},
        {"model": "deepseek-chat", "temperature": 0.7, "max_tokens": 3500,
         "messages": [{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": user}]}, timeout=300)
    return j["choices"][0]["message"]["content"].strip()


def fetch_comments(share_url, timeout=90):
    """从云端采集服务拉取评论区内容 + 完整互动数据（点赞/评论/收藏/转发）"""
    q = urllib.parse.quote(share_url, safe="")
    url = BACKEND_URL.rstrip("/") + "/api/analyze?url=" + q
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))
