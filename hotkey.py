# -*- coding: utf-8 -*-
"""
全局快捷键封装（Windows，零额外依赖）。

基于 RegisterHotKey + 独立线程消息循环实现：
- RegisterHotKey 失败即返回原因（ERROR_HOTKEY_ALREADY_REGISTERED = 被占用），
  可用于设置页的快捷键冲突检测（红字提示并禁止保存）。
- 热键消息投递到注册线程的消息队列，收到 WM_HOTKEY 后回调。
- 与旧版 WH_KEYBOARD_LL 低级钩子相比，本方案不吞键、更标准，且天然支持
  冲突检测（注册失败 = 已被占用）。
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT = 0x1
MOD_CONTROL = 0x2
MOD_SHIFT = 0x4
MOD_WIN = 0x8

WM_HOTKEY = 0x0312
WM_NULL = 0x0000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

VK_F1 = 0x70
VK_F24 = 0x87
VK_SNAPSHOT = 0x2C  # PrintScreen

MOD_NAMES = {
    MOD_CONTROL: "Ctrl",
    MOD_SHIFT: "Shift",
    MOD_ALT: "Alt",
    MOD_WIN: "Win",
}

# ---------------------------------------------------------------------------
# 组合键解析："F8" / "Ctrl+Alt+N" / "Shift+F1" -> (mods_int, vk)
# ---------------------------------------------------------------------------
def _mod_int_of(name: str) -> int | None:
    n = name.lower()
    if n in ("ctrl", "control"):
        return MOD_CONTROL
    if n == "shift":
        return MOD_SHIFT
    if n in ("alt", "menu"):
        return MOD_ALT
    if n in ("win", "meta", "windows", "super"):
        return MOD_WIN
    return None


def parse_combo(combo: str) -> tuple[int, int] | None:
    """把 "Ctrl+Alt+N" 解析为 (mods, vk)；无法解析返回 None。"""
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    key = ""
    for p in parts:
        m = _mod_int_of(p)
        if m is not None:
            mods |= m
        else:
            key = p
    vk = key_to_vk(key)
    if vk == 0:
        return None
    return mods, vk


def key_to_vk(key: str) -> int:
    """主键字符串 -> 虚拟键码。支持 F1-F24、字母、数字。"""
    k = key.upper()
    if len(k) == 1:
        if "A" <= k <= "Z":
            return ord(k)
        if "0" <= k <= "9":
            return ord(k)
        return 0
    if k.startswith("F"):
        try:
            n = int(k[1:])
        except ValueError:
            return 0
        if 1 <= n <= 24:
            return VK_F1 - 1 + n
    return 0


def format_combo(combo: str) -> str:
    """规范化显示："ctrl+alt+n" -> "Ctrl+Alt+N"；解析失败原样返回。"""
    parsed = parse_combo(combo)
    if parsed is None:
        return combo
    mods, vk = parsed
    names = [n for m, n in sorted(MOD_NAMES.items(), reverse=True) if mods & m]
    key = vk_to_key(vk)
    if key:
        names.append(key)
    return "+".join(names) if names else combo


def vk_to_key(vk: int) -> str:
    if VK_F1 <= vk <= VK_F24:
        return f"F{vk - VK_F1 + 1}"
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    return ""


# ---------------------------------------------------------------------------
# 系统保留快捷键黑名单
# ---------------------------------------------------------------------------
def is_system_reserved(combo: str) -> tuple[bool, str]:
    """
    判断组合键是否与 Windows 系统级快捷键冲突。
    返回 (是否冲突, 冲突描述)。
    """
    parsed = parse_combo(combo)
    if parsed is None:
        return True, "无法识别的按键组合"
    mods, vk = parsed

    if mods & MOD_WIN:
        return True, "该快捷键与 Windows 系统快捷键冲突，请更换。"
    key = vk_to_key(vk)
    # 无修饰键的普通键也允许（如默认 F8）；但 PrintScreen 属于系统截图键
    if vk == VK_SNAPSHOT:
        return True, "该快捷键与 Windows 系统快捷键冲突，请更换。"
    if key == "F4" and mods == MOD_ALT:  # Alt+F4 关闭窗口
        return True, "该快捷键与 Windows 系统快捷键冲突，请更换。"
    # 说明：Ctrl+Alt+Del / Ctrl+Shift+Esc / Alt+Tab 等系统保留组合由系统独占，
    # 注册必失败；主键解析层已排除 Esc/Tab/Del，此处不再逐项罗列。
    return False, ""


# ---------------------------------------------------------------------------
# 全局热键管理器
# ---------------------------------------------------------------------------
class GlobalHotkey:
    """单个全局热键：注册在独立线程，命中后回调（回调在热键线程执行）。"""

    def __init__(self, callback) -> None:
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._running = False
        self._combo: str | None = None
        self._mods = 0
        self._vk = 0
        self._hid = 0
        self._next_id = 1000

    @property
    def active_combo(self) -> str | None:
        return self._combo

    def register(self, combo: str, timeout: float = 3.0) -> tuple[bool, str]:
        """
        注册全局热键（会替换当前已注册的热键）。
        返回 (ok, reason)；reason 用于设置页红字提示。
        """
        # 预检
        conflict, reason = is_system_reserved(combo)
        if conflict:
            return False, reason
        parsed = parse_combo(combo)
        if parsed is None:
            return False, "无法识别的按键组合"
        mods, vk = parsed

        self.stop(wait=False)

        result: dict = {}
        done = threading.Event()

        def worker() -> None:
            # 确保本线程存在消息队列
            msg = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # PM_NOREMOVE
            self._next_id += 1
            hid = self._next_id
            ok = user32.RegisterHotKey(None, hid, mods, vk)
            if not ok:
                err = ctypes.get_last_error()
                result["ok"] = False
                result["err"] = err
                result["reason"] = (
                    "该快捷键已被其他程序占用，请更换。"
                    if err == ERROR_HOTKEY_ALREADY_REGISTERED
                    else "快捷键注册失败，请更换。"
                )
                done.set()
                return
            self._combo = combo
            self._mods = mods
            self._vk = vk
            self._hid = hid
            result["ok"] = True
            done.set()
            # 消息循环
            while self._running:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == hid:
                    try:
                        self._callback()
                    except Exception:
                        pass

        self._running = True
        t = threading.Thread(target=worker, daemon=True, name="global-hotkey")
        t.start()
        self._thread = t
        done.wait(timeout)
        return bool(result.get("ok")), result.get("reason", "")

    def stop(self, wait: bool = True) -> None:
        self._running = False
        t = self._thread
        if t is not None and t.is_alive():
            # 投递空消息唤醒阻塞中的 GetMessageW
            try:
                user32.PostThreadMessageW(t.ident, WM_NULL, 0, 0)
            except Exception:
                pass
            if wait:
                t.join(timeout=2.0)
        if self._hid:
            user32.UnregisterHotKey(None, self._hid)
            self._hid = 0
        self._combo = None
        self._thread = None
