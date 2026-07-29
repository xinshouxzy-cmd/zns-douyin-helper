# -*- coding: utf-8 -*-
"""
侦察兵 v14 — elementFromPoint 全顶栏扫描 + 悬停验证
- 抖音顶部导航按钮是纯 SVG 图标，没有文字节点，文本搜索注定失败
- 改为：elementFromPoint 扫描整个顶栏 → 去重得到所有按钮 → 逐个悬停验证
- 红点=扫描点，蓝点=悬停轨迹，金色=通知命中
"""

import time
import json
import random
import logging

logger = logging.getLogger("scout")


class NotificationScout:
    def __init__(self, driver, log_func=None):
        self._d = driver
        self._log = log_func or (lambda m: print(m))
        self.notify_x = None
        self.notify_y = None

    # ═══════════════════════════════════════════════════════════
    # 第1步：elementFromPoint 扫描整个顶栏，找出所有独立按钮
    # ═══════════════════════════════════════════════════════════

    def _scan_topbar(self, vw, vh):
        """在顶部 ~8% 区域内，每 3px 一次 elementFromPoint，去重后返回所有独立按钮。
        返回 [{center_x, center_y, left, right, top, bottom, tag, aria_label, title_attr, text, classes}]。
        """
        return self._d.execute_script("""
            (function() {
                var vw = arguments[0];
                var vh = arguments[1];
                var topH = Math.floor(vh * 0.08);

                var seen = {};       // signature -> bounds
                var order = [];      // appearance order

                // 多 Y 线扫描
                var yLines = [];
                for (var y = 4; y < topH; y += 6) yLines.push(y);

                for (var yi = 0; yi < yLines.length; yi++) {
                    var y = yLines[yi];
                    for (var x = vw - 10; x > 10; x -= 3) {
                        var els = document.elementsFromPoint(x, y);
                        if (!els || els.length === 0) continue;

                        // 找第一个有意义的元素（跳过 HTML/BODY/我们自己画的点）
                        var target = null;
                        for (var j = 0; j < Math.min(els.length, 5); j++) {
                            var el = els[j];
                            if (el.getAttribute && el.getAttribute('data-scout')) continue;
                            var tag = el.tagName;
                            if (tag === 'HTML' || tag === 'BODY') continue;
                            target = el;
                            break;
                        }
                        if (!target) continue;

                        // 签名：tag + class前8字符 + aria角色
                        var cls = '';
                        try { cls = (target.className || '').toString().slice(0, 10); } catch(e) {}
                        var role = '';
                        try { role = target.getAttribute('role') || ''; } catch(e) {}
                        var sig = target.tagName + '|' + cls + '|' + role;

                        if (!seen[sig]) {
                            var r = target.getBoundingClientRect();
                            var ariaLabel = '';
                            var titleAttr = '';
                            try {
                                ariaLabel = target.getAttribute('aria-label') || '';
                                titleAttr = target.getAttribute('title') || '';
                                // 也检查子元素
                                var svgTitle = target.querySelector('title');
                                if (svgTitle && !ariaLabel) ariaLabel = (svgTitle.textContent || '').trim();
                            } catch(e) {}

                            seen[sig] = {
                                left: Math.round(r.left),
                                right: Math.round(r.right),
                                top: Math.round(r.top),
                                bottom: Math.round(r.bottom),
                                tag: target.tagName.toLowerCase(),
                                aria_label: ariaLabel.slice(0, 40),
                                title_attr: titleAttr.slice(0, 40),
                                text: (target.textContent || '').trim().slice(0, 40),
                                classes: cls
                            };
                            order.push(sig);
                        } else {
                            // 扩展边界
                            var rr = target.getBoundingClientRect();
                            if (rr.left < seen[sig].left) seen[sig].left = Math.round(rr.left);
                            if (rr.right > seen[sig].right) seen[sig].right = Math.round(rr.right);
                            if (rr.top < seen[sig].top) seen[sig].top = Math.round(rr.top);
                            if (rr.bottom > seen[sig].bottom) seen[sig].bottom = Math.round(rr.bottom);
                        }

                        // 画红点可视化
                        try {
                            var dot = document.createElement('div');
                            dot.setAttribute('data-scout','1');
                            dot.style.cssText = 'position:fixed;z-index:99998;width:3px;height:3px;'+
                                'border-radius:50%;left:'+(x-1)+'px;top:'+(y-1)+'px;'+
                                'background:rgba(255,100,100,0.5);pointer-events:none;';
                            document.body.appendChild(dot);
                        } catch(e) {}
                    }
                }

                // 过滤太小的，输出按钮列表
                var buttons = [];
                for (var i = 0; i < order.length; i++) {
                    var info = seen[order[i]];
                    var w = info.right - info.left;
                    var h = info.bottom - info.top;
                    if (w < 12 || h < 12) continue;  // 太小，可能是分割线
                    if (w > 300 || h > 80) continue;   // 太大，可能是容器

                    buttons.push({
                        center_x: Math.round((info.left + info.right) / 2),
                        center_y: Math.round((info.top + info.bottom) / 2),
                        left: info.left,
                        right: info.right,
                        top: info.top,
                        bottom: info.bottom,
                        tag: info.tag,
                        aria_label: info.aria_label,
                        title_attr: info.title_attr,
                        text: info.text,
                        classes: info.classes
                    });
                }

                // 按 X 从左到右排序
                buttons.sort(function(a,b) { return a.center_x - b.center_x; });

                return JSON.stringify(buttons);
            })();
        """, vw, vh)

    # ═══════════════════════════════════════════════════════════
    # 第2步：悬停验证 — MutationObserver 确认通知面板弹出
    # ═══════════════════════════════════════════════════════════

    def _install_mutation_observer(self):
        self._d.execute_script("""
            window.__scout_new_nodes = [];
            if (window.__scout_observer) window.__scout_observer.disconnect();
            window.__scout_observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    for (var i = 0; i < mutation.addedNodes.length; i++) {
                        var node = mutation.addedNodes[i];
                        if (node.nodeType === 1) {
                            var tag = node.tagName.toLowerCase();
                            if (tag !== 'script' && tag !== 'style' && tag !== 'meta' &&
                                tag !== 'link' && tag !== 'br' && tag !== 'path' && tag !== 'svg' &&
                                tag !== 'circle' && tag !== 'rect' && tag !== 'g') {
                                window.__scout_new_nodes.push(node);
                            }
                        }
                    }
                });
            });
            window.__scout_observer.observe(document.body, {childList: true, subtree: true});
        """)

    def _check_notification_panel(self):
        return self._d.execute_script("""
            (function() {
                var url = window.location.href;
                if (url.indexOf('/message') >= 0 || url.indexOf('/notice') >= 0) return true;

                var nodes = window.__scout_new_nodes || [];
                for (var i = 0; i < nodes.length; i++) {
                    var node = nodes[i];
                    if (!node.isConnected) continue;
                    var r;
                    try { r = node.getBoundingClientRect(); } catch(e) { continue; }
                    if (r.width < 30 || r.height < 30) continue;
                    var s;
                    try { s = window.getComputedStyle(node); } catch(e) { continue; }
                    if (s.display === 'none' || s.visibility === 'hidden') continue;

                    var txt = (node.textContent || '').slice(0, 300);
                    if (txt.indexOf('消息') >= 0 || txt.indexOf('通知') >= 0 ||
                        txt.indexOf('互动') >= 0 || txt.indexOf('评论') >= 0 ||
                        txt.indexOf('赞') >= 0 || txt.indexOf('粉丝') >= 0 ||
                        txt.indexOf('@') >= 0 || txt.indexOf('系统') >= 0 ||
                        txt.indexOf('私信') >= 0 || txt.indexOf('回复') >= 0 ||
                        txt.indexOf('查看') >= 0) {
                        window.__scout_new_nodes = [];
                        return true;
                    }
                    if (r.width > 100 && r.height > 100) {
                        window.__scout_new_nodes = [];
                        return true;
                    }
                }
                window.__scout_new_nodes = [];
                return false;
            })();
        """) or False

    # ═══════════════════════════════════════════════════════════
    # 辅助函数
    # ═══════════════════════════════════════════════════════════

    def _get_viewport(self):
        try:
            w = self._d.execute_script("return window.innerWidth;") or 1100
            h = self._d.execute_script("return window.innerHeight;") or 700
            return int(w), int(h)
        except:
            return 1100, 700

    def _hover_in(self, x, y):
        jitter_y = max(5, y + random.randint(-4, 4))
        try:
            self._d.execute_script("""
                (function(cx,cy) {
                    var oldEl = document.querySelector(':hover');
                    if (oldEl) {
                        ['pointerleave','mouseleave','pointerout','mouseout'].forEach(function(t){
                            oldEl.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:cx,clientY:cy}));
                        });
                    }
                    var el = document.elementFromPoint(cx, cy);
                    if (!el && document.body) el = document.body;
                    if (!el) return;
                    var types = ['pointerenter','mouseenter','pointerover','mouseover','pointermove','mousemove'];
                    for (var i=0; i<types.length; i++) {
                        try {
                            el.dispatchEvent(new MouseEvent(types[i],
                                {bubbles:true,cancelable:true,clientX:cx,clientY:cy,view:window}));
                        } catch(e) {}
                    }
                })(arguments[0], arguments[1]);
            """, x, jitter_y)
        except:
            pass
        return jitter_y

    def _mark(self, x, y, color, size=6):
        try:
            self._d.execute_script("""
                var d = document.createElement('div');
                d.setAttribute('data-scout','1');
                d.style.cssText = 'position:fixed;z-index:99999;width:'+arguments[2]+
                  'px;height:'+arguments[2]+'px;border-radius:50%;'+
                  'left:'+(arguments[0]-arguments[2]/2)+'px;top:'+(arguments[1]-arguments[2]/2)+'px;'+
                  'background:'+arguments[3]+';pointer-events:none;opacity:0.8;';
                document.body.appendChild(d);
            """, x, y, size, color)
        except:
            pass

    def _clear_marks(self):
        try:
            self._d.execute_script(
                "document.querySelectorAll('[data-scout]').forEach(function(e){e.remove();});")
        except:
            pass

    def _dismiss_panel(self):
        try:
            self._d.execute_script("document.body.click();")
        except:
            pass
        time.sleep(0.3)

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    def locate(self):
        """扫描顶栏 → 筛选候选 → 悬停验证"""
        self.notify_x = None
        self.notify_y = None
        vw, vh = self._get_viewport()
        self._clear_marks()

        self._log(f"[侦察兵] 🔍 elementFromPoint 顶栏扫描 (vw={vw}, vh={vh})")

        # ────── 第1步：扫描顶栏所有按钮 ──────
        raw = self._scan_topbar(vw, vh)
        try:
            buttons = json.loads(raw) if raw else []
        except:
            buttons = []

        self._log(f"[侦察兵]   扫描到 {len(buttons)} 个按钮/元素")

        if not buttons:
            self._log("[侦察兵] ⚠ elementFromPoint 未找到元素，尝试 DOM 搜索...")
            # v2.0.62: elementFromPoint 失败后进行 DOM 搜索兜底
            fallback = self._d.execute_script("""
                (function() {
                    var results = [];
                    var topH = Math.floor(window.innerHeight * 0.08);
                    // 搜索顶栏区域内的所有可见元素
                    var all = document.querySelectorAll('header *');
                    if (!all.length) {
                        // 如果没有 header，搜索整个 body 顶部区域
                        all = document.querySelectorAll('body *');
                    }
                    var seen = {};
                    for (var i = 0; i < all.length; i++) {
                        var el = all[i];
                        var r = el.getBoundingClientRect();
                        // 只在顶栏区域
                        if (r.top < 0 || r.top > topH || r.bottom < 0) continue;
                        if (r.width < 8 || r.height < 8) continue;
                        var tag = el.tagName.toLowerCase();
                        if (tag === 'html' || tag === 'body' || tag === 'head' || tag === 'script' || tag === 'style') continue;
                        var cx = Math.round(r.left + r.width / 2);
                        var cy = Math.round(r.top + r.height / 2);
                        var sig = cx + ',' + cy;
                        if (seen[sig]) continue;
                        seen[sig] = true;
                        var ariaLabel = (el.getAttribute('aria-label') || '').slice(0, 40);
                        var titleAttr = (el.getAttribute('title') || '').slice(0, 40);
                        var text = (el.textContent || '').trim().slice(0, 40);
                        results.push({
                            center_x: cx, center_y: cy,
                            left: Math.round(r.left), right: Math.round(r.right),
                            top: Math.round(r.top), bottom: Math.round(r.bottom),
                            tag: tag, aria_label: ariaLabel,
                            title_attr: titleAttr, text: text,
                            classes: (el.className || '').toString().slice(0, 10)
                        });
                    }
                    return JSON.stringify(results);
                })();
            """)
            try:
                fallback_buttons = json.loads(fallback) if fallback else []
                self._log(f"[侦察兵]   DOM 搜索找到 {len(fallback_buttons)} 个元素")
                if fallback_buttons:
                    return fallback_buttons
            except:
                pass
            self._log("[侦察兵] ❌ 顶栏未找到任何元素（elementFromPoint + DOM 搜索均失败）")
            return None

        # 打印每个按钮的详情（调试用）
        for i, btn in enumerate(buttons):
            self._log(f"[侦察兵]   [{i}] ({btn['center_x']},{btn['center_y']}) "
                      f"aria=\"{btn['aria_label']}\" title=\"{btn['title_attr']}\" "
                      f"text=\"{btn['text']}\" tag={btn['tag']}")

        # ────── 第2步：筛选候选 ──────
        # 优先级1: aria-label 或 title 明确含"通知""消息"
        candidates = []
        for btn in buttons:
            al = btn['aria_label'].lower()
            ti = btn['title_attr'].lower()
            tx = btn['text'].lower()
            combined = al + ti + tx
            if any(kw in combined for kw in ['通知', '消息', 'notification', 'notice', 'message', 'bell']):
                candidates.insert(0, btn)  # 高优先级，排最前
                self._log(f"[侦察兵]   ⭐ aria/title 命中: ({btn['center_x']},{btn['center_y']})")
            elif 15 <= btn['right'] - btn['left'] <= 80:
                candidates.append(btn)  # 尺寸像小图标按钮

        # 去重（按 center_x 合并相近的）
        deduped = []
        for btn in candidates:
            dup = False
            for d in deduped:
                if abs(btn['center_x'] - d['center_x']) < 10:
                    dup = True
                    break
            if not dup:
                deduped.append(btn)

        self._log(f"[侦察兵]   候选按钮: {len(deduped)} 个")

        # ────── 第3步：逐个悬停验证 ──────
        for btn in deduped:
            cx = btn['center_x']
            cy = btn['center_y']
            self._log(f"[侦察兵] 🎯 悬停: ({cx},{cy})")

            self._install_mutation_observer()
            time.sleep(0.05)

            actual_y = self._hover_in(cx, cy)
            self._mark(cx, actual_y, "#4488ff", 5)
            time.sleep(0.5)

            if self._check_notification_panel():
                self._mark(cx, actual_y, "#ffaa00", 12)
                self._log(f"[侦察兵] ✅ 通知面板弹出 @ ({cx},{actual_y})")
                self._dismiss_panel()
                self.notify_x, self.notify_y = cx, actual_y
                return (cx, actual_y)

            self._log(f"[侦察兵]   ✗ 未触发")

        # ────── 第4步：精细扫描（在每个候选按钮内部逐像素悬停）──────
        self._log("[侦察兵] 🔍 候选未触发，精细扫描...")
        for btn in deduped:
            for sx in range(btn['left'] + 2, btn['right'] - 1, 2):
                self._install_mutation_observer()
                actual_y = self._hover_in(sx, btn['center_y'])
                self._mark(sx, actual_y, "#4488ff", 3)
                time.sleep(0.25)
                if self._check_notification_panel():
                    self._mark(sx, actual_y, "#ffaa00", 10)
                    self._log(f"[侦察兵] ✅ 精细命中 @ ({sx},{actual_y})")
                    self._dismiss_panel()
                    self.notify_x, self.notify_y = sx, actual_y
                    return (sx, actual_y)

        self._log("[侦察兵] ❌ 未找到通知按钮")
        return None
