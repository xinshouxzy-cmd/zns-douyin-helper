VERSION = "v2.2.3"
# v2.2.3: 修复校准启动即卡死的根本原因 (Codex)
#   - 根因：AccountWorker(QThread)中 _start_calib.connect(run_calibration_flow) 是直接连接，
#     因为 __init__ 在GUI线程执行，emit 时 run_calibration_flow 直接在GUI线程运行
#   - 修复：新增 _start_calib_thread() 用 Python threading.Thread 启动校准，
#     彻底绕开 Qt 线程亲和性导致的 GUI 阻塞
#   (基于 v2.2.2)
