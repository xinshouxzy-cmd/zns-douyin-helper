# -*- coding: utf-8 -*-
"""
校准数据管理模块
- 每台电脑共享一份校准数据（基于机器标识）
- 每个账号可单独覆盖
- 存储路径: comment_data/calibration.json
"""

import os
import json
import uuid
import hashlib
import platform
import socket
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CALIBRATION_FILE = os.path.join(BASE_DIR, "comment_data", "calibration.json")

# 7个校准步骤的定义
CALIBRATION_STEPS = [
    {"id": "1_通知图标", "label": "通知铃铛图标", "desc": "点击页面右上角的通知铃铛图标🔔", "tip": "通常在页面右上角，头像左侧"},
    {"id": "2_全部消息", "label": "「全部消息」按钮", "desc": "点击通知面板中的「全部消息」", "tip": "弹出面板后，找到「全部消息」标签页"},
    {"id": "3_评论筛选", "label": "「评论」筛选标签", "desc": "点击左侧导航中的「评论」", "tip": "在消息页面左侧的导航栏中"},
    {"id": "4_第一条评论", "label": "第一条评论内容", "desc": "点击第一条评论（任意一条未回复的评论）", "tip": "点击评论的文字内容区域即可"},
    {"id": "5_回复按钮", "label": "「回复」按钮", "desc": "点击评论详情中的「回复」按钮", "tip": "在评论展开后的底部或评论文字下方"},
    {"id": "6_输入框", "label": "回复输入框", "desc": "点击回复输入框", "tip": "展开回复后出现的输入区域"},
    {"id": "7_发送按钮", "label": "「发送」按钮", "desc": "点击发送按钮 ✉️", "tip": "输入框右侧的发送/纸飞机按钮"},
]


def _get_machine_id():
    """生成机器唯一标识（基于硬件信息，同电脑不变）"""
    try:
        info = f"{platform.node()}_{socket.gethostname()}"
        mid = hashlib.md5(info.encode()).hexdigest()[:12]
        return mid
    except:
        return str(uuid.getnode())[:12]


def _create_guid():
    """生成校准会话 GUID"""
    return uuid.uuid4().hex[:8]


def load_calibration():
    """加载校准数据库"""
    if os.path.exists(CALIBRATION_FILE):
        with open(CALIBRATION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"machine_id": _get_machine_id(), "shared": None, "accounts": {}}


def save_calibration(data):
    """保存校准数据库"""
    os.makedirs(os.path.dirname(CALIBRATION_FILE), exist_ok=True)
    with open(CALIBRATION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_positions_for_account(account_name):
    """
    获取某个账号的评论坐标
    优先级：账号专属校准 > 机器共享校准 > 录制 positions.json 兜底
    返回: dict 或 None（需要校准）
    """
    cal = load_calibration()

    # 1. 检查账号专属校准
    if account_name in cal.get("accounts", {}):
        acc = cal["accounts"][account_name]
        if acc and len(acc) >= 5:  # 至少有5个有效步骤
            return _format_positions(acc, account_name)

    # 2. 检查机器共享校准
    shared = cal.get("shared")
    if shared and len(shared) >= 5:
        return _format_positions(shared, "本机共享")

    # 3. 检查录制兜底文件
    pos_file = os.path.join(BASE_DIR, "comment_data", "positions.json")
    if os.path.exists(pos_file):
        try:
            with open(pos_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            positions = {}
            for k, v in raw.items():
                if k.startswith("_"):
                    continue
                if "x_pct" in v:
                    positions[k] = {"x": -1, "y": -1, "x_pct": v["x_pct"], "y_pct": v["y_pct"]}
            positions["_source"] = "positions.json(百分比)"
            positions["_resolution"] = raw.get("_resolution", "?")
            return positions
        except:
            pass

    return None


def save_account_calibration(account_name, steps_data, viewport):
    """保存某个账号的校准数据（覆盖模式）"""
    cal = load_calibration()
    cal["machine_id"] = cal.get("machine_id") or _get_machine_id()
    cal.setdefault("accounts", {})[account_name] = {
        "_resolution": f"{viewport['w']}x{viewport['h']}",
        "_dpr": viewport.get("dpr", 1),
        "_calibrated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **steps_data
    }
    save_calibration(cal)


def save_shared_calibration(steps_data, viewport):
    """保存机器共享校准数据"""
    cal = load_calibration()
    cal["machine_id"] = cal.get("machine_id") or _get_machine_id()
    cal["shared"] = {
        "_resolution": f"{viewport['w']}x{viewport['h']}",
        "_dpr": viewport.get("dpr", 1),
        "_calibrated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **steps_data
    }
    save_calibration(cal)


def copy_shared_to_account(account_name):
    """将机器共享校准复制到某个账号"""
    cal = load_calibration()
    shared = cal.get("shared")
    if not shared:
        return False
    cal.setdefault("accounts", {})[account_name] = dict(shared)
    cal["accounts"][account_name]["_calibrated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_calibration(cal)
    return True


def has_shared_calibration():
    """检查是否有机器共享校准"""
    cal = load_calibration()
    shared = cal.get("shared")
    return shared is not None and len(shared) >= 5


def has_account_calibration(account_name):
    """检查某个账号是否有专属校准"""
    cal = load_calibration()
    acc = cal.get("accounts", {}).get(account_name)
    return acc is not None and len(acc) >= 5


def _format_positions(raw, source_name):
    """将校准数据格式化为坐标字典"""
    positions = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            positions[k] = {"x": v.get("x", -1), "y": v.get("y", -1)}
    positions["_source"] = source_name
    positions["_resolution"] = raw.get("_resolution", "?")
    positions["_dpr"] = raw.get("_dpr", 1)
    return positions


def get_calibration_status(account_name):
    """获取校准状态摘要"""
    cal = load_calibration()
    has_shared = has_shared_calibration()
    has_acc = has_account_calibration(account_name)
    shared_time = ""
    acc_time = ""
    if cal.get("shared") and cal["shared"].get("_calibrated_at"):
        shared_time = cal["shared"]["_calibrated_at"]
    if account_name in cal.get("accounts", {}):
        acc_time = cal["accounts"][account_name].get("_calibrated_at", "")
    return {
        "has_shared": has_shared,
        "has_account": has_acc,
        "shared_time": shared_time,
        "account_time": acc_time,
        "machine_id": cal.get("machine_id", "?")
    }
