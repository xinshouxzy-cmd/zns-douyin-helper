VERSION = "v2.0.66"
# 改动
#       (1) 工具集合整合版：新增启动页（门户页 home_page.py），
#           打开软件先展示工具入口卡片，点击进入『评论私信助手』或『直播助手』
#       (2) 新增直播助手页面（live_page.py）：整合原 live_assistant.py，
#           Playwright 监控直播评论 + 扣子 Coze AI 生成回复话术，独立配置/启停
#       (3) 顶层工具栈 root_stack：启动页 → 评论私信助手 / 直播助手，支持返回首页
#       (4) 保留云端自动更新（updater.py）与统计上报（reportStats）
