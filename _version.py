VERSION = "v2.0.63"
# 改动
#       (1) Step 7 发送按钮修复：抖音红色发送按钮是SVG图标（无文字），
#           改用 v2.0.37 的 elementFromPoint 坐标定位方案
#       (2) Step 7a 新增：发送前先点击输入框确保焦点
#       (3) Step 7b：粘贴回复内容到输入框
#       (4) Step 7c：elementFromPoint 定位SVG/button/send/submit → 点击发送
