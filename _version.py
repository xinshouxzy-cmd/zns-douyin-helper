VERSION = "v2.0.62"
# v2.0.62: 修复评论流程"全部消息"点击后跳转失败 (Codex)
#   BUG: 全部消息点击后通知面板关闭 — 第二轮重试时面板已消失，流程中断
#   FIX: 面板关闭时自动重新点击通知按钮重新打开，不放弃
#   BUG: 侦察兵 elementFromPoint 扫描返回0按钮 — 抖音顶栏图标无法命中
#   FIX: elementFromPoint 失败后增加 DOM 元素搜索兜底 (header/body 顶栏区域)
#   (基于 v2.0.61: 窗口抢占焦点修复)
