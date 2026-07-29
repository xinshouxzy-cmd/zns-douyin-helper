VERSION = "v2.2.1"
# v2.2.1: 修复校准中5连点拦截导致页面无法导航的问题 (Codex)
#   - worker.py: do_calibration_step 确认后自动补一发真实点击触发页面导航
#   - 校准坐标优先用于第2步全部消息和第3步评论点击
#   - CalibrationWizard 保存后自动关闭对话框不再卡住
#   (基于 v2.2.0)
