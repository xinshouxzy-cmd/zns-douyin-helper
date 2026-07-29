VERSION = "v2.1.0"
# v2.1.0: 重大重构 — 移除 NotificationScout 自动校准，改为手动校准数据系统 (Codex)
#   - 新增 calibration_data.py: 校准数据库（机器级共享 + 账号专属覆盖）
#   - main.py: 新增 CalibrationWizard 7步引导式对话框，登录前可校准
#   - worker.py: Chrome 添加焦点抑制选项（--disable-features=window-activation 等），后台运行不抢前台
#   - 默认评论回复改为: "具体抖音✉️"
#   - 私信页面等待时间从20s缩短到~7s
#   - 保留 v2.0.37 baseline 的评论8步流程结构
#   (基于 v2.0.63: 面板自动重开 + DOM兜底搜索)
