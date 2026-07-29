VERSION = "v2.2.2"
# v2.2.2: 校准流程移到 worker 后台线程，GUI不再阻塞 + 点击无反馈提示 (Codex)
#   - worker.py: 新增 run_calibration_flow / cancel_calibration，通过 _start_calib 信号跨线程触发
#   - main.py: CalibrationWizard 改为异步信号驱动，不再同步阻塞 GUI
#   - 超时从120s缩减到60s，取消按钮可实时响应
#   - 校准对话框提示"点击时浏览器无视觉反馈是正常的"
#   (基于 v2.2.1)
