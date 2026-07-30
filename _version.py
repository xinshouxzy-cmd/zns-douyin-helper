VERSION = "v2.2.6"
# v2.2.6: 回到v2.0.49方案 — 按钮驱动 + execute_script单次点击 (Codex)
#   - 彻底放弃 execute_async_script+5连点方案（这是所有问题的根源）
#   - do_calibration_step: 改用 execute_script+Promise+单次点击(30s)，与v2.0.49一致
#   - CalibrationWizard: 按钮驱动流程（「已点击，下一步」「跳过」），不再自动循环
#   - 流程：用户在浏览器做准备 → 回窗口点「已点击，下一步」→ 注入JS监听下一次点击 → 捕获
#   - exit_calibration_mode: 保护execute_script调用 + 视口获取失败时使用默认值
#   - 校准坐标在评论流程中优先级最高，DOM搜索兜底
#   (基于 v2.2.5)
