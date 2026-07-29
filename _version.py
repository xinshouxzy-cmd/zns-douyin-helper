VERSION = "v2.0.61"
# 改动: 修复窗口抢占 + 定位准确性
#       (1) 移除所有 ActionChains 真实鼠标点击 → 全部替换为纯JS事件
#       (2) 通知按钮：ActionChains真实点击 → JS hover + JS click
#       (3) _cmt_click_at 方法3：ActionChains兜底 → 完整JS鼠标事件链
#       (4) 坐标加载增加 devicePixelRatio 感知
#       (5) 侦察兵失败时不再直接跳过 → 使用录制坐标兜底
#       (6) 新增 GUI「重新校准」按钮，换电脑后可手动触发
#       (7) Chrome 启动增加 CalculateNativeWinOcclusion 禁用
