VERSION = "v2.2.0"
# v2.2.0: 校准系统简化 — 7步→3步 + 浏览器5连点自动确认 (Codex)
#   - calibration_data.py: CALIBRATION_STEPS 7→3（通知铃铛/全部消息/评论筛选）
#   - worker.py: do_calibration_step 改为5连点检测（execute_async_script），超时60s→120s
#   - main.py: CalibrationWizard 3步简化UI，移除「已点击下一步」「跳过」按钮
#   - 移除运行时「重新校准」按钮和 recal_done/recalibrate_now 机制
#   - 校准入口统一在确认登录面板旁
#   (基于 v2.1.0)
