VERSION = "v2.2.4"
# v2.2.4: 修复跨线程WebDriver调用导致点击无反应 (Codex)
#   - 根因：Selenium WebDriver 不支持跨线程调用，v2.2.3 用 threading.Thread 
#     跑校准，_d.execute_async_script() 在非 WebDriver 线程中静默失败
#   - 修复：_start_calib 仅设置 _request_calibration 标志，由 worker 的
#     run() 轮询循环在自身线程检测并执行 run_calibration_flow()
#   - 这才是唯一正确的异步方案：标志驱动 + worker 自身线程执行
#   (基于 v2.2.3)
