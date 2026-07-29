VERSION = "v2.0.61"
# v2.0.61: 两大致命问题修复（Codex）
#   1. 窗口抢占焦点：_cmt_cycle 所有点击改用 _cmt_click_at (JS/CDP优先，不抢焦点)
#      - 步骤1通知点击：ActionChains → _cmt_click_at
#      - _enter_stranger: ActionChains → JS click
#      - _send_pm_reply: ActionChains.send_keys → elem.send_keys/JS
#      - _paste: ActionChains → CDP Input.dispatchKeyEvent
#   2. 跨电脑坐标不准：步骤4提取评论增强教程文字黑名单过滤
#   (基于 v2.0.60: 侦察兵v14 + 私信等待优化)
