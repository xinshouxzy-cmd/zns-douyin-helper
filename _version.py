VERSION = "v2.0.58"
# 改动: 修复窗口抢占 + 定位准确性 + 安全加固
#       (1) 移除所有 ActionChains 真实鼠标点击 → 纯JS事件
#       (2) 通知按钮：ActionChains → JS hover + JS click
#       (3) _cmt_click_at 零 ActionChains
#       (4) 坐标加载增加 devicePixelRatio 感知
#       (5) 侦察兵失败兜底录制坐标
#       (6) GUI「重新校准」按钮（线程安全）
#       (7) Chrome 增加 CalculateNativeWinOcclusion 禁用
#       (8) 安全加固：execute_script 改用 arguments 参数化（防注入）
#       (9) 安全加固：_append_log HTML 转义（防UI欺骗）
