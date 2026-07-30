VERSION = "v2.0.61"
# 改动
#       (1) 核心修复：_cmt_click_at 恢复 v2.0.37 ActionChains 方案（move_to_element_with_offset
#           会移动真实鼠标光标，触发抖音hover事件，通知铃铛可正常打开）
#       (2) 删除 _cmt_hover_at（ActionChains 的 move 自身已触发 hover）
#       (3) 删除 _do_fast_cycle，_cmt_cycle 改写为 v2.0.37 简洁逻辑 + 手动校准坐标支持
#       (4) Step 1~3 优先使用校准坐标（ActionChains点击），Step 4~7 DOM扫描回复
