# -*- coding: utf-8 -*-
"""
桌面悬浮便签（Tkinter，独立线程运行）—— Microsoft 便笺风格。

复刻 Microsoft 便笺（Sticky Notes）核心体验：
- 无边框便利贴窗口：**顶栏为金黄（#fff2ab）**，**正文与底栏同为淡黄（#fff7d1）**
- 双模式：编辑模式（顶栏 + 编辑器 + 底栏）/ 浏览模式（纯内容展示）
- 点便签内 → 进入编辑模式；点便签外（窗口失焦）→ 退出编辑模式
- 顶栏：左「+」右「…」「×」（仅编辑模式）；底栏：B / I / U / ab / ≡（无序）/ 1.（有序）/ 图片（仅编辑模式）
- 顶栏与底栏均可拖动移动窗口

背景：pywebview 6.2.1 的 winforms 后端多窗口实测不稳定，
故桌面便签用 Python 自带 Tkinter 在独立线程中运行。
数据：由注入的 DesktopApi 读写 exe 同目录 桌面便签数据.json。

===================== 关键设计（改这几处时务必先读懂） =====================

1) 【顶栏恒高占位；底栏退出编辑**不占位**】
   布局不是「顶栏 → 正文 → 底栏」直接切换，而是：
       top_holder（**恒定** TOP_BAR_HEIGHT，pack_propagate(False)）
           └─ top_bar（编辑模式挂载 / 浏览模式卸下）
       body（正文，pack fill both expand）
       bot_holder（编辑态挂载 BOTTOM_BAR_HEIGHT / 浏览态**整块 pack_forget**，不占位）
           └─ bottom_bar（同上）
   顶栏 holder 高度**永远不变** → 退出编辑时文字不会上移「吃掉」原来标题栏那一块
   （老板 0914s 的硬要求：文字不能挤占标题栏消失后的空间）。
   底栏 holder **浏览态整块 pack_forget** → 工具栏退出编辑后**不做占位**，
   正文一直延伸到底边（老板 0914v 的要求）。
   🔴 不能用 `holder.configure(height=0)` 代替 —— Tk 的 Frame 把 `-height 0` 当作
      「未指定/自适应」直接忽略，实测槽高仍等于常量值（踩过）。必须 pack_forget。
   🔴 重新 pack **必须** `before=self._body`：body 里的 Text 请求高 ≈ 480px > 可用高，
      占位槽若排在 body 之后，expand 的 body 会把剩余空间全吃掉 → 槽分到 0px → 不映射、
      底栏整条消失。`self._body` 从不卸下，故这里 `before=` 是安全的
      （历史坑是 before 指到了会被 forget 的 editor 上）。

2) 【单一 Text 承担两种模式】—— 浏览模式不再是 Label
   Label 无法滚动，且与 Text 是两套控件容易产生位置/尺寸差异。
   现在始终用同一个 Text：
       编辑模式 state="normal"（可写）
       浏览模式 state="disabled"（可滚、可点，点一下进编辑）
   位置恒定、滚动条复用、切换零跳动。浏览态点击即进编辑，故无需在浏览态选中文字。

3) 【自绘滚动条】—— 对齐参考图
   Tk 原生 Scrollbar / ttk 无法做出「空闲极细淡色条、悬浮变宽变灰」。
   用 Canvas 自绘：内容未溢出时完全不绘制（_sb_visible=False）；
   空闲：贴右边缘的淡黄褐细条（5px）；悬浮：浅灰槽 + 深灰滑块 + 上下箭头（12px）。
   Canvas 固定宽 SBAR_W=12 并常驻 place 在 body 右上角，靠右绘制，
   这样鼠标进得来（能触发 hover），空闲时又不挡正文点击太多。

4) 【无边框窗口的拉伸】—— 8 个热区
   overrideredirect(True) 的窗口没有系统边框，无法用原生方式拉伸。
   在 root 上用 place 铺 4 条边 + 4 个角的隐形 Frame（HANDLE=5px，带 cursor），
   拖拽时按起始 geometry 换算新的 x/y/w/h（含最小尺寸钳制）。

历史教训（务必保留）：`pack(before=...)` 的 `before` 目标必须**当前已挂载**，
否则 Tk 抛 `TclError: window ... isn't packed`。本窗口在「编辑→浏览→编辑」切换中
会 pack_forget 顶栏/底栏，若写 `before=self._editor` 就会整条链断掉 →
顶栏/底栏/编辑器全不显示（窗口空白）且无法拖动。故本版**完全不使用 `before=`**，
每次进入编辑都「先全部卸载、再按固定顺序重挂」，与之前挂载状态无关。

5) 【四角圆角 = Win11 DWM 抗锯齿圆角】（2026-09-14 起；替代旧的 SetWindowRgn）
   `DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE=33, DWMWCP_ROUND=2)`
   由 DWM 在合成层把窗口四角裁成圆角，**圆弧是抗锯齿的**（这是关键）。
   🔴 旧的 `CreateRoundRectRgn` + `SetWindowRgn` 是 1 位 region 裁切 —— 圆弧必然是
      硬边台阶，放大看就是一串「像素点」（老板明确否掉）。现仅作老系统回退。
   🔴 实测：无边框 `overrideredirect`（WS_POPUP）窗口上 DWM 圆角**有效且不引入原生
      边框**（不要加 WS_THICKFRAME/WS_CAPTION —— 会多出 7px 系统边框）。
   🔴 必须同时设 `DWMWA_BORDER_COLOR = DWMWA_COLOR_NONE`：DWM 给圆角窗口默认画一圈
      **1px 半透明边框**，会让窗口最外一行/一列不再是栏色（又一条「空隙」）。
   🔴 属性要在窗口**已映射**后设置才生效（hidden 时设会返回 S_OK 但不生效）→
      在 `<Map>` 与每次 `_present()` 里强制重设。
   🔴 DWM 圆角与窗口尺寸无关 → 缩放不用重设，不需要 `<Configure>` 钩子。
   🔴 顶栏 holder 高度恒定（设计 1），内层必须 `fill="both", expand=True`
      铺满 holder；主容器**不加 1px 边框**（那圈浅色线叠在金黄条上看着就是「留白」）。

6) 【拉伸热区必须与「它盖住的东西」同色】（2026-09-14 起）
   8 个拉伸热区是**不透明 Frame**，place 在最上层 —— 会把它下面的窗口内容挡住。
   底色取错就会在金黄顶栏上沿 / 底栏下沿露出一条浅色带（老板看到的「空隙」）。
   规则：顶边 / 两个上角 = 顶栏色（编辑态 `BAR_BG` 金黄、浏览态 `NOTE_BG`）；
         底边 / 两个下角 / 左边 / 右边 = `NOTE_BG`（0914x 起底栏底色 = 正文色，
         故底边 & 下角不能再取金黄，否则底栏下沿会露金黄带）。
         左边 / 右边只跨**正文区**垂直范围，不侵入顶栏。
   模式切换时必须调 `_refresh_handle_colors()` 跟着换色。
   🔴 左右两条的**垂直跨度也随模式变**（浏览态底栏不占位 → 要延伸到底边），
      统一由 `_layout_side_handles()` 放置；模式切换时一并调用。

7) 【列表按钮 = 按行改纯文本，不是富文本 <ul>】（2026-09-14 0914y 起）
   Tk 的 Text 里没有列表概念 → 列表就是**在行首写标记**：无序 `• ` / 有序 `1. 2. 3. `。
   `_toggle_list(kind)` 的规则（**0914z 起与主界面 `<ol>/<ul>` 行为对齐**）：
      · **作用于选中的每一行**（`_selected_lines()` 解析选区跨行；无选区则光标所在行）。
        🔴 旧实现只取 `ed.index("insert")` 一行 → 老板报的「选中多行只给最后一行加点」。
      · 「整块已是本类型」→ 摘掉（再点一次取消）。
        🔴 **只看标记类型，不校验序号对错** —— 主界面编号由浏览器自动生成、用户改不了手写号，
        「号乱」这种状态在主界面根本不存在；故 0914z 起取消原「号乱就重排」行为，一律「再点即取消」。
      · 两种标记**互相摘除**后再加新标记 → 无序 ↔ 有序 可直接互转，不会出现「• 1. x」。
      · 有序**顺延**：**紧邻**上一行是有序项 → 从它的号 +1 接着排；否则从 1 开始。
      · 摘/加都保留**前导空白**（缩进行不丢缩进）；加标记的插入点在前导空白之后。
      · 有选区时操作完**重新框住整块**：插删标记会顶偏原 sel 索引，不重设会让连点两次错位。
      · 行号上限用 `end`（不是 `end-1c`）—— 光标可停在正文末尾那行，那里点按钮也要生效。
   🔴 `_LIST_RE` / `_NUM_RE` 的序号限 **1~3 位**：`\d+` 会把「2026. 年度计划」当有序项 → 摘掉用户正文。
   🔴 **回车自动续号**（`_on_return`，0914z 新增）：对齐主界面 —— 非空项回车 → 新行自动带
      下一个标记（有序 = 号 +1 / 无序 = `• `）；**空项**回车 → 摘掉标记、退出列表（变普通空行）。
      不实现这条，老板会觉得「悬浮便签的列表规则和主界面不一致」（主界面里回车由浏览器处理）。
"""
from __future__ import annotations

import ast
import base64
import ctypes
import gc
import io
import math
import os
import re
import threading
import time
import tkinter as tk
from ctypes import wintypes as _wt
from ctypes import wintypes            # 外部文件拖放（WM_DROPFILES）要用 wintypes.HWND/HANDLE
from tkinter import filedialog

# ---- 图片支持（Pillow）：Tk 原生 PhotoImage 只认 PNG/GIF，JPEG/GIF/WebP 全靠 Pillow ----
try:
    from PIL import Image as _PILImage
    from PIL import ImageTk as _PILImageTk
    _HAS_PIL = True
except Exception:                 # 极简环境 / 未装 Pillow → 插图按钮给出明确提示
    _PILImage = None
    _PILImageTk = None
    _HAS_PIL = False

# 🔴 剪贴板图片要用 ImageGrab，必须**模块级**导入：写在函数里 PyInstaller 静态分析扫不到，
#    打出来的 exe 会缺 PIL.ImageGrab → 粘贴图片静默失效（build.spec 里也加了 hiddenimports 双保险）。
try:
    from PIL import ImageGrab as _PILImageGrab
except Exception:
    _PILImageGrab = None

# ---- 系统剪贴板读写（图片右键菜单：复制 / 剪切 / 粘贴 / 粘贴为纯文本）----
# 🔴 与主界面**共用同一份实现**（主界面经 pywebview 桥调同一个模块）→ 两侧复制出的图片
#    完全等价，可以互粘（悬浮便签复制 → 粘进主界面，反之亦然）。
try:
    import clip_io as _clip
except Exception:                 # 模块缺失时菜单里这些项直接不生效（不崩）
    _clip = None

# ---- Win32：无边框窗口的四角圆角 ----
# 首选 Win11 DWM 抗锯齿圆角；老系统 / 不支持时回退 SetWindowRgn（硬边，有台阶像素）。
try:
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
    # 🔴 64 位下必须显式声明 restype/argtypes，否则 HANDLE 被截断成 32 位 int，句柄损坏。
    _gdi32.CreateRoundRectRgn.restype = _wt.HANDLE
    _gdi32.CreateRoundRectRgn.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int,
    ]
    _user32.SetWindowRgn.argtypes = [_wt.HWND, _wt.HANDLE, _wt.BOOL]
    _user32.SetWindowRgn.restype = ctypes.c_int
    _user32.GetAncestor.restype = _wt.HWND
    _user32.GetAncestor.argtypes = [_wt.HWND, ctypes.c_uint]
    _HAS_WIN32 = True
except Exception:            # 非 Windows 等极简环境
    _HAS_WIN32 = False

try:
    _dwmapi = ctypes.windll.dwmapi
    _dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        _wt.HWND, _wt.DWORD, ctypes.c_void_p, _wt.DWORD,
    ]
    _HAS_DWM = True
except Exception:
    _HAS_DWM = False

DWMWA_WINDOW_CORNER_PREFERENCE = 33   # Win11 22000+
DWMWA_BORDER_COLOR = 34               # Win11 22000+
DWMWCP_ROUND = 2                      # 系统抗锯齿圆角（半径由系统给，约 8~10px）
DWMWA_COLOR_NONE = 0xFFFFFFFE         # 不画边框


# ======================== 颜色 ========================
# ⚠️ 0916b 起本模块**不再用一组单片常量描述颜色**：正文 / 顶栏 / 文字 / 图标 / 分隔线 /
#    滚动条 / 占位符的运行时取值全部来自下方「悬浮便签配色」段的 `NOTE_THEMES` 一张表。
#    原因：老板 0916b 的 7 张参考图要求「顶栏与正文**两级同色系**」，每一档都是一套独立
#    色值 —— 已不是「一个常量管一处」的关系。
#    原来那批黄系单值常量（BAR_BG / NOTE_FG / ICON_FG / PLACEHOLDER_FG / BORDER /
#    BTN_HOVER / SBAR_THUMB / SBAR_TROUGH / SBAR_ARROW）的值**一个都没变**，只是搬进了
#    `NOTE_THEMES` 的「黄」行（老板 0914x 定稿的观感完整保留）。改色请改表，改这里无效。
#
# 底栏（文字工具栏）底色 = 正文底色（老板 0914x 要求两处一致）→ 表里没有单列这一项，
# 底栏各处直接取 `self._note_bg`，正文换色时底栏自动跟随。
NOTE_BG = "#fff7d1"          # 默认底色 key（`_norm_bg` 兜底 + 新建便签复位都用它）
SBAR_THUMB_HOVER = "#a6a6a6"  # 滚动条「悬浮滑块」= 中性灰，7 档通用，不进表

# 默认窗口尺寸
WIN_WIDTH = 320
WIN_HEIGHT = 380
TOP_BAR_HEIGHT = 30          # 顶栏（金黄「标题栏」）高度：0914w 收窄（36 → 30）
BOTTOM_BAR_HEIGHT = 36       # 底栏（文字工具栏）高度：0914w 收窄（46 → 36）
ICON_H = 22                  # 底栏图标画布高：**7 个图标统一 22×22**（0914z 老板要求列表图标同尺寸）
ROUND_RADIUS = 12            # 仅「回退方案」用：SetWindowRgn 硬边圆角半径（DWM 圆角半径由系统定）
SBAR_W = 12                  # 滚动条画布宽（常驻，空闲只画右侧 5px）
HANDLE = 5                   # 拉伸热区厚度
MIN_W, MIN_H = 220, 140      # 最小尺寸（随顶栏收窄同步下调）
PLACEHOLDER = "记笔记..."

# ---- 正文字号（0915n：老板要求「悬浮便签字体小一点」）----
# 基准 11pt → 10pt。这三个常量是唯一的真相来源：正文 / bold / italic 三处都用它，
# 改字号只改这里。
# 🔴 动态字号 tag（主界面写过来的 `fs_N` / `fsb_N`）**不**跟着缩：
#    N 是主界面里的绝对值（比如主界面写 16px → 折算 12pt），这里再缩会让
#    「一行里默认字和放大字」的相对关系乱掉。若要整体缩，改进 `_pt_from_css_size`
#    的折算系数，别在 tag 侧减。
NOTE_FONT_FAMILY = "Microsoft YaHei"
NOTE_FONT_PT = 10            # 正文基准字号（原 11）
# 0917 老板要求：悬浮便签菜单里加「字号设置」（滑动调节），且**全局统一** ——
#   对全部悬浮便签生效，此后新建的也沿用（所以存进桌面便签 JSON 的 settings，而不是 per-note）。
#   范围 8~16pt：再小读不清，再大一条便签装不下几行字。
NOTE_FONT_MIN = 8
NOTE_FONT_MAX = 16
NOTE_FONT_DEFAULT = NOTE_FONT_PT
NOTE_FONT_KEY = "font_pt"    # 存进 `桌面便签数据.json` → `settings.font_pt`
FONT_SAVE_DEBOUNCE_MS = 300  # 拖动滑块时别每帧写盘（界面立即生效，落盘防抖）

# ======================== 悬浮便签配色（0916 / 0916b） ========================
# 0916：老板要求点顶栏「⋯」→ 弹出背景颜色设置，**只对本条悬浮便签生效**（per-note）。
# 0916b：老板给了 7 张配色参考图（黄 / 绿 / 粉 / 紫 / 蓝 / 灰 / 炭笔），原话
#        「注意标题颜色，和正文颜色」—— 顶栏与正文要**两级同色系**（顶栏更深、
#        正文更浅），不再是「顶栏固定金黄 + 只换正文」。
#
# 取色：`_ref7_0916b.py` + `_ref7b_0916b.py` 对 7 张图**逐像素**扫描得到
#   · bar  = 顶栏主色（大面积纯色，最可靠）
#   · body = 正文 / 底栏主色（= `bgColor` 的 key）
#   · fg   = 正文文字（浅底 6 张实测全是 #333333；炭笔 #ffffff —— 老板原话「文字变为白色」）
#   · icon = 底栏工具图标线条主色（实测最高频档）
# 派生项（hover / border / ph / sb / trough / arrow）混合比是**从黄色那张反解**出来的
#   （黄 = 老板 0914x 定稿的现有常量，一个都不动 → 零视觉回归），并被参考图实测到
#   的次要色逐条印证：绿图 `#a5b4a2`、粉图 `#b8a5ae`、紫图 `#afa6b8`、蓝图 `#a3aeb8`
#   与本表 `ph` 值**完全一致**（±1 以内）—— 说明这就是参考图自己的派生规律。
#
# 🔴 三组「值域封闭集合」（body / bar / border）必须**两两互斥**：
#   遍历刷色靠「控件的 bg 落在哪个集合里」决定改成什么色。集合一旦有交集，顶栏就会
#   被当成正文改掉（或反之）—— 这是静默串色的根因。测试里有专门的互斥断言。
NOTE_THEMES = {
    # key = 正文底色（落盘值）；bar = 顶栏色；fg = 正文文字；icon = 顶栏按钮 / 底栏图标
    "#fff7d1": dict(name="黄",   bar="#fff2ab", fg="#333333", icon="#5c5648",
                    hover="#f7ea9e", border="#e8dfb4", ph="#b7ae90", sb="#ddd3a3",
                    trough="#f2f1ea", arrow="#5c5648", sel="#ffe9a8"),
    "#e4f9e0": dict(name="绿",   bar="#cbf1c4", fg="#333333", icon="#5b645a",
                    hover="#c0e3b9", border="#cde0c9", ph="#a5b4a2", sb="#c0d2bd",
                    trough="#d9edd5", arrow="#5b645a", sel="#cbf1c4"),
    "#ffe4f1": dict(name="粉",   bar="#ffcce5", fg="#333333", icon="#665b60",
                    hover="#f0c1d8", border="#e5cdd8", ph="#b9a5ae", sb="#d7c0cb",
                    trough="#f3d9e5", arrow="#665b60", sel="#ffcce5"),
    "#f2e6ff": dict(name="紫",   bar="#e7cfff", fg="#333333", icon="#615c66",
                    hover="#dac4f0", border="#d9cfe5", ph="#afa7b9", sb="#ccc2d7",
                    trough="#e6dbf3", arrow="#615c66", sel="#e7cfff"),
    "#e2f1ff": dict(name="蓝",   bar="#cde9ff", fg="#333333", icon="#5a6066",
                    hover="#c2dbf0", border="#cbd8e5", ph="#a3aeb9", sb="#bfcbd7",
                    trough="#d7e5f3", arrow="#5a6066", sel="#cde9ff"),
    "#f3f2f1": dict(name="灰",   bar="#e1dfdd", fg="#333333", icon="#616160",
                    hover="#d4d2d0", border="#dad9d8", ph="#b0afae", sb="#cdcccb",
                    trough="#e7e6e5", arrow="#616160", sel="#e1dfdd"),
    # 炭笔：深底 → 白字 + 亮图标；选区底色改用蓝（深底上的淡黄选区完全看不出来）
    "#696969": dict(name="炭笔", bar="#494745", fg="#ffffff", icon="#d2d2d2",
                    hover="#575553", border="#7b7b7b", ph="#999999", sb="#848484",
                    trough="#717171", arrow="#d2d2d2", sel="#4a6da7"),
}
# 面板里的 7 个色块显示 `bar`（顶栏色）而不是 `body`：它就是便签的「身份色」，
# 比淡色正文好分辨，也与老板第一版给的 MS 便签色块风格一致。
NOTE_BG_PRESETS = [(k, v["name"]) for k, v in NOTE_THEMES.items()]
# 深底判据：只有「炭笔」这一档是白字（其余 6 档实测都是 #333333）
NOTE_FG_ON_DARK = "#ffffff"
# 0916 第一版的色块色（当时只换正文色）→ 0916b 的正文色。老板数据里若已存旧值，
# 读回来必须映射到新配色，否则 `_norm_bg` 会把它当非法值打回默认黄。
NOTE_BG_LEGACY = {
    "#ffe66e": "#fff7d1", "#a1ef9b": "#e4f9e0", "#ffafdf": "#ffe4f1",
    "#d7afff": "#f2e6ff", "#9edfff": "#e2f1ff", "#e0e0e0": "#f3f2f1",
    "#767676": "#696969",
}
# 值域封闭集合（body / bar / border 三组，互斥）：`_norm_bg` 只放行 body 集合，
# `_apply_note_bg_widgets` 三个集合都认 —— 两边共用同一份，别各写一份。
NOTE_BG_ALLOWED = frozenset(NOTE_THEMES)
NOTE_BAR_ALLOWED = frozenset(v["bar"] for v in NOTE_THEMES.values())
NOTE_BORDER_ALLOWED = frozenset(v["border"] for v in NOTE_THEMES.values())

# ---- 颜色面板（自绘 Toplevel，参考图为蓝框 + 白底 + 无间隙色块行）----
PICK_BORDER = "#0078d4"      # 面板 1px 外框（参考图实测的蓝框）
PICK_SWATCH_W = 44           # 色块宽（参考图 51px；这里 7×44=308，不超出悬浮窗默认宽 320）
PICK_SWATCH_H = 44           # 色块高（参考图 50px）
PICK_ITEM_H = 38             # 菜单项行高（参考图 50px，这里收窄以免面板过高）
PICK_ITEM_BG = "#ffffff"     # 菜单项常态底（参考图实测）
PICK_ITEM_HOVER = "#eeeeee"  # 菜单项悬停底（参考图实测：那一行「删除笔记」就是悬停态）
PICK_TEXT = "#1a1a1a"        # 菜单项文字
PICK_TEXT_DANGER = "#c62828"  # 「删除便签」红字（对齐参考图「删除笔记」的红色）
PICK_SEP = "#e8e8e8"         # 菜单项之间的细分隔线
PICK_CHECK = "#1a1a1a"       # 当前色块上的 ✓（参考图首个黄块上的黑勾）
PICK_ICON = "#4a4a4a"        # 菜单项图标色
PICK_SHADOW = "#c8c8c8"      # 面板下方 1px 假阴影（无边框窗没有系统阴影，留一道压边更立体）
PICK_GAP = 6                 # 面板与屏幕边缘的最小留白（防弹到视口外）

# ---- 列表标记（底栏 ≡ / 1. 两个按钮；纯文本模型，标记直接写进行首）----
BULLET = "\u2022 "           # • （无序）
# 行首标记识别：允许前导空白；同时认「•」和「1.」两种，便于两种列表互相切换。
# 🔴 序号限 1~3 位：不要匹配到「2026. 年度计划」这种以年份开头的普通句子（会误摘用户正文）。
_LIST_RE = re.compile(r"^(\s*)(?:\u2022\s+|\d{1,3}[.\uff0e]\s+)")
_NUM_RE = re.compile(r"^(\s*)(\d{1,3})[.\uff0e]\s+")

# ---- 内嵌图片规则（🔴 数值必须与主界面 `便签应用.html` 的 IMG_* 逐条对齐）----
# 主界面：const IMG_MAX_EDGE = 1400 / IMG_MAX_BYTES = 2*1024*1024 / IMG_MAX_BATCH = 10
IMG_MAX_EDGE = 1400                     # 长边上限（px），超出等比压缩
IMG_MAX_BYTES = 2 * 1024 * 1024         # 单张上限（压缩后仍超则拒绝插入）
IMG_MAX_BATCH = 10                      # 单次最多插入张数
IMG_JPEG_Q = 86                         # JPEG 重编码质量（主界面 canvas.toDataURL("image/jpeg", 0.86)）
IMG_PAD = 3                             # 图片四周留白（px）
IMG_LINE_COLOR = "#7ba7f0"              # 拖动时的插入指示线颜色（与主界面 img-insert-line 同色系）
IMG_MIN_MOVE = 4                        # 拖动死区（px）：小于它算点击，不算拖动
# ---- 图片「选中 + 拉角调大小」规则（对齐主界面：IMG_MIN_W / .ib-h / img-selected）----
IMG_MIN_W = 40                          # 最小显示宽度（主界面 IMG_MIN_W = 40）
IMG_SEL_COLOR = "#3370ff"               # 选中框 + 角手柄色（主界面 img.img-selected outline）
IMG_HANDLE = 10                         # 角手柄边长（主界面 .ib-h 10×10 圆形）
# 8 个手柄：4 角（等比缩放）+ 4 边（n/s 按纵向差值、e/w 按横向差值）。
IMG_HANDLES = ("nw", "ne", "sw", "se", "n", "s", "e", "w")
IMG_CORNERS = ("nw", "ne", "sw", "se")
# 命中判定外扩（px）：10px 的圆点按**纯像素**判太难抓（老板 0917e 报「拉不动」）
IMG_HANDLE_PAD = 4
# ---- 外部拖入：只认这些图片扩展名（其余交给 `_prepare_image_file` 再判一次）----
IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")
DROP_POLL_MS = 150                      # Tk 侧取「拖入收件箱」的轮询间隔（见 `_wndproc` 注释）

# ---- 底栏工具：选中态 + 悬浮提示（0915 老板要求「类似主界面的文字工具」）----
# 🔴 配色**照抄主界面**：`.tb-item.active { background: var(--accent-weak); color: var(--accent-text); }`
#    选中态（老板 0915d4 定稿，参考图）：**内阴影（凹陷的立体感）**——一块比底栏略深的
#    **中性暖灰**色块 + 一圈「上/左暗、下/右亮」的内阴影；图标/文字保持黑色。
#    压在淡黄底栏（NOTE_BG）上清晰可辨，不与主界面/悬停的蓝、黄混淆。
FMT_ON_BG = "#ddd9cd"                   # 选中态底色（中性暖灰，取自参考图；叠黄底读作阴影色块）
FMT_ON_FG = "#000000"                   # 选中态图标色（黑）
FMT_SHADOW = "#a8a294"                  # 内阴影暗边（上 / 左）
FMT_LIGHT = "#f6f4ec"                   # 内阴影亮边（下 / 右，做出凹陷高光）
# 提示气泡：对齐主界面 `#ui-tip`（白底 / 1px 边框 / 圆角 10 / 阴影由无边框窗口近似）
TIP_BG = "#ffffff"
TIP_BORDER = "#e3e6ea"
TIP_L1_FG = "#1f5ee8"                   # 标题行（主界面 .tip-l1）
TIP_L2_FG = "#646a73"                   # 说明行（主界面 .tip-l2）
TIP_DELAY_MS = 300                      # 悬浮满 300ms 才弹（主界面 setTimeout 300）
TIP_GAP = 9                             # 气泡与按钮的间距（主界面 9px）
# 工具栏提示文案 kind → (标题, 说明)。未列的 kind 不出提示。
FMT_TIPS = {
    "bold": ("加粗", "把选中的文字加粗"),
    "italic": ("斜体", "把选中的文字变斜体"),
    "underline": ("下划线", "给选中的文字加下划线"),
    "strike": ("删除线", "给选中的文字加删除线"),
    "list": ("无序列表", "变成项目符号列表（•）"),
    "olist": ("有序列表", "变成数字编号列表（1. 2. 3.）"),
    "image": ("插入图片", "选本地图片插入；也可 Ctrl+V 粘贴、或从外部拖进来"),
}
FMT_KINDS = ("bold", "italic", "underline", "strike", "list", "olist", "image")

# 0917 老板要求：「悬浮便签的标题栏功能按钮在鼠标悬浮时显示气泡提示」。
# 与底栏工具**共用同一个气泡窗口**（`_tip_win`），只是文案表分开、目标控件不同
# （底栏是 Canvas 图标，顶栏是 tk.Button）→ `_tip_schedule` 统一按 kind 查目标。
BAR_TIPS = {
    "bar_add":   ("新建悬浮便签", "与托盘右键一致：在「未分类」建一条新便签并双向同步"),
    "bar_more":  ("更多", "背景颜色 / 字号设置 / 置顶 / 删除便签"),
    "bar_close": ("收起", "把这个悬浮便签收起来（不删除内容）"),
    "bar_save":  ("保存状态", "编辑时转圈，保存完成变对号"),
}

# ---- 顶栏「保存状态」小图标（0915 老板要求）----
# 老板原话：「在悬浮标签页键入文字的时候，标题栏三个点的按钮左侧添加一个动画效果（循环箭头），
#           当停止输入，并保存好的时候，变为一个对号」
# 状态机：saved（对号，初始/落盘完成）⇄ saving（旋转双弧箭头，编辑中）
SAVE_ICON = 18                  # 状态图标画布边长（顶栏高 30，取 18 视觉平衡）
SAVE_ANIM_MS = 90               # 旋转动画帧间隔（≈11fps，够顺不费 CPU）
SAVE_ANIM_STEP = 30             # 每帧转过的角度
# 🔴 老板 0915 报「保存中转圈、保存成功对号都是灰色，看不清」：顶栏是金黄底，
#    原来 fill=ICON_FG(#5c5648) 灰压金黄、对比太弱。改成醒目的蓝（转圈）+ 绿（对号）。
SAVE_SPIN_FG = "#1f5ee8"        # 编辑中「循环箭头」= 蓝（与主界面强调色一致）
SAVE_OK_FG = "#2e9e4f"          # 保存成功「对号」= 绿（成功语义，压金黄底最醒目）

# ---- 外部拖放「悬停预览」（0915 老板要求：拖进来时也有一条横杠指示插到哪一行）----
# 🔴 为什么必须轮询：OLE 拖放期间鼠标被**源进程**（资源管理器）独占，目标窗口收不到
#    `<B1-Motion>` / `WM_MOUSEMOVE`；`WM_DROPFILES` 又只在**松手那一刻**才来。
#    想「拖动过程中就显示落点」只能自己查全局鼠标状态（GetAsyncKeyState + winfo_pointerxy）。
DROP_HOVER_POLL_MS = 80         # 悬停检测间隔
# 0915c2：拖动 / 缩放的限流间隔（秒）。鼠标 125~1000Hz 报告率下 <B1-Motion>
# 每秒可上千次，全量处理会把消息队列压爆 → 需要限流到 ≈100fps。
#
# 🔴 为什么**不用 `after()` 节流**（0915c 踩过的坑）：Tk 的 `after` 在 Windows 上走
#    WM_TIMER，受系统时钟量化 —— 实测排 `after(8)` 实际 **≈31ms** 才回调一次，
#    拖动反而被锁死在 ~32fps，比不节流更涩（老板反馈「还是有点卡」）。
#    改成「在 Motion 事件里直接应用 + 时间闸门（perf_counter）限流」：
#    帧率由**真实鼠标事件**驱动，不受定时器量化影响。
DRAG_FLUSH_S = 0.010    # 10ms ≈ 100fps 上限（高于显示器刷新率，跟手且不浪费）

# ---- 与主界面便签的双向同步（0915 老板要求「两边实时同步」）----
# 两侧各有一个轮询：主界面 JS 每 800ms 拉一次桌面便签（`list_bound`），
# 悬浮便签这边每 800ms 读一次自己的文件（`load_by_id`）比对。
# 🔴 为什么不做「推」：推送要从 Tk 线程回调 GUI 线程的 evaluate_js，极易死锁；
#    轮询只碰文件 + 锁，谁都不会把对方的数据写坏。代价是 ≈0.8s 的同步延迟。
SYNC_POLL_MS = 300              # 悬浮便签轮询间隔（0915：从 800ms 收紧到 300ms，对方「键入同时」更快看到）
# 0915i：0.5 → 1.2s。0.5s 太短 —— 打字时稍作停顿（选词、想一下）就被判定为「没在输入」，
#   于是远端内容被铺进来 → 光标被顶走（老板「键入几个字就跳到头上」）。
#   正在打字的人优先，晚 1.2s 同步换不打断，这笔交易划算。
SYNC_EDIT_GUARD_S = 1.2

# 正文左右内边距（与 Text 的 padx 一致）→ 图片显示宽度上限 = 正文宽 - 2*此值
BODY_PADX = 16

# ==================== 外部文件拖入（Win32 WM_DROPFILES）====================
# 🔴 悬浮便签是 Tk 独立线程窗口，Tk 自身**没有**跨进程拖放能力 → 收「从资源管理器拖进来的
#    文件」只能走 Win32 原生三步：
#      ① `DragAcceptFiles(hwnd, True)`              —— 让窗口接受拖放
#      ② `SetWindowLongPtrW(hwnd, GWLP_WNDPROC, …)` —— 子类化窗口过程，截 WM_DROPFILES
#      ③ `DragQueryFileW` 取路径 → `DragFinish` 释放
#    ⚠️ 回调是在 **Tk 自己的消息泵线程**里被调的（Tk mainloop 负责派发该窗口的消息），
#       所以在回调里调 Tk 是安全的；但真正的插入仍用 `root.after(0, …)` 推回事件循环，
#       避免在窗口过程里做耗时操作（拖慢消息处理）。
WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
_LRESULT = ctypes.c_ssize_t
_WPARAM = ctypes.c_size_t
_LPARAM = ctypes.c_ssize_t

if os.name == "nt":                                        # pragma: no cover
    _WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, _WPARAM, _LPARAM)
    _user32 = ctypes.windll.user32
    _shell32 = ctypes.windll.shell32
    # 64 位用 SetWindowLongPtrW；32 位只有 SetWindowLongW
    _SET_WNDPROC = (_user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                    else _user32.SetWindowLongW)
    _SET_WNDPROC.restype = ctypes.c_void_p
    _SET_WNDPROC.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    _user32.CallWindowProcW.restype = _LRESULT
    _user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                        wintypes.UINT, _WPARAM, _LPARAM]
    # ⚠️ DragAcceptFiles / DragQueryFileW / DragFinish 三个都导出自 **shell32**（不是 user32）
    _shell32.DragAcceptFiles.restype = None
    _shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    _shell32.DragQueryFileW.restype = wintypes.UINT
    _shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                        wintypes.LPWSTR, wintypes.UINT]
    _shell32.DragQueryPoint.restype = wintypes.BOOL
    _shell32.DragQueryPoint.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.POINT)]
    _shell32.DragFinish.restype = None
    _shell32.DragFinish.argtypes = [wintypes.HANDLE]
    # 全局按键状态（外部拖放悬停检测用）：必须显式声明返回 SHORT，
    # 否则 ctypes 默认按 c_int 读 → 0x8000 位判不准。
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
else:                                                      # pragma: no cover
    _WNDPROC = None
    _user32 = _shell32 = _SET_WNDPROC = None


def _mark_kind(line: str) -> str | None:
    """行首标记类型：`"olist"`（`1. `）/ `"list"`（`• `）/ `None`（无标记）。

    🔴 判「无序」必须先排除数字标记 —— `_LIST_RE` 同时认 `• ` 和 `1. `（为了两种列表能互转），
       直接拿它判无序会把有序行误判成无序行（再点一次就摘错）。
    """
    if _NUM_RE.match(line):
        return "olist"
    if _LIST_RE.match(line):
        return "list"
    return None


def _flatten_images(html: str) -> str:
    """把正文里的内嵌图片折叠成 [图片]（仅在含 <img> 时处理）。"""
    if "<img" not in html:
        return html
    return re.sub(r"<img\b[^>]*>", "[图片]", html, flags=re.I)


# ======================== 行内样式 ⇄ Tk tag（0915）========================
# 🔴 老板 0915 报的问题：「主界面添加的便签格式，颜色，等等，在便签页都是以代码的形式体现的」。
#    根因：主界面正文是 contenteditable 的产出 —— 加粗/颜色/字号是
#    `<span style="font-weight:700">` / `<span style="color:rgb(255,0,0)">` / `<font color=…>`，
#    而不是我们这套 `<b>/<i>/<u>`。旧版 `_parse_html_segments` 只「识别白名单标签」，
#    **没被识别的标签会原样当文本塞进 Text** → 直接显示成 HTML 代码。
#    这里补两件事：
#      ① 「样式属性 → Tk tag」的解析（含 span / font / code / blockquote / a / h1~h6）；
#      ② **双向对称** —— `_get_html` 能把同一批 tag 还原成等价 HTML，
#         否则悬浮便签保存一次就把主界面的颜色/字号全冲掉（比显示成代码更严重）。
#    tag 命名约定：颜色 `sf_<rrggbb>` / 底色 `sb_<rrggbb>` / 字号 `fs_<pt>`，一眼可逆。

_NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0", "maroon": "#800000",
    "navy": "#000080", "teal": "#008080", "olive": "#808000", "lime": "#00ff00",
    "aqua": "#00ffff", "cyan": "#00ffff", "fuchsia": "#ff00ff", "magenta": "#ff00ff",
}
# 标题 → 字号（pt）：按主界面 h1≈32px / h2≈25px / h3≈21px / h4≈18px / h5≈16px / h6≈14px 折算
_HEAD_PT = {"h1": 24, "h2": 19, "h3": 16, "h4": 14, "h5": 12, "h6": 11}
_STYLE_RE = re.compile(r"""style\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
_ATTR_COLOR_RE = re.compile(r"""\bcolor\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)


def _style_of(tok: str) -> str:
    """从标签串里取 style 属性的值（没有返回空串）。"""
    m = _STYLE_RE.search(tok or "")
    if not m:
        return ""
    return m.group(1) if m.group(1) is not None else (m.group(2) or "")


def _attr_color_of(tok: str) -> str:
    """从标签串里取 `color="…"` 属性值（`<font color=…>` 用）。"""
    m = _ATTR_COLOR_RE.search(tok or "")
    if not m:
        return ""
    return m.group(1) if m.group(1) is not None else (m.group(2) or "")


def _norm_color(v: str) -> str | None:
    """颜色串 → `#rrggbb`；认不出来返回 None。"""
    s = (v or "").strip().lower()
    if not s or s in ("transparent", "inherit", "initial", "currentcolor", "none"):
        return None
    m = re.match(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", s)
    if m:
        try:
            r, g, b = (max(0, min(255, int(x))) for x in m.groups())
            return "#%02x%02x%02x" % (r, g, b)
        except Exception:
            return None
    m = re.match(r"^#([0-9a-f]{3})$", s)
    if m:
        c = m.group(1)
        return "#" + c[0] * 2 + c[1] * 2 + c[2] * 2
    m = re.match(r"^#([0-9a-f]{6})", s)
    if m:
        return "#" + m.group(1)
    return _NAMED_COLORS.get(s)


def _norm_size_pt(v: str) -> int | None:
    """`font-size` → pt（Tk 字号单位是 pt；主界面写 px/em/%）。认不出返回 None。"""
    m = re.match(r"^([0-9.]+)\s*(px|pt|em|rem|%)?$", (v or "").strip().lower())
    if not m:
        return None
    try:
        n = float(m.group(1))
    except Exception:
        return None
    unit = m.group(2) or "px"
    if unit == "pt":
        pt = n
    elif unit == "px":
        pt = n * 0.75
    elif unit in ("em", "rem"):
        pt = n * 12.0                      # 正文 16px ≈ 12pt
    else:
        pt = n / 100.0 * 12.0
    pt = int(round(pt))
    return pt if 6 <= pt <= 72 else None


def _parse_style(s: str) -> dict:
    """`style="a:1;b:2"` → {"a": "1", "b": "2"}。"""
    d = {}
    for part in str(s or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            d[k.strip().lower()] = v.strip()
    return d


def _style_items(d: dict) -> list:
    """样式字典 → [(tk_tag, open_html, close_html), …]（顺序固定 → 往返稳定）。

    🔴 「同时有粗体与字号」时合并成 **`fsb_N`**：Tk 的 tag `font` 属性不叠加，
       单独的字号 tag 会把粗体吃掉（`tag_configure` 的 font 由优先级最高者整份胜出）。
       合并后写回 HTML 是 `font-size:Npt;font-weight:700`，与「`<b>` + span」语义等价。
    """
    out = []
    fg = _norm_color(d.get("color", ""))
    if fg:
        out.append(("sf_%s" % fg[1:], '<span style="color:%s">' % fg, "</span>"))
    bg = _norm_color(d.get("background-color", "") or d.get("background", ""))
    if bg:
        out.append(("sb_%s" % bg[1:], '<span style="background-color:%s">' % bg, "</span>"))
    w = str(d.get("font-weight", "")).strip().lower()
    is_bold = w in ("bold", "bolder") or (w.isdigit() and int(w) >= 600)
    fs = str(d.get("font-style", "")).strip().lower()
    if fs in ("italic", "oblique"):
        out.append(("italic", "<i>", "</i>"))
    td = (str(d.get("text-decoration", "")) + " "
          + str(d.get("text-decoration-line", ""))).strip().lower()
    if "underline" in td:
        out.append(("underline", "<u>", "</u>"))
    if "line-through" in td:
        out.append(("strike", "<s>", "</s>"))
    pt = _norm_size_pt(d.get("font-size", ""))
    if pt and is_bold:
        out.append(("fsb_%d" % pt,
                    '<span style="font-size:%dpt;font-weight:700">' % pt, "</span>"))
    elif pt:
        out.append(("fs_%d" % pt, '<span style="font-size:%dpt">' % pt, "</span>"))
    elif is_bold:
        out.append(("bold", "<b>", "</b>"))
    return out


# 固定 tag → HTML（颜色/底色/字号三类按 tag 名反推，见 `_html_for_tag`）
TAG_HTML_FIXED = {
    "bold": ("<b>", "</b>"),
    "italic": ("<i>", "</i>"),
    "underline": ("<u>", "</u>"),
    "strike": ("<s>", "</s>"),
    "code": ("<code>", "</code>"),
    "quote": ("<blockquote>", "</blockquote>"),
    "link": ('<a href="#">', "</a>"),
}

# 「闭合本身就代表一个块换行」的 tag（写回 HTML 时用**块级**标签）。
# 用于 `_get_html`：块闭合后紧随的那个 `\n` 不再写 `<br>`，否则往返多一个空行。
_BLOCK_HTML_TAGS = {"quote"}


def _html_for_tag(tag: str):
    """Tk tag 名 → (open_html, close_html)；不是格式 tag 返回 None。"""
    if not tag:
        return None
    hit = TAG_HTML_FIXED.get(tag)
    if hit:
        return hit
    m = re.match(r"^sf_([0-9a-f]{6})$", tag)
    if m:
        return ('<span style="color:#%s">' % m.group(1), "</span>")
    m = re.match(r"^sb_([0-9a-f]{6})$", tag)
    if m:
        return ('<span style="background-color:#%s">' % m.group(1), "</span>")
    m = re.match(r"^fs_(\d{1,2})$", tag)
    if m:
        return ('<span style="font-size:%spt">' % m.group(1), "</span>")
    # `fsb_N` = 字号 + 粗体（Tk 的 font 属性不叠加，所以显示侧合并；写回时拆成两个声明）
    m = re.match(r"^fsb_(\d{1,2})$", tag)
    if m:
        return ('<span style="font-size:%spt;font-weight:700">' % m.group(1), "</span>")
    return None


# 行内标签 → 打开的样式项列表
_INLINE_TAGS = {
    "b": [("bold", "<b>", "</b>")],
    "strong": [("bold", "<b>", "</b>")],
    "i": [("italic", "<i>", "</i>")],
    "em": [("italic", "<i>", "</i>")],
    "u": [("underline", "<u>", "</u>")],
    "s": [("strike", "<s>", "</s>")],
    "strike": [("strike", "<s>", "</s>")],
    "del": [("strike", "<s>", "</s>")],
    "code": [("code", "<code>", "</code>")],
    "kbd": [("code", "<code>", "</code>")],
    "samp": [("code", "<code>", "</code>")],
    "tt": [("code", "<code>", "</code>")],
    "a": [("link", '<a href="#">', "</a>")],
    "mark": [("sb_ffff00", '<span style="background-color:#ffff00">', "</span>")],
}
# 块级标签（闭合时要补换行）
_BLOCK_TAGS = ("div", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
               "blockquote", "pre", "section", "article", "tr", "ul", "ol",
               "table", "figure", "figcaption", "header", "footer")


# ======================== 内嵌图片：编解码 / 压缩工具 ========================
# 🔴 规则逐条对齐主界面 `便签应用.html` 的 prepareImage()：
#      · 小图**原样保留**（不重编码 → 不损画质、不丢透明）
#      · GIF 不重编码（重编码会丢动画帧）
#      · 长边 > IMG_MAX_EDGE 或字节 > IMG_MAX_BYTES → 等比缩到 1400；PNG/WebP 保 PNG，
#        其余转 JPEG 0.86；保 PNG 后仍超限 → 再转 JPEG 0.86
#      · 最终仍 > IMG_MAX_BYTES → 拒绝插入（不让数据文件失控）

_FMT_MIME = {
    "PNG": "image/png", "JPEG": "image/jpeg", "JPG": "image/jpeg",
    "GIF": "image/gif", "WEBP": "image/webp", "BMP": "image/bmp",
    "TIFF": "image/tiff", "ICO": "image/x-icon",
}


def _fmt_kb(n: int) -> str:
    return "%d KB" % int(round((n or 0) / 1024.0))


def _data_url_bytes(url: str) -> int:
    """dataURL 的实际字节数（base64 → 原始字节），对齐主界面 dataUrlBytes()。"""
    s = str(url or "")
    _, _, b = s.partition(",")
    if not b:
        b = s
    b = b.strip()
    pad = 2 if b.endswith("==") else (1 if b.endswith("=") else 0)
    return max(0, len(b) * 3 // 4 - pad)


def _is_data_image_url(s) -> bool:
    return isinstance(s, str) and s.startswith("data:image/")


def _to_rgb(im):
    """转成可存 JPEG 的 RGB：带透明的按**白底**合成（比直接丢弃 alpha 变成黑底好看）。"""
    if im.mode == "RGB":
        return im
    if im.mode == "L":
        return im.convert("RGB")
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = _PILImage.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return im.convert("RGB")


def _encode_img(im, as_png: bool):
    """把 PIL 图编码成 (bytes, mime)。"""
    buf = io.BytesIO()
    if as_png:
        im.save(buf, "PNG")
        return buf.getvalue(), "image/png"
    _to_rgb(im).save(buf, "JPEG", quality=IMG_JPEG_Q, optimize=True)
    return buf.getvalue(), "image/jpeg"


def _make_info(out: bytes, mime: str, nat_w: int, nat_h: int) -> dict:
    nbytes = len(out)
    if nbytes > IMG_MAX_BYTES:
        raise ValueError("图片过大（%s，上限 %s），请先压缩" % (_fmt_kb(nbytes), _fmt_kb(IMG_MAX_BYTES)))
    b64 = base64.b64encode(out).decode("ascii")
    return {"data_url": "data:%s;base64,%s" % (mime, b64),
            "bytes": nbytes, "nat_w": nat_w, "nat_h": nat_h}


def _prepare_pil(im, raw: bytes | None = None, fmt: str = "") -> dict:
    """PIL 图 → 按主界面同款规则压缩 → {data_url, bytes, nat_w, nat_h}。

    raw = 原始文件字节（可原样保留时用它，避免重编码损画质）；剪贴板位图传 None。
    """
    nat_w, nat_h = im.size
    fmt = (fmt or im.format or "").upper()
    is_gif = (fmt == "GIF")
    need_scale = max(nat_w, nat_h) > IMG_MAX_EDGE
    # 位图（raw=None）没有「原字节」可留 → 必须编码一次
    too_big = (raw is None) or (len(raw) > IMG_MAX_BYTES)
    if raw is not None and not need_scale and not too_big:
        out, mime = raw, _FMT_MIME.get(fmt, "image/png")      # 小图原样保留
    elif is_gif and raw is not None and not need_scale:
        out, mime = raw, _FMT_MIME.get(fmt, "image/gif")      # GIF 不重编码（保动画）
    else:
        k = (IMG_MAX_EDGE / float(max(nat_w, nat_h))) if need_scale else 1.0
        w, h = max(1, int(round(nat_w * k))), max(1, int(round(nat_h * k)))
        work = im.resize((w, h), _PILImage.LANCZOS) if (w, h) != (nat_w, nat_h) else im
        keep_png = fmt in ("PNG", "WEBP") or (raw is None)     # 位图/截图走 PNG（无损、保透明）
        out, mime = _encode_img(work, keep_png)
        if keep_png and len(out) > IMG_MAX_BYTES:
            out, mime = _encode_img(work, False)               # 保 PNG 仍超限 → JPEG 兜底
    return _make_info(out, mime, nat_w, nat_h)


def _prepare_image_file(path: str) -> dict:
    """读一个图片文件 → 解码 → 按规则压缩。失败一律抛 ValueError（调用方提示用户）。"""
    if not _HAS_PIL:
        raise ValueError("缺少 Pillow，无法处理图片")
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ValueError("文件读不了：%s" % e)
    if not raw:
        raise ValueError("文件是空的")
    try:
        im = _PILImage.open(io.BytesIO(raw))
        im.load()                       # 强制解码：坏图 / 非图在这里就抛
    except Exception:
        raise ValueError("不是有效的图片文件")
    return _prepare_pil(im, raw, im.format or "")



def _clamp_img_w(w, max_w: int) -> int:
    """图片显示宽度夹取：下限 `IMG_MIN_W`，上限 `max(正文可用宽, 60)`（对齐主界面）。

    主界面 setImageWidth() / 角手柄拖动都是这套夹取：`const min = 40, max = Math.max(imgMaxWidth(), 60)`。
    """
    try:
        v = int(round(float(w)))
    except Exception:
        return IMG_MIN_W
    hi = max(int(max_w or 0), 60)
    return max(IMG_MIN_W, min(v, hi))


def _data_url_to_photo(url: str, max_w: int, master, want_w: int | None = None):
    """dataURL → (PhotoImage, nat_w, nat_h)。

    显示宽度：
      · `want_w` 给了 → 按它（**含放大**，夹取到 [IMG_MIN_W, 正文可用宽]）——图片工具箱/角手柄调大小走这条；
      · 否则 → `min(原宽, max_w)`（只缩不放，小图保持原始像素，不重采样）。
    """
    if not _HAS_PIL:
        raise ValueError("缺少 Pillow，无法显示图片")
    _, _, b64 = str(url).partition(",")
    raw = base64.b64decode(b64)
    im = _PILImage.open(io.BytesIO(raw))
    im.load()
    nat_w, nat_h = im.size
    if want_w:
        target = _clamp_img_w(want_w, max_w)
    else:
        target = nat_w if (not max_w or nat_w <= max_w) else int(max_w)
    target = max(1, int(target))
    if nat_w and target != nat_w:
        h = max(1, int(round(target * nat_h / float(nat_w))))
        im = im.resize((target, h), _PILImage.LANCZOS)
    return _PILImageTk.PhotoImage(im, master=master), nat_w, nat_h



_GCS_COMPSTR = 0x0008          # ImmGetCompositionString 的「组合串」标志
_IME_ARGTYPES_SET = [False]    # argtypes 只需声明一次（打包后同样生效）


def _ime_composing(hwnd) -> bool:
    """Windows：输入法是否**正在组合**（拼音/五笔打了还没上屏）。

    🔴 0915e 为什么需要：Tk 在 IME 组合期间**不派发** KeyPress（按键被输入法吞掉），
       `_last_key_ts` 不会刷新 → 编辑保护 0.5s 一过，同步就可能把正文重铺，
       正在拼的字被清掉、光标跳走 —— 中文用户打字时的经典鬼畜（规格三.6 明确要求）。
       检测失败（非 Windows / 没开输入法 / 句柄取不到）一律返回 False，
       自动降级成原来的时间守卫，不会让同步彻底停摆。
    """
    try:
        if not hwnd:
            return False
        imm = ctypes.windll.imm32
        if not _IME_ARGTYPES_SET[0]:
            # 64 位 Python 下 HWND 是 64 位指针：不声明 argtypes 会被截断成 int32
            imm.ImmGetContext.argtypes = [ctypes.c_void_p]
            imm.ImmGetContext.restype = ctypes.c_void_p
            imm.ImmGetCompositionStringW.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
            imm.ImmGetCompositionStringW.restype = ctypes.c_int
            imm.ImmReleaseContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            imm.ImmReleaseContext.restype = ctypes.c_int
            _IME_ARGTYPES_SET[0] = True
        h = ctypes.c_void_p(int(hwnd))
        himc = imm.ImmGetContext(h)
        if not himc:
            return False
        try:
            return imm.ImmGetCompositionStringW(
                ctypes.c_void_p(himc), _GCS_COMPSTR, None, 0) > 0
        finally:
            imm.ImmReleaseContext(h, ctypes.c_void_p(himc))
    except Exception:
        return False


def _html_to_text(html: str) -> str:
    """富文本 HTML → 纯文本（用于悬浮便签展示）。"""
    if not html:
        return ""
    s = str(html)
    if not re.search(r"</?[a-z][^>]*>", s, re.I):
        return s
    import html as _html
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</?(?:div|p|h[1-6]|li|blockquote|pre|tr)\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return _html.unescape(s).strip()


# ===========================================================================
# 0915j：内容指纹 —— 文本 + 行内格式 + 图片
# ===========================================================================
# 🔴 为什么需要它：0915b 为了打断「主界面 innerHTML ↔ 悬浮便签 `_get_html`」
#    的往返永动循环，加了一条「**纯文本相等就跳过**」。可它把**格式与图片**
#    也一起丢掉了 —— 老板 0915j 报的两件事其实是**同一个根因**：
#      · 只改颜色 / 字号 → 文本没变 → 判成「没变化」→ 格式永不同步
#      · 插入图片       → 文本没变（`<img>` 被剥掉）→ 图片永不同步
#    指纹把「文本 + 行内格式 + 图片」一起编码，同时**归一化掉纯序列化差异**
#    （容器嵌套、属性顺序、颜色写法 rgb() vs #hex、字号 px vs pt、多余换行）
#    → 既认得出真变化，又能收敛（不会每 300ms 互相重铺）。
#
# ⚠️ JS 侧 `fmtFingerprint()`（便签应用.html）必须与本函数**逐条对齐**：
#    任何一边改规则都要同步改另一边，否则指纹永不相等 → 退回永动循环。
# ⚠️ 指纹只取 dataURL 的头尾各一小段做哈希 —— 正文里可能嵌着几 MB 的
#    base64，全量遍历会把 300ms 的轮询拖垮（0915i 卡顿就是这么来的）。

_FP_COLOR_NAMES = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000",
    "green": "#008000", "blue": "#0000ff", "yellow": "#ffff00",
    "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0",
    "orange": "#ffa500", "purple": "#800080", "pink": "#ffc0cb",
    "cyan": "#00ffff", "magenta": "#ff00ff", "brown": "#a52a2a",
    "transparent": "",          # 透明 = 无色 → 不参与指纹
    "inherit": "", "initial": "", "currentcolor": "", "auto": "",
}
# `<font size="1..7">` → pt（浏览器经典映射；两边一致即可，不追求精确）
_FP_FONT_SIZE_PT = {"1": 6, "2": 8, "3": 10, "4": 12, "5": 15, "6": 20, "7": 27}

_FP_TOKEN = re.compile(
    r"<img\b[^>]*>|</?[a-zA-Z][a-zA-Z0-9]*[^>]*>|<!--[\s\S]*?-->|&[a-zA-Z#0-9]{1,8};",
    re.I)                                   # 必须 I：`<IMG SRC=…>` 大小写混写也要认成图片
_FP_ATTR = re.compile(r"""([a-zA-Z-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")
_FP_STYLE_KV = re.compile(r"([a-zA-Z-]+)\s*:\s*([^;]*)")
_FP_IMGSRC = re.compile(r"""src\s*=\s*["']?([^"'\s>]+)""", re.I)
_FP_BLOCK = ("div", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
             "blockquote", "pre", "section", "article", "tr", "ul", "ol",
             "table", "figure", "figcaption", "header", "footer")


def _fp_color(v) -> str:
    """各种颜色写法 → `#rrggbb`（认不出的返回 ""，不参与指纹）。"""
    v = str(v or "").strip().lower()
    if not v:
        return ""
    if v.startswith("#"):
        h = v[1:].strip()
        if len(h) == 3:
            h = "".join(c * 2 for c in h[:3])
        return ("#" + h[:6]) if len(h) >= 6 else ""
    if v.startswith("rgb"):
        nums = re.findall(r"\d+", v)
        if len(nums) >= 3:
            return "#%02x%02x%02x" % (int(nums[0]) & 255,
                                      int(nums[1]) & 255,
                                      int(nums[2]) & 255)
        return ""
    return _FP_COLOR_NAMES.get(v, "")


def _fp_size(v) -> str:
    """字号 → 归一化 pt（只认 px/pt；em/rem/关键字一律放弃，避免两边不一致）。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(px|pt)?", str(v or "").strip().lower())
    if not m:
        return ""
    try:
        n = float(m.group(1))
    except Exception:
        return ""
    u = m.group(2) or "px"
    if u == "pt":
        pt = n
    elif u == "px":
        pt = n / 1.3333          # 96dpi：1pt = 1.333px
    else:
        return ""
    return str(int(round(pt)))


def _fp_img_key(src) -> str:
    """图片指纹：只哈希 dataURL 的**头尾片段 + 长度**（几 MB 全量哈希会拖垮轮询）。"""
    s = str(src or "")
    if not s:
        return "empty"
    sample = s[:256] + "|" + str(len(s)) + "|" + s[-128:]
    h = 0x811C9DC5                       # FNV-1a 32bit（JS 侧同算法）
    for ch in sample:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return "%08x" % h


def _fp_items(name: str, attrs: dict) -> list:
    """标签名 + 属性 → 样式项（B/I/U/S/M/Q/L/H*/C#xxx/G#xxx/Z nn）。"""
    out = []
    if name in ("b", "strong"):
        out.append("B")
    elif name in ("i", "em"):
        out.append("I")
    elif name == "u":
        out.append("U")
    elif name in ("s", "strike", "del"):
        out.append("S")
    elif name in ("code", "kbd", "samp", "tt", "pre"):
        out.append("M")
    elif name == "blockquote":
        out.append("Q")
    elif name == "a":
        out.append("L")
    elif name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        out.append("H" + name[1])
    style = str(attrs.get("style") or "")
    for k, v in _FP_STYLE_KV.findall(style):
        k = k.strip().lower()
        v = str(v or "").strip()
        if k == "color":
            c = _fp_color(v)
            if c:
                out.append("C" + c)
        elif k in ("background-color", "background"):
            c = _fp_color(v)
            if c:
                out.append("G" + c)
        elif k == "font-size":
            z = _fp_size(v)
            if z:
                out.append("Z" + z)
        elif k == "font-weight" and v.lower() in ("bold", "bolder", "700", "800", "900"):
            out.append("B")
        elif k == "font-style" and v.lower() in ("italic", "oblique"):
            out.append("I")
        elif k == "text-decoration":
            lv = v.lower()
            if "underline" in lv:
                out.append("U")
            if "line-through" in lv:
                out.append("S")
        elif k == "font-family" and re.search(r"mono|courier|consolas|menlo", v, re.I):
            out.append("M")
    if name == "font":
        c = _fp_color(attrs.get("color"))
        if c:
            out.append("C" + c)
        z = _FP_FONT_SIZE_PT.get(str(attrs.get("size") or "").strip())
        if z:
            out.append("Z%d" % z)
        if re.search(r"mono|courier|consolas", str(attrs.get("face") or ""), re.I):
            out.append("M")
    return out


def _fp_fold(s: str) -> str:
    """折叠空白 / 连续换行（主界面按块换行、悬浮窗按 `<br>`，折叠后才可比）。"""
    s = str(s or "").replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"(?: *\n *)+", "\n", s)
    return s.strip()


def html_fingerprint(html: str) -> str:
    """HTML → 内容指纹（文本 + 行内格式 + 图片）。规则须与 JS `fmtFingerprint` 一致。"""
    import html as _html
    s = str(html or "")
    if not s:
        return ""
    if "<" not in s:                                   # 纯文本 / markdown 老数据
        return _fp_fold(_html.unescape(s))
    out = []
    stack = []

    def cur_style() -> str:
        seen = []
        for e in stack:
            for it in e:
                if it not in seen:
                    seen.append(it)
        return "".join(sorted(seen))

    i, n = 0, len(s)
    while i < n:
        m = _FP_TOKEN.search(s, i)
        if m:
            chunk = s[i:m.start()]
            i = m.end()
        else:
            chunk = s[i:]
            i = n
        if chunk:
            out.append("\x01%s\x02%s" % (cur_style(), _html.unescape(chunk)))
        if not m:
            break
        tok = m.group(0)
        low = tok.lower()
        if low.startswith("<!--"):
            continue
        if low.startswith("<img"):
            sm = _FP_IMGSRC.search(tok)
            out.append("\x01IMG\x02%s" % _fp_img_key(sm.group(1) if sm else ""))
            continue
        if tok.startswith("&"):
            out.append("\x01%s\x02%s" % (cur_style(), _html.unescape(tok)))
            continue
        mm = re.match(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)", tok)
        if not mm:
            continue
        closing = bool(mm.group(1))
        name = mm.group(2).lower()
        if name == "br":
            out.append("\n")      # ⚠️ 必须是**光秃秃的 \n**：带前缀的话 `_fp_fold`
            continue
        if closing:
            if stack:
                stack.pop()
            if name in _FP_BLOCK:
                out.append("\n")      # ⚠️ 必须是**光秃秃的 \n**：带前缀的话 `_fp_fold`
        else:
            if name in _FP_BLOCK:
                out.append("\n")      # ⚠️ 必须是**光秃秃的 \n**：带前缀的话 `_fp_fold`
            attrs = {}
            for k, v in _FP_ATTR.findall(tok):
                attrs[k.lower()] = str(v).strip("\"'")
            stack.append(_fp_items(name, attrs))
    return _fp_fold("".join(out))


def same_content(a: str, b: str) -> bool:
    """两边内容是否「实质相同」（文本 + 格式 + 图片都算）。

    🔴 取代 0915b 的「纯文本相等就跳过」：那个判据看不见格式与图片变化。
       指纹算不出来时**退回纯文本比较**（宁可漏同步，也不要每 300ms 互重铺闪烁）。
    """
    if a == b:
        return True
    try:
        fa = html_fingerprint(a)
        fb = html_fingerprint(b)
        if fa == fb:
            return True
        # 兜底：指纹都算空（解析异常）时退回老判据
        if not fa and not fb:
            return _html_to_text(a) == _html_to_text(b)
    except Exception:
        return _html_to_text(a) == _html_to_text(b)
    return False


# ---------------------------------------------------------------------------
# FloatHost：全进程**唯一**的 Tk root / 线程 / mainloop（0915c 多悬浮窗）
# ---------------------------------------------------------------------------
# 🔴 为什么必须是「单 root + 多 Toplevel」，而不是「每窗一个 Tk() + 一个线程」：
#    Tk 的 root 与 mainloop 一一对应；多 root 虽能跑，但要开 N 个线程 N 个消息泵，
#    而本文件的 WM_DROPFILES 窗口子类化、DWM 圆角、`after` 定时器都是按单 Tk 环境
#    写的。共享一个 root、每个悬浮窗各拿一个 Toplevel → 既省资源，
#    又让现有几千行代码几乎不用改（原理见 `DesktopNoteWindow._build` 的注释）。
class FloatHost:
    """持有唯一 Tk root 的宿主；悬浮窗口都以它的 Toplevel 形式存在。"""

    def __init__(self) -> None:
        self.root: tk.Tk | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def is_alive(self) -> bool:
        """Tk 线程是否已起来（session 构建窗口前必须为真）。"""
        return bool(self._thread and self._thread.is_alive() and self.root is not None)

    def start(self) -> None:
        """启动唯一的 Tk 线程 + mainloop。host root 本身永远不可见（withdraw）。"""
        if self.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="float-host-tk")
        self._thread.start()
        self._ready.wait(5)

    def _run(self) -> None:
        root = tk.Tk()
        root.withdraw()          # host root 隐藏，真正的窗口是各会话的 Toplevel
        self.root = root
        self._ready.set()
        root.mainloop()

    def run_in_tk(self, fn) -> bool:
        """把一段 Tk 操作投递到 Tk 线程执行。

        🔴 **绝不能直接跨线程碰 widget**（GUI/pywebview 线程 → Tk 线程）：
           Tk 在 mainloop 里派发消息时用的是它自己的线程状态，跨线程直接调用
           widget 方法轻则无效、重则 `Fatal Python error`。统一走 `after(0, fn)`，
           由 Tk 自己的消息泵去执行。
        """
        root = self.root
        if root is None:
            return False
        try:
            root.after(0, fn)
            return True
        except Exception:
            return False

    def stop(self) -> None:
        """应用退出：停掉 mainloop 并释放 root（各会话应先各自 `_cleanup()`）。"""
        root = self.root
        if root is None:
            return
        try:
            root.after(0, root.quit)
        except Exception:
            pass
        self.root = None


class DesktopNoteWindow:
    def __init__(self, api, host=None) -> None:
        self.api = api
        # 0915c 多悬浮窗：`host` = 共享 Tk root / 线程的 FloatHost。
        # 不传则为兼容旧用法（单窗口脚本 / 探针），start() 时自建一个私有 host。
        self._host = host
        self._root: tk.Misc | None = None      # **host root**（共享），只判断 Tk 是否还活着
        self._win: tk.Toplevel | None = None   # 本会话真正的窗口（多窗时每窗一个）
        self._thread: threading.Thread | None = None   # 已废弃：线程统一归 FloatHost
        self._ready = threading.Event()
        self._stopping = False
        self._current_id: str | None = None
        self._save_timer: str | None = None  # Tk after id

        # 模式状态
        self._editing = False              # True=编辑模式, False=浏览模式
        self._has_content = False          # 正文是否有内容（控制占位符）
        self._showing_placeholder = False  # 当前 Text 里显示的是占位符（非真实内容）

        # 拖拽 / 拉伸状态
        self._drag_data: dict[str, int] = {"x": 0, "y": 0}
        self._dragging = False
        # 0915c2：拖动/缩放限流改用「时间闸门」(perf_counter)，不再用 after id。
        # 原因：Tk 的 after 走 WM_TIMER 被系统时钟量化（实测 after(8)≈31ms 才回调），
        # 会把拖动锁死在 ~32fps。下面两个 job 字段仅作兼容保留（现恒为 None）。
        self._drag_job = None
        self._rs_job = None
        self._rs_t = 0.0           # 0915c2：缩放时间闸门的上次应用时刻
        # 0915d Stage3：窗口状态持久化
        self._always_on_top = False    # 本窗是否常驻置顶（存到 note.alwaysOnTop）
        self._rev = 0                  # 本会话已知的本便签版本号（防同步回环）
        self._miss_polls = 0           # 0915e：连续读不到绑定记录的轮数（判「便签被删了」）
        self._rs_pt: tuple | None = None   # 缩放节流：最近一次 Motion 的屏幕坐标
        self._resize_edge: str | None = None
        self._rs: tuple | None = None

        # 自绘滚动条状态
        self._sb_first = 0.0
        self._sb_last = 1.0
        self._sb_visible = False
        self._sb_hover = False
        self._drag_thumb = False
        self._drag_off = 0.0

        # 控件引用
        self._top_holder: tk.Frame | None = None
        self._bot_holder: tk.Frame | None = None
        self._top_bar: tk.Frame | None = None
        self._bottom_bar: tk.Frame | None = None
        self._body: tk.Frame | None = None
        self._editor: tk.Text | None = None
        self.editor: tk.Text | None = None        # 兼容旧测试脚本的公开别名
        self._sbar: tk.Canvas | None = None
        self._fmt_items: dict[str, tk.Canvas] = {}    # 底栏格式图标
        self._rs_handles: dict[str, tk.Frame] = {}    # 8 个拉伸热区（需随模式换底色）

        # ---- 内嵌图片状态 ----
        # 🔴 PhotoImage 必须**常驻引用**，否则被 Python GC 回收 → 图变空白（Tk 只持有弱引用）
        self._img_store: dict[str, dict] = {}   # Tk 图片名 → {photo, data_url, nat_w, nat_h, shown_w}
        self._img_seq = 0                       # 图片名自增序号（im1 / im2 / ...）
        self._img_drag: dict | None = None      # 拖动状态 {name, x0, y0, moved}
        self._img_resize: dict | None = None    # 拉角缩放状态 {name, dir, x0, start_w}
        self._sel_img: str | None = None        # 当前选中的图片名（选中态才显示边框 + 角手柄）
        self._sel_shown = False                 # 选中框/手柄当前是否已 place 出来（避免反复 place_forget）
        self._sel_parts: dict = {}              # 选中框部件：4 条边（t/b/l/r）+ 4 个角手柄（nw/ne/sw/se）
        self._ind_line: tk.Frame | None = None  # 拖动插入指示线（place 在 body 上）
        self._img_busy = False                  # 插入图片时防重入（对话框是模态的）
        self._dialog_open = False               # 文件对话框打开中 → 抑制「失焦退出编辑」
        # ---- 图片右键菜单（0915：复制 / 剪切 / 粘贴 / 粘贴为纯文本 / 删除图片）----
        self._ctx_menu = None                   # 菜单对象（常驻引用，GC 掉菜单会瞬间消失）
        self._ctx_menu_open = False             # 菜单弹出中 → 同 _dialog_open 抑制「失焦退编辑」
        self._ctx_icon_store: dict = {}         # 菜单图标（🔴 Tk 只持弱引用，必须常驻）
        self._ctx_icon_supported = None         # 懒探测：Tk 菜单项是否支持 image + compound
        self._probe_photo = None                # 探测用的临时 PhotoImage（常驻防回收）
        # ---- 0916：背景色（per-note）----
        # 🔴 这是「**本会话当前这条便签**的底色」。窗口构建时用它做初始色，之后
        #    `_set_note_bg()` 负责整树改色 + 落盘（note.bgColor）。切到另一条便签时
        #    由 `_apply_note_meta` 重新设回来 —— 所以绝不能把用户选的颜色写回模块常量。
        # `_note_bg` = 本条便签的正文/底栏底色，同时也是落盘的 `bgColor` 值
        # 🔴 它必须**始终是 `NOTE_THEMES` 的某个 key** —— 遍历刷色拿它当"目标色"，
        #    拿三个封闭集合当"匹配基准"，两者对不上就会出现「换完色某块还是旧色」。
        self._note_bg: str = NOTE_BG
        th0 = NOTE_THEMES[NOTE_BG]
        self._note_bar: str = th0["bar"]        # 顶栏底色（标题栏那一条）
        self._note_fg: str = th0["fg"]          # 正文文字（炭笔 = 白字）
        self._note_icon_fg: str = th0["icon"]   # 顶栏按钮 / 底栏工具图标
        self._note_hover: str = th0["hover"]    # 顶栏按钮悬停底色
        self._note_border: str = th0["border"]  # 底栏上方 1px 分隔线
        self._note_ph: str = th0["ph"]          # 占位符「记笔记…」
        self._note_sb: str = th0["sb"]          # 滚动条空闲滑块
        self._note_trough: str = th0["trough"]  # 滚动条悬浮轨道
        self._note_arrow: str = th0["arrow"]    # 滚动条悬浮上下箭头
        self._note_sel: str = th0["sel"]        # 选区底色
        # 顶栏 3 个按钮：`bg` 能被遍历改到，但 `activebackground` / `activeforeground`
        # **不是** `cget("bg")`，遍历看不见 → 必须显式登记（否则悬停还是旧色系）。
        self._bar_buttons: list = []
        # 0917：顶栏按钮 / 状态图标 → 悬浮气泡的 kind 映射（`_tip_schedule` 靠它找目标控件）
        self._bar_tip_items: dict = {}
        self._bg_ready = False                  # 底色是否已铺过一次（没铺过就别跳过首次）
        self._pick_panel = None                 # 颜色面板（无边框 Toplevel，常驻引用防 GC）
        self._pick_open = False                 # 面板开着 → 同 _ctx_menu_open 抑制「失焦退编辑」
        # ---- 0917：字号设置（全局统一；存桌面便签 JSON 的 settings.font_pt）----
        # 🔴 `_font_pt` 是**本会话当前实际用的**基准字号；真值来源在全局设置里，
        #    `_build` 时读一次、滑块改动时写回（见 `_apply_font` / `_persist_font`）。
        self._font_pt: int = NOTE_FONT_DEFAULT
        self._font_panel = None                 # 字号面板（无边框 Toplevel，常驻引用防 GC）
        self._font_open = False                 # 面板开着 → 抑制「失焦退编辑」
        self._font_save_timer = None            # 落盘防抖的 after id
        self._font_scale = None                 # 面板里那条滑块（重建面板时换新的）
        # ---- 外部文件拖入（WM_DROPFILES）状态 ----
        # 🔴 窗口过程里**不能碰 Tk**（会崩，详见 `_wndproc`）→ 它只往 inbox 塞，
        #    Tk 侧用 `_poll_drop()` 定期取走并插入。
        self._drop_inbox: list = []             # [{paths, pt, hwnd}] 待处理的拖入
        self._drop_hwnds: list = []             # 已接管拖放的 HWND（退出时要还原）
        self._old_wndproc: dict = {}            # HWND → 原窗口过程地址
        self._wndproc_refs: list = []           # 🔴 子类化回调必须常驻引用（被 GC → 回调地址失效 → 崩）
        self._drop_busy = False                 # 拖入处理中（防重入）

        # ---- 底栏工具栏状态（0915：选中态 + 悬浮提示）----
        self._fmt_on: dict[str, bool] = {k: False for k in FMT_KINDS}   # 各工具「是否选中」
        self._fmt_hover: str | None = None      # 鼠标正悬在哪个工具上（None = 都不在）
        # 已配置过的「样式 tag」（颜色/底色/字号/等宽/引用/链接），见 `_ensure_style_tag`
        self._style_tags: set = set()
        self._tip_win = None                    # 提示气泡（无边框 Toplevel）
        self._tip_box = None                    # 气泡外框（画边框）
        self._tip_labels: dict = {}             # {"l1": 标题 Label, "l2": 说明 Label}
        self._tip_timer = None                  # 「悬浮满 N ms 才弹」的 after id
        self._tip_kind: str | None = None       # 当前气泡对应的工具 kind

        # ---- 顶栏「保存状态」图标（0915）----
        self._save_cv = None                    # 状态图标画布（顶栏 ⋯ 左侧）
        self._save_state = "saved"              # "saved"=对号 / "saving"=旋转箭头
        self._save_anim_timer = None            # 旋转动画的 after id
        self._save_anim_angle = 0.0             # 当前旋转角（度）

        # ---- 外部拖放悬停预览（0915）----
        # 🔴 用来区分「外部拖进来」和「在便签里按住左键拖选文字」：
        #    后者的 ButtonPress 一定发生在本窗口内（这个标志为 True）；前者的按下
        #    发生在资源管理器 → 我们窗口从没收到过 ButtonPress（标志一直 False）。
        self._press_inside = False
        self._drop_hover_timer = None
        self._ind_last = None                   # 上一次指示线用的 y（相同就不重算，省 Tcl 开销）

        # ---- 与主界面便签的双向同步（0915）----
        self._src_id: str = ""                  # 绑定的主界面便签名（空 = 独立便签，不联动）
        # 0917：本会话在 `FloatingWindowManager._sessions` 里的 key（由 manager 在注册
        #   会话时注入）。「删除便签」要把**窗口自己**也收掉 → 会话必须知道自己在
        #   注册表里叫什么，才能让 manager 精确摘除它（不能靠猜 src_id：独立便签的
        #   key 是 `@local:N`，与任何便签 id 都对不上）。
        self._session_key: str = ""
        self._sync_timer = None                 # 轮询主界面改动的 after id
        self._last_key_ts = 0.0                 # 最近一次按键时间（编辑保护用）
        self._self_written = ""                 # 最近一次自己落盘的 HTML（避免自读自刷）
        # 0915j：内容指纹同步的振荡保险（连续 N 轮不收敛 → 退回纯文本比较）
        self._fp_last_remote: str | None = None
        self._fp_stall = 0
        self._fp_giveup = False
        # 0915h：窗口是否**真的在桌面上**。× 走的是 withdraw（窗口对象还在），
        #   所以 `floating_ids()` 不能只看「有没有 _win」，否则关掉的窗仍被算成悬浮中
        #   → 主界面「浮」徽章不消失。纯属性读写，可跨线程（Tk 方法不可以）。
        self._visible = False

        # 圆角方案：None=未定 / "dwm"=Win11 抗锯齿圆角 / "rgn"=SetWindowRgn 回退
        self._round_mode: str | None = None
        # 圆角 region 已应用的尺寸（仅回退方案用；None = 尚未设置）
        self._rgn_size: tuple | None = None

    # ======================== 生命周期 ========================

    def start(self) -> None:
        """构建**本会话**的悬浮窗口（默认隐藏）。

        0915c：线程与 mainloop 已归 FloatHost，这里只把自己那个 Toplevel 建起来。
        没传 host（旧脚本 / 真机探针）时自建一个私有 host → 保持单窗口时代的行为。
        """
        if self._host is None:
            self._host = FloatHost()
        if not self._host.is_alive():
            self._host.start()
        self._stopping = False
        self._ready.clear()
        self._host.run_in_tk(self._build)
        self._ready.wait(5)

    def stop(self) -> None:
        """销毁**本会话**的悬浮窗口（**不是**销毁 Tk host，别的应用可能还在用）。"""
        self._stopping = True
        host = self._host
        try:
            if host is not None:
                host.run_in_tk(self._cleanup)
            else:
                self._cleanup()
        except Exception:
            pass

    # ======================== Tk 线程内构建 ========================

    def _build(self) -> None:
        """在 Tk 线程（FloatHost 的唯一主循环）里构建**本会话**的悬浮窗口。

        🔴 0915c 多悬浮窗改造：本类不再自己 `tk.Tk()` —— 全进程只有 `FloatHost`
           持有一个 root，每个会话在这里开一个 **Toplevel** 作为真正的窗口。
           好处：一个 Tk 线程 + 一个 mainloop + N 个窗口（而不是 N 个线程 N 个 root）。

           · `self._root` 降级为 **host root**（只用来判断「Tk 是否还活着」）
           · `self._win`    = 本会话的真正窗口（Toplevel）
           · 局部变量 `root` 指向 Toplevel → 下方几千行 `tk.Frame(root, …)` /
             `root.geometry(…)` / `root.after(…)` **一行都不用改**。
        """
        # 0916b：本方法可能被再次调用（窗口重开）→ 清掉上一轮的顶栏按钮登记，
        # 免得列表里留着已销毁的控件（configure 会一直抛异常，还被 try 吞掉）。
        self._bar_buttons = []
        # 0917：气泡目标表同理（留旧的会对着已销毁的控件定位 → 气泡飘到屏幕角落）
        self._bar_tip_items = {}
        hroot = self._host.root if self._host is not None else None
        if hroot is None:
            return
        root = tk.Toplevel(hroot)
        root.withdraw()  # 默认隐藏
        root.overrideredirect(True)   # 无边框（MS 便笺风格）
        root.geometry(f"{WIN_WIDTH}x{WIN_HEIGHT}")
        root.minsize(MIN_W, MIN_H)
        root.configure(bg=self._note_bg)
        self._root = hroot       # host root：仅用于存活判断
        self._win = root         # 真正的悬浮窗口（本会话私有）

        # ---- 主容器 ----
        # 🔴 不加 highlightthickness 边框：那圈 1px 浅色线在金黄顶栏/底栏上看着像「留白」。
        #    现在顶栏/底栏的金黄直接铺到窗口边缘（边界感交给圆角裁切）。
        main = tk.Frame(root, bg=self._note_bg)
        main.pack(fill="both", expand=True)

        # ---- 顶栏恒高占位槽（高度永不变，仅其内部 top_bar 随模式挂/卸）----
        top_holder = tk.Frame(main, bg=self._note_bg, height=TOP_BAR_HEIGHT)
        top_holder.pack(side="top", fill="x")
        top_holder.pack_propagate(False)   # 🔴 关键：不让子控件改变槽高
        self._top_holder = top_holder

        top = tk.Frame(top_holder, bg=self._note_bar)
        self._top_bar = top
        # 左：+ 新建（0917b：改走托盘同一条链路 → 在主界面未分类建条 + 双向同步）
        btn_add = self._make_bar_button(top, "+", 15, self._new_note_linked, tip_kind="bar_add")
        btn_add.pack(side="left", padx=(9, 0))
        # 右：… 更多 / × 关闭
        right = tk.Frame(top, bg=self._note_bar)
        right.pack(side="right", padx=(0, 6))
        btn_close = self._make_bar_button(right, "\u00d7", 15, self._hide,
                                          tip_kind="bar_close")   # ×
        btn_close.pack(side="right", padx=3)
        btn_more = self._make_bar_button(right, "\u22ef", 15, self._show_more_menu,
                                         tip_kind="bar_more")     # ⋯
        btn_more.pack(side="right", padx=3)
        # 保存状态图标：`side="right"` 下**后 pack 的排在更左边** → 它落在 ⋯ 的左侧 ✓
        self._save_cv = tk.Canvas(right, width=SAVE_ICON, height=SAVE_ICON,
                                  bg=self._note_bar, highlightthickness=0, bd=0)
        self._save_cv.pack(side="right", padx=(0, 4))
        # 0917：状态图标也给气泡（它左侧就是 ⋯，老板会顺手悬上去看是什么）
        self._bar_tip_items["bar_save"] = self._save_cv
        self._save_cv.bind("<Enter>", lambda e: self._tip_schedule("bar_save"))
        self._save_cv.bind("<Leave>", lambda e: self._tip_cancel())
        spacer = tk.Frame(top, bg=self._note_bar)
        spacer.pack(side="left", fill="x", expand=True)
        self._bind_drag(top)
        self._bind_drag(top_holder)   # 浏览模式下顶栏卸掉，拖占位槽也能移动窗口

        # ---- 底栏恒高占位槽 ----
        bot_holder = tk.Frame(main, bg=self._note_bg, height=BOTTOM_BAR_HEIGHT)
        bot_holder.pack(side="bottom", fill="x")
        bot_holder.pack_propagate(False)
        self._bot_holder = bot_holder

        # 🔴 底栏底色 = 正文色 NOTE_BG（老板 0914x：两处必须一致）→ 不留金黄底。
        bot = tk.Frame(bot_holder, bg=self._note_bg)
        self._bottom_bar = bot
        # 0916b：分隔线也跟色系走（绿底便签上留一条黄褐线会突兀）→ 进 `NOTE_BORDER_ALLOWED`
        sep = tk.Frame(bot, bg=self._note_border, height=1)
        sep.pack(side="top", fill="x")
        inner = tk.Frame(bot, bg=self._note_bg)
        # fill="both" + expand → 工具栏底色铺满整个底栏槽（底部不留白），图标在其中垂直居中
        inner.pack(side="top", fill="both", expand=True, padx=10)
        for kind in FMT_KINDS:
            # 🔴 0914z：7 个图标**统一 ICON_H(22)×22** 画布（旧版两个列表图标单独加高到 26px，
            #    老板反馈「比别的图标大一圈」）。尺寸一致后 padx 也统一 → 视觉上等距等大。
            cv = tk.Canvas(inner, width=22, height=ICON_H,
                           bg=self._note_bg,
                           highlightthickness=0, bd=0, cursor="hand2")
            self._draw_tool_icon(cv, kind)
            cv.pack(side="left", padx=7)
            cv.bind("<Button-1>", lambda e, k=kind: self._apply_format(k))
            # 🔴 0915：悬停 / 选中都改「底色 + 图标色」——统一走 `_paint_fmt`，
            #    否则悬停直接把 Canvas 底色改成 BTN_HOVER 会把选中态的底色盖掉。
            cv.bind("<Enter>", lambda e, k=kind: self._fmt_hover_on(k))
            cv.bind("<Leave>", lambda e, k=kind: self._fmt_hover_off(k))
            self._fmt_items[kind] = cv
        self._bind_drag(bot)
        self._bind_drag(bot_holder)

        # ---- 正文区（body）----
        body = tk.Frame(main, bg=self._note_bg)
        body.pack(side="top", fill="both", expand=True)
        self._body = body

        # 编辑器：两种模式共用同一个 Text（浏览模式只置 disabled）
        # 0915n：老板要求「悬浮便签字体小一点」→ 正文基准 11pt → 10pt。
        # 🔴 基准字号只在这三处（正文 / bold / italic）写死过，动态字号 tag
        #    `fs_N`/`fsb_N` 的 N 是**主界面写过来的值**，不跟着缩（见 _style_tag_pt）。
        ed = tk.Text(
            body, bg=self._note_bg, fg=self._note_fg,
            font=(NOTE_FONT_FAMILY, NOTE_FONT_PT),
            wrap="word", relief="flat", bd=0,
            padx=16, pady=12, insertbackground=self._note_fg,
            selectbackground=self._note_sel, selectforeground="#000000",
            spacing1=3, spacing3=3,
            yscrollcommand=self._on_yscroll,
        )
        ed.tag_configure("bold", font=(NOTE_FONT_FAMILY, NOTE_FONT_PT, "bold"))
        ed.tag_configure("italic", font=(NOTE_FONT_FAMILY, NOTE_FONT_PT, "italic"))
        ed.tag_configure("underline", underline=True)
        ed.tag_configure("strike", overstrike=True)
        ed.tag_configure("placeholder", foreground=self._note_ph)
        ed.pack(side="left", fill="both", expand=True)
        self._editor = ed
        self.editor = ed

        # 自绘滚动条：常驻 place 在 body 右上角，靠右绘制
        sbar = tk.Canvas(body, width=SBAR_W, bg=self._note_bg,
                         highlightthickness=0, bd=0)
        sbar.place(relx=1.0, rely=0.0, x=-1, y=4, anchor="ne",
                   relheight=1.0, height=-8)
        sbar.bind("<Enter>", self._sbar_enter)
        sbar.bind("<Leave>", self._sbar_leave)
        sbar.bind("<Button-1>", self._sbar_press)
        sbar.bind("<B1-Motion>", self._sbar_drag)
        sbar.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag_thumb", False))
        sbar.bind("<Configure>", lambda e: self._redraw_sbar())
        self._sbar = sbar

        # 拖动图片时的「插入指示线」：2px 细横条，默认不显示（拖动过程中 place 出来）。
        # 🔴 主界面是画在 editorWrap 上的 div（img-insert-line），这里等价实现放在 body 上。
        ind = tk.Frame(body, bg=IMG_LINE_COLOR, height=2)
        self._ind_line = ind

        # 图片选中态浮层：2px 蓝框 + 4 个圆形角手柄（对齐主界面 #img-box；默认全部 place_forget）
        self._make_img_sel_widgets(body)

        # ---- 事件 ----
        ed.bind("<KeyPress>", self._on_keypress)
        ed.bind("<KeyRelease>", self._on_edit)
        # 选区变化（鼠标拖选 / 键盘 Shift 选）→ 工具栏选中态跟着变（0915）
        ed.bind("<<Selection>>", lambda e: self._refresh_fmt_state())
        # 🔴 图片拖动与「点正文进编辑」共用左键：按下时先做图片命中检测，
        #    命中 → 进入拖动流程（不把光标塞进图片、不弹原生选区）；
        #    未命中 → 走原来的「浏览态点一下进编辑」逻辑。
        ed.bind("<Button-1>", self._on_editor_press)
        ed.bind("<B1-Motion>", self._on_editor_motion)
        ed.bind("<ButtonRelease-1>", self._on_editor_release)
        # 粘贴：剪贴板里是图片（或图片文件路径）时插入图片；否则返回 None 走默认纯文本粘贴。
        # 🔴 绑 <<Paste>>（覆盖 Ctrl+V / 右键粘贴 / 菜单粘贴），比只绑 <Control-v> 全。
        ed.bind("<<Paste>>", self._on_paste)
        # 图片右键菜单（0915）：命中内嵌图片 → 复制 / 剪切 / 粘贴 / 粘贴为纯文本 / 删除图片。
        ed.bind("<Button-3>", self._on_editor_right_click)
        ed.bind("<Button-2>", self._on_editor_right_click)   # 少数鼠标/触摸板把右键报成中键
        ed.bind("<MouseWheel>", self._on_wheel)
        root.bind("<MouseWheel>", self._on_wheel)
        root.bind("<Escape>", lambda e: self._hide())
        root.bind("<FocusOut>", self._on_focus_out)  # 点外部 → 退出编辑

        # 无边框窗口自建 8 个拉伸热区（铺在 root 最上层）
        self._make_resize_handles()

        # 外部文件拖入（资源管理器 → 悬浮便签）：DragAcceptFiles + 子类化窗口过程收 WM_DROPFILES
        self._enable_file_drop()
        try:
            root.after(DROP_POLL_MS, self._poll_drop)   # 只往 inbox 塞，这里定期取走
        except Exception:
            pass
        # 拖动**过程中**的落点指示线（0915）：拖放期间窗口收不到鼠标消息 → 轮询全局鼠标状态。
        # `_press_inside` 用来区分「外部拖进来」和「在本窗口按住左键拖选文字」。
        try:
            root.bind_all("<ButtonPress-1>",
                          lambda e: setattr(self, "_press_inside", True), add="+")
            # 🔴 0917e：松手兜底 —— 拉手柄时指针可能停在上层手柄 / 顶栏 / 窗口外，
            #    `<ButtonRelease-1>` 不一定回到 Text → 尺寸改了却永不落盘。
            #    `_finalize_img_resize()` 幂等（没在缩放就直接返回），多窗口并发也安全。
            root.bind_all("<ButtonRelease-1>",
                          lambda e: (setattr(self, "_press_inside", False),
                                     self._finalize_img_resize()), add="+")
            root.after(DROP_HOVER_POLL_MS, self._poll_drop_hover)
        except Exception:
            pass
        # 与主界面便签的双向同步：定期读自己的文件，看主界面有没有改过我（0915）
        try:
            root.after(SYNC_POLL_MS, self._poll_sync)
        except Exception:
            pass

        # 窗口四角圆角（优先 Win11 DWM 抗锯齿圆角；回退方案自行挂 <Configure> 重裁）
        self._apply_round_corners()
        # 🔴 DWM 的圆角偏好在窗口**尚未映射**时设置可能不生效（实测：hidden 时设 S_OK，
        #    但显示后四角仍是直角）。映射时强制再设一次，保证任何时候显示都带圆角。
        try:
            root.bind("<Map>", lambda e: self._apply_round_corners(force=True))
        except Exception:
            pass

        # ---- 载入数据 + 初始进入浏览模式 ----
        self._load_current()
        # 0917：套用**全局**字号 —— 老板要求「字号设置对全部悬浮便签统一生效，
        #       包括此后新建的悬浮便签」。放在这里（editor / 滚动条都已建好）最稳。
        self._apply_font_from_global()
        # 直接置 editing=True 再调 _exit_edit_mode，让浏览态被完整铺一次
        # （否则 _exit_edit_mode 会因 editing=False 提前 return，留下不一致布局）
        self._editing = True
        self._exit_edit_mode()
        # 顶栏状态图标初始 = 对号（内容刚从磁盘读出来，本来就是「已保存」）
        self._set_save_state("saved")

        self._ready.set()
        return

    def _cleanup(self) -> None:
        """会话销毁时：停定时任务 / 还原窗口过程 / 释放引用 / 销毁窗口。

        🔴 0915c：这段原来挂在 `root.mainloop()` **返回之后**（单窗口时代才跑得到）。
           现在 mainloop 归 FloatHost 所有 → 改由 FloatHost 在「关闭悬浮窗 / 删除便签 /
           应用退出」时显式调用，保证每个会话都能各自收摊，不会残留 after 回调泄漏。
        """
        root = self._win or self._root
        self._visible = False      # 0915h：销毁了当然不算悬浮中
        # 0915e：销毁前**先立即落盘正文**（规格「退出前立即保存一次」）。
        # 防抖是 250ms，若用户敲完字立刻关窗/退出，那次保存还没触发 → 改动直接丢。
        # 这里 `_editor` 还没被置 None，是最后能取到正文的时刻。
        try:
            if self._save_timer is not None and root is not None:
                try:
                    root.after_cancel(self._save_timer)
                except Exception:
                    pass
                self._save_timer = None
                self._save_now()
        except Exception:
            pass
        # 0915d：销毁前把位置尺寸落盘 —— 这是最后一次机会（窗口马上就没了），
        # 否则「拖动过但没重启就退出」的位置会丢。
        try:
            self._save_bounds()
        except Exception:
            pass
        self._root = None
        self._editor = None
        self.editor = None
        self._sbar = None
        self._body = None
        self._top_holder = None
        self._bot_holder = None
        self._top_bar = None
        self._bottom_bar = None
        self._fmt_items.clear()
        self._rs_handles.clear()
        self._img_store.clear()
        self._img_drag = None
        self._img_resize = None
        self._sel_img = None
        self._sel_parts = {}
        self._drop_inbox = []
        self._ind_line = None
        self._round_mode = None
        self._rgn_size = None
        self._fmt_hover = None
        self._fmt_on = {k: False for k in FMT_KINDS}
        self._style_tags.clear()
        # 🔴 气泡是独立 Toplevel：必须在 destroy 之前收掉，否则残留窗口 + after 回调会报错
        self._tip_cancel()
        self._destroy_tip()
        # 0916：⋯ 面板同理 —— 独立 Toplevel，且带鼠标 grab，不 release 会连累整个应用
        #（面板 master 是本窗口，destroy 时 Tk 也会连带销毁，但 grab 必须先放掉）
        self._close_pick_panel()
        # 0917：字号面板同理（带 grab 的独立 Toplevel）
        self._close_font_panel()
        # 顶栏保存动画的 after 也要停掉（这里 root 还是局部变量，能正常 after_cancel）
        if self._save_anim_timer is not None:
            try:
                root.after_cancel(self._save_anim_timer)
            except Exception:
                pass
        self._save_anim_timer = None
        self._save_cv = None
        if self._drop_hover_timer is not None:
            try:
                root.after_cancel(self._drop_hover_timer)
            except Exception:
                pass
        self._drop_hover_timer = None
        self._ind_last = None
        # 停掉双向同步轮询（否则窗口销毁后 after 回调还会跑）
        if self._sync_timer is not None:
            try:
                root.after_cancel(self._sync_timer)
            except Exception:
                pass
        self._sync_timer = None
        self._self_written = ""
        # 🔴 必须在 destroy 之前还原窗口过程：窗口没了还留着我们的回调 → 之后再来消息就崩
        self._disable_file_drop()
        try:
            root.destroy()
        except Exception:
            pass
        del root
        self._win = None        # 0915c：不留悬空引用（多会话下防内存泄漏）
        gc.collect()

    # ======================== 顶栏 / 底栏控件 ========================

    def _make_bar_button(self, parent: tk.Widget, text: str, size: int, cmd,
                         tip_kind: str | None = None) -> tk.Button:
        """顶栏的清爽按钮（+ / ⋯ / ×）：无边框、悬停一档同色系的深色。

        0916b：底 / 字 / 悬停三色都随本便签配色走，并把按钮**登记**到
        `self._bar_buttons` —— `activebackground` / `activeforeground` 不是
        `cget("bg")`，统一刷色的遍历看不见它们，只能显式改
        （否则绿底便签上把鼠标移到「⋯」，按钮会闪一下金黄）。

        0917：`tip_kind` 非空时登记到 `_bar_tip_items` 并挂「悬浮出气泡」
        （老板要求标题栏按钮也要有气泡提示）。气泡位置由 `_tip_show` 自动判断：
        顶栏按钮上方没空间 → 自动改到按钮**下方**（沿用底栏那套兜底逻辑）。
        """
        btn = tk.Button(
            parent, text=text, font=("Segoe UI", size),
            bg=self._note_bar, fg=self._note_icon_fg, relief="flat", bd=0,
            highlightthickness=0, cursor="hand2", padx=7, pady=3,
            activebackground=self._note_hover, activeforeground=self._note_icon_fg,
            command=cmd,
        )
        self._bar_buttons.append(btn)
        if tip_kind:
            self._bar_tip_items[tip_kind] = btn
            btn.bind("<Enter>", lambda e, k=tip_kind: self._tip_schedule(k))
            btn.bind("<Leave>", lambda e: self._tip_cancel())
        return btn

    # ---------------- 顶栏「保存状态」图标（0915）----------------
    # 老板原话：「键入文字的时候，标题栏三个点的按钮左侧添加一个动画效果（循环箭头），
    #           当停止输入，并保存好的时候，变为一个对号」。
    # 状态机：`saved`（对号：打开时 / 落盘完成）⇄ `saving`（旋转双弧箭头：编辑中）。

    def _draw_save_ok(self) -> None:
        """对号：一笔带过的细线勾（圆头 + 圆角接点，贴近参考图那种干净笔画）。"""
        cv = self._save_cv
        if cv is None:
            return
        try:
            cv.delete("all")
            cv.create_line(4.0, 9.5, 7.6, 13.0, 14.5, 6.0,
                           fill=SAVE_OK_FG, width=1.9,
                           capstyle="round", joinstyle="round")
        except Exception:
            pass

    def _draw_save_spin(self, deg: float) -> None:
        """循环箭头 = 两段弧（各 112°、相差 180°）+ 末端小三角，整体按 `deg` 旋转。

        18px 画布里取 r=5.4 / 弧宽 1.6 / 箭头 2.6px —— 笔画够开，不会糊成一坨。
        ⚠️ Tk 的 `create_arc(start=…)` 是**逆时针**、0° 在 3 点方向；屏幕 y 轴向下，
           所以点坐标要写成 `cy - r*sin(a)`（否则图形会上下镜像）。
        """
        cv = self._save_cv
        if cv is None:
            return
        try:
            cv.delete("all")
        except Exception:
            return
        cx = cy = SAVE_ICON / 2.0
        r = 5.4
        ext = 112.0
        for start in (deg, deg + 180.0):
            try:
                cv.create_arc(cx - r, cy - r, cx + r, cy + r,
                              start=start, extent=ext, style="arc",
                              outline=SAVE_SPIN_FG, width=1.6)
            except Exception:
                continue
            a = math.radians(start + ext)            # 弧的扫描末端
            ex = cx + r * math.cos(a)
            ey = cy - r * math.sin(a)
            d = a + math.pi / 2.0                    # 逆时针扫描在该点的切线方向
            px, py = math.cos(d + math.pi / 2.0), -math.sin(d + math.pi / 2.0)
            try:
                cv.create_polygon(
                    ex + 2.6 * math.cos(d), ey - 2.6 * math.sin(d),
                    ex + 1.7 * px, ey + 1.7 * py,
                    ex - 1.7 * px, ey - 1.7 * py,
                    fill=SAVE_SPIN_FG, outline="")
            except Exception:
                pass

    def _set_save_state(self, state: str) -> None:
        """切保存状态：`"saving"` → 旋转箭头（自转）；其它值 → 停转并画对号。"""
        if self._save_cv is None:
            return
        if state == "saving":
            self._save_state = "saving"
            if self._save_anim_timer is None:
                self._save_anim_tick()               # 立刻出第一帧，别干等 90ms
            return
        self._save_state = "saved"
        root = self._win
        if self._save_anim_timer is not None and root is not None:
            try:
                root.after_cancel(self._save_anim_timer)
            except Exception:
                pass
        self._save_anim_timer = None
        self._draw_save_ok()

    def _save_anim_tick(self) -> None:
        """动画帧：转一步 + 排下一帧（只在 saving 态循环）。"""
        self._save_anim_timer = None
        root = self._win
        if self._save_state != "saving" or root is None or self._save_cv is None:
            return
        self._save_anim_angle = (self._save_anim_angle + SAVE_ANIM_STEP) % 360.0
        self._draw_save_spin(self._save_anim_angle)
        try:
            self._save_anim_timer = root.after(SAVE_ANIM_MS, self._save_anim_tick)
        except Exception:
            self._save_anim_timer = None

    def _draw_tool_icon(self, cv: tk.Canvas, kind: str, fg: str | None = None,
                        clear: bool = True) -> None:
        """在画布上画一个工具栏图标（细线风格，贴近参考图）。

        画布统一 **ICON_H(22)×22**（0914z：7 个图标尺寸必须一致）。
        🔴 两个列表图标在 22px 内的画法（`_icon_exp5_0914z.py` 并排渲染 + BitBlt 放大 8×
           实测定稿，`icon_22px_0914z.png`）：
             · 无序 = **三圆点 + 三横线**，y=5/11/17（行距 6）—— 清晰，与 B/I/U/ab 同高。
             · 有序 = **单个「1.」**（10 号粗，与主界面工具栏同款字符）。
               ❌ 三行 1/2/3（4~6 号字）在 22px 里上下顶成一团糊字；两行 1/2 也糊。
               → 与其画糊，不如用主界面那套「1.」记号，一眼认得出、笔画干净。

        `fg` = 图标颜色；0915 起悬停 / 选中态要换色重绘，所以本函数**可重复调用**
        （内部先 `delete("all")`），不再只在创建时画一次。
        """
        # 0916b：默认图标色从模块常量 ICON_FG 改为**本条便签**的配色（炭笔底 = 亮白）
        fg = self._note_icon_fg if fg is None else fg
        if clear:
            try:
                cv.delete("all")           # 重绘前清空（悬停/选中换色时复用同一块画布）
            except Exception:
                pass
        if kind == "bold":
            cv.create_text(11, 11, text="B", fill=fg, font=("Segoe UI", 12, "bold"))
        elif kind == "italic":
            cv.create_text(11, 11, text="I", fill=fg, font=("Segoe UI", 12, "italic"))
        elif kind == "underline":
            cv.create_text(11, 10, text="U", fill=fg, font=("Segoe UI", 12))
            cv.create_line(5, 17, 17, 17, fill=fg, width=1)
        elif kind == "strike":
            cv.create_text(11, 11, text="ab", fill=fg, font=("Segoe UI", 10))
            cv.create_line(3, 11, 19, 11, fill=fg, width=1)
        elif kind == "list":
            # 无序：三行「圆点 + 横线」，y=5/11/17（回到 22px 画布的行距）
            for y in (5, 11, 17):
                cv.create_line(3, y, 5, y, fill=fg, width=2)
                cv.create_line(8, y, 19, y, fill=fg, width=1)
        elif kind == "olist":
            # 有序：单「1.」大字（对齐主界面工具栏的 1. 记号）
            cv.create_text(11, 11, text="1.", fill=fg, font=("Segoe UI", 10, "bold"))
        elif kind == "image":
            cv.create_rectangle(3, 4, 19, 18, outline=fg, width=1)
            cv.create_oval(6, 7, 9, 10, outline=fg, width=1)
            cv.create_line(4, 16, 9, 11, 13, 15, fill=fg, width=1)
            cv.create_line(11, 16, 14, 12, 18, 17, fill=fg, width=1)

    # ---------------- 底栏工具：选中态 / 悬浮提示（0915）----------------
    # 🔴 老板 0915 要求：① 光标/选区处的格式要让对应按钮**显示选中态**（像主界面文字工具）；
    #                    ② 鼠标悬浮任意工具要**弹提示**（像主界面文字工具的气泡）。
    #    主界面实现见 `便签应用.html`：`.tb-item.active`（bg #e8f1ff / fg #1f5ee8）
    #    + `syncFormatState()`；气泡是 `#ui-tip`（白底 1px 边框圆角 10，300ms 延迟）。

    def _paint_fmt(self, kind: str) -> None:
        """按「选中 / 悬停 / 常态」三态刷新**一个**工具的底色与图标色。

        🔴 悬停**不能**直接 `configure(bg=BTN_HOVER)`：选中态也要用底色表达，
           悬停会把选中底色盖掉。统一走这里，选中优先级高于悬停。
        """
        cv = self._fmt_items.get(kind)
        if cv is None:
            return
        on = bool(self._fmt_on.get(kind))
        hov = (self._fmt_hover == kind)
        if on:
            bg, fg = FMT_ON_BG, FMT_ON_FG      # 选中：平面灰底 + 黑图标（0915d5 去掉内阴影，回到平面高亮）
        elif hov:
            # 0916b：悬停底色也走本便签配色（黄系 #f7ea9e = 老板 0914x 定稿值，未变）
            bg, fg = self._note_hover, self._note_icon_fg
        else:
            # 0916：常态底色与图标色都随本便签的底色走（炭笔底 → 亮白图标，见 _note_icon_fg）
            bg, fg = self._note_bg, self._note_icon_fg
        try:
            cv.configure(bg=bg)
            # 0915d5：去掉内阴影凹陷，选中态 = 平面灰底（FMT_ON_BG）+ 黑图标（FMT_ON_FG），无框无阴影。
            self._draw_tool_icon(cv, kind, fg)
        except Exception:
            pass

    def _fmt_hover_on(self, kind: str) -> None:
        self._fmt_hover = kind
        self._paint_fmt(kind)
        self._tip_schedule(kind)

    def _fmt_hover_off(self, kind: str) -> None:
        if self._fmt_hover == kind:
            self._fmt_hover = None
        self._paint_fmt(kind)
        self._tip_cancel()

    def _refresh_fmt_state(self) -> None:
        """读光标 / 选区处的格式 → 刷新 7 个工具的选中态（对齐主界面 `syncFormatState`）。

        判定规则与主界面一致：
          · B / I / U / ab → 光标（或有选区时的选区起点）处的 tag
          · 无序 / 有序   → **光标所在行**的行首标记类型（`_mark_kind`）
          · 图片按钮       → 是「动作」不是「状态」，永远不选中
        状态没变就**不重绘**（每次按键都会调 → 省开销）。
        """
        ed = self._editor
        if ed is None:
            return
        new = {k: False for k in FMT_KINDS}
        if self._editing:
            try:
                sel = ed.tag_ranges("sel")
                pos = "sel.first" if sel else "insert"
                tn = set(ed.tag_names(pos))
                for k in ("bold", "italic", "underline", "strike"):
                    new[k] = k in tn
                ln = int(ed.index(pos).split(".")[0])
                mk = _mark_kind(ed.get("%d.0" % ln, "%d.end" % ln))
                new["list"] = (mk == "list")
                new["olist"] = (mk == "olist")
            except Exception:
                pass
        if new == self._fmt_on:
            return
        changed = [k for k in FMT_KINDS if new[k] != self._fmt_on.get(k)]
        self._fmt_on = new
        for k in changed:
            self._paint_fmt(k)

    def _clear_fmt_state(self) -> None:
        """浏览态 / 退出编辑：所有工具回到未选中。"""
        if not any(self._fmt_on.values()):
            return
        self._fmt_on = {k: False for k in FMT_KINDS}
        for k in FMT_KINDS:
            self._paint_fmt(k)

    # ---- 悬浮提示气泡（对齐主界面 #ui-tip）----

    def _tip_text(self, kind: str):
        """kind → (标题, 说明)；**两类气泡共用一套窗口**（底栏工具 / 顶栏按钮）。"""
        return FMT_TIPS.get(kind) or BAR_TIPS.get(kind)

    def _tip_target(self, kind: str):
        """kind → 气泡要对齐的控件（顶栏按钮 / 保存状态图标 / 底栏工具图标）。

        🔴 分两张表查而不是合并成一张：底栏工具的控件是 Canvas、会随模式挂卸重建，
           顶栏按钮是 Button、登记在 `_bar_buttons` —— 合并会让「重建后拿到旧控件」
           变得不容易发现。
        """
        for d in (self._bar_tip_items, self._fmt_items):
            w = d.get(kind)
            if w is not None:
                return w
        return None

    def _tip_schedule(self, kind: str) -> None:
        """鼠标停在控件上满 `TIP_DELAY_MS` 才弹（主界面也是 300ms 延迟）。"""
        self._tip_cancel()
        if self._tip_text(kind) is None or self._win is None:
            return
        try:
            self._tip_timer = self._win.after(
                TIP_DELAY_MS, lambda k=kind: self._tip_show(k))
        except Exception:
            self._tip_timer = None

    def _tip_cancel(self) -> None:
        """取消尚未弹出的定时器 + 收起已弹出的气泡。"""
        root = self._win
        if self._tip_timer is not None and root is not None:
            try:
                root.after_cancel(self._tip_timer)
            except Exception:
                pass
        self._tip_timer = None
        self._tip_hide()

    def _build_tip(self) -> None:
        """建气泡窗口：无边框 + 白底 + 1px 灰边 + Win11 DWM 圆角（近似主界面 #ui-tip）。"""
        root = self._win
        if root is None:
            return
        w = tk.Toplevel(root)
        w.withdraw()
        w.overrideredirect(True)
        try:
            w.attributes("-topmost", True)
        except Exception:
            pass
        box = tk.Frame(w, bg=TIP_BORDER)
        box.pack(fill="both", expand=True)
        inner = tk.Frame(box, bg=TIP_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        l1 = tk.Label(inner, text="", bg=TIP_BG, fg=TIP_L1_FG,
                      font=("Microsoft YaHei", 9, "bold"), anchor="w", justify="left")
        l1.pack(side="top", anchor="w", padx=10, pady=(5, 0))
        l2 = tk.Label(inner, text="", bg=TIP_BG, fg=TIP_L2_FG,
                      font=("Microsoft YaHei", 8), anchor="w", justify="left")
        l2.pack(side="top", anchor="w", padx=10, pady=(2, 5))
        self._tip_win, self._tip_box = w, box
        self._tip_labels = {"l1": l1, "l2": l2}

    def _tip_show(self, kind: str) -> None:
        """弹出气泡：优先在控件**上方**；上方没空间（顶栏按钮）就自动改到**下方**。"""
        self._tip_timer = None
        tgt = self._tip_target(kind)
        tip = self._tip_text(kind)
        root = self._win
        if tgt is None or tip is None or root is None:
            return
        if self._tip_kind == kind and self._tip_win is not None:
            try:
                if self._tip_win.winfo_viewable():
                    return                       # 同一个气泡已在显示 → 别反复折腾（会闪）
            except Exception:
                pass
        try:
            if self._tip_win is None:
                self._build_tip()
            self._tip_labels["l1"].configure(text=tip[0])
            l2 = self._tip_labels["l2"]
            if tip[1]:
                l2.configure(text=tip[1])
                if not l2.winfo_manager():
                    l2.pack(side="top", anchor="w", padx=10, pady=(2, 5))
            elif l2.winfo_manager():
                l2.pack_forget()
            self._tip_kind = kind
            w = self._tip_win
            w.update_idletasks()
            tw, th = w.winfo_reqwidth(), w.winfo_reqheight()
            x = tgt.winfo_rootx() + max(1, tgt.winfo_width()) // 2 - tw // 2
            y = tgt.winfo_rooty() - th - TIP_GAP
            try:                                  # 贴边兜底：不出屏、不盖按钮
                sw = root.winfo_screenwidth()
                x = max(4, min(x, sw - 4 - tw))
                # 🔴 判据是**本便签窗口的顶沿**，不是屏幕顶沿（0917 修）：
                #    悬浮便签通常在桌面中间，窗口顶沿离屏幕顶沿很远。若只看 `y < 4`，
                #    顶栏按钮上方的气泡会「放到窗口外面去」——飘在桌面/别的窗口上，
                #    看着像掉了，却永远等不到翻转。
                #    底栏工具的上方是编辑区、仍在窗口**内** → 不翻转，保持向上弹的原观感。
                top_edge = 0
                try:
                    top_edge = tgt.winfo_toplevel().winfo_rooty()
                except Exception:
                    top_edge = 0
                if y < top_edge + 2 or y < 4:
                    y = tgt.winfo_rooty() + tgt.winfo_height() + TIP_GAP
            except Exception:
                pass
            w.geometry("+%d+%d" % (int(x), int(y)))
            w.deiconify()
            w.lift()
            self._round_tip()                     # 无边框窗口映射后再套圆角才生效
        except Exception:
            pass

    def _round_tip(self) -> None:
        """给气泡套 Win11 DWM 抗锯齿圆角（失败静默，直角也能看）。"""
        w = self._tip_win
        if w is None or not _HAS_DWM:
            return
        try:
            hwnd = _user32.GetAncestor(w.winfo_id(), 2) or w.winfo_id()
            val = ctypes.c_int(DWMWCP_ROUND)
            _dwmapi.DwmSetWindowAttribute(
                int(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(val), ctypes.sizeof(val))
            none_color = ctypes.c_uint(DWMWA_COLOR_NONE)
            _dwmapi.DwmSetWindowAttribute(
                int(hwnd), DWMWA_BORDER_COLOR,
                ctypes.byref(none_color), ctypes.sizeof(none_color))
        except Exception:
            pass

    def _tip_hide(self) -> None:
        self._tip_kind = None
        w = self._tip_win
        if w is None:
            return
        try:
            w.withdraw()
        except Exception:
            pass

    def _destroy_tip(self) -> None:
        """销毁气泡窗口（Tk 退出前必须调，否则 after / Toplevel 残留会报错）。"""
        self._tip_kind = None
        w, self._tip_win = self._tip_win, None
        self._tip_box = None
        self._tip_labels = {}
        if w is None:
            return
        try:
            w.destroy()
        except Exception:
            pass

    # ======================== 模式切换 ========================
    # 🔴 关键：绝不用 pack(before=...) —— 目标未挂载会抛 TclError，整条链断掉（见文件头教训）
    # 🔴 关键：顶/底只挂卸 holder 里的 bar，holder 本身常驻 → 正文区尺寸恒定（见文件头设计 1）

    def _enter_edit_mode(self, caret_index: str | None = None) -> None:
        """进入编辑模式：显示顶栏 + 底栏，编辑器切为可写。"""
        if self._root is None:
            return
        if self._editing and caret_index is None:
            return
        self._editing = True
        try:
            # 🔴 必须用 `before=self._body` 恢复**原始 pack 顺序**（占位槽排在 body 之前）：
            #    body 里装着 Text（请求高 ≈ 24 行 ≈ 480px > 可用高），若占位槽被排到 body
            #    之后，pack 会把剩余空间全判给 expand 的 body → 槽分到 0px → **根本不映射**
            #    （实测 mapped=0 / h=1，底栏整条消失）。
            #    `before` 目标 `self._body` 自创建起**从不卸下**，故不会踩「before 目标未挂载」
            #    那个历史坑（那次的坑是把 before 指到会被 forget 的 editor 上）。
            try:
                self._bot_holder.pack(side="bottom", fill="x", before=self._body)
            except Exception:
                self._bot_holder.pack(side="bottom", fill="x")
            self._top_bar.pack(fill="both", expand=True)
            self._bottom_bar.pack(fill="both", expand=True)
            self._editor.config(state="normal")
            self._editor.focus_set()
            if caret_index:
                self._editor.mark_set("insert", caret_index)
            elif self._showing_placeholder:
                self._editor.mark_set("insert", "1.0")
            else:
                self._editor.mark_set("insert", "end")
            self._editor.see("insert")
        except Exception:
            pass
        self._refresh_handle_colors()   # 顶/底栏变金黄 → 拉伸热区跟着换色（防浅色条）
        self._layout_side_handles()     # 左右热区恢复到「只跨正文」的跨度
        self._sync_sbar()
        self._refresh_fmt_state()       # 进编辑 → 工具栏按当前光标位置亮起选中态

    def _exit_edit_mode(self) -> None:
        """退出编辑模式：隐藏顶栏，**底栏彻底不占位**，编辑器切为只读（可滚动）。"""
        if not self._editing or self._root is None:
            return
        self._editing = False
        self._clear_image_sel()          # 退出编辑 → 收起图片选中框/角手柄（对齐主界面 blur 行为）
        try:
            self._save_now()
            self._top_bar.pack_forget()
            self._bottom_bar.pack_forget()
            # 🔴 底栏「不做占位」：连**占位槽本身**一起 pack_forget，正文区随即向下
            #    延伸吃掉这 BOTTOM_BAR_HEIGHT px（`body` 是 expand 的，会自动补上）。
            #    ⚠️ 别用 `holder.configure(height=0)` —— Tk 的 Frame 把 `-height 0`
            #       当作「未指定/自适应」直接忽略，实测槽高仍为常量值（踩过）。
            #    ⚠️ 重新 pack **必须** `before=self._body` 把顺序挪回 body 之前 ——
            #       body 里的 Text 请求高 ≈ 480px > 可用高，占位槽若排在 body 之后，
            #       expand 的 body 会把剩余空间全吃掉 → 槽分到 0px → 不映射、底栏消失。
            #       （用「空 body」做的简化实验会骗人：空 body 请求高只有 1px，
            #         顺序怎么排都对；真实 app 必须按真实结构验。）
            #       `self._body` 从不卸下，故 `before=` 安全（历史坑是 before 指到会被
            #       forget 的 editor 上）。
            self._bot_holder.pack_forget()
            self._editor.config(state="disabled")
            # 🔴 绝不能像旧版那样「取纯文本 → 重写整个 Text」：那会把内嵌图片和格式全抹掉。
            #    只有正文真的空了才铺占位符，否则**原样保留**（文字 / 格式 / 图片都在）。
            if self._editor_empty():
                self._has_content = False
                self._set_display("", placeholder=True)
            else:
                self._has_content = True
            self._editor.yview_moveto(0.0)
        except Exception:
            pass
        self._refresh_handle_colors()   # 顶/底栏隐去 → 热区回到正文色
        self._layout_side_handles()     # 左右热区延伸到底边（正文已占满）
        self._sync_sbar()
        self._clear_fmt_state()         # 退编辑（底栏都不在了）→ 工具选中态清零
        self._tip_cancel()              # 收起可能还挂着的提示气泡

    def _on_focus_out(self, event) -> None:
        """失去焦点时退出编辑模式（模拟「点外部」）。

        用 after 延迟检查：避免点击本窗口内部控件（按钮等）时 FocusOut 误触发。
        """
        if self._root is None:
            return
        self._win.after(120, self._check_focus_out)

    def _check_focus_out(self) -> None:
        if self._root is None:
            return
        if self._dialog_open:
            return              # 🔴 文件对话框开着 → 这次失焦不是「点了便签外面」，别退编辑
        if self._ctx_menu_open:
            return              # 图片右键菜单弹出中 → 焦点暂时在菜单上，别退编辑
        if self._pick_open:
            return              # 0916 ⋯ 面板弹出中 → 同上（焦点在面板那个 toplevel 上）
        if self._font_open:
            return              # 0917 字号面板弹出中 → 同上
        try:
            focus = self._win.focus_get()
            if focus is not None and focus.winfo_toplevel() == self._win:
                return
        except Exception:
            pass
        if self._editing:
            self._exit_edit_mode()

    def _on_editor_click(self, event) -> None:
        """浏览模式点击正文：进入编辑模式并把光标落到点击处。"""
        if self._editing:
            return
        idx = None
        try:
            idx = self._editor.index("@%d,%d" % (event.x, event.y))
        except Exception:
            idx = None
        self._editing = False   # 确保 _enter_edit_mode 走完整挂载流程
        self._enter_edit_mode(idx)

    # ======================== 占位符 / 文本读写 ========================

    def _set_display(self, text: str, placeholder: bool = False) -> None:
        """把文本写进 Text（占位符走灰色 tag）。保持当前 state 不变。"""
        ed = self._editor
        if ed is None:
            return
        st = "normal"
        try:
            st = ed.cget("state")
        except Exception:
            pass
        try:
            ed.config(state="normal")
            ed.delete("1.0", "end")
            if placeholder:
                ed.insert("1.0", PLACEHOLDER, ("placeholder",))
                self._showing_placeholder = True
            else:
                ed.insert("1.0", text)
                self._showing_placeholder = False
            ed.config(state=st)
        except Exception:
            pass

    def _clear_placeholder(self) -> None:
        """用户开始输入时，清掉灰色占位符。"""
        ed = self._editor
        if ed is None or not self._showing_placeholder:
            return
        try:
            st = ed.cget("state")
            ed.config(state="normal")
            ed.delete("1.0", "end")
            ed.config(state=st)
        except Exception:
            pass
        self._showing_placeholder = False

    def _get_text(self) -> str:
        """取真实内容（占位符状态返回空串，避免把「记笔记...」存进数据）。"""
        ed = self._editor
        if ed is None or self._showing_placeholder:
            return ""
        try:
            return ed.get("1.0", "end-1c")
        except Exception:
            return ""

    def _on_keypress(self, event=None) -> str | None:
        """键盘按下：清占位符；**回车交给 `_on_return`**（列表续号必须拦住默认换行）。

        ⚠️ 同一 widget 上 `<KeyPress>` 与更具体的 `<Return>` 同时绑定的话，Tk **只执行更具体的
           那个**（`_on_keypress` 会被跳过）→ 所以这里一并接管回车，不另开 `<Return>` 绑定；
           `_on_return` 内部也调了 `_clear_placeholder()`（幂等）做双保险。
        返回值：普通按键返回 `None`（让默认逻辑插入字符）；回车由 `_on_return` 返回 `"break"`。
        """
        if self._editing:
            self._clear_placeholder()
        self._last_key_ts = time.time()      # 编辑保护用（见 `_poll_sync`）
        ks = getattr(event, "keysym", "") if event is not None else ""
        # ---- 图片选中态下的按键（对齐主界面）----
        if self._sel_img:
            if ks in ("Delete", "BackSpace"):
                self._delete_image(self._sel_img)
                return "break"
            if ks == "Escape":
                self._clear_image_sel()      # 有图选中时 Esc = 取消选中（return "break" 拦住「关窗口」）
                return "break"
            if ks not in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                          "Alt_L", "Alt_R", "Super_L", "Super_R", "Caps_Lock"):
                self._clear_image_sel()      # 其它按键 = 离开选中态（同主界面 keydown 逻辑）
        # ---- 0917f：光标贴着「块级图片」时的删除键 ----
        # 🔴 图片前面那个 `\n` 是**布局胶水**（`_insert_image_block` 补的），Tk 把它当普通字符：
        #    Backspace 会删掉它 → 文字与图片并成一行 → `<KeyRelease>` 上的 `_on_edit` →
        #    `_enforce_image_blocks()` 又立刻把换行插回去 = 「删了又补」，**单击净零**
        #    （老板报的「单击删不掉上方文字、长按能删」；长按期间 `<KeyRelease>` 只在松手时
        #      来一次 → 兜底不跑 → 多次删除累积生效）。
        #    这里按用户语义接管：Backspace 删**上一行末尾的字符**，胶水换行原样留着。
        if ks == "BackSpace":
            if self._backspace_before_image():
                return "break"
            # 对称面（贴图**右**边退格）：`insert-1c` 就是图片本体 → 走 `_delete_image()`
            #（Tk 默认也会把它删掉，但不清理 `_img_store`、不落盘、后面的换行留成空行）。
            if self._editor is not None:
                # ⚠️ 必须先用 `compare` 排掉文首：光标在 `1.0` 时 `insert -1c` = `0.0`，
                #    而 Tk 会把 `0.0` **规范化成 `1.0`** → `_img_at("0.0")` 会命中
                #    「就是第一个字符的那张图」→ 文首退格把图删了（0917f 正测 A9 抓到）。
                cur = str(self._editor.index("insert"))
                if self._editor.compare(cur, ">", "1.0"):
                    nm_prev = self._img_at(str(self._editor.index("%s -1c" % cur)))
                    if nm_prev:
                        self._delete_image(nm_prev)
                        return "break"
        elif ks == "Delete" and self._editor is not None:
            # 对称面：Delete 删「光标右边」= 图片本体 → 必须走 `_delete_image()`
            #（Tk 默认也能把图删掉，但不清理 `_img_store`、不落盘、图片后的换行也留成空行）。
            nm_at = self._img_at(str(self._editor.index("insert")))
            if nm_at:
                self._delete_image(nm_at)
                return "break"
        # ---- 0917g：光标贴「块级图片」左边界时打字 ----
        # 图片是块级（独占一行）→ 光标停在图片左边界 = 停在**图片本体那个 index** 上：
        #   · 插入符被拉成整段图片高（实测 96px vs 正常 19px）；
        #   · 字插在图片左边 → 兜底把图挤下去 → `insert` 右重力又把它顶回图片左边界
        #     → 下一个字重复 → **每字独占一行（竖直排列）**。
        # 这里先把光标挪到上一行行尾（= 主界面里图片左边界在视觉上的归属），
        # 返回 None 让默认逻辑在新位置落字 → 横向排版 + 正常插入符。
        # 🔴 必须放在 Backspace / Delete **之后**：那两条分支（0917f）就是**靠**
        #    「光标停在图片左边界」判断的，提前挪走光标它们就永远不触发（失去可测性）。
        #    只对**会插入文字**的按键生效（`char` 可打印）；方向键 / 组合键 `char` 为空 → 不受影响。
        if event is not None:
            ch = getattr(event, "char", "") or ""
            if ch and ch.isprintable():
                self._caret_off_image_left()
        if ks in ("Return", "KP_Enter"):
            return self._on_return()
        return None

    def _on_return(self) -> str | None:
        """回车：列表项**自动续号**，空项**退出列表**（对齐主界面原生 `<ol>/<ul>`，0914z 新增）。

        主界面里列表是 contenteditable 的原生行为，回车由浏览器处理：
          · **非空**列表项回车 → 新行自动带下一个标记（有序 = 本行号 +1 / 无序 = `• `）
          · **空**列表项回车   → 摘掉标记变普通空行 = 退出列表（**不新增行**）
        悬浮便签是纯 Tk Text，没有列表概念 → 手工补上，否则两处规则不一致。

        返回 `"break"` = 拦住默认换行（换行与标记已在本函数里插好）。
        非列表行 / 有选区 / 光标不在行尾 → 返回 `None` 走 Tk 默认行为（不去干预）。
        """
        ed = self._editor
        if ed is None or not self._editing:
            return None
        try:
            if ed.tag_ranges("sel"):
                return None                    # 有选区：默认逻辑要负责「删选区 + 换行」
            ln = int(ed.index("insert").split(".")[0])
            if ed.index("insert") != ed.index("%d.end" % ln):
                return None                    # 光标不在行尾：不干预，避免与默认的「拆行」打架
            line = ed.get("%d.0" % ln, "%d.end" % ln)
            m = _LIST_RE.match(line)
            if not m:
                return None                    # 非列表行 → 普通换行
            if not line[m.end(0):].strip():
                # 空项 → 退出列表：整行清干净（含标记与缩进空白），光标留在该行，不新增行
                ed.delete("%d.0" % ln, "%d.end" % ln)
                ed.mark_set("insert", "%d.0" % ln)
            else:
                # 非空项 → 换行 + 新行带下一个标记（保留前导缩进）
                nm = _NUM_RE.match(line)
                mark = ("%d. " % (int(nm.group(2)) + 1)) if nm else BULLET
                ed.insert("insert", "\n" + m.group(1) + mark)
                ed.mark_set("insert", "%d.end" % (ln + 1))
            ed.see("insert")
            self._on_edit()
            return "break"
        except Exception:
            return None

    # ======================== 数据与保存 ========================

    def _load_current(self) -> None:
        """载入最新一条便签：正文 HTML → Text（文字 + 行内格式 + 内嵌图片）。"""
        try:
            # 有 id 就按 id 读（`load()` 取的是"最后一条"，新建/弹窗后两者可能不是同一条）
            if self._current_id and hasattr(self.api, "load_by_id"):
                data = self.api.load_by_id(self._current_id) or self.api.load()
            else:
                data = self.api.load()
            self._current_id = data.get("id") or self._current_id
            self._src_id = data.get("src_id", "") or ""
            self._fill_from_html(data.get("content") or "")
            self._has_content = not self._editor_empty()
            if not self._has_content:
                self._set_display("", placeholder=True)
        except Exception:
            self._current_id = None
            self._has_content = False
            self._set_display("", placeholder=True)
        self._sync_sbar()

    def _save_now(self) -> None:
        """落盘：正文以 **HTML** 存（内嵌图片的 dataURL 就在里面）。"""
        if not self._current_id or self._editor is None:
            self._set_save_state("saved")    # 没东西可存 → 别让顶栏箭头一直空转
            return
        # 🔴 0915c 多悬浮窗：**绝不能跨会话踩别人的记录**。
        #    会话刚建好时可能还临时指向那条「起始空便签」（多会话会共享同一条），
        #    此刻它若已被**别的会话**绑定（src_id 属于别人），本次保存必须跳过 ——
        #    否则自己空荡荡的正文会把别人刚写进去的内容清掉。
        #    典型触发：`_show_content_in_tk` 开头会先 `_save_now()` 保存旧内容，
        #    而此刻新的 target/src_id 还没解析出来（`_multitest_0915c` 抓到的正是这个）。
        try:
            cur = self.api.load_by_id(self._current_id) or {}
        except Exception:
            cur = {}
        owner = cur.get("src_id") or ""
        if owner and owner != self._src_id:
            self._set_save_state("saved")    # 别人的记录：不写，也别让图标空转
            return
        try:
            html = self._get_html()
            # 0915d：与 api 端同规则（内容变才 +1）本地推算新版本号 ——
            # 不用为了取号再读一次盘（`_save_now` 在防抖里高频跑）。
            if (cur.get("content") or "") != html:
                self._rev = int(cur.get("revision") or 0) + 1
            self.api.save_note(self._current_id, html)
            # 记下自己写进去的内容 → 轮询比对时能一眼认出「这是我刚写的」，不自读自刷
            self._self_written = html
        except Exception:
            pass
        finally:
            # 0915：落盘结束 → 顶栏状态图标切回对号。
            # ⚠️ 写盘失败也切：否则箭头会永远转下去（比短暂误导更糟）。
            self._set_save_state("saved")

    def _poll_sync(self) -> None:
        """主界面改了绑定的便签 → 同步到本悬浮窗（老板 0915「实时同步到两边」）。

        🔴 编辑保护：**正在打字时绝不覆盖正文** —— 把外来的内容铺进去会直接吃掉
           用户刚敲的字（数据丢失），比「延迟一会儿同步」严重得多。
           所以只在「非编辑态」或「编辑态但 1.5s 内没敲键」时才重铺。
        """
        root = self._win
        if root is None:
            return
        try:
            self._sync_timer = root.after(SYNC_POLL_MS, self._poll_sync)
        except Exception:
            self._sync_timer = None
            return
        # 0915c2：拖动/缩放期间不做「读文件 + 全文序列化」，把主线程整个让给跟手
        if self._dragging or self._resize_edge:
            return
        if not self._src_id or not self._current_id or self._drop_busy:
            return                              # 独立便签（无绑定）→ 不联动
        if self._editing and (time.time() - self._last_key_ts) < SYNC_EDIT_GUARD_S:
            return                              # 用户正在输入 → 本轮跳过
        # 0915e：输入法正在组合（拼音还没上屏）→ 本轮绝不重铺。
        # 组合期间 Tk 不派发 KeyPress，`_last_key_ts` 不刷新，上面那条时间守卫会
        # 误判成「他没在打字」→ 硬铺正文会把正在拼的字清掉、光标跳走。
        if self._editing and self._ime_busy():
            return
        try:
            data = self.api.load_by_id(self._current_id) or {}
        except Exception:
            return
        # 0915e 规格六.5：绑定的记录没了 = 主界面把这条便签删了 → 悬浮窗自行收起，
        # 别再挂着（更不能写盘，否则会把已删的记录复活）。
        # 连续 3 轮（≈900ms）都取不到才认定 —— 避开「记录还没建好」的时序空档。
        if not data:
            self._miss_polls += 1
            if self._src_id and self._miss_polls >= 3:
                self._on_note_deleted()
            return
        self._miss_polls = 0
        # 0915d：revision 防回环 —— 远端版本号 ≤ 我已知的版本，说明那是我自己写进去的
        # （或是一条更旧的数据）→ 绝不拿它覆盖正文。真正的更新必然来自 `revision+1`。
        remote_rev = int(data.get("revision") or 0)
        if remote_rev <= self._rev:
            return
        content = data.get("content") or ""
        # 🔴 0915i：先做**便宜**的「这就是我自己刚写的」判断，再决定要不要序列化。
        #    `_get_html()` 要遍历整个 Text（含 base64 图片）拼字符串，很贵；
        #    而「自己刚保存完 → 下一轮拉回来的就是自己那份」是**最常见**的情形，
        #    原来把它排在 `_get_html()` 之后 → 每 300ms 白序列化一次全文（打字卡顿）。
        if content == self._self_written:
            return
        try:
            mine = "" if self._showing_placeholder else self._get_html()
        except Exception:
            return
        if content == mine:
            return                              # 没变化
        # 0915j 🔴：用「文本 + 行内格式 + 图片」的指纹比较，**取代** 0915b 的纯文本比较。
        #   纯文本判据看不见「只改颜色/字号」和「插入图片」→ 老板 0915j 报的两件事都源于此。
        #   指纹归一化掉纯序列化差异（容器嵌套 / 颜色写法 / 字号单位 / 多余换行）→ 仍会收敛。
        if same_content(content, mine):
            return
        # 振荡保险：若连续多轮「远端指纹一样、应用完本地仍不等」→ 说明这次同步
        # 没法收敛（罕见：某样式一边有、另一边没有）→ 该便签退回纯文本比较，
        # 宁可漏掉格式，也不能每 300ms 重铺一次把正文闪成幻灯片。
        try:
            rfp = html_fingerprint(content)
        except Exception:
            rfp = None
        if self._fp_giveup:
            try:
                if _html_to_text(content) == _html_to_text(mine):
                    return
            except Exception:
                pass
        elif rfp is not None:
            if rfp == self._fp_last_remote:
                self._fp_stall = getattr(self, "_fp_stall", 0) + 1
                if self._fp_stall >= 4:
                    self._fp_giveup = True
            else:
                self._fp_stall = 0
            self._fp_last_remote = rfp
        # 🔴 0915i：重铺会清掉光标与滚动位置，必须先记下来。
        #    原来铺完无条件 `see("1.0")` → 老板「键入几个字鼠标就跳到头上」的**直接元凶**。
        ed = self._editor
        try:
            caret = ed.index("insert")
        except Exception:
            caret = None
        try:
            yv = ed.yview()
        except Exception:
            yv = None
        was_editing = self._editing
        try:
            self._fill_from_html(content)
            self._rev = remote_rev        # 已采纳远端版本 → 本地版本基线跟着走
            self._has_content = not self._editor_empty()
            if not self._has_content:
                self._set_display("", placeholder=True)
            # 把光标放回原处（不是开头），滚动位置一并还原
            if caret:
                try:
                    ed.mark_set("insert", caret)
                except Exception:
                    pass
            if yv:
                try:
                    ed.yview_moveto(yv[0])
                except Exception:
                    pass
            elif caret:
                try:
                    ed.see(caret)        # 保证光标可见（但不强制滚到顶部）
                except Exception:
                    pass
            if was_editing:
                try:
                    ed.focus_set()
                except Exception:
                    pass
            self._sync_sbar()
            self._refresh_fmt_state()
        except Exception:
            pass

    def _ime_busy(self) -> bool:
        """0915e：编辑器是否正处于输入法组合态（取不到一律 False → 降级为时间守卫）。"""
        try:
            ed = self._editor
            return bool(ed is not None and _ime_composing(ed.winfo_id()))
        except Exception:
            return False

    def _on_note_deleted(self) -> None:
        """0915e：绑定的便签被主界面删掉了 → 悬浮窗自行收起。

        不清掉绑定就留着，窗口会显示一份「数据已不存在」的内容；更糟的是一旦触发
        `_save_now`，会把刚删掉的记录重新写回磁盘（复活）。这里直接断链 + 收窗。
        """
        self._miss_polls = 0
        self._current_id = None
        self._src_id = ""
        self._rev = 0
        self._self_written = ""
        try:
            self._hide()
        except Exception:
            pass

    def _on_edit(self, _event=None) -> None:
        root = self._win
        if root is None:
            return
        # 🔴 0917e 兜底：图片**必须独占一行**。插图 / 载入 / 搬动三条路径各自已块级化，
        #    但「用户直接在图片那一行里打字」「主界面同步过来一份图文同行的旧内容」
        #    仍会让文字贴到图片左右 —— 落盘前统一规范一次（无图时 `image_names()` 为空，
        #    本方法立刻返回，不产生 dump 开销）。
        try:
            if self._enforce_image_blocks():
                self._refresh_img_sel()
                # 🔴 0917g 兜底（对称面）：`_enforce_image_blocks()` 刚把字挤到图片上面那一行，
                #    而 Tk 的 `insert` mark 被插进去的 `\\n` 顶回了图片左边界（右重力）→
                #    顺手把光标挪回**文字那一行的行尾**，否则下一个字又被挤成新的一行。
                #    这一步护住不经过 `<KeyPress>` 的路径（输入法提交 / 粘贴 / 主界面同步）。
                # ⚠️ 只在「兜底确实动过正文」时才碰光标：内容没动就别动光标，
                #    否则「点一下图片左边再按 Backspace」（0917f）就失效了。
                self._caret_off_image_left()
        except Exception:
            pass
        self._sync_sbar()
        # 0915：键盘 / 光标 / 选区一变，工具栏的选中态就要跟上（对齐主界面 taChanged）
        self._refresh_fmt_state()
        # 顶栏状态图标：一有改动就转起来，落盘后由 `_save_now` 切回对号
        self._set_save_state("saving")
        if self._save_timer:
            try:
                root.after_cancel(self._save_timer)
            except Exception:
                pass
        # 🔴 0915：保存防抖从 400ms 收紧到 250ms → 悬浮便签落盘更快，
        #    主界面 300ms 轮询拉取后「键入同时」就能看到另一边更新。
        self._save_timer = root.after(250, self._save_now)

    # ======================== 自绘滚动条 ========================

    def _on_yscroll(self, first, last) -> None:
        """Text 的 yscrollcommand 回调：同步滑块位置 + 跟着挪图片选中框。"""
        try:
            self._sb_first = float(first)
            self._sb_last = float(last)
        except Exception:
            return
        self._sb_visible = (self._sb_last - self._sb_first) < 0.9999
        self._redraw_sbar()
        # 文字增减 / 滚动都会挪动内嵌图片 → 选中框和角手柄要重新贴上去
        self._refresh_img_sel()
        self._refresh_img_sel()          # 滚动后图片位置变了 → 选中框/手柄要跟过去

    def _sync_sbar(self, _event=None) -> None:
        """主动从 Text 读一次可视比例（文本变化后 yscrollcommand 未必立刻触发）。"""
        ed = self._editor
        if ed is None:
            return
        try:
            first, last = ed.yview()
            self._sb_first = float(first)
            self._sb_last = float(last)
            self._sb_visible = (self._sb_last - self._sb_first) < 0.9999
        except Exception:
            return
        self._redraw_sbar()

    def _redraw_sbar(self, _event=None) -> None:
        cv = self._sbar
        if cv is None:
            return
        try:
            cv.delete("all")
        except Exception:
            return
        if not self._sb_visible:
            return
        try:
            W = cv.winfo_width()
            H = cv.winfo_height()
        except Exception:
            return
        if W <= 1 or H <= 24:
            return

        hover = self._sb_hover
        if hover:
            cv.create_rectangle(0, 0, W, H, fill=self._note_trough, outline="")
            try:
                cx = W / 2.0
                cv.create_polygon(cx, 3, cx - 4, 9, cx + 4, 9, fill=self._note_arrow, outline="")
                cv.create_polygon(cx, H - 3, cx - 4, H - 9, cx + 4, H - 9,
                                  fill=self._note_arrow, outline="")
            except Exception:
                pass
            top, bot = 12.0, H - 12.0
            bar_w = float(W)
            color = SBAR_THUMB_HOVER
        else:
            top, bot = 1.0, H - 1.0
            bar_w = 5.0
            # 0916b：空闲滑块也跟色系（黄褐滑块压在绿/粉/紫底上会像脏点）
            color = self._note_sb
        span = max(bot - top, 1.0)

        y0 = top + span * self._sb_first
        y1 = top + span * self._sb_last
        if y1 - y0 < 16:            # 滑块最小长度，保证可抓
            y1 = y0 + 16
            if y1 > bot:
                y1 = bot
                y0 = max(top, y1 - 16)

        x0 = 0.0 if hover else (W - bar_w - 1.0)
        r = bar_w / 2.0
        try:
            cv.create_oval(x0, y0, x0 + bar_w, y0 + bar_w, fill=color, outline="")
            cv.create_oval(x0, y1 - bar_w, x0 + bar_w, y1, fill=color, outline="")
            cv.create_rectangle(x0, y0 + r, x0 + bar_w, y1 - r, fill=color, outline="")
        except Exception:
            pass

    def _sbar_enter(self, _e=None) -> None:
        if self._sb_hover:
            return
        self._sb_hover = True
        self._redraw_sbar()

    def _sbar_leave(self, _e=None) -> None:
        if not self._sb_hover:
            return
        self._sb_hover = False
        self._drag_thumb = False
        self._redraw_sbar()

    def _sbar_track(self) -> tuple:
        """返回 (轨道顶, 轨道底, 滑块顶, 滑块高)。"""
        cv = self._sbar
        H = cv.winfo_height() if cv is not None else 1
        top, bot = (12.0, H - 12.0) if self._sb_hover else (1.0, H - 1.0)
        span = max(bot - top, 1.0)
        y0 = top + span * self._sb_first
        y1 = top + span * self._sb_last
        return top, bot, y0, max(y1 - y0, 16.0)

    def _sbar_press(self, event) -> None:
        if not self._sb_visible:
            return
        _top, _bot, y0, hh = self._sbar_track()
        if y0 <= event.y <= y0 + hh:
            self._drag_thumb = True
            self._drag_off = event.y - y0
        else:
            try:
                self._editor.yview_scroll(-1 if event.y < y0 else 1, "pages")
            except Exception:
                pass

    def _sbar_drag(self, event) -> None:
        if not self._drag_thumb:
            return
        top, bot, _y0, _hh = self._sbar_track()
        span = max(bot - top, 1.0)
        frac = (event.y - self._drag_off - top) / span
        frac = max(0.0, min(1.0, frac))
        try:
            self._editor.yview_moveto(frac)
        except Exception:
            pass

    def _on_wheel(self, event) -> str:
        """滚轮滚动正文（浏览/编辑模式通用）。"""
        try:
            delta = int(-1 * (event.delta / 120)) if event.delta else 0
        except Exception:
            delta = 0
        if delta:
            try:
                self._editor.yview_scroll(delta, "units")
            except Exception:
                pass
        return "break"

    # ======================== 窗口四角圆角（DWM 抗锯齿优先）========================
    # 🔴 首选 Win11 DWM 抗锯齿圆角：DwmSetWindowAttribute(hwnd, 33, DWMWCP_ROUND)。
    #    实测在无边框 overrideredirect(WS_POPUP) 窗口上有效，且**不引入原生边框**；
    #    圆弧由 DWM 在合成层抗锯齿 → 没有 SetWindowRgn 那种台阶「像素点」。
    #    DWM 圆角与窗口尺寸无关（缩放不用重设），故**不需要** <Configure> 重算。
    # 🔴 回退（老系统 / 调用失败）：SetWindowRgn 硬边圆角，需在尺寸变化时重裁。

    def _apply_round_corners(self, force: bool = False) -> None:
        """应用四角圆角：优先 DWM 抗锯齿，失败回退 SetWindowRgn 硬边。可重复调用。"""
        root = self._win
        if root is None or not _HAS_WIN32:
            return
        try:
            hwnd = _user32.GetAncestor(root.winfo_id(), 2)   # GA_ROOT=2 → 真正顶层句柄
            if not hwnd:
                hwnd = root.winfo_id()
        except Exception:
            return
        if self._round_mode == "dwm" and not force:
            return
        if _HAS_DWM:
            try:
                val = ctypes.c_int(DWMWCP_ROUND)
                hr = _dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(val), ctypes.sizeof(val))
                if hr == 0:                     # S_OK
                    self._round_mode = "dwm"
                    # 🔴 顺手去掉 DWM 给圆角窗口画的 **1px 半透明边框** ——
                    #    实测该圈边让窗口最外一行/一列不再是栏色（= 老板看到的「空隙」），
                    #    且叠在桌面壁纸上会有一条脏边。NONE 之后内容直抵窗口 rect 边缘。
                    try:
                        nb = ctypes.c_int(DWMWA_COLOR_NONE)
                        _dwmapi.DwmSetWindowAttribute(
                            hwnd, DWMWA_BORDER_COLOR,
                            ctypes.byref(nb), ctypes.sizeof(nb))
                    except Exception:
                        pass
                    return
            except Exception:
                pass
        # ---- 回退：SetWindowRgn 硬边圆角（尺寸变化需重裁 → 挂 <Configure>）----
        self._round_mode = "rgn"
        self._apply_region_fallback()
        try:
            root.bind("<Configure>", self._on_root_configure)
        except Exception:
            pass

    def _apply_region_fallback(self) -> None:
        """回退方案：按当前窗口尺寸重设圆角 region（尺寸变化后必须重调）。"""
        root = self._win
        if root is None or not _HAS_WIN32 or self._round_mode != "rgn":
            return
        try:
            w = root.winfo_width()
            h = root.winfo_height()
            if w <= 1 or h <= 1:
                # 窗口尚未映射：从 geometry 串（"320x380+100+100"）里取尺寸
                try:
                    wh = root.geometry().split("+")[0]
                    w, h = (int(v) for v in wh.split("x"))
                except Exception:
                    w, h = WIN_WIDTH, WIN_HEIGHT
            if w <= 1 or h <= 1:
                return
            hwnd = _user32.GetAncestor(root.winfo_id(), 2)
            if not hwnd:
                hwnd = root.winfo_id()
            d = ROUND_RADIUS * 2
            # CreateRoundRectRgn 的 right/bottom 是开区间，必须 +1 才覆盖满窗口。
            rgn = _gdi32.CreateRoundRectRgn(0, 0, int(w) + 1, int(h) + 1, d, d)
            if rgn:
                # SetWindowRgn 后 region 所有权移交系统，无需手动 DeleteObject；
                # 传 True 让系统立即重绘。
                _user32.SetWindowRgn(hwnd, rgn, True)
                self._rgn_size = (int(w), int(h))
        except Exception:
            pass

    def _on_root_configure(self, event=None) -> None:
        """root 的 Configure：仅回退方案需要（DWM 圆角与尺寸无关）。"""
        root = self._win
        if root is None or self._round_mode != "rgn":
            return
        if event is not None and getattr(event, "widget", None) is not root:
            return
        try:
            size = (root.winfo_width(), root.winfo_height())
        except Exception:
            return
        if size[0] > 1 and size[1] > 1 and size != self._rgn_size:
            self._apply_region_fallback()

    # ======================== 无边框窗口拉伸 ========================

    def _make_resize_handles(self) -> None:
        """在 root 上铺 4 边 + 4 角的隐形热区（place 在最上层）。

        🔴 热区是**不透明 Frame**，会盖住它下面的内容 —— 底色必须与「它盖住的东西」
           一致，否则会在顶栏上沿 / 底栏下沿露出一条异色带（老板看到的「空隙」）。
           顶边 / 两个上角 = 顶栏色（编辑态金黄 / 浏览态正文色）；
           底边 / 两个下角 / 左右边 = 正文色 `NOTE_BG`
           （0914x 起底栏底色已与正文一致，故底边不能再取金黄）。
           左边 / 右边只跨**正文区**垂直范围，不侵入顶栏。
        """
        root = self._win
        if root is None:
            return
        H = HANDLE
        cursors = {
            "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
            "w": "sb_h_double_arrow", "e": "sb_h_double_arrow",
            "nw": "size_nw_se", "se": "size_nw_se",
            "ne": "size_ne_sw", "sw": "size_ne_sw",
        }
        self._rs_handles.clear()
        for edge, cur in cursors.items():
            f = tk.Frame(root, bg=self._note_bg, cursor=cur)
            kw = {}
            is_side = edge in ("w", "e")
            if edge in ("n", "s"):
                # 横条：左右各让出角，避免与角热区重叠
                kw.update(relx=0.0, x=H, relwidth=1.0, width=-2 * H, height=H)
                kw.update(y=0) if edge == "n" else kw.update(rely=1.0, y=-H)
            elif is_side:
                # 🔴 只跨正文区：不覆盖金条，否则金条左右两端露浅色竖条。
                #    垂直跨度随模式变（浏览态底栏不占位 → 延伸到底边），
                #    故这里不 place，统一交给 _layout_side_handles()（循环后调用）。
                pass
            else:
                kw.update(width=H, height=H)
                kw.update(x=0) if "w" in edge else kw.update(relx=1.0, x=-H)
                kw.update(y=0) if "n" in edge else kw.update(rely=1.0, y=-H)
            if not is_side:
                try:
                    f.place(**kw)
                except Exception:
                    continue
            f.bind("<Button-1>", lambda e, ed=edge: self._rs_start(ed, e))
            f.bind("<B1-Motion>", self._rs_move)
            f.bind("<ButtonRelease-1>", self._rs_stop)
            self._rs_handles[edge] = f
        self._layout_side_handles()
        self._refresh_handle_colors()

    def _layout_side_handles(self) -> None:
        """放置左右拉伸热区（垂直跨度随模式变）。

        编辑态：顶栏是金黄 → 左右热区只跨**正文**（不侵入顶栏那条金带）；
        浏览态：**底栏不占位**（0914v）→ 正文一直延伸到底边，左右热区也延伸到底边。
        （0914x 起底栏底色 = 正文色，但左右热区跨度**保持不变**：编辑态仍只跨正文区，
          底栏那 36px 由底边热区负责拉伸。）
        """
        root = self._win
        if root is None:
            return
        bot_h = BOTTOM_BAR_HEIGHT if self._editing else 0
        for edge in ("w", "e"):
            f = self._rs_handles.get(edge)
            if f is None:
                continue
            kw = dict(rely=0.0, y=TOP_BAR_HEIGHT, relheight=1.0,
                      height=-(TOP_BAR_HEIGHT + bot_h), width=HANDLE)
            if edge == "w":
                kw["x"] = 0
            else:
                kw.update(relx=1.0, x=-HANDLE)
            try:
                f.place(**kw)
            except Exception:
                pass

    def _refresh_handle_colors(self) -> None:
        """让拉伸热区底色跟随「它盖住的东西」。

        0914x 起底栏底色 = 正文色 → **只有顶边 / 两个上角**需要金黄（编辑态），
        底边 / 两个下角 / 左右边一律正文色（否则底栏下沿会露出一条金黄带）。
        """
        top_bg = self._note_bar if self._editing else self._note_bg
        for edge, f in self._rs_handles.items():
            try:
                f.configure(bg=(top_bg if edge in ("n", "nw", "ne") else self._note_bg))
            except Exception:
                pass

    def _rs_start(self, edge: str, event) -> None:
        root = self._win
        if root is None:
            return
        self._resize_edge = edge
        self._rs_t = 0.0        # 0915c2：闸门归零 → 第一个 Motion 立即生效
        # 🔴 同 `_start_drag`：基准走 `_win_geom()`，不用 winfo_x/y（缓存旧值会算错）
        gx, gy, gw, gh = self._win_geom()
        self._rs = (event.x_root, event.y_root, gx, gy, gw, gh)

    def _rs_move(self, event) -> None:
        """0915c2：与拖动同理 —— 时间闸门限流，在 Motion 里直接改尺寸（不用 `after`）。

        改尺寸比移动更贵：每次都会触发正文重排 + 自绘滚动条重绘 + 拉伸手柄重排，
        高频 Motion 下必然发涩。限流原因同 `_do_drag`（after 会被系统时钟量化）。
        """
        if not self._resize_edge or not self._rs:
            return
        self._rs_pt = (event.x_root, event.y_root)
        now = time.perf_counter()
        if now - self._rs_t < DRAG_FLUSH_S:
            return
        self._rs_t = now
        self._rs_flush()

    def _rs_flush(self) -> None:
        root = self._win
        if root is None or not self._resize_edge or not self._rs or not self._rs_pt:
            return
        self._rs_job = None
        edge = self._resize_edge
        sx, sy, wx, wy, ww, wh = self._rs
        ex, ey = self._rs_pt
        dx = ex - sx
        dy = ey - sy
        nx, ny, nw, nh = wx, wy, ww, wh
        # 🔴 收边（w / n）必须同时平移原点，否则窗口「只缩不挪」——左上锚点不动
        if "e" in edge:
            nw = ww + dx
        if "w" in edge:
            nw = ww - dx
            nx = wx + dx
        if "s" in edge:
            nh = wh + dy
        if "n" in edge:
            nh = wh - dy
            ny = wy + dy
        if nw < MIN_W:
            if "w" in edge:
                nx = wx + (ww - MIN_W)
            nw = MIN_W
        if nh < MIN_H:
            if "n" in edge:
                ny = wy + (wh - MIN_H)
            nh = MIN_H
        try:
            root.geometry("%dx%d+%d+%d" % (int(nw), int(nh), int(nx), int(ny)))
        except Exception:
            pass

    def _rs_stop(self, _event=None) -> None:
        if self._rs_job is not None:
            try:
                self._win.after_cancel(self._rs_job)
            except Exception:
                pass
            self._rs_job = None
        self._rs_flush()      # 补上最后一次尺寸，避免松手时“差一口气”
        self._resize_edge = None
        self._rs = None
        self._rs_pt = None
        self._save_bounds()     # 0915d：缩放结束 → 尺寸落盘

    # ======================== 格式工具栏 ========================

    def _selected_lines(self) -> tuple[int, int]:
        """返回受影响的起止行号（1 基，含两端）。有选区取选区跨的行，无选区取光标所在行。

        🔴 选区末尾正好落在**下一行行首**（col == 0）时不算选它 —— 否则鼠标从行首前面
           往下拖到下一行行首，会凭空多带一行。
        """
        ed = self._editor
        sel = ed.tag_ranges("sel")
        if sel:
            first, last = str(sel[0]), str(sel[1])
            l0 = int(first.split(".")[0])
            l1 = int(last.split(".")[0])
            if l1 > l0 and last.split(".")[1] == "0":
                l1 -= 1
        else:
            l0 = l1 = int(ed.index("insert").split(".")[0])
        return l0, l1

    def _toggle_list(self, kind: str) -> None:
        """列表开关：无序 `• ` / 有序 `1. 2. 3. …`，**作用于选中的每一行**。

        老板 0914y 报的问题：选中多行只给最后一行加点。
        旧实现只取 `ed.index("insert")` 那一行 → 多行选区完全失效。现在按行循环。

        规则（**0914z 起与主界面 `<ol>/<ul>` 行为对齐**）：
          · 选中的行**全部**已是本类型标记 → 摘掉（再点一次取消）。
            🔴 **只看标记类型，不校验序号对错**：主界面编号由浏览器自动生成、用户改不了手写号，
               「号乱」这种状态在主界面根本不存在 → 取消原「号乱就重排」行为，一律「再点即取消」。
          · 否则统一改成本类型标记（无序 ↔ 有序 直接互转：先把两种旧标记都摘掉再加）。
          · 有序列表**序号顺延**：**紧邻**的上一行是有序项 → 从它的号 +1 接着排；否则从 1 开始。
          · 回车续号见 `_on_return`。
        """
        ed = self._editor
        if ed is None:
            return
        had_sel = bool(ed.tag_ranges("sel"))
        l0, l1 = self._selected_lines()
        # 🔴 行号上限用 `end`（含末尾换行那行的 0 列），不是 `end-1c`：光标能停在正文末尾那行，
        #    在那里点列表按钮也应生效（用 end-1c 会把这一行判成不存在 → 静默什么都不做）。
        l_last = int(ed.index("end").split(".")[0])
        if l1 > l_last:
            l1 = l_last
        lines = list(range(l0, l1 + 1))
        if not lines:
            return

        raws = {ln: ed.get("%d.0" % ln, "%d.end" % ln) for ln in lines}

        # 有序列表：先把「本块应该用的序号」算出来
        # 🔴 **只有紧邻的上一行**是有序项才接着它的号顺延（中间隔了普通段落 = 新开一个列表 → 从 1 开始）
        #    —— 对齐主界面：浏览器里 `<ol>` 之间隔着 `<p>` 时，后面那个 `<ol>` 从 1 重新编号。
        start = 1
        if kind == "olist" and l0 > 1:
            pm = _NUM_RE.match(ed.get("%d.0" % (l0 - 1), "%d.end" % (l0 - 1)))
            if pm:
                start = int(pm.group(2)) + 1
        marks = [BULLET if kind == "list" else "%d. " % (start + i)
                 for i in range(len(lines))]

        # 是否「整块已经是本类型」→ 再点一次即取消
        # 🔴 0914z：只看**标记类型**（`_mark_kind`），不再要求序号正好对上 ——
        #    主界面编号由浏览器生成、用户手改不了；「号乱 → 重排」是只在悬浮便签存在的怪行为，
        #    老板要求「和主界面一致」→ 一律「整块已是本类型 → 再点即取消」。
        all_marked = all(_mark_kind(raws[ln]) == kind for ln in lines)

        # ① 先按**倒序**摘掉行首已有标记（无序 / 有序都摘）——倒序是为了不扰动未处理行的列号
        for ln in reversed(lines):
            m = _LIST_RE.match(raws[ln])
            if m:
                ind = len(m.group(1))            # 保留前导空白
                ed.delete("%d.%d" % (ln, ind), "%d.%d" % (ln, m.end(0)))
                raws[ln] = m.group(1) + raws[ln][m.end(0):]

        if not all_marked:
            # ② 逐行加标记（行内插入不改变行号，故可正序）
            #    插入点 = **前导空白之后**（缩进行不丢缩进，标记与上一版「• 」对齐）
            for i, ln in enumerate(lines):
                txt = raws.get(ln, "")
                ind = len(txt) - len(txt.lstrip())
                ed.insert("%d.%d" % (ln, ind), marks[i])

        # ④ 有选区就**重新框住整块**：插/删标记会顶偏原来的 sel 索引，
        #    不重设的话连点两次「取消」会错位（选区边界落在标记里）
        if had_sel:
            try:
                ed.tag_remove("sel", "1.0", "end")
                ed.tag_add("sel", "%d.0" % l0, "%d.end" % l1)
            except Exception:
                pass
        self._on_edit()

    # ==================== 内嵌图片：插入 / 粘贴 / 拖动 / 序列化 ====================
    # 🔴 规则与主界面 `便签应用.html` 的图片模块逐条对齐：
    #    · 底栏「图片」按钮 → 多选文件（单次 ≤ IMG_MAX_BATCH）→ 每张按 IMG_* 规则压缩
    #    · Ctrl+V：剪贴板是图片（位图截图 / 复制的图片文件）→ 走同一条插入路径
    #    · 图片**行内插入**（像字符一样落在光标处，左右都能打字；不再强制独占一行）
    #    · 显示宽度 = min(原宽, 正文可用宽)，**插入时定死**（主界面也是写死 px，不随窗口变）
    #    · 以 dataURL 内嵌进正文 HTML 落盘 → 不依赖外部文件，换机器 / 换路径都还在
    #    · 拖动 = 按住图片上下搬（对齐主界面 imgDropTarget：行级落点 + 插入指示线）

    def _img_max_width(self) -> int:
        """图片显示宽度上限（对齐主界面 imgMaxWidth()：正文可用宽，下限 120px）。"""
        ed = self._editor
        w = 0
        try:
            w = int(ed.winfo_width())
        except Exception:
            w = 0
        if w <= 1:                      # 窗口还没布局好 → 用默认窗口宽兜底
            w = WIN_WIDTH
        avail = w - BODY_PADX * 2 - 6   # 再留 6px 给自绘滚动条
        return avail if avail > 120 else 120

    def _register_image(self, data_url: str, want_w: int | None = None) -> str:
        """dataURL → PhotoImage 并登记，返回 Tk 图片名（im1 / im2 / …）。

        `want_w`：正文 HTML 里带来的显示宽度（`style="width:NNNpx"`）→ 还原用户调过的尺寸；
                 不给就按「不超过正文宽」自动定（小图保持原始像素）。

        🔴 PhotoImage 必须存进 `_img_store` 常驻 —— Tk 只持弱引用，Python GC 一回收图就变空白。
        """
        ed = self._editor
        if ed is None:
            raise ValueError("编辑器不可用")
        cap = self._img_max_width()
        photo, nat_w, nat_h = _data_url_to_photo(data_url, cap, ed, want_w)
        self._img_seq += 1
        name = "im%d" % self._img_seq
        shown = _clamp_img_w(want_w, cap) if want_w else min(int(nat_w or cap), cap)
        self._img_store[name] = {"photo": photo, "data_url": data_url,
                                 "nat_w": nat_w, "nat_h": nat_h,
                                 "shown_w": int(shown)}
        return name

    # ---------------- 图片选中 / 拉角调大小 ----------------

    def _make_img_sel_widgets(self, body: tk.Widget) -> None:
        """建选中框浮层：4 条 2px 蓝边 + **8 个**手柄（4 角 + 4 边）。

        浮层是 body 的**兄弟控件**（同时在上层），用 place 摆到图片 bbox 上 ——
        Tk 的 Text 内嵌图片没法直接加边框，只能在外面叠一层。

        🔴 0917e：每个手柄**三个事件都要绑**（按下 / 移动 / 松开）。
           旧版只绑了 `<Button-1>`，而 `<B1-Motion>` / `<ButtonRelease-1>` 只绑在 Text 上
           → 按住手柄后**只要指针还在那 10px 里**，事件全派发给手柄 Canvas（Text 收不到），
           拖动「完全没反应」；小幅调整时松手也仍在手柄上 → `_on_editor_release` 从不被调用
           → 尺寸**改了但没落盘**（下一次重铺就弹回原尺寸）。这就是老板报的「图片无法调整大小」。
        """
        parts: dict = {}
        for side in ("t", "b", "l", "r"):
            parts[side] = tk.Frame(body, bg=IMG_SEL_COLOR)
        for d in IMG_HANDLES:
            cv = tk.Canvas(body, width=IMG_HANDLE, height=IMG_HANDLE,
                           bg=self._note_bg, highlightthickness=0, bd=0)
            if d in IMG_CORNERS:                       # 角 = 圆点（对齐主界面 .ib-h）
                cv.create_oval(1, 1, IMG_HANDLE - 1, IMG_HANDLE - 1,
                               fill="#ffffff", outline=IMG_SEL_COLOR, width=2)
            else:                                      # 边 = 小方块（与角区分）
                cv.create_rectangle(2, 2, IMG_HANDLE - 2, IMG_HANDLE - 2,
                                    fill="#ffffff", outline=IMG_SEL_COLOR, width=2)
            try:
                if d in IMG_CORNERS:
                    cur = "size_nw_se" if d in ("nw", "se") else "size_ne_sw"
                elif d in ("n", "s"):
                    cur = "sb_v_double_arrow"
                else:
                    cur = "sb_h_double_arrow"
                cv.configure(cursor=cur)
            except Exception:
                pass
            cv.bind("<Button-1>", lambda e, dd=d: self._on_handle_press(dd, e))
            # 🔴 这条 `<B1-Motion>` 是本修复的关键：拖动手柄时指针多半**一直压在手柄上**
            #    （那 10px 里能走上好几帧），事件全派发给手柄 Canvas、Text 收不到 →
            #    不绑就等于「拉不动」。松手**不在这里绑** —— 由 `root` 上的
            #    `bind_all("<ButtonRelease-1>")` 统一兜底（见 `_finalize_img_resize`），
            #    指针停在手柄 / 顶栏 / 窗口外都能收到，不留第二条测不到的冗余路径。
            cv.bind("<B1-Motion>", self._on_editor_motion)
            parts[d] = cv
        self._sel_parts = parts

    def _select_image(self, name: str) -> None:
        """选中一张图片（显示边框 + 角手柄）。"""
        if not name:
            return
        self._sel_img = name
        self._refresh_img_sel()

    def _clear_image_sel(self) -> None:
        """取消图片选中态（点空白 / 按键 / 退出编辑 / 滚动出视野时调）。"""
        self._sel_img = None
        self._img_resize = None
        self._refresh_img_sel()

    def _refresh_img_sel(self) -> None:
        """把选中框 + 4 个角手柄摆到选中图片的位置；图不在视野内 / 非编辑态 → 全部收起。"""
        parts = self._sel_parts
        if not parts:
            return
        ed = self._editor
        name = self._sel_img
        b = None
        if ed is not None and name and self._editing:
            try:
                b = ed.bbox(name)
            except Exception:
                b = None
        if not b:
            if self._sel_shown:                 # 只在「本来显示着」时收一次（本方法被频繁调用）
                for wdg in parts.values():
                    try:
                        wdg.place_forget()
                    except Exception:
                        pass
                self._sel_shown = False
            return
        self._sel_shown = True
        bx, by, bw, bh = b
        h = IMG_HANDLE
        half = h // 2
        mid_x = bx + bw / 2.0 - half
        mid_y = by + bh / 2.0 - half
        layout = {
            "t": (bx, by, bw, 2),
            "b": (bx, by + bh - 2, bw, 2),
            "l": (bx, by + 2, 2, max(1, bh - 4)),
            "r": (bx + bw - 2, by + 2, 2, max(1, bh - 4)),
            "nw": (bx - half, by - half, h, h),
            "ne": (bx + bw - half, by - half, h, h),
            "sw": (bx - half, by + bh - half, h, h),
            "se": (bx + bw - half, by + bh - half, h, h),
            # 4 边手柄（0917e）：摆在各边中点
            "n": (mid_x, by - half, h, h),
            "s": (mid_x, by + bh - half, h, h),
            "w": (bx - half, mid_y, h, h),
            "e": (bx + bw - half, mid_y, h, h),
        }
        for k, (x, y, ww, hh) in layout.items():
            wdg = parts.get(k)
            if wdg is None:
                continue
            try:
                wdg.place(x=int(x), y=int(y), width=int(ww), height=int(hh))
                wdg.lift()
            except Exception:
                pass

    def _handle_at(self, x: int, y: int) -> str | None:
        """坐标是否压在某只角手柄上（手柄就是普通 widget，直接问它自己的位置）。

        判定范围外扩 `IMG_HANDLE_PAD` px —— 10px 的小圆点直接按像素判，手会很难抓。
        """
        if not self._sel_img:
            return None
        pad = IMG_HANDLE_PAD
        for d in IMG_HANDLES:
            wdg = self._sel_parts.get(d)
            if wdg is None:
                continue
            try:
                if not wdg.winfo_ismapped():
                    continue
                wx, wy = int(wdg.winfo_x()), int(wdg.winfo_y())
                ww, wh = int(wdg.winfo_width()), int(wdg.winfo_height())
            except Exception:
                continue
            if wx - pad <= x <= wx + ww + pad and wy - pad <= y <= wy + wh + pad:
                return d
        return None

    def _on_handle_press(self, d: str, event) -> str | None:
        """按住角手柄 → 进入等比缩放（规则对齐主界面：横向差值 / 40~正文宽 夹取）。"""
        ed = self._editor
        name = self._sel_img
        info = self._img_store.get(name) if name else None
        if ed is None or not info or not self._editing:
            return None
        start_w = int(info.get("shown_w") or 0)
        if start_w <= 0:
            try:
                b = ed.bbox(name)
                start_w = int(b[2]) if b else IMG_MIN_W
            except Exception:
                start_w = IMG_MIN_W
        self._img_resize = {"name": name, "dir": d,
                            "x0": int(getattr(event, "x_root", 0) or 0),
                            "y0": int(getattr(event, "y_root", 0) or 0),
                            "start_w": start_w}
        try:
            if d in IMG_CORNERS:
                cur = "size_nw_se" if d in ("nw", "se") else "size_ne_sw"
            elif d in ("n", "s"):
                cur = "sb_v_double_arrow"
            else:
                cur = "sb_h_double_arrow"
            ed.config(cursor=cur)
        except Exception:
            pass
        return "break"

    def _orig_pil(self, name: str):
        """取图片**原始** PIL 图（缩放时从原图重采样，而不是拿已缩过的图再缩）。

        🔴 只在缩放期间缓存（松手 `_release_orig_pil` 释放）：常驻的话一张 1400×1400
           解码后就 ~7.8MB，多张图会把内存吃光。
        """
        info = self._img_store.get(name)
        if info is None or not _HAS_PIL:
            return None
        im = info.get("orig")
        if im is not None:
            return im
        try:
            _, _, b64 = str(info.get("data_url") or "").partition(",")
            im = _PILImage.open(io.BytesIO(base64.b64decode(b64)))
            im.load()
        except Exception:
            return None
        info["orig"] = im
        return im

    def _release_orig_pil(self, name: str) -> None:
        info = self._img_store.get(name)
        if info:
            info.pop("orig", None)

    def _apply_img_width(self, name: str, w) -> int:
        """把图片显示宽度改成 `w`（等比 + 夹取），原地替换 Text 里那张图。返回实际宽度。

        🔴 用 `ed.image_configure(<图片名>, image=<新 PhotoImage>)` **原地换代**：
           删了重建会挪动 index、把光标和其它图片位置全搞乱。
        🔴 新 PhotoImage 必须写回 `_img_store[name]["photo"]` 常驻引用，否则下一帧就变空白。
        """
        ed = self._editor
        info = self._img_store.get(name)
        if ed is None or not info:
            return 0
        nat_w, nat_h = int(info.get("nat_w") or 0), int(info.get("nat_h") or 0)
        im = self._orig_pil(name)
        if not nat_w or not nat_h or im is None:
            return 0
        target = _clamp_img_w(w, self._img_max_width())
        h = max(1, int(round(target * nat_h / float(nat_w))))
        photo = None
        try:
            photo = _PILImageTk.PhotoImage(im.resize((target, h), _PILImage.LANCZOS),
                                           master=ed)
            ed.image_configure(name, image=photo)
        except Exception:
            return 0
        info["photo"] = photo
        info["shown_w"] = target
        if self._sel_img == name:
            self._refresh_img_sel()
        return target

    # ---------------- 图片「块级化」：独占一行（0917e）----------------
    # 🔴 Tk 的 Text 里没有 CSS，`display:block` 的等价物只有一条：**图片前后各有一个 \n**
    #    —— 图片自成一个**逻辑行**，文字只能排在它的上方或下方；窗口拉多宽 / 收多窄、
    #    正文怎么重排，都不可能出现「文字贴在图片左右」的环绕排版（主界面
    #    `#content-area img { display:block }` 的语义在这里就是这个）。
    #    旧版（0915）是**行内**插入（老板当时要「左右能打字」），0917e 反过来要独占一行。

    def _insert_image_block(self, name: str, pos: str) -> str:
        """在 `pos` 处插入图片并让它**独占一行**，返回图片所在 index。

        · 前面不在行首 → 补一个 `\\n`（把同行左侧的文字挤到上一行）；
        · 后面不是换行 / 不是文末 → 补一个 `\\n`（把右侧的文字挤到下一行）；
        · 光标落到图片**下一行的行首**（留在图片那行继续打字就又变行内了）。
        """
        ed = self._editor
        if ed is None:
            return pos
        info = self._img_store.get(name)
        if info is None:
            return pos
        try:
            if str(ed.index(pos)).split(".")[1] != "0":     # 不在行首 → 先断行
                ed.insert(pos, "\n")
                pos = ed.index("%s +1c" % pos)
            ed.image_create(pos, image=info["photo"], name=name,
                            padx=IMG_PAD, pady=IMG_PAD)
            after = "%s +1c" % pos
            nxt = ed.get(after, "%s +1c" % after)
            # 🔴 Tk 的 Text **永远**自带一个结尾换行：图片正好在文末时 `nxt` 读出来
            #    也是 "\n"，但那是系统自动补的、不是用户内容 —— 照它判断就会「不补换行」，
            #    于是后面再插进来的文字直接贴到图片右边（图文同行，0917e 实测踩到）。
            #    用 `end-1c` 把这种情况排除掉：只有「后面真有一个属于正文的换行」才不补。
            at_end = False
            try:
                at_end = bool(ed.compare(after, ">=", "end-1c"))
            except Exception:
                at_end = False
            if at_end or nxt != "\n":
                ed.insert(after, "\n")
        except Exception:
            return pos
        try:
            # 图片算 1 个字符 → pos+1c 是它后面的换行，pos+2c 才是**下一行行首**
            ed.mark_set("insert", "%s +2c" % pos)
        except Exception:
            pass
        return pos

    def _enforce_image_blocks(self) -> bool:
        """兜底：把正文里**所有**内嵌图片规范成独占一行。返回是否动过正文。

        插图 / 载入 / 搬动这三条路径各自都做了块级化，但用户在图片那一行里打字、
        或从主界面同步进来一份「图片与文字同行」的旧内容，都可能又变回行内 ——
        本方法在每次编辑（落盘前）统一收口，保证存出去、显示出来都是块级。
        """
        ed = self._editor
        if ed is None:
            return False
        try:
            if not ed.image_names():
                return False
            pairs = [(it[1], str(it[2]))
                     for it in ed.dump("1.0", "end", image=True) if it[0] == "image"]
        except Exception:
            return False
        changed = False
        for nm, idx in pairs:
            try:
                cur = str(ed.index(nm))
                ln = int(cur.split(".")[0])
                if ed.get("%d.0" % ln, cur) != "":           # 图片左边还有字 → 断到下一行
                    ed.insert(cur, "\n")
                    changed = True
                    cur = str(ed.index(nm))
                    ln = int(cur.split(".")[0])
                after = "%s +1c" % cur
                if ed.get(after, "%d.end" % ln) != "":       # 图片右边还有字 → 断到下一行
                    ed.insert(after, "\n")
                    changed = True
            except Exception:
                continue
        return changed

    def _delete_image(self, name: str) -> None:
        """删掉一张内嵌图片（连同它独占的那行换行）。对齐主界面 Delete / Backspace。"""
        ed = self._editor
        src = self._img_index(name)
        if ed is None or src is None:
            self._clear_image_sel()
            return
        try:
            # 🔴 同 `_move_image`：读「图片的下一格」判换行（对图片本体 get 只会返空串）。
            #    0917e 反测确认：图片已是块级 → 它后面必有换行，**必须连这个换行一起删**，
            #    否则原处留下一条空行（变异 `tail_nl = False` 会被 A11 抓住）。
            tail_nl = (ed.get("%s +1c" % src, "%s +2c" % src) == "\n")
            ed.delete(src, ("%s +2c" % src) if tail_nl else ("%s +1c" % src))
        except Exception:
            return
        self._img_store.pop(name, None)
        self._clear_image_sel()
        self._has_content = not self._editor_empty()
        self._on_edit()

    def _img_index(self, name: str) -> str | None:
        """图片当前所在 index（`ed.dump` 的元组顺序是 (kind, name, index)）。"""
        ed = self._editor
        if ed is None:
            return None
        try:
            for _kind, nm, i in ed.dump("1.0", "end", image=True):
                if nm == name:
                    return str(i)
        except Exception:
            return None
        return None

    def _img_at(self, idx: str) -> str | None:
        """`idx` 处是不是内嵌图片 → 返回图片名（否则 None）。

        🔴 必须用 `dump`：对图片位置 `ed.get()` 只会返回空串，`index()` 也照常给坐标，
           都分辨不出「这里站着一张图」。`dump` 的元组是 (kind, name, index)。
        """
        ed = self._editor
        if ed is None:
            return None
        try:
            for it in ed.dump(idx, "%s +1c" % idx, image=True):
                if it[0] == "image":
                    return str(it[1])
        except Exception:
            return None
        return None

    def _backspace_before_image(self) -> bool:
        """光标紧贴「块级图片」左边界时，Backspace 删的是**上一行末尾的字符**。

        🔴 0917f 根因：图片是块级（独占一行），它前面那个 `\\n` 由 `_insert_image_block()`
           补的，是**布局胶水** —— 不是用户敲出来的换行。但 Tk 不知道这件事：
           光标在图片左侧按 Backspace，Tk 删掉的正是这个胶水换行（文字与图片并成一行），
           紧接着 `<KeyRelease>` 触发 `_on_edit()` → `_enforce_image_blocks()` 发现
           「图片左边有文字」→ **又插回一个 `\\n`** → 删了又补，**单击净零**。
           长按之所以「有效」，是因为 `<KeyRelease>` 只在松手时来一次，
           重复的 `<KeyPress>` 连续删掉了多个字符（换行 + 若干文字），兜底最后只补一个换行。

           本方法按用户语义接管：删**上一行最后一个字符**（= 视觉上光标左边那个字），
           胶水换行原样保留 → 单击删一个、长按连续删，两者行为一致。

        返回 True 表示已处理（调用方应 `return "break"` 吃掉默认行为）。
        """
        ed = self._editor
        if ed is None:
            return False
        try:
            if ed.tag_ranges("sel"):
                return False                    # 有选区 → 交给默认逻辑（删选区）
            cur = str(ed.index("insert"))
            if self._img_at(cur) is None:
                return False                    # 光标右边不是图片 → 不干预
            ln = int(cur.split(".")[0])
            if cur != "%d.0" % ln:
                return False                    # 图片左侧还有文字（图文同行）→ 不干预
            # ⚠️ 「图片就在第 1 行」必须**显式不接管**。删掉本行 A9 **也**是绿的
            #    （那时 `p = 0.end-1c` 会落到 `1.0`，删的是空区间，净效果一样），
            #    但本函数会改而返回 True（把按键吃掉）→ `_on_keypress` 里那条
            #    **文首 `compare` 守护**（防 `insert-1c` = `0.0` 被 Tk 规范化成 `1.0`
            #    反而命中「就是第一个字符的那张图」）就永远走不到了。
            #    🔴 实测依据：0917f 反测里「删本行」（M11）全绿，而「删那条守护」（M8）
            #       只有在**保留本行**时才变红 —— 两条互为前提，故本行必须留。
            if ln <= 1:
                return False                    # 图片就在第 1 行 → 左边没有可删的字符
            # ⚠️ 「上一行是空行」则**不**特判：`ln-1.end-1c` 会**跨行**落到上一个换行上，
            #    删掉它 = 删掉那个空行 = 与 Tk 默认的「合并行」结果**逐字节相同**
            #    （0917f 反测 M5 证实）→ 特判是测不到的冗余，按铁律删掉。
            #    前提：Tk 的 `end-1c` 会跨行、越界 index 会规范化。失效条件：若某版本
            #    不这样，**A10**（上方是空行仍删空行）会红。
            p = str(ed.index("%d.end-1c" % (ln - 1)))   # 上一行最后一个字符；空行 → 上一个换行
            # ⚠️ 删完**不必**显式 `mark_set("insert", cur)`：实测 Tk 会把 `insert` mark
            #    自动吸附到删除区间的右端 —— 删掉 N 个字符，图片也左移 N 个字符，
            #    两者正好同位（= 新的图片左边界）。显式重设是**等价**的
            #    （0917f 反测 M3 证实）→ 按「不留测不到的代码」删掉；
            #    性质仍由 **A4**（单击后光标仍在图片左边界）守着。
            ed.delete(p, "%d.end" % (ln - 1))
        except Exception:
            return False
        return True

    def _caret_off_image_left(self) -> bool:
        """光标停在「块级图片」左边界时，把它挪到**上一行行尾**（那才是视觉上它左边那个位置）。

        🔴 0917g 根因（两个症状同一个因）：Tk 的文本光标必须**坐在一个字符上**，而这里那个
           「字符」就是图片本体 —— 块级图片独占一行，它的行首就是它自己。于是：
             · **光标样式异常**：插入符高度取「插入点那个字符的高度」→ 图片 90px 高
               → 插入符被拉成 **96px 长条**（真截图差分实测：正常 19px，比值 **5.1×**）；
             · **输入竖直排列**：字插在图片左边 → `<KeyRelease>` 的 `_enforce_image_blocks()`
               把图片挤到下一行（这正是它的职责），但 Tk 的 `insert` mark 有**右重力**，
               `\\n` 一插它又被顶回图片左边界 → 下一个字重复同样的过程 → **每字独占一行**。
               （实测：停用兜底 → `AAA\\nxyz<IMG>`（同一行）；启用兜底 → `AAA\\nx\\ny\\nz\\n<IMG>`。）

        修法 = 对齐主界面语义：那边图片是 `display:block`（`float:none; clear:both`），
           **光标根本不可能停在图片上** —— 图片左边界在视觉上就是上一行的行尾。
           这里照抄：把光标挪到上一行行尾（图片就在第 1 行时，先在上面开一行）。
           → 插入符恢复正常高度；打出来的字接在上一行末尾，**横向排版**。
           （与 0917f「贴图左侧 Backspace = 删上一行末字符」是同一个位置语义，两处一致。）

        ⚠️ 只用在**打字路径**：`_on_keypress` 的可打印键 + `_on_edit` 里兜底确实动过正文时。
           **绝不能**在鼠标点击后无条件调用 —— 图片的左边界 `L.0` / 右边界 `L.1` 正是
           0917f 里「Backspace 删上一行末字符」「贴图右侧 Backspace 删图」依赖的位置，
           把光标从那里挪走会让那两条分支**永远走不到**（失去可测性，0917f 反测会翻成 MISSED）。

        返回 True 表示挪过（调用方**不要** `return "break"`，要让默认逻辑在新位置落字）。
        """
        ed = self._editor
        if ed is None:
            return False
        try:
            # 有选区 → 交给默认逻辑（Tk 会先删选区再插字）。挪光标会把「插在哪」改掉，
            # 与 `_backspace_before_image()` 里同一条规则保持一致。
            if ed.tag_ranges("sel"):
                return False
            cur = str(ed.index("insert"))
            if self._img_at(cur) is None:
                return False                    # 光标右边不是图片 → 不干预
            ln = int(cur.split(".")[0])
            if cur != "%d.0" % ln:
                return False                    # 图片左侧还有文字（图文同行）→ 不干预
            if ln <= 1:
                # 图片就在第 1 行 → 左边没有可承接的行，先在上面开一行：
                # 用户接着打的字落在新开出来的第 1 行，图片顺延到第 2 行。
                ed.insert("1.0", "\n")
                ed.mark_set("insert", "1.0")
            else:
                # `L.end` = 该行末尾那个换行符的位置 → 在它前面落字 = 接在该行末尾
                ed.mark_set("insert", "%d.end" % (ln - 1))
        except Exception:
            return False
        return True

    def _insert_images(self) -> None:
        """底栏「图片」按钮：选文件 → 按规则插入。"""
        ed = self._editor
        if ed is None or not self._editing or self._img_busy or self._root is None:
            return
        if not _HAS_PIL:
            return
        self._img_busy = True
        # 🔴 文件对话框会抢走焦点 → 触发窗口 <FocusOut> → 「失焦即退出编辑模式」
        #    会把底栏卸掉（插完图回来已是浏览态）。用 _dialog_open 抑制这次误判。
        self._dialog_open = True
        try:
            paths = filedialog.askopenfilenames(
                parent=self._win,
                title="插入图片",
                filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff"),
                           ("所有文件", "*.*")],
            )
        except Exception:
            paths = ()
        finally:
            self._dialog_open = False
            self._img_busy = False
        try:
            ed.focus_set()
        except Exception:
            pass
        if paths:
            self._do_insert_images(list(paths))

    def _do_insert_images(self, paths) -> int:
        """按文件路径插入图片（按钮 / 粘贴共用），返回成功张数。"""
        ed = self._editor
        if ed is None:
            return 0
        files = [p for p in (paths or []) if isinstance(p, str) and p]
        if len(files) > IMG_MAX_BATCH:
            files = files[:IMG_MAX_BATCH]
        if not files:
            return 0
        names = []
        for p in files:
            try:
                info = _prepare_image_file(p)
                names.append(self._register_image(info["data_url"]))
            except Exception:
                continue                        # 单张失败不影响其它（与主界面一致）
        if not names:
            return 0
        try:
            self._place_images(names)
        except Exception:
            return 0
        self._on_edit()
        return len(names)

    def _insert_pil_image(self, im) -> int:
        """把内存中的 PIL 图（剪贴板位图）按同规则插入。"""
        try:
            info = _prepare_pil(im, None, "")
            name = self._register_image(info["data_url"])
        except Exception:
            return 0
        try:
            self._place_images([name])
        except Exception:
            return 0
        self._on_edit()
        return 1

    def _place_images(self, names) -> None:
        """把已登记的图片插到光标处（**块级**：每张图独占一行）。

        🔴 0917e 反转 0915 的决定：0915 为「图片左右能打字」把图片改成**行内**
           （`image_create` 本就像字符一样插在光标处，左右紧贴文字）。
           0917e 老板要求反过来 —— 图片必须独占一行，左右不允许有任何文字，
           且窗口拉伸 / 收窄后仍然独占一行。故这里恢复「前后补换行」的块级插入。
           序列化侧配套见 `_get_html`（`prev_img` 吞掉图片后那个换行）。
        """
        ed = self._editor
        if ed is None:
            return
        # 🔴 空便签的 Text 里挂着灰色占位符「记笔记...」：不先清掉的话
        #    ① 图片会插进占位符文字里；② `_showing_placeholder` 一直是 True，
        #    会让 `_get_html()` 永远返回空 / `_editor_empty()` 永远判空 → 存不下也留不住。
        self._clear_placeholder()
        try:
            ed.focus_set()
            if ed.tag_ranges("sel"):            # 有选区 → 先收起到选区末尾，别插进选区里
                ed.mark_set("insert", "sel.last")
                ed.tag_remove("sel", "1.0", "end")
        except Exception:
            pass
        # 🔴 0917e：图片**一律独占一行**（`_insert_image_block` 负责前后补换行）。
        for name in names:
            if not self._img_store.get(name):
                continue
            try:
                self._insert_image_block(name, ed.index("insert"))
            except Exception:
                continue
        try:
            ed.see("insert")
        except Exception:
            pass

    def _on_paste(self, event=None) -> str | None:
        """<<Paste>>：剪贴板是图片 → 插图并吃掉事件；否则返回 None 走默认纯文本粘贴。"""
        ed = self._editor
        if ed is None or not self._editing or _PILImageGrab is None:
            return None
        try:
            data = _PILImageGrab.grabclipboard()
        except Exception:
            return None
        if data is None:
            return None
        n = 0
        try:
            if isinstance(data, list):
                paths = [p for p in data if isinstance(p, str) and os.path.isfile(p)]
                n = self._do_insert_images(paths[:IMG_MAX_BATCH])
            elif isinstance(data, _PILImage.Image):
                n = self._insert_pil_image(data)
        except Exception:
            n = 0
        return "break" if n else None

    # ---------------- 图片右键菜单（0915）----------------
    # 复制 / 剪切 / 粘贴 / 粘贴为纯文本（+ 删除图片），与主界面 `#img-ctx` 一一对应。
    # 🔴 剪贴板读写全走 `clip_io`（与主界面**同一份实现**）→ 两侧复制出的图完全等价、可互粘。

    def _on_editor_right_click(self, event) -> str | None:
        """右键：命中内嵌图片 → 进编辑态 + 选中它 → 弹图片菜单。

        未命中图片时返回 None（Tk 的 Text 本身没有默认右键菜单，等于不响应）。
        """
        if self._root is None or self._editor is None:
            return None
        try:
            name = self._img_name_at(event.x, event.y)
        except Exception:
            name = None
        if not name:
            return None
        if not self._editing:
            self._enter_edit_mode()          # 浏览态右键图片 → 直接进编辑，菜单项才可用
        try:
            self._select_image(name)
        except Exception:
            pass
        self._popup_img_menu(name)
        return "break"

    def _menu_icon_ok(self) -> bool:
        """Tk 菜单项是否支持 `image=` + `compound="left"`（Tk ≥ 8.6.9）。

        不支持就别塞图标（老 Tk 会抛 `TclError: unknown option "-compound"`），
        退化成纯文字菜单 —— 功能不受影响，只是少一排小图标。
        """
        if self._ctx_icon_supported is None:
            ok = False
            root = self._win
            if root is not None:
                try:
                    probe = tk.Menu(root)
                    ph = tk.PhotoImage(master=root, width=2, height=2)
                    probe.add_command(label="x", image=ph, compound="left")
                    probe.destroy()
                    self._probe_photo = ph   # 常驻，免得探测完就被回收
                    ok = True
                except Exception:
                    ok = False
            self._ctx_icon_supported = ok
        return self._ctx_icon_supported

    def _ctx_icons(self) -> dict:
        """右键菜单 5 个图标（16×16）。

        PIL 上画 4 倍大图（64×64）再 LANCZOS 缩到 16：直接在小画布上画线是硬锯齿，
        缩下来才有抗锯齿的圆润观感（同「DWM 圆角」那次的教训）。
        🔴 图标必须存进 `_ctx_icon_store` 常驻 —— Tk 对 PhotoImage 只持弱引用，GC 一回收图标就空白。
        """
        if self._ctx_icon_store:
            return self._ctx_icon_store
        root = self._win
        store: dict = {}
        if root is None or not _HAS_PIL:
            return store
        try:
            from PIL import ImageDraw as _Draw
        except Exception:
            return store
        S = 4                                   # 超采样倍数
        W = 1.35 * S                            # 线宽（16 空间里 1.35px）
        lw = max(1, int(round(W)))
        specs = (("copy", "#4caf50"), ("cut", "#7c4dff"),
                 ("paste", "#00acc1"), ("plain", "#2979ff"), ("del", "#e5484d"))
        for kind, color in specs:
            try:
                im = _PILImage.new("RGBA", (16 * S, 16 * S), (0, 0, 0, 0))
                d = _Draw.Draw(im)

                def line(pts, c=color, _d=d):
                    _d.line([(p[0] * S, p[1] * S) for p in pts], fill=c, width=lw, joint="curve")

                if kind == "copy":
                    d.rounded_rectangle([5.4 * S, 1.7 * S, 13.5 * S, 11.6 * S],
                                        radius=1.4 * S, outline=color, width=lw)
                    line([(10.6, 13.9), (3.7, 13.9), (2.3, 12.5), (2.3, 4.9)])
                elif kind == "cut":
                    r = 1.9 * S
                    for cx in (4.3, 11.7):
                        d.ellipse([cx * S - r, 12.1 * S - r, cx * S + r, 12.1 * S + r],
                                  outline=color, width=lw)
                    line([(5.6, 10.6), (11.7, 2.1)])
                    line([(10.4, 10.6), (4.3, 2.1)])
                elif kind == "paste":
                    d.rounded_rectangle([3.3 * S, 2.7 * S, 12.7 * S, 14.2 * S],
                                        radius=1.6 * S, outline=color, width=lw)
                    d.rounded_rectangle([6.0 * S, 1.2 * S, 10.0 * S, 3.8 * S],
                                        radius=0.95 * S, outline=color, width=lw)
                elif kind == "plain":
                    line([(5.4, 3.5), (4.5, 3.5), (3.1, 4.9), (3.1, 13.1), (4.5, 14.5), (7.1, 14.5)])
                    line([(8.3, 3.5), (11.5, 3.5), (12.9, 4.9), (12.9, 8.9)])
                    d.rounded_rectangle([6.1 * S, 1.6 * S, 9.9 * S, 4.1 * S],
                                        radius=0.9 * S, outline=color, width=lw)
                    line([(9.4, 14.2), (12.0, 8.6), (14.6, 14.2)])
                    line([(10.4, 12.3), (13.6, 12.3)])
                else:                            # del（删除图片）
                    line([(2.6, 4.3), (13.4, 4.3)])
                    line([(6.2, 4.3), (6.2, 2.6), (9.8, 2.6), (9.8, 4.3)])
                    line([(4.3, 4.3), (5.0, 13.4), (11.0, 13.4), (11.7, 4.3)])
                store[kind] = _PILImageTk.PhotoImage(
                    im.resize((16, 16), _PILImage.LANCZOS), master=root)
            except Exception:
                continue
        self._ctx_icon_store = store
        return store

    def _popup_img_menu(self, name: str, popup: bool = True) -> None:
        """在鼠标处弹出图片菜单（样式对齐主界面：图标 + 快捷键 + 分隔线）。

        `popup=False` → 只构建不弹出（`tk_popup` 是**模态**的，会一直阻塞到用户关掉菜单；
        自动化验证需要能单独断言菜单内容，故留这个口子，不影响正常调用）。
        """
        root = self._win
        if root is None:
            return
        icons = self._ctx_icons() if self._menu_icon_ok() else {}
        menu = tk.Menu(root, tearoff=0, bg="#ffffff", fg="#333333",
                       activebackground="#e8f1ff", activeforeground="#000000",
                       font=("Microsoft YaHei", 10), bd=1, relief="solid")
        can_edit = bool(self._editing)

        def add(label, kind, acc, cmd, enabled):
            kw = {"label": label, "command": cmd,
                  "state": ("normal" if enabled else "disabled")}
            if acc:
                kw["accelerator"] = acc
            ic = icons.get(kind)
            if ic is not None:
                kw["image"] = ic
                kw["compound"] = "left"
            try:
                menu.add_command(**kw)
            except Exception:                   # 极端情况：主题不支持 compound → 退回纯文字
                kw.pop("compound", None)
                kw.pop("image", None)
                try:
                    menu.add_command(**kw)
                except Exception:
                    pass

        add("复制", "copy", "Ctrl + C", lambda: self._ctx_copy_image(name), True)
        add("剪切", "cut", "Ctrl + X", lambda: self._ctx_cut_image(name), can_edit)
        add("粘贴", "paste", "Ctrl + V", lambda: self._ctx_paste_at_image(name), can_edit)
        add("粘贴为纯文本", "plain", "Ctrl + Shift + V",
            lambda: self._ctx_paste_text_at_image(name), can_edit)
        menu.add_separator()
        add("删除图片", "del", "Delete", lambda: self._delete_image(name), can_edit)

        self._ctx_menu = menu                  # 常驻引用
        if not popup:
            return
        self._ctx_menu_open = True
        try:
            menu.tk_popup(root.winfo_pointerx(), root.winfo_pointery())
        except Exception:
            pass
        finally:
            self._ctx_menu_open = False
            try:
                menu.grab_release()
            except Exception:
                pass
            # 菜单关闭后把焦点还给编辑器：否则接下来的打字不生效（焦点还在菜单上）
            try:
                if self._editing and self._editor is not None:
                    self._editor.focus_set()
            except Exception:
                pass

    def _ctx_copy_image(self, name: str) -> bool:
        """把图片写进系统剪贴板（CF_DIB 位图）。成功返回 True。"""
        info = self._img_store.get(name)
        if not info or _clip is None:
            return False
        try:
            return bool(_clip.copy_data_url(info.get("data_url") or ""))
        except Exception:
            return False

    def _ctx_cut_image(self, name: str) -> None:
        """剪切 = **确认复制成功之后**再删图（复制失败就不删，免得白丢一张图）。"""
        if not self._ctx_copy_image(name):
            return
        self._delete_image(name)

    def _cursor_after_image(self, name: str) -> None:
        """把插入光标挪到图片**右侧**（右键哪张图，粘贴就落在它旁边）。"""
        ed = self._editor
        src = self._img_index(name)
        if ed is None or src is None:
            return
        try:
            ed.tag_remove("sel", "1.0", "end")
            ed.mark_set("insert", "%s +1c" % src)
        except Exception:
            pass

    def _ctx_paste_at_image(self, name: str) -> None:
        """粘贴到这张图右侧：剪贴板是图片就插图片，否则当纯文本插。"""
        ed = self._editor
        if ed is None or _clip is None or not self._editing:
            return
        self._cursor_after_image(name)
        try:
            data = _clip.read_image()
        except Exception:
            data = None
        n = 0
        try:
            if isinstance(data, list):
                paths = [p for p in data if isinstance(p, str) and os.path.isfile(p)]
                if paths:
                    n = self._do_insert_images(paths[:IMG_MAX_BATCH])
            elif _HAS_PIL and isinstance(data, _PILImage.Image):
                n = self._insert_pil_image(data)
        except Exception:
            n = 0
        if not n:
            self._ctx_paste_text_at_image(name)   # 没有图片 → 退化成粘文本

    def _ctx_paste_text_at_image(self, name: str) -> None:
        """粘贴为纯文本：只取剪贴板文本，插到图片右侧。"""
        ed = self._editor
        if ed is None or _clip is None or not self._editing:
            return
        try:
            txt = _clip.read_text()
        except Exception:
            txt = ""
        if not txt:
            return
        self._cursor_after_image(name)
        self._clear_placeholder()          # 空便签的灰色占位符必须先清（否则文字插进占位符里）
        try:
            ed.insert("insert", txt)
            ed.see("insert")
        except Exception:
            return
        self._on_edit()

    # ---------------- 拖动 ----------------

    def _img_name_at(self, x: int, y: int) -> str | None:
        """坐标处是否压在内嵌图片上 → 返回图片名。

        🔴 必须用 `ed.bbox(<图片名>)`：`bbox(<普通 index>)` 返回的是**整行**框（宽=行宽），
           拿它判命中会把整行文字都当成图片。
        """
        ed = self._editor
        if ed is None:
            return None
        for name in list(self._img_store.keys()):
            try:
                b = ed.bbox(name)
            except Exception:
                b = None
            if not b:
                continue
            bx, by, bw, bh = b
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return name
        return None

    def _on_editor_press(self, event) -> str | None:
        """左键按下：先判角手柄 / 图片（命中 → 吃事件），否则走「点正文进编辑」。

        🔴 **必须 `return "break"`**：Tk 的绑定顺序是「widget → class → toplevel」，
           我们这里只是 widget 级绑定；返回 None 的话 **Text 的类绑定照样会跑**
           （把光标塞到点击处并开始拖选）→ 按住图片上下拖时就会**把沿途文字全选中**
           （老板 0915 报的 bug）。返回 "break" 才真正截住类绑定。
        """
        if self._editing:
            h = self._handle_at(event.x, event.y)
            if h:
                return self._on_handle_press(h, event)
            name = self._img_name_at(event.x, event.y)
            if name:
                try:
                    self._editor.tag_remove("sel", "1.0", "end")   # 清掉已有选区（同主界面）
                except Exception:
                    pass
                self._select_image(name)
                self._img_drag = {"name": name, "x0": event.x_root,
                                  "y0": event.y_root, "moved": False}
                return "break"
            if self._sel_img:
                self._clear_image_sel()
        self._on_editor_click(event)
        # 🔴 点正文空白时我们返回 None → 由 Tk 类绑定把光标挪到点击处，光标位置要等
        #    类绑定跑完才知道 → 延后一拍再算工具栏选中态（0915）。
        try:
            if self._root is not None:
                self._win.after(1, self._refresh_fmt_state)
        except Exception:
            pass
        return None

    def _on_editor_motion(self, event) -> str | None:
        """拖动中：拉角缩放 / 图片上下移动（过死区才算「移动」）+ 插入指示线。"""
        r = self._img_resize
        if r:
            d = r["dir"]
            er = int(getattr(event, "x_root", 0) or 0)
            ey = int(getattr(event, "y_root", 0) or 0)
            if d in ("n", "s"):
                # 上/下边手柄：纵向差值 → 按原图宽高比折算成**宽度**增量
                # （Tk 内嵌图片只能整体换 PhotoImage，高度永远由宽度等比推出来）
                info = self._img_store.get(r["name"]) or {}
                nat_w = int(info.get("nat_w") or 0)
                nat_h = int(info.get("nat_h") or 0)
                k = (float(nat_w) / nat_h) if nat_h else 1.0
                dy = (r["y0"] - ey) if d == "n" else (ey - r["y0"])
                grow = int(round(dy * k))
            else:
                # 与主界面同款：含 e 的手柄往右变宽、含 w 的往左变宽（横向差值）
                grow = (er - r["x0"]) if "e" in d else (r["x0"] - er)
            self._apply_img_width(r["name"], r["start_w"] + grow)
            return "break"
        d = self._img_drag
        ed = self._editor
        if not d or ed is None:
            return None
        if not d["moved"]:
            if (abs(event.x_root - d["x0"]) < IMG_MIN_MOVE
                    and abs(event.y_root - d["y0"]) < IMG_MIN_MOVE):
                return "break"              # 死区内 → 仍算「点击」，也不许起选区
            d["moved"] = True
            try:
                ed.config(cursor="hand2")
            except Exception:
                pass
        self._show_ind_line(event.y)
        return "break"

    def _finalize_img_resize(self) -> bool:
        """结束一次拉手柄缩放：清状态 + 释放原图缓存 + **落盘**。

        🔴 0917e：这是**唯一**保证「尺寸一定能写回」的收口。松手时指针可能压在
           手柄 Canvas 上 / 顶栏上 / 窗口外，`<ButtonRelease-1>` 不一定回到 Text，
           所以除 Text 与手柄自身的绑定外，`root` 上还有一条 `bind_all` 兜底调它。
           本方法**幂等**（没有进行中的缩放直接返回 False），多处调用无副作用。
        """
        r = self._img_resize
        if not r:
            return False
        self._img_resize = None
        try:
            self._editor.config(cursor="")
        except Exception:
            pass
        try:
            self._release_orig_pil(r["name"])
        except Exception:
            pass
        try:
            self._on_edit()                 # 尺寸定稿才落盘（拖动过程中不写，对齐主界面）
        except Exception:
            pass
        if self._sel_img == r["name"]:
            self._refresh_img_sel()
        return True

    def _on_editor_release(self, event) -> str | None:
        if self._finalize_img_resize():
            return "break"
        d = self._img_drag
        self._img_drag = None
        self._hide_ind_line()
        if not d:
            return None
        try:
            self._editor.config(cursor="")
        except Exception:
            pass
        if d["moved"]:
            self._move_image(d["name"], event.y)
            if self._sel_img == d["name"]:
                self._refresh_img_sel()
        return "break"

    def _ind_target(self, y: int):
        """鼠标 y → (目标 index, 指示线像素 y)。

        对齐主界面 `imgDropTarget(clientX, clientY, block)` 的「行级落点」：
          · 先用 Tk 的 `@0,y` 把 y 归到某一行；
          · 再用**行盒中线**做上下半区分界：上半 → 落点 = 本行之前；下半 → 落点 = 下一行之前。
            上下半区共用同一个锚点（目标行行顶）→ 落点唯一，不会两行之间反复跳。
          · 已是最后一行且落在下半区 → 落点 = 文末（`end`），指示线画在该行下方。

        🔴 0915 修正（老板报「还没拖到行中间，落点就往上跳了一行」）：
           旧实现用 `bbox` 的**内容框中线**判分界，而 Tk 的 `bbox` 高度**不含**
           `spacing1`/`spacing3`（本便签各 3px）→ 内容中线比视觉行中线**高 3px**
           （图片行更高：内容 60px vs 行盒 69px，差 4.5px）。
           结果鼠标刚过行中部，指示线就跳到下一行 → 手感「提前」。
           改用**行盒中线**（本行行顶 → 下一行行顶的中点）后，切换点正好落在
           两行之间的视觉缝隙上，与主界面 `rect.height/2` 的判法一致。
        """
        ed = self._editor
        if ed is None:
            return None, None
        try:
            idx = ed.index("@0,%d" % max(0, int(y)))
            ln = int(str(idx).split(".")[0])
            cur = ed.bbox("%d.0" % ln)
            if not cur:
                # 🔴 该行 bbox 取不到（文档最末空行等 Tk 偶发返回 None 的情况）：
                #    退化成「落点 = 这一行行首、横线画在指针处」，保证能插进去，
                #    而不是返回 None 让这一行「拖不进」（老板 0915 报「有的行不能拖入」）。
                return "%d.0" % ln, max(0, int(y))
            nxt = ed.bbox("%d.0" % (ln + 1))
            box_h = (nxt[1] - cur[1]) if nxt else 0
            if box_h <= 0:
                box_h = cur[3]                       # 末行 / 邻行不可见 → 退化成内容高
            if y > cur[1] + box_h / 2.0:             # 行盒下半区 → 落点归下一行
                if nxt:
                    return "%d.0" % (ln + 1), nxt[1]
                return ed.index("end"), cur[1] + cur[3]
            return "%d.0" % ln, cur[1]
        except Exception:
            return None, None

    def _show_ind_line(self, y: int) -> None:
        ind = self._ind_line
        ed = self._editor
        if ind is None or ed is None:
            return
        # 落点没变就别重算 + 重 place（外部拖放悬停时每 80ms 会调一次本函数）
        if self._ind_last is not None and abs(int(y) - self._ind_last) < 2:
            return
        _idx, ly = self._ind_target(y)
        if ly is None:
            self._ind_last = None
            self._hide_ind_line()
            return
        try:
            x = BODY_PADX - IMG_PAD
            w = max(40, int(ed.winfo_width()) - 2 * x)
            ind.place(x=x, y=max(0, int(ly) - 1), width=w, height=2)
            ind.lift()
            self._ind_last = int(y)
        except Exception:
            pass

    def _hide_ind_line(self) -> None:
        self._ind_last = None
        if self._ind_line is None:
            return
        try:
            self._ind_line.place_forget()
        except Exception:
            pass

    def _move_image(self, name: str, y: int) -> None:
        """把图片搬到鼠标所在位置（始终独占一行；原地不留空行）。

        🔴 先算好「字符线性偏移」再删原图 —— 直接删会挪动后面的行号/列号，
           再按旧 index 插入就落偏了。
        """
        ed = self._editor
        info = self._img_store.get(name)
        src = self._img_index(name)
        if ed is None or not info or src is None:
            return
        idx, _ly = self._ind_target(y)
        if idx is None:
            return
        if str(idx).split(".")[0] == str(src).split(".")[0]:
            return                                  # 落在自己那一行 → 不用动
        try:
            # 🔴 0915j：落点必须用 **mark** 跟踪，不能先算字符偏移再删。
            #    旧实现先量 `tgt_off` → 再删图（连同它后面的换行）→ 行数整体变了，
            #    「第 N 行行首」这个语义在删完以后已经不是同一处 → 图插到错误位置，
            #    而且吞掉的那个换行会把上下两行**粘成一行**（实测：
            #    `AAA\nBBB[图]\nCCC` 拖到文末 → 变成 `AAA\nBBBCCC[图]`，图还没换行）。
            #    mark 会随 delete 自动跟着走 → 落点语义不会漂移。
            ed.mark_set("__imgdrop", idx)
            ed.mark_gravity("__imgdrop", "left")
            ln = str(src).split(".")[0]
            # 🔴 只在「图片独占这一行」时才连后面的换行一起删（否则原处留空行）。
            #    0917e：图片现在**一律**独占一行 → 该行 `ed.get` 只返回 ""（图片不是文本）
            #    → `solo` 恒真 → 连它后面那个换行一起删，原处不留空行。
            solo = (ed.get("%s.0" % ln, "%s.end" % ln) == "")
            tail_nl = bool(solo) and (ed.get("%s +1c" % src, "%s +2c" % src) == "\n")
            if tail_nl:
                ed.delete(src, "%s +2c" % src)
            else:
                ed.delete(src)
            ed.image_create("__imgdrop", image=info["photo"], name=name,
                            padx=IMG_PAD, pady=IMG_PAD)
            ed.mark_unset("__imgdrop")
            # 🔴 块级（0917e）：落点行原本可能就有文字 → 搬过去后重新规范成独占一行
            self._enforce_image_blocks()
            new_idx = self._img_index(name) or "__imgdrop"
            ed.mark_set("insert", str(new_idx))
            ed.see(str(new_idx))
            self._on_edit()
        except Exception:
            try:
                ed.mark_unset("__imgdrop")
            except Exception:
                pass

    # ---------------- 外部拖入（资源管理器 → 悬浮便签）----------------

    def _enable_file_drop(self) -> None:
        """让悬浮便签窗口接受「从外部拖进来的文件」（Win32 WM_DROPFILES）。

        注册两个 HWND：**窗口本体** + **编辑器 Text**。Text 占满正文区，是最主要的落点；
        注册窗口本体兜住顶栏 / 底栏 / 边缘（Windows 会从指针下的窗口往父级找接受拖放的窗口）。
        """
        if _user32 is None or self._root is None:
            return
        hwnds = []
        for wdg in (self._win, self._editor):
            if wdg is None:
                continue
            try:
                hwnds.append(int(wdg.winfo_id()))
            except Exception:
                pass
        if not hwnds:
            return
        # 🔴 回调对象必须**常驻引用**：ctypes 的 WINFUNCTYPE 一旦被 GC，窗口过程地址就失效
        #     → 下一次消息进来直接崩进程。
        proc = _WNDPROC(self._wndproc)
        self._wndproc_refs.append(proc)
        try:
            ptr = ctypes.cast(proc, ctypes.c_void_p)
        except Exception:
            return
        for h in hwnds:
            try:
                _shell32.DragAcceptFiles(wintypes.HWND(h), True)
                old = _SET_WNDPROC(wintypes.HWND(h), GWLP_WNDPROC, ptr)
            except Exception:
                continue
            if old:
                self._old_wndproc[h] = int(old)
                self._drop_hwnds.append(h)

    def _disable_file_drop(self) -> None:
        """还原窗口过程 + 取消接受拖放（**销毁窗口前必须调**，否则残回调会崩）。"""
        if _shell32 is None:
            return
        for h in list(self._drop_hwnds):
            try:
                _shell32.DragAcceptFiles(wintypes.HWND(h), False)
            except Exception:
                pass
            old = self._old_wndproc.get(h)
            if old and _SET_WNDPROC is not None:
                try:
                    _SET_WNDPROC(wintypes.HWND(h), GWLP_WNDPROC, ctypes.c_void_p(old))
                except Exception:
                    pass
        self._drop_hwnds = []
        self._old_wndproc = {}

    def _wndproc(self, hwnd, msg, wparam, lparam):
        """子类化后的窗口过程：只截 `WM_DROPFILES`，其余原样转给 Tk 原过程。

        🔴🔴 **绝不能在窗口过程里调 Tk / Tcl（本机实测直接崩进程）**
            窗口过程是系统在 **Tk 线程**里回调的，而此刻 Tk 的 `mainloop` 已经把 GIL 释放、
            当前线程态置空；ctypes 回调会临时建一个线程态把 GIL 拿回来 —— 此时若再
            `root.after(...)` 进 Tcl，`_tkinter` 的 ENTER_TCL/LEAVE_TCL 会再做一次线程态腾挪，
            两者打架 → `Fatal Python error: PyEval_RestoreThread: …（current Python thread
            state is NULL）`，进程当场死（不是异常，捕获不到）。
            实测三档（`_wndproc_exp_0914C.py`）：纯 Python 计数 ✅ / 再调一次 ctypes ✅ /
            `root.after` ❌。
            → 所以这里**只把「路径 + 落点」塞进 inbox**（纯 Python + ctypes），
              真正的插入交给 Tk 侧轮询 `_poll_drop()`（那是在正常 Tk 回调里，随便调 Tk）。
        """
        if msg == WM_DROPFILES:
            try:
                self._collect_dropped(wparam, hwnd)
            except Exception:
                pass
            return 0
        old = self._old_wndproc.get(int(hwnd))
        if old:
            try:
                return _user32.CallWindowProcW(ctypes.c_void_p(old),
                                               hwnd, msg, wparam, lparam)
            except Exception:
                pass
        return 0

    def _collect_dropped(self, hdrop, hwnd) -> None:
        """（**在窗口过程里跑**）取路径 + 落点 → 塞 inbox。只许纯 Python / ctypes，禁止碰 Tk。"""
        paths = []
        pt = None
        try:
            n = _shell32.DragQueryFileW(wintypes.HANDLE(hdrop), 0xFFFFFFFF, None, 0)
            buf = ctypes.create_unicode_buffer(32768)
            for i in range(int(n)):
                if _shell32.DragQueryFileW(wintypes.HANDLE(hdrop), i, buf, 32768):
                    paths.append(buf.value)
            # 落点：收到消息的那个窗口的**客户区坐标**（比「稍后读鼠标位置」准，鼠标可能已经挪走）
            p = wintypes.POINT()
            if _shell32.DragQueryPoint(wintypes.HANDLE(hdrop), ctypes.byref(p)):
                pt = (int(p.x), int(p.y))
        except Exception:
            paths = []
        finally:
            try:
                _shell32.DragFinish(wintypes.HANDLE(hdrop))
            except Exception:
                pass
        if paths:
            self._drop_inbox.append({"paths": paths, "pt": pt, "hwnd": int(hwnd)})

    def _poll_drop(self) -> None:
        """Tk 侧轮询：把窗口过程塞进 inbox 的落点真正插进去（此处可以放心调 Tk）。

        ⚠️ 为什么用轮询而不是 `after(0)`：见 `_wndproc` 的说明 —— 窗口过程里碰 Tcl 会崩。
           轮询间隔 150ms，用户感知不到；空转成本极低（每 150ms 一次列表判空）。
        """
        root = self._win
        try:
            if self._drop_inbox:
                item = self._drop_inbox.pop(0)
                self._handle_dropped(item.get("paths"), item.get("pt"), item.get("hwnd"))
        except Exception:
            pass
        if root is not None and not self._stopping:
            try:
                root.after(DROP_POLL_MS, self._poll_drop)
            except Exception:
                pass

    def _poll_drop_hover(self) -> None:
        """外部拖放**悬停**检测：拖动过程中就画插入指示线（对齐主界面 img-insert-line）。

        🔴 为什么必须轮询、以及怎么不误报（原理见模块顶部 `DROP_HOVER_POLL_MS` 注释）：
            · OLE 拖放期间鼠标归源进程独占，目标窗口收不到任何鼠标移动消息 → 只能查全局状态；
            · 用 `_press_inside` 区分「外部拖进来」与「在本便签里按住左键拖选文字」：
              后者的 ButtonPress 一定发生在我们窗口内（标志 True）→ 直接跳过，绝不画线。
        """
        root = self._win
        if root is None:
            return
        try:
            self._drop_hover_timer = root.after(DROP_HOVER_POLL_MS, self._poll_drop_hover)
        except Exception:
            self._drop_hover_timer = None
            return
        try:
            down = bool(_user32.GetAsyncKeyState(0x01) & 0x8000)      # VK_LBUTTON 是否按下
        except Exception:
            down = False
        if not down:
            # 左键已松开（哪怕 Release 事件没落到我们窗口里）→ 复位标志，别卡住后续检测
            self._press_inside = False
        # 0915c：`_dragging` = 正在拖**窗口本身**（不是拖文件进来）→ 别去正文里画落点线，
        # 免得拖动期间每 80ms 多算一次行级落点 + place（白白干扰拖动流畅度）。
        if (not down or self._press_inside or self._img_drag
                or self._img_resize or self._drop_busy or self._dragging):
            self._hide_ind_line()
            return
        ed = self._editor
        if ed is None or self._ind_line is None:
            return
        try:
            px, py = root.winfo_pointerxy()
            x = int(px) - int(ed.winfo_rootx())
            y = int(py) - int(ed.winfo_rooty())
            w, h = int(ed.winfo_width()), int(ed.winfo_height())
        except Exception:
            return
        if 0 <= x < w and 0 <= y < h:
            self._show_ind_line(y)           # 落在正文里 → 画线（行级落点）
        else:
            self._hide_ind_line()            # 顶栏 / 底栏 / 窗口外 → 不画

    def _drop_index_at(self, pt=None, hwnd=None) -> str | None:
        """拖放落点 → 目标行行首 index（与内部上下拖动共用 `_ind_target` 的行级落点）。

        `pt` 是「收到 WM_DROPFILES 的那个窗口」的客户区坐标；若那个窗口不是编辑器
        （比如落在顶栏/底栏上，消息被 root 收了），换算到编辑器坐标系。
        """
        ed = self._editor
        if ed is None or self._root is None:
            return None
        px = py = None
        if pt:
            px, py = int(pt[0]), int(pt[1])
            try:
                if hwnd and int(hwnd) != int(ed.winfo_id()):
                    px -= int(ed.winfo_rootx()) - int(self._win.winfo_rootx())
                    py -= int(ed.winfo_rooty()) - int(self._win.winfo_rooty())
            except Exception:
                pass
        if px is None:
            try:
                px = int(self._win.winfo_pointerx()) - int(ed.winfo_rootx())
                py = int(self._win.winfo_pointery()) - int(ed.winfo_rooty())
            except Exception:
                return None
        try:
            tgt, _ly = self._ind_target(max(0, py))
            if tgt:
                return tgt
            return ed.index("@%d,%d" % (max(0, px), max(0, py)))
        except Exception:
            return None

    def _handle_dropped(self, paths, pt=None, hwnd=None) -> None:
        """外部拖进来的文件 → 落进便签（复刻主界面：落点决定插入行）。

        🔴 老板 0915 明确要求：拖进来时若是**非编辑模式**，**先切编辑模式**再插入
           （浏览态 Text 是 disabled，直接插会插不进去）。
        """
        ed = self._editor
        if ed is None or self._root is None or self._drop_busy:
            return
        files = [p for p in (paths or [])
                 if isinstance(p, str) and p.lower().endswith(IMG_EXTS)]
        if not files:
            return
        self._drop_busy = True
        try:
            if not self._editing:
                self._enter_edit_mode()             # 浏览态 → 编辑态
            try:
                self._win.update_idletasks()       # 让编辑态布局先落地，落点才算得准
            except Exception:
                pass
            idx = self._drop_index_at(pt, hwnd)     # 进编辑态后算（底栏占位会改可见高度）
            if idx:
                try:
                    ed.mark_set("insert", idx)
                    ed.tag_remove("sel", "1.0", "end")
                except Exception:
                    pass
            try:
                ed.focus_set()
            except Exception:
                pass
            self._do_insert_images(files)
        finally:
            self._drop_busy = False

    # ---------------- 序列化：Text ⇄ HTML ----------------

    def _editor_has_image(self) -> bool:
        """Text 里是否有内嵌图片对象。"""
        ed = self._editor
        if ed is None:
            return False
        try:
            return bool(ed.dump("1.0", "end", image=True))
        except Exception:
            return False

    def _editor_empty(self) -> bool:
        """正文既无文字也无图片（占位符态同样算空）。

        🔴 必须先查图片：只要有图就绝不判空 —— 否则空便签插图后 `_showing_placeholder`
           仍为真，会被误判成「空」而用占位符把图片整批覆盖掉。
        """
        ed = self._editor
        if ed is None:
            return True
        if self._editor_has_image():
            return False
        if self._showing_placeholder:
            return True
        try:
            return not ed.get("1.0", "end-1c").strip()
        except Exception:
            return True

    def _get_html(self) -> str:
        """Text → 正文 HTML（行内格式 + 内嵌 dataURL 图片）。

        🔴 `ed.dump` 的事件流是 (`tagon`|`tagoff`, 标签名, index) / (`text`, 内容, index)
           / (`image`, 图片名, index) —— 按顺序开关标签即可还原行内格式。
        """
        ed = self._editor
        if ed is None:
            return ""
        if self._showing_placeholder and not self._editor_has_image():
            return ""
        try:
            items = ed.dump("1.0", "end-1c", text=True, tag=True, image=True)
        except Exception:
            return ""
        out = []
        prev_img = False                       # 上一项是不是图片（决定要不要吞掉紧随的换行）
        prev_block = False                     # 上一项是不是「块级 tag 的闭合」（同理）
        for it in items:
            k = it[0]
            if k == "image":
                info = self._img_store.get(it[1])
                if info:
                    # 🔴 0917e：图片在 Tk 里是**块级**（独占一行）→ 紧随其后的那个 `\n`
                    #    只是「这一行的结束」，不是用户要的空行 → 由下面 text 分支吞掉，
                    #    避免往返一趟就多一个空行（0914C 修过一次的同源坑）。
                    out.append('<img src="%s" style="width:%dpx">'
                               % (info["data_url"], int(info.get("shown_w") or 0)))
                    prev_img = True
                continue
            if k in ("tagon", "tagoff"):
                # 🔴 0915：改按 **tag 名反推 HTML**（`_html_for_tag`），于是颜色/底色/字号/
                #    等宽/引用/链接这些 tag 也能对称写回 —— 否则悬浮便签一保存，
                #    主界面加的颜色和字号就全丢了（比显示成代码更严重）。
                #    不是格式 tag 的（sel / placeholder 等）自动返回 None → 被忽略。
                pair = _html_for_tag(it[1])
                if pair:
                    closing = (k == "tagoff")
                    out.append(pair[1] if closing else pair[0])
                    # 🔴 块级标签（引用 = `<blockquote>`）的闭合**本身就表示一个换行** →
                    #    紧随其后的那个 `\n` 不能再出 `<br>`，否则解析回来时
                    #    「块闭合补的 \n」+「<br> 的 \n」= 多一个空行（0914C 图片双空行的同款坑，
                    #    这里推广到所有块级 tag）。
                    prev_block = closing and (it[1] in _BLOCK_HTML_TAGS)
                continue
            if k != "text":
                continue
            s = str(it[1])
            # 🔴 块级 tag 闭合（`</blockquote>` 等）：块闭合本身就表示一个换行，
            #    紧随其后的那个 `\n` 不能再出 `<br>`，否则解析回来时
            #    「块闭合补的 \n」+「<br> 的 \n」= 多一个空行（同源坑，0914C 修）。
            #    0917e：图片恢复块级（独占一行）→ 图片后那个 `\n` 同样只是「行结束」，
            #    也要吞掉（`prev_img`），否则每往返一趟就多一个空行。
            if (prev_block or prev_img) and s.startswith("\n"):
                s = s[1:]
            prev_img = False
            prev_block = False
            if not s:
                continue
            s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            out.append(s.replace("\n", "<br>"))
        html = "".join(out)
        return html if html.strip("<br>").strip() or "<img" in html else ""

    def _ensure_style_tag(self, tag: str) -> None:
        """按需配置「颜色 / 底色 / 字号 / 等宽 / 引用 / 链接」tag。

        Tk 的 tag 必须先 `configure` 才有样式；这些 tag 的名字本身就编码了样式值
        （`sf_ff0000` = 前景红、`sb_ffff00` = 黄底、`fs_16` = 16pt、`fsb_16` = 16pt 粗），
        所以同一个 tag 只需配一次 → 用 `_style_tags` 记账，避免每段文字都重配。
        """
        ed = self._editor
        if ed is None or not tag or tag in self._style_tags:
            return
        try:
            if re.match(r"^sf_[0-9a-f]{6}$", tag):
                ed.tag_configure(tag, foreground="#" + tag[3:])
            elif re.match(r"^sb_[0-9a-f]{6}$", tag):
                ed.tag_configure(tag, background="#" + tag[3:])
            elif re.match(r"^fs_\d{1,2}$", tag):
                ed.tag_configure(tag, font=(NOTE_FONT_FAMILY, int(tag[3:])))
            elif re.match(r"^fsb_\d{1,2}$", tag):
                ed.tag_configure(tag, font=(NOTE_FONT_FAMILY, int(tag[4:]), "bold"))
            elif tag == "code":
                ed.tag_configure(tag, font=("Consolas", 10), background="#f1f1f1")
            elif tag == "quote":
                ed.tag_configure(tag, lmargin1=16, lmargin2=16, foreground="#5f5f5f")
            elif tag == "link":
                ed.tag_configure(tag, foreground="#1f5ee8", underline=True)
            else:
                return               # bold / italic / underline / strike 在 `_run` 里已配好
            self._style_tags.add(tag)
        except Exception:
            pass

    def _tag_names_for(self, items) -> list:
        """样式项 → 实际 `tag_add` 的 tag 名（顺带处理 Tk 的 font 覆盖坑）。

        🔴 Tk 的 tag 之间 `font` 属性**不叠加**，而是由「优先级更高（后创建）」的那个
           整份覆盖 → 单独建一个 16pt 的字号 tag 会把加粗 tag 的粗体吃掉。
           所以「同时有 bold 与 fs_N」时合并成 `fsb_N`（字体 = Microsoft YaHei, N, bold）。
           只影响 Tk 侧渲染；写回 HTML 时 `fsb_N` → `font-size:Npt;font-weight:700`，语义等价
           （`_html_for_tag` 里有对应分支）。
        """
        names = []
        for it in items or ():
            nm = it[0] if isinstance(it, (tuple, list)) else str(it)
            names.append(nm)
        if "bold" in names:
            for i, nm in enumerate(names):
                if nm.startswith("fs_"):
                    names[i] = "fsb_" + nm[3:]
                    names.remove("bold")
                    break
        out = []
        for nm in names:
            self._ensure_style_tag(nm)
            if nm and nm not in out:
                out.append(nm)
        return out

    def _fill_from_html(self, html: str) -> None:
        """正文 HTML → Text（文字 + 行内格式 + 内嵌图片）；纯文本内容也走这里。"""
        ed = self._editor
        if ed is None:
            return
        self._clear_image_sel()               # 整篇重铺 → 旧的选中态失效
        # 🔴 整篇重铺 = 旧的内嵌图片全部作废（Text 内容马上被清空重写）。
        #    不清 `_img_store` 的话每铺一次就多留一批 PhotoImage（内存只涨不降），
        #    旧图片名还会一直被 `_img_name_at` 扫到（命中判定无谓变慢）。
        self._img_store.clear()
        s = str(html or "")
        if "<" not in s:                      # 旧数据 / 纯文本：直接铺进去
            self._set_display(s, placeholder=not s.strip())
            return
        segs = self._parse_html_segments(s)
        try:
            st = ed.cget("state")
        except Exception:
            st = "normal"
        try:
            ed.config(state="normal")
            ed.delete("1.0", "end")
            ed.mark_set("insert", "1.0")
            for seg in segs:
                if seg[0] == "img":
                    try:
                        want_w = seg[2] if len(seg) > 2 else None
                        nm = self._register_image(seg[1], want_w)   # 还原存过的显示宽度
                        # 🔴 块级插入：图片独占一行（0917e；与 `_place_images` 同源）
                        self._insert_image_block(nm, ed.index("insert"))
                    except Exception:
                        continue
                else:
                    txt, items = seg[1], seg[2]
                    if not txt:
                        continue
                    start = ed.index("insert")
                    ed.insert("insert", txt)
                    for tname in self._tag_names_for(items):
                        ed.tag_add(tname, start, "insert")
            self._showing_placeholder = False
            ed.mark_set("insert", "1.0")
            ed.config(state=st)
            self._refresh_fmt_state()          # 整篇重铺后光标回到 1.0 → 选中态重算
        except Exception:
            pass

    def _parse_html_segments(self, html: str):
        """HTML → [("text", 文本, 样式项元组) | ("img", dataURL, 宽度)]。

        样式项 = `(tk_tag, open_html, close_html)`（`_get_html` 按 tag 名反推，故双向对称）。

        🔴 0915 重写。旧版「只认白名单标签」，**认不出的标签会当普通文本原样塞进 Text**
           → 主界面 contenteditable 产出的 `<span style="color:…">` / `<font color=…>`
           / `<code>` 在悬浮便签里直接显示成 HTML 代码（老板报的「以代码形式体现」）。
           新版改成「**认样式 + 一律剥标签**」：
             · `<span style／font color／h1~h6／code／pre／blockquote／a／mark>`
               → 解析成颜色 / 底色 / 字号 / 粗斜下删 / 等宽 / 引用 / 链接样式；
             · 其余标签（`<section>`、`<table>`、`<figure>`…）→ **剥掉标签只留文字**。
        块级闭合时补换行；只有「整块全是图片」的块不补（`_fill_from_html` 里图片段自己补过
        `\\n`，再补就是双空行 —— 0914C 修的往返 bug）。
        """
        import html as _html_mod
        # 🔴 `<img>` 必须排在最前：它的 `src="data:…"` 可能几 MB，只有 `[^>]*` 能一次吃完。
        TOKEN = re.compile(r"<img\b[^>]*>|<[^>]*>|&[a-zA-Z#0-9]{1,8};", re.I)
        IMG_SRC = re.compile(r'src\s*=\s*["\']([^"\']+)["\']', re.I)
        # 显示宽度：`style="width:300px"` / `width="300"` 两种写法都认（主界面写的是前者）
        IMG_W = re.compile(r'width\s*[:=]\s*["\']?\s*(\d{1,5})', re.I)
        segs = []
        buf = []
        buf_items = ()                    # 当前 buf 对应的样式项（变了就切段）
        # 元素栈：每层 = {name, items, block, has_text, has_img}
        stack = []

        def flat():
            out = []
            for e in stack:
                out.extend(e["items"])
            return tuple(out)

        def flush():
            if buf:
                segs.append(("text", "".join(buf), buf_items))

        def mark(mode):
            for e in stack:
                e[mode] = True

        def turn(items=None):
            """样式切换点：把已缓冲的文字按**旧样式**落成一段。"""
            nonlocal buf, buf_items
            k = flat() if items is None else items
            if k != buf_items or not buf:
                flush()
                buf = []
                buf_items = k

        i, n = 0, len(html)
        while i < n:
            m = TOKEN.search(html, i)
            if m:
                chunk = html[i:m.start()]
                i = m.end()
            else:
                chunk = html[i:]
                i = n
            if chunk:
                turn()
                buf.append(_html_mod.unescape(chunk).replace("\n", " "))
                mark("has_text")
            if not m:
                break
            tok = m.group(0)
            low = tok.lower()
            if low.startswith("<!--"):
                continue                                   # 注释：剥掉
            if low.startswith("<img"):
                mark("has_img")                            # 图片占掉这一块（决定块闭合要不要换行）
                src = IMG_SRC.search(tok)
                url = src.group(1) if src else ""
                if _is_data_image_url(url):
                    wm = IMG_W.search(tok)
                    try:
                        wpx = int(wm.group(1)) if wm else None
                    except Exception:
                        wpx = None
                    flush()
                    buf = []
                    segs.append(("img", url, wpx))         # 第三项 = 保存时的显示宽度（无则 None）
                continue
            if low.startswith("&"):
                turn()
                buf.append(_html_mod.unescape(tok))
                mark("has_text")
                continue
            if low.startswith("<br"):
                turn()
                buf.append("\n")
                mark("has_text")
                continue
            mm = re.match(r"</?\s*([a-z0-9]+)", low)
            name = mm.group(1) if mm else ""
            if not name:
                continue                                   # 认不出的标签 → 直接剥掉
            # ---------------- 闭合标签 ----------------
            if tok.startswith("</"):
                pos = None
                for j in range(len(stack) - 1, -1, -1):
                    if stack[j]["name"] == name:
                        pos = j
                        break
                if pos is None:
                    continue                               # 没开过（或已被剥掉）→ 忽略
                popped = stack[pos:]
                del stack[pos:]
                need_nl = any(e["block"] and (e["has_text"] or not e["has_img"])
                              for e in popped)
                turn()
                # 🔴 块结束补换行，但**末尾已经是换行就不重复补** ——
                #    `_get_html` 会把段内的 `\n` 写成 `<br>`，块闭合时再补一个就成了双换行，
                #    一趟往返就凭空长行（和 0914C 修的图片块双空行同源）。
                if need_nl and (not buf or not buf[-1].endswith("\n")):
                    buf.append("\n")
                continue
            # ---------------- 开标签 ----------------
            items = list(_INLINE_TAGS.get(name, ()))
            if name in ("span", "font", "div", "p", "li", "td", "th", "section"):
                d = _parse_style(_style_of(tok))
                if name == "font":
                    c = _norm_color(_attr_color_of(tok))
                    if c:
                        d.setdefault("color", c)
                items.extend(_style_items(d))
            elif name == "pre":
                items.append(("code", "<code>", "</code>"))
            elif name in _HEAD_PT:
                pt = _HEAD_PT[name]
                items.append(("fsb_%d" % pt,
                              '<span style="font-size:%dpt;font-weight:700">' % pt, "</span>"))
            elif name == "blockquote":
                items.append(("quote", "<blockquote>", "</blockquote>"))
            is_block = name in _BLOCK_TAGS
            if not items and not is_block:
                continue                                   # 无样式的装饰标签 → 剥掉
            turn()
            stack.append({"name": name, "items": items, "block": is_block,
                          "has_text": False, "has_img": False})
        if buf:
            segs.append(("text", "".join(buf), buf_items))
        return segs

    def _apply_format(self, kind: str) -> None:
        """对当前选区 / 光标位置应用格式；列表（无序 / 有序）按行切换；图片 = 插入。"""
        ed = self._editor
        if ed is None:
            return
        try:
            if kind in ("list", "olist"):
                self._toggle_list(kind)
                return
            if kind == "image":
                self._insert_images()
                return
            sel = ed.tag_ranges("sel")
            if sel:
                if kind in ed.tag_names("sel.first"):
                    ed.tag_remove(kind, "sel.first", "sel.last")
                else:
                    ed.tag_add(kind, "sel.first", "sel.last")
            else:
                if kind in ed.tag_names("insert"):
                    ed.tag_remove(kind, "insert", "insert + 1c")
                else:
                    ed.tag_add(kind, "insert", "insert + 1c")
            self._on_edit()
        except Exception:
            pass

    # ======================== 交互：按钮动作 ========================

    def _new_note(self) -> None:
        """＋（**兜底路径专用**）：旧内容自动保存 → 在本窗里换一条**独立**空便签。

        🔴 0917b：这个方法**不再**给顶栏 `+` 按钮用。它造的是「主界面不认识、没有
           `src_id`」的独立便签（两个方向都同步不上），只该作为
           `FloatingWindowManager.new_local()` 的**兜底**（主界面没在跑 / 命令文件写不进去时
           「点了至少得有反应」）。顶栏 `+` 现在走 `_new_note_linked()`。
        """
        self._save_now()
        try:
            r = self.api.new_note()
            self._current_id = r.get("id")
            self._src_id = ""            # 手动新建 = 独立便签，不与主界面某条联动
            self._self_written = ""
            self._has_content = False
            # 0916：新便签没有 bgColor 字段 → 底色回到默认（不清的话会继承上一条的颜色）
            self._set_note_bg(NOTE_BG, persist=False)
            self._set_display("", placeholder=True)
        except Exception:
            pass
        self._sync_sbar()

    def _new_note_linked(self) -> None:
        """顶栏 `+`：**与托盘右键「新建桌面便签」完全同一条链路**地新建一条悬浮便签。

        0917b 老板报的 bug：`+` 原来调 `_new_note()` → 造出一条「主界面不认识、
        没有 `src_id`」的孤儿便签（铁律 4：没绑定 = 两个方向必然都不通）。
        现在统一交给 `DesktopApi.new_float_like_tray()`（内部就是 `open_desktop_note()`，
        托盘与全局快捷键用的同一个入口）：
            主界面「未分类」组首建空便签 + 落盘 + 写 `src_id` 绑定 → 双向同步生效。

        🔴 行为要点（与托盘一致）：
           ① **当前这个窗原地不动** —— 它的便签还在这条窗里，只是新开了另一条窗；
           ② 主界面没在跑时，沿用托盘那套看门狗兜底（退回一条独立便签，点了得有反应）；
           ③ 先 `_save_now()` 把当前内容落盘，绝不因为点 `+` 丢掉正在写的东西。
        """
        self._save_now()
        try:
            # 🔴 非静默：桥方法不存在（AttributeError）或返回 False 都要看出来，
            #    否则就是「点了没反应且毫无报错」（本项目已栽过一次同类隐身 bug，见铁律 16）。
            fn = getattr(self.api, "new_float_like_tray", None)
            if fn is None:
                print("[float] 桥缺 new_float_like_tray → 退回旧行为（独立便签）")
                self._new_note()
                return
            if not fn():
                print("[float] new_float_like_tray 返回 False → 退回旧行为（独立便签）")
                self._new_note()
        except Exception as e:
            print("[float] _new_note_linked error: %r" % (e,))

    def _hide(self) -> None:
        """× / Esc：仅隐藏弹窗，不退出应用。"""
        root = self._win
        if root is None:
            return
        # 0915h：可见标志供 `floating_ids()` 从**别的线程**读（不能跨线程调 winfo_viewable）
        self._visible = False
        self._close_pick_panel()         # 0916：窗口要藏了，⋯ 面板别留在桌面上
        self._close_font_panel()         # 0917：字号面板同理（关闭时会补写一次未落盘的字号）
        self._clear_image_sel()
        self._tip_cancel()               # 窗口要藏了，气泡别留在桌面上
        self._save_now()
        self._save_bounds()      # 0915d：位置尺寸落盘
        try:
            # 0915d：用户主动收起 → 不再算「正在悬浮」，重启后不要自己冒出来
            if self._current_id:
                self.api.set_flag(self._current_id, "isFloating", False)
        except Exception:
            pass
        try:
            root.withdraw()
        except Exception:
            pass

    # ======================== 0916：⋯ 面板（背景色 + 菜单） ========================

    # ---- 背景色的应用与落盘（per-note）----

    @staticmethod
    def _norm_bg(value) -> str:
        """把外部色值规整成 `NOTE_THEMES` 的 key（正文底色）；非法值退回默认黄。

        🔴 值域必须**封闭**（= `NOTE_THEMES` 的 7 个 key）：`_apply_note_bg_widgets()`
           靠「控件的 bg 落在哪个封闭集合里」判断该改成什么色。放开值域会让匹配失准
           （手改 JSON 塞个 `#123456` 进来，整窗就再也刷不动了）。
        0916b 还要认 0916 第一版的 7 个旧色块值（老板数据里可能已经存了）→ `NOTE_BG_LEGACY`。
        """
        s = str(value or "").strip().lower()
        s = NOTE_BG_LEGACY.get(s, s)
        return s if s in NOTE_BG_ALLOWED else NOTE_BG

    def _set_note_bg(self, color, persist: bool = True) -> None:
        """切换**本条**悬浮便签的整套配色（正文 + 顶栏 + 图标 + 分隔线 + 滚动条…），落盘。

        0916b 起一次换的是「一个色系」而不是「一个底色」—— 顶栏与正文是同色系两级
        （顶栏更深），文字 / 图标 / 分隔线的色值全部查 `NOTE_THEMES` 一张表。

        `persist=False` → 只改界面不写盘。切便签恢复 / 新建便签时必须用它：
        否则会把「刚从磁盘读回来的值」又原样写一遍 —— 白涨一次 mtime，主界面还要
        为这次无意义的改动多跑一轮轮询。
        """
        new = self._norm_bg(color)
        if new == self._note_bg and self._bg_ready:
            return                          # 没变 → 不折腾（切便签时绝大多数都是同色）
        th = NOTE_THEMES[new]
        self._note_bg = new
        self._note_bar = th["bar"]
        self._note_fg = th["fg"]
        self._note_icon_fg = th["icon"]
        self._note_hover = th["hover"]
        self._note_border = th["border"]
        self._note_ph = th["ph"]
        self._note_sb = th["sb"]
        self._note_trough = th["trough"]
        self._note_arrow = th["arrow"]
        self._note_sel = th["sel"]
        self._bg_ready = True
        self._apply_note_bg_widgets()
        if persist and self._current_id:
            try:
                self.api.set_flag(self._current_id, "bgColor", new)
            except Exception:
                pass

    def _apply_note_bg_widgets(self) -> None:
        """把本条配色的**三类底色**铺到所有控件上，并重绘自绘件。

        🔴 为什么用「递归遍历 + 三集合匹配」而不是维护一张控件登记表：
           取底色的控件散在 `_build` / `_make_resize_handles` / `_make_img_sel_widgets`
           三处十几行里，登记表一旦漏一处就是「换完色某块还是旧色」的脏 bug；而遍历
           只有当控件 bg **正好落在三个封闭集合之一**时才改：
             · `NOTE_BG_ALLOWED`     → 正文 / 底栏 / 滚动条画布 / 拉伸热区 / 图片角手柄
             · `NOTE_BAR_ALLOWED`    → 顶栏那一条（含顶栏按钮与保存状态小画布）
             · `NOTE_BORDER_ALLOWED` → 底栏上方那条 1px 分隔线
           三集合**两两互斥**（测试里有专门断言）→ 不会串色。而选中色 `FMT_ON_BG`、
           滚动条悬浮色 `SBAR_THUMB_HOVER` 等不在任何集合里 → 天然不会被误伤。
        """
        root = self._win
        if root is None:
            return
        body, bar, border = self._note_bg, self._note_bar, self._note_border
        stack = [root]
        while stack:
            w = stack.pop()
            try:
                cur = str(w.cget("bg")).lower()
            except Exception:
                cur = ""
            if cur != body and cur in NOTE_BG_ALLOWED:
                try:
                    w.configure(bg=body)
                except Exception:
                    pass
            elif cur != bar and cur in NOTE_BAR_ALLOWED:
                try:
                    w.configure(bg=bar)
                except Exception:
                    pass
            elif cur != border and cur in NOTE_BORDER_ALLOWED:
                try:
                    w.configure(bg=border)
                except Exception:
                    pass
            try:
                stack.extend(w.winfo_children())
            except Exception:
                pass
        # 顶栏 3 个按钮的**悬停色 / 字色**：`activebackground` / `activeforeground` 不是
        # `cget("bg")`，上面的遍历看不见它们 → 只能显式改（否则绿底便签上悬停闪金黄）。
        for btn in self._bar_buttons:
            try:
                btn.configure(bg=bar, fg=self._note_icon_fg,
                              activebackground=self._note_hover,
                              activeforeground=self._note_icon_fg)
            except Exception:
                pass
        self._sync_note_text_colors()
        for kind in FMT_KINDS:
            # 7 个工具图标：Canvas 不会自己跟随父色，底色 + 图标色都得重算
            self._paint_fmt(kind)
        # ⚠️ 这里**故意不调** `_redraw_sbar()`（结论与 0916b 初版相反 —— 反测 M6 已证）：
        #    0916b 让空闲滑块改用 `self._note_sb`（跟色系）之后，一度以为「必须显式重绘」，
        #    于是加了这一句。反向验证把它删掉 → 用例 N8（换紫后查滑块图元 fill）**照样绿**：
        #    遍历里 `w.configure(bg=…)` 改到正文 Text → Text 自身的 `yscrollcommand` 被触发
        #    → `_on_yscroll()` → `_redraw_sbar()`，用的已经是新 `self._note_sb`。
        #    即「被 Tk 回调路径顶掉的**等价变异**」，不是漏测 —— 反向验证的标准处置就是:
        #    等价变异从变异集合里剔除 + 在此处留记录。按本文件规矩删掉，不留「永远测不到」
        #    的死代码（0916 删 `_redraw_sbar` / `_refresh_handle_colors` 同理，那条结论没被推翻）。
        #    ⚠️ 前提：正文 Text 每次换色都得真被 configure 到。哪天真加了「颜色没变就跳过
        #    configure」的优化，这句就得加回来（N7b/N7c/N8 会先红，不会静默漏）。
        # ⚠️ 同理**故意不调** `_refresh_handle_colors()`：8 个拉伸热区的常态底色要么是
        #    body（在 `NOTE_BG_ALLOWED` 里）要么是顶边 / 上角的 bar（在 `NOTE_BAR_ALLOWED`
        #    里）→ 上面的遍历已按集合改对，属冗余调用。

    def _sync_note_text_colors(self) -> None:
        """正文的文字色 / 光标色 / 选中底色 / 占位符色：全部查本条便签的配色表。

        0916b 起这几项都是 `NOTE_THEMES` 里的显式项（`fg` / `sel` / `ph`），不再按
        底色亮度现算 —— 参考图给的是**每一档独立的颜色**（炭笔 = 白字 + 蓝选区），
        算法二选一只能近似，没法逐像素对齐老板给的图。
        """
        ed = self._editor
        if ed is None:
            return
        fg = self._note_fg
        on_dark = (fg == NOTE_FG_ON_DARK)
        try:
            ed.configure(
                fg=fg,
                insertbackground=fg,
                selectbackground=self._note_sel,
                selectforeground=("#ffffff" if on_dark else "#000000"),
            )
        except Exception:
            pass
        try:
            ed.tag_configure("placeholder", foreground=self._note_ph)
        except Exception:
            pass

    # ---- 面板本体 ----

    def _show_more_menu(self) -> None:
        """⋯：弹出「背景色 + 菜单」面板（0916 起自绘，替换原来的 `tk.Menu`）。

        样式对齐参考图（MS 便签）：顶上一排 7 个色块（当前色打 ✓），下面跟菜单项。
        **色块只改本条便签的底色**（per-note，落盘 `note.bgColor`），互不影响。

        🔴 为什么不用 `tk.Menu`：Tk 原生菜单**放不了色块**（只能文字 / 图标 / 勾选），
           参考图那种整排色块只能自绘；顺带也避开了 `tk_popup` 的模态阻塞，自动化
           测试能直接断言面板里的色块与菜单项。
        """
        root = self._win
        if root is None:
            return
        self._close_pick_panel()        # 再点一次 ⋯ = 重弹（不是叠一个）

        panel = tk.Toplevel(root)
        panel.withdraw()                # 先量尺寸再摆位置，免得在屏幕角落闪一下
        panel.overrideredirect(True)
        try:
            panel.attributes("-topmost", True)
        except Exception:
            pass
        self._pick_panel = panel
        self._pick_open = True

        # 外框 = 1px 蓝边（参考图那道 #0078d4）
        outer = tk.Frame(panel, bg=PICK_BORDER)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=PICK_ITEM_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # ---- ① 色块行（7 块紧贴、无间隙 —— 同参考图）----
        # 0916b：色块显示**顶栏色** `bar`（便签的身份色，比淡色正文好分辨）；
        #        点击时传的仍然是正文底色 key（落盘 `bgColor` 存的就是它）。
        row = tk.Frame(inner, bg=PICK_ITEM_BG)
        row.pack(side="top", fill="x")
        for key, _name in NOTE_BG_PRESETS:
            cv = tk.Canvas(row, width=PICK_SWATCH_W, height=PICK_SWATCH_H,
                           bg=NOTE_THEMES[key]["bar"],
                           highlightthickness=0, bd=0, cursor="hand2")
            cv.pack(side="left")
            if key == self._note_bg:
                # 当前色：参考图首个色块上那道黑勾
                cv.create_line(PICK_SWATCH_W * 0.30, PICK_SWATCH_H * 0.53,
                               PICK_SWATCH_W * 0.44, PICK_SWATCH_H * 0.68,
                               PICK_SWATCH_W * 0.73, PICK_SWATCH_H * 0.31,
                               fill=PICK_CHECK, width=2,
                               capstyle="round", joinstyle="round")
            cv.bind("<Button-1>", lambda e, c=key: self._pick_color(c))

        # ---- ② 菜单项（参考图里各项之间没有分隔线，靠悬停高亮区分 → 保持一致）----
        items = tk.Frame(inner, bg=PICK_ITEM_BG)
        items.pack(side="top", fill="x")
        self._pick_item(items, "pin",
                        "取消置顶" if self._always_on_top else "置顶",
                        self._toggle_always_on_top)
        # 0917 需求 6：字号设置（滑动调节；全局统一，见 `_show_font_panel`）
        self._pick_item(items, "font", "字号设置", self._show_font_panel)
        # 0915f 起就把「这个窗跟主界面到底绑没绑」写在菜单里。独立便签（托盘新建 /
        # src_id 为空）**设计上就不与主界面同步** —— 老板此前「同步没反应」多半是开的
        # 这种窗，一眼能看出来就不用猜。重构菜单时这条不能漏。
        self._pick_item(items, ("sync" if self._src_id else "nosync"),
                        "已与主界面同步（改动双向生效）" if self._src_id
                        else "独立便签 · 不与主界面同步", None)
        # 0917：绑定了主界面的便签，删除是**两边一起删**（老板要求「两处状态一致」）
        #       → 文案必须说清楚，让用户能预期到这个后果；独立便签照旧只删自己。
        self._pick_item(items, "del",
                        "删除便签（含主界面这条）" if self._src_id else "删除便签",
                        self._delete_note, danger=True)

        # ---- ③ 摆位置：从鼠标处弹出，并夹进可用视口 ----
        panel.update_idletasks()
        pw = panel.winfo_reqwidth()
        ph = panel.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x = min(max(root.winfo_pointerx(), PICK_GAP),
                max(PICK_GAP, sw - pw - PICK_GAP))
        y = min(max(root.winfo_pointery(), PICK_GAP),
                max(PICK_GAP, sh - ph - PICK_GAP))
        panel.geometry("%dx%d+%d+%d" % (pw, ph, x, y))
        panel.deiconify()

        # ---- 关闭：Esc / 点面板外（grab 会把外部点击也送到这个 toplevel）----
        panel.bind("<Escape>", lambda e: self._close_pick_panel())
        panel.bind("<Button-1>", self._pick_outside_click)
        try:
            panel.grab_set()
        except Exception:
            pass
        try:
            panel.focus_force()
        except Exception:
            pass

    def _pick_outside_click(self, event) -> None:
        """面板上的任意左键：落在面板**外面**才收（里面交给色块 / 菜单项自己处理）。

        `grab_set` 会把面板外的点击也路由到这个 toplevel，所以这里能用坐标判定
        「点在外面了」。色块 / 菜单项点击一定落在面板矩形内 → 不会被误收。
        """
        p = self._pick_panel
        if p is None:
            return
        try:
            x0, y0 = p.winfo_rootx(), p.winfo_rooty()
            x1 = x0 + p.winfo_width()
            y1 = y0 + p.winfo_height()
        except Exception:
            return
        if not (x0 <= event.x_root < x1 and y0 <= event.y_root < y1):
            self._close_pick_panel()

    def _pick_color(self, color: str) -> None:
        """点了一个色块：改本条便签底色 → 落盘 → 收面板。"""
        self._close_pick_panel()
        self._set_note_bg(color)

    def _close_pick_panel(self) -> None:
        """收起 ⋯ 面板（幂等；没开时什么都不做）。"""
        was = self._pick_open
        self._pick_open = False
        p = self._pick_panel
        self._pick_panel = None
        if p is not None:
            try:
                p.grab_release()
            except Exception:
                pass
            try:
                p.destroy()
            except Exception:
                pass
        if was:
            # 面板关掉后把焦点还给编辑器：否则接下来的打字不生效（同图片菜单的处理）
            try:
                if self._editing and self._editor is not None:
                    self._editor.focus_set()
            except Exception:
                pass

    def _pick_item(self, parent: tk.Widget, kind: str, label: str,
                   cmd, danger: bool = False) -> None:
        """面板里的一个菜单项：图标 + 文字，悬停高亮；`cmd=None` = 只读项（灰字）。

        图标用 Canvas 细线画（与底栏 7 个工具同一套画法），**不用 PIL** —— PIL 在本
        项目是可选依赖，缺了会整排菜单项没图标，不划算。
        """
        enabled = cmd is not None
        fg = PICK_TEXT_DANGER if danger else (PICK_TEXT if enabled else "#9a9a9a")
        fr = tk.Frame(parent, bg=PICK_ITEM_BG, height=PICK_ITEM_H,
                      cursor=("hand2" if enabled else "arrow"))
        fr.pack(side="top", fill="x")
        fr.pack_propagate(False)        # 🔴 锁行高：否则子控件会把 38px 撑成内容高
        ic = tk.Canvas(fr, width=16, height=16, bg=PICK_ITEM_BG,
                       highlightthickness=0, bd=0)
        ic.pack(side="left", padx=(12, 0))
        self._draw_pick_icon(ic, kind, fg)
        lb = tk.Label(fr, text=label, bg=PICK_ITEM_BG, fg=fg,
                      font=("Microsoft YaHei", 10), anchor="w")
        lb.pack(side="left", padx=(9, 12), fill="x", expand=True)

        def _hover(on: bool) -> None:
            if not enabled:
                return
            c = PICK_ITEM_HOVER if on else PICK_ITEM_BG
            for w in (fr, ic, lb):      # Canvas 只改 bg：图标是线条，不用重画
                try:
                    w.configure(bg=c)
                except Exception:
                    pass

        def _click(_e):
            self._close_pick_panel()    # 选完就收（同 MS 便签）
            if enabled:
                try:
                    cmd()
                except Exception:
                    pass
            return "break"             # 别冒泡给 panel 的「点外面」判定

        for w in (fr, ic, lb):
            w.bind("<Enter>", lambda e: _hover(True))
            w.bind("<Leave>", lambda e: _hover(False))
            if enabled:
                w.bind("<Button-1>", _click)

    def _draw_pick_icon(self, cv: tk.Canvas, kind: str, fg: str) -> None:
        """面板菜单项的小图标（16×16 细线，风格同底栏工具图标）。"""
        try:
            cv.delete("all")
            if kind == "pin":                   # 置顶：上箭头 + 底线（「移到最上」）
                cv.create_line(3.5, 13.5, 12.5, 13.5, fill=fg, width=1.5)
                cv.create_line(8, 11, 8, 3.5, fill=fg, width=1.5)
                cv.create_line(4.5, 7, 8, 3.5, 11.5, 7, fill=fg, width=1.5,
                               joinstyle="round", capstyle="round")
            elif kind == "sync":                # 已绑定主界面：对号
                cv.create_line(3, 8.5, 6.5, 12, 13, 4, fill=fg, width=1.7,
                               capstyle="round", joinstyle="round")
            elif kind == "font":                # 0917 字号：大写 A + 小写 a
                cv.create_text(5.0, 8.0, text="A", fill=fg,
                               font=("Segoe UI", 9, "bold"), anchor="center")
                cv.create_text(12.0, 11.5, text="a", fill=fg,
                               font=("Segoe UI", 7), anchor="center")
            elif kind == "nosync":              # 未绑定：叉号
                cv.create_line(4, 4, 12, 12, fill=fg, width=1.5, capstyle="round")
                cv.create_line(12, 4, 4, 12, fill=fg, width=1.5, capstyle="round")
            else:                               # del：垃圾桶（与图片菜单同款画法）
                cv.create_line(2.6, 4.3, 13.4, 4.3, fill=fg, width=1.5)
                cv.create_line(6.2, 4.3, 6.2, 2.6, 9.8, 2.6, 9.8, 4.3,
                               fill=fg, width=1.5)
                cv.create_line(4.3, 4.3, 5.0, 13.4, 11.0, 13.4, 11.7, 4.3,
                               fill=fg, width=1.5)
        except Exception:
            pass

    def _delete_note(self) -> None:
        """「删除便签」：删掉两边数据，并**把本窗口也关掉**（0917 老板要求）。

        老板原话：「悬浮便签中执行『删除便签』时，需同时关闭该悬浮便签，并删除主界面
        中对应的便签，保证两处状态一致。」

        🔴 与旧版的关键差别：旧版是「删当前便签 → 再 `_new_note()` 建一条空的」
           （单窗口时代的做法：桌面只有一个悬浮窗，删完得还用户一个空的）。
           多窗口 + 双向绑定之后那样做就错了 —— 主界面那条便签已经没了，悬浮窗却还
           顶着一个新建的空便签，两边状态对不上。现在改成**关窗**，语义才与「删除」一致。

        顺序（每一步都不能换）：
          ① 先把 `_current_id` / `_src_id` 断掉 → 之后任何补保存都写不出这条数据；
          ② 通知后端删两边数据（桌面记录 + 命令通道通知主界面删对应便签）；
          ③ 让 manager 把本会话收掉（摘注册表 + 投递销毁，不阻塞 Tk 线程）。
        """
        did, src = self._current_id, self._src_id
        # ① 立刻断链：``_cleanup``（会话销毁）在销毁前还会补一次 `_save_now()` /
        #    `_save_bounds()`，不先断掉就会把刚删掉的这条又写回桌面便签 JSON。
        self._current_id = None
        self._src_id = ""
        self._self_written = ""
        self._tip_cancel()               # 提示气泡别留在桌面上
        self._close_pick_panel()         # ⋯ 面板要收（否则鼠标 grab 残留）
        self._close_font_panel()         # 字号面板同理（顺带补写未落盘的字号）
        # ② 删数据（`delete_both` 内部还会写命令文件，让主界面删掉它那条）
        try:
            self.api.delete_both(did, src)
        except Exception:
            pass
        # ③ 关掉本窗口（manager 会把它从 `_sessions` 摘掉，再投递销毁）
        try:
            self.api.close_self(self)
        except Exception:
            pass

    # ======================== 0917：字号设置（全局统一） ========================
    # 老板原话：「在悬浮便签的菜单栏中新增『字号设置』，用于调整悬浮便签的整体字号，
    #           仅作用于悬浮便签（主界面便签字号保持不变），支持滑动调节。」
    #          「字号设置需对全部悬浮便签统一生效，包括此后新建的悬浮便签。」
    #
    # 设计要点：
    #   · 字号是**全局设置**（`桌面便签数据.json` → `settings.font_pt`），不是 per-note：
    #     存 per-note 的话「新建的自动沿用」就无从谈起（新便签压根没那个字段）。
    #   · 改字号 = 改三个基准 `font`（正文 / bold / italic tag）。主界面写过来的
    #     动态字号 tag（`fs_N` / `fsb_N`）**不动** —— 与 0915n 的约定一致
    #     （见文件顶部那段注释：N 是主界面里的绝对值，跟着缩会让「一行里默认字与
    #      放大字」的相对关系乱掉）。
    #   · 「仅作用于悬浮便签」是天然成立的：主界面是 WebView 里的另一套渲染，
    #     两边各写各的 JSON，谁的字号都影响不到对方。

    def set_font_pt(self, pt) -> None:
        """广播入口（`FloatingWindowManager.broadcast_font` 调）：只改本会话，不落盘。"""
        self._set_font_local(pt)

    def _set_font_local(self, pt) -> None:
        """改**本会话**编辑器的基准字号（正文 / 加粗 / 斜体三个 tag）。"""
        try:
            pt = int(pt)
        except Exception:
            return
        pt = max(NOTE_FONT_MIN, min(NOTE_FONT_MAX, pt))
        if pt == self._font_pt:
            return
        self._font_pt = pt
        ed = self._editor
        if ed is None:
            return
        fam = NOTE_FONT_FAMILY
        try:
            ed.configure(font=(fam, pt))
            # 🔴 加粗 / 斜体是独立 tag，而 `tag_configure` 的 font 是**整份胜出**（不叠加），
            #    所以基准字号变了必须跟着重设 —— 否则粗体字会停在旧字号上。
            ed.tag_configure("bold", font=(fam, pt, "bold"))
            ed.tag_configure("italic", font=(fam, pt, "italic"))
        except Exception:
            pass
        try:
            self._sync_sbar()        # 行高变了 → 滚动条滑块长度要跟着重算
        except Exception:
            pass

    def _apply_font(self, pt) -> None:
        """改本会话 + 广播给其他会话（界面立即生效；落盘由 `_schedule_font_save` 防抖）。"""
        self._set_font_local(pt)
        broadcast = getattr(self.api, "broadcast_font", None)
        if broadcast is None:
            # 🔴 别静默：缺这个方法就等于「字号只改了当前这一条」，而界面看起来
            #    一切正常 —— 典型隐身 bug（本项目在桥方法上已经栽过一次同类）。
            print("[font] api 上缺少 broadcast_font → 字号只对当前便签生效")
            return
        try:
            broadcast(self._font_pt)
        except Exception:
            pass

    def _schedule_font_save(self, pt) -> None:
        """落盘防抖：拖滑块时 `Scale.command` 每动一格回调一次，别每格写一次盘。"""
        root = self._win
        if root is None:
            return
        if self._font_save_timer is not None:
            try:
                root.after_cancel(self._font_save_timer)
            except Exception:
                pass
        try:
            self._font_save_timer = root.after(
                FONT_SAVE_DEBOUNCE_MS, lambda p=pt: self._persist_font(p))
        except Exception:
            self._font_save_timer = None

    def _persist_font(self, pt) -> None:
        """把字号写进全局设置（所有悬浮便签共用；新建的会话启动时读它）。"""
        self._font_save_timer = None
        try:
            self.api.set_global(NOTE_FONT_KEY, int(pt))
        except Exception:
            pass

    def _apply_font_from_global(self) -> None:
        """`_build` 时调：把全局字号套用到本会话（**新建的悬浮便签也沿用**）。"""
        try:
            pt = self.api.get_global(NOTE_FONT_KEY, NOTE_FONT_DEFAULT)
        except Exception:
            pt = NOTE_FONT_DEFAULT
        try:
            self._set_font_local(int(pt))
        except Exception:
            pass

    def _show_font_panel(self) -> None:
        """「字号设置」面板：一条滑块，拖动即实时改**所有**悬浮便签的字号。"""
        root = self._win
        if root is None:
            return
        self._close_font_panel()

        panel = tk.Toplevel(root)
        panel.withdraw()                 # 先量尺寸再摆位置，免得在屏幕角落闪一下
        panel.overrideredirect(True)
        try:
            panel.attributes("-topmost", True)
        except Exception:
            pass
        self._font_panel = panel
        self._font_open = True

        # 外框沿用 ⋯ 面板那套（1px 蓝边 + 白底）
        outer = tk.Frame(panel, bg=PICK_BORDER)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=PICK_ITEM_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(inner, bg=PICK_ITEM_BG)
        head.pack(side="top", fill="x", padx=12, pady=(10, 2))
        tk.Label(head, text="悬浮便签字号", bg=PICK_ITEM_BG, fg=PICK_TEXT,
                 font=("Microsoft YaHei", 10)).pack(side="left")
        val = tk.Label(head, text="%d pt" % self._font_pt, bg=PICK_ITEM_BG,
                       fg=PICK_TEXT, font=("Microsoft YaHei", 10, "bold"))
        val.pack(side="right")

        def on_change(v) -> None:
            try:
                pt = int(float(v))
            except Exception:
                return
            if pt == self._font_pt:
                return
            self._apply_font(pt)                   # 立即生效（本会话 + 其他悬浮便签）
            val.configure(text="%d pt" % pt)
            self._schedule_font_save(pt)           # 落盘防抖

        scale = tk.Scale(
            inner, from_=NOTE_FONT_MIN, to=NOTE_FONT_MAX, orient="horizontal",
            showvalue=0, resolution=1, length=210,
            bg=PICK_ITEM_BG, fg=PICK_TEXT, troughcolor="#c9d2dd",
            activebackground="#dbe7ff", highlightthickness=0, bd=0,
            # 🔴 滑块（knob）的颜色就是 `bg`：原来 `bg=白 + sliderrelief="flat"` →
            #    白色平扣在浅灰槽上**等于看不见**（截图复查才发现），「滑动调节」的可辨识度就没了。
            #    改成 `raised`（有立体边）+ 把槽调深一档，白 knob 才立得住。
            sliderrelief="raised", sliderlength=16, width=12, cursor="hand2",
            command=on_change,
        )
        scale.set(self._font_pt)
        scale.pack(side="top", fill="x", padx=12, pady=(0, 4))
        self._font_scale = scale

        tk.Label(inner, text="对所有悬浮便签生效（含新建）", bg=PICK_ITEM_BG,
                 fg="#8a8a8a", font=("Microsoft YaHei", 8), anchor="w").pack(
            side="top", fill="x", padx=12, pady=(0, 10))

        # ---- 摆位置：从鼠标处弹出，并夹进可用视口（同 ⋯ 面板）----
        panel.update_idletasks()
        pw, ph = panel.winfo_reqwidth(), panel.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x = min(max(root.winfo_pointerx(), PICK_GAP), max(PICK_GAP, sw - pw - PICK_GAP))
        y = min(max(root.winfo_pointery(), PICK_GAP), max(PICK_GAP, sh - ph - PICK_GAP))
        panel.geometry("%dx%d+%d+%d" % (pw, ph, x, y))
        panel.deiconify()

        # ---- 关闭：Esc / 点面板外 ----
        panel.bind("<Escape>", lambda e: self._close_font_panel())
        panel.bind("<Button-1>", self._font_outside_click)
        try:
            panel.grab_set()
        except Exception:
            pass
        try:
            panel.focus_force()
        except Exception:
            pass

    def _font_outside_click(self, event) -> None:
        """面板上的左键：落在面板**外面**才收（滑块在面板内，不会被误收）。"""
        p = self._font_panel
        if p is None:
            return
        try:
            x0, y0 = p.winfo_rootx(), p.winfo_rooty()
            x1, y1 = x0 + p.winfo_width(), y0 + p.winfo_height()
        except Exception:
            return
        if not (x0 <= event.x_root < x1 and y0 <= event.y_root < y1):
            self._close_font_panel()

    def _close_font_panel(self) -> None:
        """收起字号面板（幂等）；收之前把还没落盘的字号补写一次。"""
        was = self._font_open
        self._font_open = False
        p = self._font_panel
        self._font_panel = None
        self._font_scale = None
        if p is not None:
            try:
                p.grab_release()
            except Exception:
                pass
            try:
                p.destroy()
            except Exception:
                pass
        if was:
            # 🔴 防抖定时器可能还没到点就被关掉 → 这里立即补写一次，
            #    否则「拖完马上点面板外」这次改动会丢（`set_global` 值没变时不重复写盘）。
            if self._font_save_timer is not None:
                root = self._win
                if root is not None:
                    try:
                        root.after_cancel(self._font_save_timer)
                    except Exception:
                        pass
                self._font_save_timer = None
            self._persist_font(self._font_pt)
            # 面板关掉后把焦点还给编辑器：否则接下来的打字不生效（同 ⋯ 面板的处理）
            try:
                if self._editing and self._editor is not None:
                    self._editor.focus_set()
            except Exception:
                pass

    # ======================== 窗口拖拽 ========================

    # ---------------- 0915d Stage3：窗口状态持久化 ----------------

    def _apply_note_meta(self, meta: dict) -> None:
        """恢复该便签的窗口状态：位置尺寸 + 常驻置顶 + 底色（都来自 note 里的字段）。"""
        root = self._win
        if root is None:
            return
        b = meta.get("bounds")
        # 0915g：老数据里 bounds 可能是 Python dict 的字符串形态（"{'x': 1511, ...}"）
        # → 直接判成「没记过」，位置恢复失效。这里尽力解析回来。
        if isinstance(b, str) and b.strip().startswith("{"):
            try:
                b = ast.literal_eval(b)
            except Exception:
                b = None
        if isinstance(b, dict) and b.get("w") and b.get("h"):
            try:
                x, y = int(b.get("x", 0)), int(b.get("y", 0))
                w, h = int(b["w"]), int(b["h"])
                w, h = max(w, MIN_W), max(h, MIN_H)
                # 🔴 别恢复到一个「已经不在屏幕上」的坐标（换了显示器/改了分辨率）：
                #    窗口会落在视口外，用户以为悬浮窗没打开。
                sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
                if x > sw - 60 or y > sh - 60 or x + w < 60 or y + h < 60:
                    x, y = 120, 110
                root.geometry("%dx%d+%d+%d" % (w, h, x, y))
            except Exception:
                pass
        aot = bool(meta.get("alwaysOnTop", False))
        self._always_on_top = aot
        try:
            root.attributes("-topmost", aot)
        except Exception:
            pass
        # 0916：底色（per-note）—— 切到这条便签就把窗口刷成它自己的颜色。
        # 🔴 `persist=False`：这是「刚从磁盘读回来的值」，再写回去只会白涨 mtime，
        #    让主界面为一次无意义的改动多跑一轮轮询。
        self._set_note_bg(meta.get("bgColor"), persist=False)

    def _save_bounds(self) -> None:
        """把当前窗口位置/尺寸写回磁盘（拖动 / 缩放结束、隐藏、退出时调用）。"""
        if not self._current_id or self._win is None:
            return
        try:
            x, y, w, h = self._win_geom()
            self.api.save_bounds(self._current_id, x, y, w, h)
        except Exception:
            pass

    def _toggle_always_on_top(self) -> None:
        """切换常驻置顶并落盘（`…` 菜单项）。"""
        self._always_on_top = not self._always_on_top
        try:
            self._win.attributes("-topmost", self._always_on_top)
        except Exception:
            pass
        try:
            if self._current_id:
                self.api.set_flag(self._current_id,
                                  "alwaysOnTop", self._always_on_top)
        except Exception:
            pass

    def _win_geom(self) -> tuple:
        """读窗口当前的 (x, y, w, h)（屏幕坐标）。

        🔴 为什么不用 `winfo_x()/winfo_y()/winfo_width()`：Tk 的 winfo 读的是**内部
        缓存**，窗口未映射（withdraw）或刚下发 geometry 还没处理 Configure 事件时会
        返回旧值甚至 0 —— 拖动/缩放的基准就会算错，表现为「一按下去窗口跳一下」。
        `geometry()` 返回的是 Tk **已记录的目标值**，与我们要写入的坐标系一致，可靠。
        """
        w = self._win
        if w is None:
            return 0, 0, WIN_WIDTH, WIN_HEIGHT
        try:
            g = w.geometry()                  # 形如 "320x380+300+200"（负坐标也兼容）
            size, _, rest = g.partition("+")
            xs = rest.split("+")
            ww, wh = (int(v) for v in size.split("x"))
            x, y = int(xs[0]), int(xs[1])
            if ww < MIN_W:
                ww = WIN_WIDTH
            if wh < MIN_H:
                wh = WIN_HEIGHT
            return x, y, ww, wh
        except Exception:
            return 0, 0, WIN_WIDTH, WIN_HEIGHT

    def _bind_drag(self, widget: tk.Widget) -> None:
        """给顶栏 / 底栏（含其恒高占位槽）绑定拖拽（移动无边框窗口）。

        只绑在栏容器本身，不绑子控件 —— Tk 事件直接派发给指针下的控件，
        点按钮/图标不会冒泡到栏容器，故不会误触拖动。
        """
        widget.bind("<Button-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._do_drag)
        widget.bind("<ButtonRelease-1>", self._stop_drag)

    def _start_drag(self, event) -> None:
        if self._root is None:
            return
        # 🔴 老板 0915：浏览态点「标题栏」位置也要进编辑模式（原来顶栏只绑了拖拽，
        #    点标题栏不会进编辑，只有点正文才行）。进编辑后再走拖拽，两者不冲突。
        if not self._editing:
            self._enter_edit_mode()
        root = self._win
        self._dragging = True
        d = self._drag_data
        d["x"] = d["x0"] = event.x_root
        d["y"] = d["y0"] = event.y_root
        d["t"] = 0.0                # 0915c2：时间闸门基准（置 0 → 第一个 Motion 立即生效）
        # 基准位置只在**开始拖动时**问一次：后面用「基准 + 累计位移」算绝对坐标，
        # 省掉每个 Motion 事件两次窗口管理器往返。
        # 🔴 必须走 `_win_geom()`（解析 geometry 目标值），不能用 winfo_x/y —— 见其注释。
        d["bx"], d["by"], _w, _h = self._win_geom()
        self._drag_job = None

    def _do_drag(self, event) -> None:
        """🔴 0915c2：**在 Motion 里直接搬窗**，用时间闸门限流（不再用 `after`）。

        为什么限流：鼠标报告率常见 125~1000Hz，`<B1-Motion>` 每秒能派发上千次，
        全量处理会把消息队列压爆、窗口跟着手指走不动。

        🔴 为什么不用 `after()` 做限流（0915c 的教训）：Tk 的 `after` 在 Windows 上
        走 WM_TIMER，被系统时钟量化 —— 实测 `after(8)` 要 **≈31ms** 才回调一次，
        等于把拖动锁死在 ~32fps（老板反馈「还是有点卡」的真因）。
        时间闸门用 `perf_counter()` 判断，帧率由**真实鼠标事件**驱动，不受量化影响。
        """
        if not self._dragging:
            return
        d = self._drag_data
        d["x"] = event.x_root
        d["y"] = event.y_root
        now = time.perf_counter()
        if now - d.get("t", 0.0) < DRAG_FLUSH_S:
            return                       # 太密 → 交给下一个 Motion（松手时会补最后一次）
        d["t"] = now
        self._flush_drag()

    def _flush_drag(self) -> None:
        """真正执行位移（由 `_do_drag` 合并调度；位置 = 拖动开始时的基准 + 累计位移）。"""
        self._drag_job = None
        root = self._win
        if root is None or not self._dragging:
            return
        d = self._drag_data
        try:
            nx = d.get("bx", 0) + (d["x"] - d.get("x0", d["x"]))
            ny = d.get("by", 0) + (d["y"] - d.get("y0", d["y"]))
            root.geometry("+%d+%d" % (int(nx), int(ny)))
        except Exception:
            pass

    def _stop_drag(self, _event=None) -> None:
        if self._drag_job is not None:
            try:
                self._win.after_cancel(self._drag_job)
            except Exception:
                pass
            self._drag_job = None
        self._flush_drag()      # 补上最后一次位移，避免松手时“差一口气”
        self._dragging = False
        self._save_bounds()     # 0915d：拖动结束 → 位置落盘（重启后原位恢复）

    # ======================== 显示到最前 ========================

    def _present(self) -> None:
        """显示 + 抬到最前 + 短暂置顶。"""
        root = self._win
        if root is None:
            return
        self._visible = True      # 0915h：参见 `_hide()` 里的同名标志
        try:
            root.deiconify()
            root.state("normal")
            root.update_idletasks()      # 先让真实尺寸就绪，再应用圆角
        except Exception:
            pass
        self._apply_round_corners(force=True)   # 显示后再确认一次 DWM 圆角（隐藏期设过也稳）
        try:
            root.lift()
            root.attributes("-topmost", True)

            def _unpin():
                try:
                    # 🔴 0915d：若本窗是「常驻置顶」，这里不能一刀切取消 ——
                    #    否则用户设的置顶会在弹出后 600ms 被悄悄撤掉。
                    root.attributes("-topmost", bool(self._always_on_top))
                except Exception:
                    pass
            root.after(600, _unpin)
        except Exception:
            pass
        try:
            root.focus_force()
        except Exception:
            pass
        # 0915d：窗口已显示 → 标记为「正在悬浮」，退出/重启后据此自动恢复
        try:
            if self._current_id:
                self.api.set_flag(self._current_id, "isFloating", True)
        except Exception:
            pass

    # ======================== 公开 API（跨线程调用）========================

    def show_new(self) -> bool:
        """托盘「新建桌面便签」：显示窗口并新建空白便签。"""
        root = self._win
        if root is None or self._stopping:
            return False
        try:
            root.after(0, self._show_new_in_tk)
            return True
        except Exception:
            return False

    def _show_new_in_tk(self) -> None:
        if self._root is None:
            return
        self._new_note()
        self._present()
        self._editing = False        # 确保走完整挂载流程
        self._enter_edit_mode()
        self._sync_sbar()

    def show_content(self, title: str, content: str, src_id: str = "",
                     wait: bool = False) -> bool:
        """把主界面当前便签弹出为悬浮便签。

        🔴 0915 起 `src_id`（主界面便签 id）会被记下来 → 两边**实时互为镜像**
           （老板要求「主界面的数据修改，或者悬浮便签页面的数据修改需要实时同步到两边」）。
           `src_id` 为空时退化成老行为（一条独立的桌面便签，不与主界面联动）。

        `wait=True`（0915f）：**等 Tk 线程真正铺完内容再返回**。
        原来一律 `after(0)` 异步 → `popout_note` 立刻返回 True，而 `src_id` 绑定
        可能还没写进磁盘；JS 紧接着那次 `pushDeskSync()` 必然空转（找不到绑定记录），
        表现为「刚弹出来那一会儿不同步」。最多等 3 秒，超时照常返回（不卡死调用方）。
        """
        root = self._win
        if root is None or self._stopping:
            return False
        ev = threading.Event() if wait else None

        def _job():
            try:
                self._show_content_in_tk(title, content, src_id)
            finally:
                if ev is not None:
                    ev.set()          # 异常也要放闸，绝不让调用方死等

        try:
            root.after(0, _job)
        except Exception:
            return False
        if ev is not None:
            ev.wait(3.0)
        return True

    def _show_content_in_tk(self, title: str, content: str, src_id: str = "") -> None:
        root = self._win
        if root is None:
            return
        self._save_now()
        try:
            # 🔴 复用策略（0915）：不要每次都 `new_note()` ——
            #    ① 同一条主界面便签反复点「弹出」→ 复用已绑定的那条桌面便签
            #       （否则文件里会堆出一串一模一样的新便签）；
            #    ② 当前这条若还是「没绑定的空便签」（启动时 `load()` 建的）→ 也复用它。
            target = ""
            try:
                if src_id:
                    target = self.api.find_by_src(src_id)
                    if not target and self._current_id and not self._src_id \
                            and self._editor_empty():
                        # 🔴 0915c 多悬浮窗：这条待复用的桌面便签若**已经被别的会话绑定**
                        #    （它的 src_id 属于别人），就绝不能抢 ——
                        #    否则多个悬浮窗共用同一条磁盘记录，最后一个写的人盖掉前面所有人
                        #    （冒烟 `_multitest_0915c` 里三个会话 curr_id 撞成同一个）。
                        #    抢之前先确认它是「无主」或「本就是我的」。
                        try:
                            cur = self.api.load_by_id(self._current_id) or {}
                        except Exception:
                            cur = {}
                        owner = cur.get("src_id") or ""
                        if owner and owner != src_id:
                            target = ""          # 已被别的会话占用 → 下面走 new_note
                        else:
                            target = self._current_id
                            self.api.bind_src(target, src_id)
            except Exception:
                target = ""
            if target:
                self._current_id = target
                self._src_id = src_id
            else:
                r = self.api.new_note(src_id)          # 新建时带上绑定关系
                self._current_id = r.get("id")
                self._src_id = (r.get("src_id") or src_id or "")
            # 0915d Stage3：先把这条便签的窗口状态（位置尺寸 / 置顶 / revision）恢复好
            try:
                meta = self.api.load_by_id(self._current_id) or {}
            except Exception:
                meta = {}
            self._rev = int(meta.get("revision") or 0)
            self._apply_note_meta(meta)
            self._self_written = ""
            self._fill_from_html(content or "")
            self._has_content = not self._editor_empty()
            if not self._has_content:
                self._set_display("", placeholder=True)
            self._save_now()
            self._present()
            self._editing = False    # 确保走完整挂载流程
            self._enter_edit_mode()
            self._sync_sbar()
            self._refresh_fmt_state()
        except Exception:
            pass
