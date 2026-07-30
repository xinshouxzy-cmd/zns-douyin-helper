VERSION = "v2.2.5"
# v2.2.5: 回到 v2.2.0 同步方案 — 唯一经过验证的可行方案 (Codex)
#   - 移除所有异步/跨线程/轮询机制，回到最简方案：
#     CalibrationWizard._start() 同步调用 enter_calibration_mode → do_calibration_step×3 → exit_calibration_mode
#   - Selenium execute_async_script 从 GUI 线程发起 HTTP 调用（已验证可行）
#   - 校准期间 GUI 会短暂无响应（每步最多60s），但这是唯一靠谱的做法
#   - 修复保存：try-catch 包裹 exit_calibration_mode，不再同时调用 accept+reject
#   (基于 v2.2.4)
