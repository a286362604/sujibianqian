# -*- coding: utf-8 -*-
"""0915c Stage2：**多悬浮窗管理器** —— per-note 会话映射 + 去重激活 + 统一收尾。

设计要点
--------
1. **一个 FloatHost（单 Tk root / 单线程 / 单 mainloop）+ 每便签一个 Toplevel**：
   Tk 多 root 多线程长期不稳，所以全部悬浮窗共享同一个 host。
2. **去重**：同一 noteId 只建一个会话。重复调用 `open()` 时走「更新内容 +
   deiconify + lift」路径（悬浮窗的 × 是 `withdraw` 隐藏，不是销毁），即「只激活」。
3. **关闭 ≠ 删除**：窗口隐藏/会话销毁都不动便签数据；只有 `close()`（主界面删除
   便签时调用）才真销毁会话。
4. **绝不跨线程碰 Tk**：所有窗口操作通过 `FloatHost.run_in_tk()`（`after(0,fn)`）投递。
"""

import threading
import time

from desk_note_window import DesktopNoteWindow, FloatHost

# 新建悬浮窗的错位摆位（避免叠成一坨）；超过 6 个回到起点循环
_STAGGER_DX = 46
_STAGGER_DY = 38
_STAGGER_MAX = 6
_BASE_X = 120
_BASE_Y = 110
# 启动时预热的隐藏会话的 key（真正新建悬浮便签时会被“转正”成 @local:N）
_WARM_KEY = "@warmup"


class FloatingWindowManager:
    """noteId → 悬浮窗会话的注册表 + 生命周期管理。"""

    def __init__(self, api) -> None:
        self.api = api                       # DesktopApi 实例（所有会话共享，同一份 JSON）
        self.host = FloatHost()
        self._sessions: dict = {}            # key(noteId 或 @local:N) → DesktopNoteWindow
        self._local_seq = 0
        self._lock = threading.RLock()

    # ------------------------- 内部工具 -------------------------

    def _ensure_host(self) -> bool:
        if not self.host.is_alive():
            self.host.start()
        return self.host.is_alive()

    @staticmethod
    def _wait_window(s, timeout: float = 4.0) -> bool:
        """等 Tk 线程把该会话的 Toplevel 建出来（_build 里赋值 s._win）。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if getattr(s, "_win", None) is not None:
                return True
            time.sleep(0.05)
        return False

    @staticmethod
    def _make_stagger(s, idx):
        def _do():
            try:
                w = s._win
                if w is None:
                    return
                i = idx % _STAGGER_MAX
                w.geometry("+%d+%d" % (_BASE_X + i * _STAGGER_DX,
                                       _BASE_Y + i * _STAGGER_DY))
            except Exception:
                pass
        return _do

    def _bounds_for(self, note_id: str):
        """0915d：该便签是否已有存过的位置尺寸（有就不必再做错位摆位，避免闪一下）。"""
        if not note_id:
            return None
        try:
            did = self.api.find_by_src(note_id)
            if not did:
                return None
            return (self.api.load_by_id(did) or {}).get("bounds")
        except Exception:
            return None

    @staticmethod
    def _make_activate(s):
        def _do():
            try:
                w = s._win
                if w is None:
                    return
                w.deiconify()
                w.lift()
                # 只为把它顶到最前一次，不长期强制置顶（否则会压住主界面）
                w.attributes("-topmost", True)
                w.attributes("-topmost", False)
                try:
                    w.focus_force()
                except Exception:
                    pass
            except Exception:
                pass
        return _do

    def _activate(self, s) -> None:
        self.host.run_in_tk(self._make_activate(s))

    # ------------------------- 对外接口 -------------------------

    def has(self, note_id: str) -> bool:
        """该便签是否已有悬浮窗（可用于主界面「悬浮中」标记）。"""
        s = self._sessions.get(note_id or "")
        return bool(s is not None and getattr(s, "_win", None) is not None)

    def warmup(self) -> bool:
        """应用启动时预热：起 Tk host + 预置一个**隐藏**会话。

        两个目的：
          ① 保持单窗口时代的既有行为——启动后 Tc 侧就存在一个 TkTopLevel（隐藏），
             冷启动点验（`_boot_check_0914x`）依赖它；
          ② 首次「弹出悬浮便签 / 新建桌面便签」不必现建 Toplevel，响应更快。
        注意：这里**不** load 任何便签内容，纯粹是把窗口骨架先搭好。
        """
        if not self._ensure_host():
            return False
        with self._lock:
            if self._sessions:
                return True
            s = DesktopNoteWindow(self.api, self.host)
            s._session_key = _WARM_KEY
            self._sessions[_WARM_KEY] = s
            try:
                s.start()
                return self._wait_window(s)
            except Exception:
                self._sessions.pop(_WARM_KEY, None)
                return False

    def open(self, title: str = "", content: str = "", note_id: str = "") -> bool:
        """弹出 / 激活某条便签的悬浮窗。

        - 已有会话 → **只更新内容并激活**（绝不重复创建）
        - 没有会话 → 新建 Toplevel 会话后弹出
        """
        if not note_id:
            return bool(self.new_local(title, content))
        with self._lock:
            s = self._sessions.get(note_id)
            if s is not None and getattr(s, "_win", None) is not None:
                try:
                    # 0915f：等 Tk 真的铺完再返回（JS 拿到 True 后立刻 pushDeskSync 才有意义）
                    s.show_content(title or "", content or "", note_id, wait=True)
                except Exception:
                    pass
                self._activate(s)
                return True
            if s is not None:                       # 会话对象还在但窗口已被销毁 → 丢弃重建
                self._sessions.pop(note_id, None)
            if not self._ensure_host():
                return False
            s = DesktopNoteWindow(self.api, self.host)
            s._session_key = note_id            # 0917：会话自报「我在注册表里叫这个」
            self._sessions[note_id] = s
            try:
                s.start()
                if not self._wait_window(s):
                    return False
                # 0915d：已存过位置 → 让会话自己恢复（`_apply_note_meta`），别再错位摆一次
                if not self._bounds_for(note_id):
                    self.host.run_in_tk(self._make_stagger(s, len(self._sessions) - 1))
                ok = s.show_content(title or "", content or "", note_id, wait=True)
                self._activate(s)
                return bool(ok)
            except Exception:
                self._sessions.pop(note_id, None)
                return False

    def new_local(self, title: str = "", content: str = "") -> str:
        """托盘「新建桌面便签」：一条不与主界面便签绑定的独立会话。返回内部 key。"""
        with self._lock:
            # 启动预热的那个空会话：第一次「新建桌面便签」直接复用它（等价于旧版行为）
            warm = self._sessions.get(_WARM_KEY)
            if warm is not None and getattr(warm, "_win", None) is not None \
                    and not getattr(warm, "_current_id", None):
                self._sessions.pop(_WARM_KEY, None)
                self._local_seq += 1
                key = "@local:%d" % self._local_seq
                warm._session_key = key         # 0917：转正后要把 key 改成新的
                self._sessions[key] = warm
                try:
                    warm.show_new()
                    self._activate(warm)
                except Exception:
                    pass
                return key
            self._local_seq += 1
            key = "@local:%d" % self._local_seq
            if not self._ensure_host():
                return ""
            s = DesktopNoteWindow(self.api, self.host)
            s._session_key = key                # 0917：会话自报「我在注册表里叫这个」
            self._sessions[key] = s
            try:
                s.start()
                self._wait_window(s)
                self.host.run_in_tk(self._make_stagger(s, len(self._sessions) - 1))
                s.show_new()
                self._activate(s)
            except Exception:
                self._sessions.pop(key, None)
                return ""
            return key

    def close(self, note_id: str) -> bool:
        """真销毁某条便签的悬浮窗（**只关窗口，不删便签数据**）。"""
        with self._lock:
            s = self._sessions.pop(note_id or "", None)
            if s is None:
                return False
            try:
                s.stop()
            except Exception:
                pass
            # 给 Tk 线程一点时间把 _cleanup / 最后一次 _save_now 跑完：
            # 否则「关窗 → 立刻删掉桌面便签记录」会被回落的那次保存重新写回来。
            time.sleep(0.3)
            return True

    def close_all(self, keep_warm: bool = True) -> int:
        """关掉**所有**悬浮窗（开发者选项「清除所有数据」用），返回关掉的数量。

        🔴 `keep_warm=True` 保留启动预热那个隐藏会话 —— 它与任何便签数据无关，
           留着可以让下次「新建悬浮便签」少等一次 Toplevel 构建。
        🔴 必须逐个走 `close()`：它内部会等 0.3s 让 Tk 把最后一次 `_save_now()` /
           `_save_bounds()` 跑完。调用方（`Api.clear_all_data`）紧接着要清空数据
           文件，若这里不等待，会话收尾那次保存会把刚清掉的内容又写回一条新记录。
        """
        with self._lock:
            keys = [k for k in list(self._sessions.keys())
                    if not (keep_warm and k == _WARM_KEY)]
        n = 0
        for k in keys:
            try:
                if self.close(k):
                    n += 1
            except Exception:
                pass
        return n

    def broadcast_font(self, pt: int) -> int:
        """把字号推给**所有**悬浮便签会话（0917：字号设置要「对全部悬浮便签统一生效」）。

        🔴 必须走 `host.run_in_tk`（`after(0, fn)`）：调用方虽然也在 Tk 线程里，
           但排队执行最稳 —— 我们可能在别的会话的回调里被调到，直接改另一个会话的
           控件属于「同线程跨会话」，Tk 能接受但仍以排队为妥。
        返回值 = 投递成功的会话数（不代表已经重画完，那是下一轮事件循环的事）。
        """
        n = 0
        try:
            sessions = list(self._sessions.values())
        except Exception:
            return 0
        for s in sessions:
            try:
                self.host.run_in_tk(lambda s=s, p=pt: s.set_font_pt(p))
                n += 1
            except Exception:
                pass
        return n

    def close_by_window(self, win) -> bool:
        """**由会话自己发起**的「关闭我自己」（悬浮便签里点「删除便签」时用）。

        与 `close()` 的区别：`close()` 是给外部调用方（Python 侧 / GUI 线程）用的，
        内部会 `sleep(0.3)` 等 Tk 把收尾跑完；本方法是在 **Tk 线程内**被调的，
        绝不能再睡 —— 一睡整个 Tk 事件循环就停住（桌面上所有悬浮窗一起僵）。
        所以这里只做「从注册表摘除 + 投递销毁」，真正的收尾交给 Tk 线程排队执行。
        """
        key = getattr(win, "_session_key", "") or ""
        if not key:
            return False
        with self._lock:
            s = self._sessions.pop(key, None)
        if s is None:
            return False
        try:
            self.host.run_in_tk(s.stop)
        except Exception:
            return False
        return True

    def restore_all(self) -> int:
        """0915d：重启后恢复上次退出时仍在悬浮的窗口（位置尺寸一并还原）。

        只恢复**与主界面便签绑定**的那些（有 `src_id`）—— 独立的桌面便签（托盘新建的）
        沿用旧行为，不自动冒出来。
        返回实际恢复的窗口数。
        """
        try:
            items = self.api.list_floating() or []
        except Exception:
            return 0
        n = 0
        for it in items:
            sid = str(it.get("src_id") or "")
            if not sid:
                continue
            try:
                if self.open("", it.get("content") or "", sid):
                    n += 1
            except Exception:
                pass
        return n

    def floating_ids(self) -> list:
        """正在悬浮（且与主界面便签绑定）的 noteId 列表，供主界面做状态标记。"""
        out = []
        for k, s in self._sessions.items():
            if k.startswith("@"):        # @warmup / @local:N —— 都没绑主界面便签
                continue
            if getattr(s, "_win", None) is None:
                continue
            # 🔴 0915h：× 关闭 = withdraw，窗口对象仍在 → 只看 `_win` 会把已关的窗
            #    也算成「悬浮中」，主界面「浮」徽章就再也消不掉。
            #    这里读的是 DesktopNoteWindow 上的纯 Python 标志（本方法由 GUI 线程调用，
            #    绝不能跨线程去调 Tk 的 winfo_viewable）。
            if not getattr(s, "_visible", False):
                continue
            out.append(k)
        return out

    def count(self) -> int:
        return len(self._sessions)

    def shutdown(self) -> None:
        """应用退出：逐个销毁会话，最后停掉唯一那个 Tk host。"""
        with self._lock:
            for s in list(self._sessions.values()):
                try:
                    s.stop()
                except Exception:
                    pass
            self._sessions.clear()
        time.sleep(0.4)          # 让 Tk 线程把 cleanup 跑完
        try:
            self.host.stop()
        except Exception:
            pass
