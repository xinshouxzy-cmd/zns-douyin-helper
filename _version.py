VERSION = "v2.0.65"
# 改动
#       (1) 环境自检：启动时输出系统版本/屏幕缩放/分辨率/Chrome版本到日志（远程排障用）
#       (2) 启动参数适配新 Chrome：补充 --disable-background-timer-throttling、--no-first-run 等，
#           保留遮挡检测禁用（防"抢窗口"），移除写死的 --force-device-scale-factor=1
#       (3) 窗口大小自适应屏幕（不超过屏幕90%），避免小屏/高缩放导致窗口越界
#       (4) 主界面新增「导出日志」按钮，一键导出运行日志为 txt 供分析
