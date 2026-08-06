# -*- coding: utf-8 -*-
"""
云端更新与统计上报模块（不依赖 PyQt，可独立测试）
功能：
  1. check_update       —— 启动时检查是否有新版本
  2. download_update    —— 带 COS 签名下载更新包（支持进度回调）
  3. report_stats       —— 静默上报使用统计
"""
import os
import sys
import json
import uuid
import time
import threading
import urllib.request
import urllib.error

# ── 云端接口地址（HTTP 触发域名） ─────────────────────────
API_BASE = "https://yileyuanyunfuwu-d1f5mb6o341623f5-1462248439.ap-shanghai.app.tcloudbase.com"
# 统一管理后台（采集服务隧道地址；可在 config.json 的 backend_url 字段覆盖）
BACKEND_URL = "https://framework-keys-varying-neutral.trycloudflare.com"
TIMEOUT = 15


def _post(path, payload):
    """POST JSON 到云端，返回解析后的 dict"""
    url = API_BASE.rstrip("/") + "/" + path.lstrip("/")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_device_id(cfg_file):
    """读取/生成稳定的设备 ID（存于 config.json 的 device_id 字段）"""
    cfg = {}
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    did = str(cfg.get("device_id") or "").strip()
    if not did:
        did = uuid.uuid4().hex[:16]
        cfg["device_id"] = did
        try:
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return did


def check_update(current_version, timeout=TIMEOUT):
    """
    检查更新。
    返回 dict（含 hasUpdate/latestVersion/downloadUrl/downloadAuth/downloadToken/notes/size/force）
    失败时返回 None（不抛异常）。
    """
    try:
        r = _post("checkUpdate", {"currentVersion": current_version})
        if not isinstance(r, dict) or r.get("code") != 0:
            return None
        return r
    except Exception:
        return None


def download_update(url, auth, token, save_path, progress_cb=None, timeout=120):
    """
    带 COS 签名下载更新包。
    progress_cb(done_bytes, total_bytes) 可选；total 为 0 时表示未知。
    成功返回 save_path，失败抛异常。
    """
    req = urllib.request.Request(url)
    req.add_header("Authorization", auth)
    if token:
        req.add_header("x-cos-security-token", token)

    done = 0
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        tmp = save_path + ".part"
        with open(tmp, "wb") as f:
            while True:
                buf = resp.read(65536)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                if progress_cb:
                    progress_cb(done, total)
    if os.path.exists(tmp):
        os.replace(tmp, save_path)
    if progress_cb:
        progress_cb(done, done)
    return save_path


def report_stats(cfg_file, app_version, account_count, extra=None):
    """
    静默上报使用统计，失败不抛异常。
    extra 可含 commentCount/liveCount/privateMsgCount/durationMin。
    """
    try:
        payload = {
            "deviceId": get_device_id(cfg_file),
            "appVersion": app_version,
            "platform": "windows" if sys.platform.startswith("win") else sys.platform,
            "accountCount": int(account_count or 0),
        }
        if extra:
            for k in ("commentCount", "liveCount", "privateMsgCount", "durationMin"):
                if extra.get(k) is not None:
                    payload[k] = int(extra[k] or 0)
        _post("reportStats", payload)
    except Exception:
        pass


def report_usage_remote(cfg_file, app, app_version, extra=None):
    """静默上报到统一管理后台（采集服务 /api/report），失败不影响使用。
    app: workbench / zhlian / zhibo / zhijian-exe / zhijian-apk"""
    try:
        url = BACKEND_URL
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("backend_url"):
                    url = str(cfg["backend_url"]).strip()
            except Exception:
                pass
        if not url:
            return
        payload = {
            "deviceId": get_device_id(cfg_file),
            "appVersion": app_version,
            "app": app,
            "platform": "windows" if sys.platform.startswith("win") else sys.platform,
        }
        if extra:
            payload.update(extra)
        req = urllib.request.Request(
            url.rstrip("/") + "/api/report",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=6)
    except Exception:
        pass


# ── 业务动作埋点（本地累计 + 每 60 秒批量上报一次，避免每次回复都发请求） ──
_action_buf = {}
_action_lock = threading.Lock()
_flush_at = 0.0


def report_action(cfg_file, app, action, count=1):
    """记录一次业务动作：评论回复/私信回复/场景特效/视频解析。
    先累计到内存，每 60 秒批量上报一次（失败静默，不影响使用）"""
    global _flush_at
    with _action_lock:
        _action_buf[(app, action)] = _action_buf.get((app, action), 0) + int(count or 1)
    now = time.time()
    if now - _flush_at < 60:
        return
    _flush_at = now
    threading.Thread(target=_flush_actions, args=(cfg_file,), daemon=True).start()


def _flush_actions(cfg_file):
    with _action_lock:
        buf = dict(_action_buf)
        _action_buf.clear()
    if not buf:
        return
    for (app, action), n in buf.items():
        try:
            url = BACKEND_URL
            if os.path.exists(cfg_file):
                try:
                    with open(cfg_file, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    if cfg.get("backend_url"):
                        url = str(cfg["backend_url"]).strip()
                except Exception:
                    pass
            if not url:
                continue
            payload = {
                "deviceId": get_device_id(cfg_file),
                "appVersion": "v2.0.92",
                "app": app,
                "action": action,
                "count": n,
                "platform": "windows" if sys.platform.startswith("win") else sys.platform,
            }
            req = urllib.request.Request(
                url.rstrip("/") + "/api/report",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=6)
        except Exception:
            pass
