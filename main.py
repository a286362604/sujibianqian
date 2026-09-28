# -*- coding: utf-8 -*-
"""
便签应用 - 桌面版主程序

技术栈：pywebview(WebView2) + HTML/CSS/JS + PyInstaller
系统能力：全局快捷键（RegisterHotKey，零依赖）、开机启动（注册表 Run 键）、
          系统托盘（pystray）、桌面便签小窗、JSON 原子持久化。
行为：主窗口点 [X] / 快捷键 → 隐藏到托盘（不退出）；退出仅通过托盘菜单“退出”。
运行：python main.py   （或双击 run.bat / 打包后的 exe）

===================== 文件导航（本文件 6000+ 行，按这个顺序找） =====================
· 常量 / 工具        ：APP_TITLE、DATA_FILE_NAME、resource_path()、_si_log()
· class DesktopApi   ：**悬浮便签**的 JS 桥 + `桌面便签数据.json` 的读写。
                       🔴 0917d 起，凡是「读-改-写」的方法（load / new_note /
                       save_note / delete_note / clear_all …）统一 `with self._lock`
                       整体加锁，否则两线程会各自读到旧列表、互相覆盖。
· class Api          ：**主界面网页**的 JS 桥。🔴 `webview.create_window(js_api=api)`
                       挂的就是**这个类** —— 给 JS 新加方法必须加在这里，加到
                       DesktopApi 上 JS 端 `typeof` 会直接不是 function 而**静默失效**
                       （本项目踩过两次的坑）。0917d 新增 encrypt_secret /
                       decrypt_secret（WebDAV 凭据用 DPAPI 加密后落盘）。
· open_desktop_note()：托盘右键 / 全局快捷键 / 悬浮窗顶栏「+」**共用**的新建入口
                       —— 走「写命令文件 + 主界面 300ms 轮询」，绝不跨线程 evaluate_js。
· main()             ：单实例 Mutex → 建窗口 → 起托盘/热键 → webview.start()
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import sys
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import webview

from desk_note_window import DesktopNoteWindow
from float_manager import FloatingWindowManager
from hotkey import GlobalHotkey
from tray import Tray

APP_TITLE = "速记便签"
APP_VERSION = "2.1"     # 0917q：设置页「版本号」展示用，单一来源；改版本号只改这里 + README 版本表
DATA_FILE_NAME = "便签应用数据.json"
DESKTOP_DATA_FILE_NAME = "桌面便签数据.json"
DESKTOP_TITLE = "便签 · 标签页"
DEFAULT_HOTKEY = "F8"


def _documents_dir_via_shell() -> "str | None":
    """通过 Windows Shell 已知文件夹 API 取「用户文档目录」真实路径。

    用 FOLDERID_Documents（SHGetKnownFolderPath）+ CSIDL_PERSONAL 回退，
    能正确处理中文 Windows 的本地化/重定向文档路径，返回 None 表示当前环境不可用。
    """
    try:
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
    except AttributeError:
        return None
    # 1) FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
    try:
        fid = ctypes.create_unicode_buffer("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
        SHGetKnownFolderPath = shell32.SHGetKnownFolderPath
        SHGetKnownFolderPath.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p)]
        SHGetKnownFolderPath.restype = ctypes.c_int32
        ppath = ctypes.c_void_p()
        hr = SHGetKnownFolderPath(fid, 0, None, ctypes.byref(ppath))
        if hr == 0 and ppath:
            path = ctypes.wstring_at(ppath)
            try:
                ole32.CoTaskMemFree(ppath)
            except Exception:
                pass
            return path or None
    except Exception:
        pass
    # 2) CSIDL_PERSONAL(5) 回退
    try:
        buf = ctypes.create_unicode_buffer(260)
        shell32.SHGetFolderPathW(None, 5, None, 0, buf)
        if buf.value:
            return buf.value
    except Exception:
        pass
    return None


def get_documents_dir() -> str:
    """动态获取当前系统的「用户文档目录」。

    全程不硬编码桌面/用户名绝对路径：优先 Windows Shell 已知文件夹 API，
    回退 ~/Documents，再回退程序所在目录（极端环境兜底，保证不报错）。
    """
    d = _documents_dir_via_shell()
    if d and os.path.isdir(d):
        return d
    home_docs = os.path.join(os.path.expanduser("~"), "Documents")
    if os.path.isdir(home_docs):
        return home_docs
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _legacy_data_dir() -> str:
    """旧版数据所在目录（exe/脚本同目录）。用于首次运行的旧数据迁移。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_writable_dir(d: str) -> str:
    """创建目录（若不存在）并探测可写；不可写则回退到程序目录，绝不抛错。"""
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".writetest_%d.tmp" % os.getpid())
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return d
    except Exception as e:
        try:
            sys.stderr.write(
                "速记便签：专用数据目录不可写，已回退到程序目录：%s（原因：%r）\n" % (d, e))
            sys.stderr.flush()
        except Exception:
            pass
        fb = (os.path.dirname(sys.executable)
              if getattr(sys, "frozen", False)
              else os.path.dirname(os.path.abspath(__file__)))
        try:
            os.makedirs(fb, exist_ok=True)
        except Exception:
            pass
        return fb


def _maybe_migrate_legacy_data(d: str) -> None:
    """首次运行把旧位置（程序同目录）的数据一次性迁到新专用目录，避免丢数据。

    新目录已有文件则跳过（以新为准，不覆盖）；新旧同目录则无需迁移。
    """
    global _LEGACY_MIGRATED
    if _LEGACY_MIGRATED:
        return
    _LEGACY_MIGRATED = True
    legacy = _legacy_data_dir()
    if os.path.abspath(legacy) == os.path.abspath(d):
        return
    for fname in (DATA_FILE_NAME, DESKTOP_DATA_FILE_NAME):
        src = os.path.join(legacy, fname)
        dst = os.path.join(d, fname)
        if os.path.isfile(src) and not os.path.isfile(dst):
            try:
                shutil.copy2(src, dst)
                _si_log("迁移旧数据 %s -> %s" % (src, dst))
            except Exception as e:
                _si_log("迁移旧数据失败 %s：%r" % (src, e))


_DATA_DIR: "str | None" = None
_LEGACY_MIGRATED = False


def app_dir() -> str:
    """专用数据目录：用户文档目录下的「速记便签」子目录。

    - 动态解析（SHGetKnownFolderPath / ~/Documents / 程序目录兜底），不硬编码桌面路径；
    - 首次访问自动创建并确保可读写；
    - 首次运行把旧位置数据一次性迁过来（防丢）；
    - 换机/迁移环境按新系统重新解析，数据落在对应文档目录下。
    """
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    docs = get_documents_dir()
    d = _ensure_writable_dir(os.path.join(docs, APP_TITLE))
    _DATA_DIR = d
    _maybe_migrate_legacy_data(d)
    return _DATA_DIR


def resource_path(rel: str) -> str:
    """打包后静态资源在 _MEIPASS 解压目录中。"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


from webdav_sync import WebDavClient, WebDavError


# ---------------------------------------------------------------------------
# 开机自启（注册表 Run 键）
# ---------------------------------------------------------------------------
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "便签应用"


def _autostart_command() -> str:
    # 0917n：开机自启带 --startup 参数 → main() 据此只常驻托盘、不弹主窗、恢复悬浮便签
    # 0917r：打包态必须用**原始真实 exe 路径**，不能用 sys.executable。
    #   PyInstaller 单文件 exe 运行时 sys.executable 指向一次性临时解压目录
    #   %TEMP%\_MEIxxxx\速记便签.exe，进程退出后该目录被 bootloader 清理，
    #   写进 Run key 的路径下次启动即失效 → 自启静默失败（无论关机前是否主动退出）。
    #   sys.argv[0] 在单文件模式下保持为用户双击/Run key 启动时的真实 exe 路径，
    #   且 main() 每次启动会据当前 argv[0] 重写 Run key（自动跟随 exe 当前位置）。
    tail = " --startup"
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.argv[0])
        return f'"{exe}"{tail}'
    py = sys.executable
    pyw = py.replace("python.exe", "pythonw.exe")
    if os.path.exists(pyw):
        py = pyw
    script = os.path.abspath(__file__)
    return f'"{py}" "{script}"{tail}'


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as k:
            winreg.QueryValueEx(k, RUN_VALUE_NAME)
        return True
    except (FileNotFoundError, OSError):
        return False


def autostart_set(on: bool) -> bool:
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as k:
            if on:
                winreg.SetValueEx(k, RUN_VALUE_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 桌面便签数据（独立 JSON，结构：{"notes": [{"id","content","pinned"}]}）
# ---------------------------------------------------------------------------
def _brand_new_note(note_id: str, content: str = "", src_id: str = "") -> dict:
    """0915d Stage3：新建桌面便签的字段骨架（统一在此，避免各处漏字段）。

    字段：`id` / `content` / `src_id` / `pinned`(旧字段，主窗口置顶用) /
    `bounds:{x,y,w,h}` 悬浮窗位置尺寸 / `alwaysOnTop` 悬浮窗置顶 /
    `isFloating` 是否正在悬浮（重启恢复用） /
    `revision` 版本号（防同步回环）/ `createdAt` / `updatedAt`。
    缺字段一律按默认处理 → 老数据文件无需迁移。
    """
    now = int(time.time() * 1000)
    n = {"id": note_id, "content": content, "pinned": False,
         "bounds": None, "alwaysOnTop": False, "isFloating": False,
         "revision": 0, "createdAt": now, "updatedAt": now}
    if src_id:
        n["src_id"] = src_id
    return n


class DesktopApi:
    """桌面便签小窗口的 JS 桥。窗口引用在创建后注入（window 属性）。"""

    def __init__(self, data_file: str) -> None:
        self.data_file = data_file
        self.window = None
        # 0917：由 `main()` 注入 FloatingWindowManager —— 悬浮便签里点「删除便签」时，
        #       会话需要请 manager 把**自己**从注册表摘掉并销毁窗口（见 `close_self`）。
        self.manager = None
        # 🔴 用 RLock：下面这些方法会「先拿锁 → 再调 _write（内部也拿锁）」，
        #    普通 Lock 不可重入会自锁（0915 双向同步改造后出现该调用形态）。
        self._lock = threading.RLock()
        # 0915i：解析结果缓存（见 `_read`）。🔴 老板实测「键入文字特别卡」的真因：
        #   桌面数据文件已达 **11.6MB**（正文里内嵌 base64 图片），而两侧轮询各每 300ms
        #   调一次 `list_bound()` / `load_by_id()` → 每次都 `json.load` 整个 11.6MB，
        #   主线程被反复阻塞几百毫秒 → 打字肉眼可见地卡。
        self._cache: list | None = None
        self._cache_sig: tuple | None = None     # (mtime_ns, size)
        # 0917：文件级**全局设置**（`settings` 段）。悬浮便签字号是全局统一的
        # （对全部悬浮便签生效、新建的也沿用），所以放这里而不是 per-note。
        # 🔴 `_write` 必须原样写回它 —— 旧版 `_write` 只写 `{"notes": ...}`，
        #    每存一次便签就会把 settings 整段抹掉（字号/其它全局项会莫名其妙丢失）。
        self._gsettings: dict = {}

    # ---------------- 内部读写 ----------------
    def _sig(self):
        """文件指纹：mtime_ns + size 都一致才认为「没变过」。"""
        try:
            st = os.stat(self.data_file)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _read(self) -> list[dict]:
        sig = self._sig()
        with self._lock:
            if sig is not None and self._cache_sig == sig and self._cache is not None:
                # 浅拷贝：调用方对 list 的增删不会污染缓存（dict 内的改写在锁内且必落盘）
                return list(self._cache)
        notes: list = []
        gsettings: dict = {}
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj.get("notes"), list):
                notes = obj["notes"]
            # 0917：顺带把全局设置读进来（`_write` 要原样写回，别丢了）
            if isinstance(obj.get("settings"), dict):
                gsettings = obj["settings"]
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            notes = []
        with self._lock:
            self._cache = notes
            self._cache_sig = sig
            self._gsettings = gsettings
        return list(notes)

    def _write(self, notes: list[dict]) -> bool:
        try:
            with self._lock:
                tmp = self.data_file + ".tmp.%d" % os.getpid()
                with open(tmp, "w", encoding="utf-8") as f:
                    # 0917：`settings` 段（全局设置，如悬浮便签字号）必须原样写回
                    json.dump({"notes": notes, "settings": self._gsettings or {}},
                              f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.data_file)
                # 🔴 写盘后必须让缓存跟着走：否则下次读到的是刚被覆盖的旧内容
                self._cache = notes
                self._cache_sig = self._sig()
            return True
        except OSError:
            return False

    # ---------------- 0917：全局设置读写（悬浮便签字号等）----------------

    def get_global(self, key: str, default=None):
        """读一条全局设置（读不到给 default）。"""
        if not key:
            return default
        with self._lock:
            self._read()                     # 刷新缓存（文件可能被别处改过）
            return (self._gsettings or {}).get(key, default)

    def set_global(self, key: str, value) -> bool:
        """写一条全局设置并落盘。值没变就**不写盘**（省一次全量序列化）。

        🔴 顺序：先 `_read()` 取最新 notes（顺带刷新 `_gsettings`），**再**改
           `_gsettings` —— 反过来的话 `_read()` 会把刚设的值又覆盖回磁盘上的旧值。
        """
        if not key:
            return False
        with self._lock:
            notes = self._read()
            if (self._gsettings or {}).get(key) == value:
                return True
            g = dict(self._gsettings or {})
            g[key] = value
            self._gsettings = g
            return self._write(notes)

    # ---------------- JS 接口 ----------------
    def load(self) -> dict:
        """返回最新一条便签（无则创建空白条）。"""
        # 0917d P1：与 `save_note` 保持同一策略 —— **整个「读-改-写」加锁**。
        # 不加锁时两条线程会同时看到「没有便签」而各自创建一条（凭空多出空白便签）；
        # `_read` / `_write` 各自加锁挡不住这种跨调用的竞态。
        with self._lock:
            notes = self._read()
            if not notes:
                notes.append(_brand_new_note(uuid.uuid4().hex[:12]))
                self._write(notes)
            last = notes[-1]
            return {
                "id": last.get("id", ""),
                "content": last.get("content", ""),
                "pinned": bool(last.get("pinned", False)),
                "bounds": last.get("bounds"),
                "alwaysOnTop": bool(last.get("alwaysOnTop", False)),
                "revision": int(last.get("revision") or 0),
            }

    def save_note(self, note_id: str, content: str) -> bool:
        # 🔴 读-改-写整体加锁：Tk 线程（悬浮便签落盘）与 GUI 线程
        #    （`push_from_main` 同步）都会走这里，锁在 `_write` 里才拿的话
        #    两次「读」会读到同一份旧数据 → 后写的那次把前一次覆盖掉。
        with self._lock:
            notes = self._read()
            for n in notes:
                if n.get("id") == note_id:
                    # 🔴 内容没变就**不要**涨 revision：否则两侧轮询会把「同一份内容」
                    #    反复判成新版本，进而互相覆写（抖动/闪烁）。
                    if (n.get("content") or "") != (content or ""):
                        n["content"] = content or ""
                        n["revision"] = int(n.get("revision") or 0) + 1
                        n["updatedAt"] = int(time.time() * 1000)
                        return self._write(notes)
                    return True
            # 找不到则追加（防止窗口数据与文件不同步）—— 新条目保持「独立便签」（无 src_id）
            notes.append(_brand_new_note(note_id or uuid.uuid4().hex[:12],
                                         content or "", ""))
            return self._write(notes)

    def new_note(self, src_id: str = "") -> dict:
        """保存完成旧内容后调用：新建一条空便签并返回其 id。

        `src_id` = 该桌面便签**绑定**的主界面便签 id（0915 双向同步用）。
        非空时，这条桌面便签与主界面那条便签互为镜像；空 = 独立的桌面便签（老行为）。
        """
        # 0917d P1：同样整体加锁 —— 否则两个线程读到同一份旧列表，
        # 后写的那次会把前一次刚追加的便签整条覆盖掉（新建的便签凭空消失）。
        with self._lock:
            note = _brand_new_note(uuid.uuid4().hex[:12], "", src_id)
            notes = self._read()
            notes.append(note)
            self._write(notes)
        return {"id": note["id"], "src_id": src_id}

    # ---------------- 与主界面便签的双向同步（0915）----------------
    # 🔴 老板要求：「主界面的数据修改，或者悬浮便签页面的数据修改需要实时同步到两边」。
    #    两侧是**两个独立 JSON**（主界面 `便签应用数据.json` / 桌面便签 `桌面便签数据.json`），
    #    靠桌面便签里的 `src_id` 建立一一绑定。
    # 🔴 同步全部走**文件 + 锁**，**不用跨线程 evaluate_js** ——
    #    Tk 线程回调 GUI 线程的 evaluate_js 极易死锁（本项目 `on_closing` 已踩过）。
    #    代价是两侧各有一个 800ms 的轮询，换来的是「谁都不会把对方的数据写坏」。

    def load_by_id(self, note_id: str) -> dict:
        """按 id 读一条桌面便签（悬浮便签轮询用；找不到返回空）。"""
        if not note_id:
            return {}
        notes = self._read()
        for n in notes:
            if n.get("id") == note_id:
                return {"id": n.get("id", ""), "content": n.get("content", ""),
                        "pinned": bool(n.get("pinned", False)),
                        "src_id": n.get("src_id", ""),
                        # 0915d Stage3：窗口状态 + 版本号（悬浮窗恢复/防回环用）
                        "bounds": n.get("bounds"),
                        "alwaysOnTop": bool(n.get("alwaysOnTop", False)),
                        "isFloating": bool(n.get("isFloating", False)),
                        # 0916：本条便签的底色（⋯ 面板里选的那个色块，per-note）
                        "bgColor": n.get("bgColor", ""),
                        "revision": int(n.get("revision") or 0),
                        "updatedAt": int(n.get("updatedAt") or 0)}
        return {}

    def list_bound(self) -> dict:
        """`{src_id: content}`：所有与主界面便签绑定的桌面便签（主界面轮询用）。

        🔴 只返回绑定的那几条（通常是 1~3 条），不返回全部 —— content 里可能含
           base64 图片（数 MB），全量回传会拖垮 800ms 的轮询。
        """
        out = {}
        for n in self._read():
            sid = n.get("src_id")
            if sid:
                out[str(sid)] = n.get("content", "") or ""
        return out

    def push_from_main(self, mapping) -> bool:
        """主界面 → 桌面便签：`mapping = {主界面便签id: content}`。

        只更新「src_id 命中」的桌面便签；没有绑定关系的桌面便签**一律不动**
        （老行为：独立便签的数据不会被主界面覆盖）。
        """
        if not isinstance(mapping, dict) or not mapping:
            return False
        with self._lock:
            notes = self._read()
            changed = False
            for n in notes:
                sid = n.get("src_id")
                if sid and str(sid) in mapping:
                    new_c = mapping[str(sid)] or ""
                    if (n.get("content") or "") != new_c:
                        n["content"] = new_c
                        # 🔴 0915e 必须涨号：悬浮窗的防回环闸门是「remote_rev <= 我的 rev
                        #   就跳过」。这里不 +1，主界面的每次改动都会被判成旧数据而永久
                        #   忽略 → 主改永远同步不到悬浮窗（端到端实测 T1/T5 直接失败）。
                        n["revision"] = int(n.get("revision") or 0) + 1
                        changed = True
            if changed:
                return self._write(notes)
        return False

    def rev(self) -> int:
        """桌面便签文件的版本号（mtime_ns，主界面用来跳过无变化的轮询）。"""
        try:
            return os.stat(self.data_file).st_mtime_ns
        except OSError:
            return 0

    def find_by_src(self, src_id: str) -> str:
        """返回**绑定到该主界面便签**的桌面便签 id（没有则空串）。

        用于「弹出悬浮便签」时复用已有的那条 —— 否则反复点弹出会在文件里
        堆出一串重复的桌面便签（一条比一条新，越积越多）。
        """
        if not src_id:
            return ""
        for n in self._read():
            if n.get("src_id") == src_id:
                return str(n.get("id") or "")
        return ""

    def bind_src(self, note_id: str, src_id: str) -> bool:
        """把一条**已存在**的桌面便签绑定到主界面便签（复用一个空便签时用）。"""
        if not note_id:
            return False
        with self._lock:
            notes = self._read()
            for n in notes:
                if n.get("id") == note_id:
                    if src_id:
                        n["src_id"] = src_id
                    else:
                        n.pop("src_id", None)
                    return self._write(notes)
        return False

    # ---------------- 0915d Stage3：窗口状态持久化 ----------------

    def save_bounds(self, note_id: str, x: int, y: int, w: int, h: int) -> bool:
        """悬浮窗位置/尺寸落盘（拖动 / 缩放结束时调用，重启后据此恢复）。"""
        if not note_id:
            return False
        with self._lock:
            notes = self._read()
            for n in notes:
                if n.get("id") == note_id:
                    b = n.get("bounds") or {}
                    # 0915g：老数据里 bounds 可能是 Python dict 的 str（"{'x': 1511, ...}"）
                    # → 直接 .get 会 AttributeError，整次落盘失败。这里当「没记过」处理。
                    if not isinstance(b, dict):
                        b = {}
                    if (b.get("x") == int(x) and b.get("y") == int(y)
                            and b.get("w") == int(w) and b.get("h") == int(h)):
                        return True          # 没动 → 别白写一次盘
                    n["bounds"] = {"x": int(x), "y": int(y),
                                   "w": int(w), "h": int(h)}
                    n["updatedAt"] = int(time.time() * 1000)
                    return self._write(notes)
        return False

    def set_flag(self, note_id: str, key: str, value) -> bool:
        """通用开关落盘：`alwaysOnTop`（置顶）/ `isFloating`（是否正在悬浮）。"""
        if not note_id or not key:
            return False
        with self._lock:
            notes = self._read()
            for n in notes:
                if n.get("id") == note_id:
                    if n.get(key) == value:
                        return True
                    n[key] = value
                    n["updatedAt"] = int(time.time() * 1000)
                    return self._write(notes)
        return False

    def list_floating(self) -> list:
        """上次退出时仍在悬浮的便签（含 bounds）→ 供**重启后自动恢复**窗口。"""
        out = []
        for n in self._read():
            if not n.get("isFloating"):
                continue
            out.append({
                "id": n.get("id", ""),
                "src_id": n.get("src_id", ""),
                "content": n.get("content", "") or "",
                "bounds": n.get("bounds"),
                "alwaysOnTop": bool(n.get("alwaysOnTop", False)),
                "bgColor": n.get("bgColor", ""),   # 0916：底色（重启恢复悬浮窗要用）
            })
        return out

    def delete_note(self, note_id: str) -> None:
        """删除指定 ID 的桌面便签。"""
        # 0917d P1：整体加锁 —— 与 `save_note` 并发时，删除若基于旧列表写回，
        # 会把别的线程刚保存的修改一并抹掉。
        with self._lock:
            notes = self._read()
            notes = [n for n in notes if n.get("id") != note_id]
            self._write(notes)

    def clear_all(self) -> bool:
        """清空**全部**桌面便签记录（开发者选项「清除所有数据」用）。

        🔴 调用方必须先关掉所有悬浮窗（`FloatingWindowManager.close_all`）：
           会话销毁时会补一次保存，顺序反了就会把数据写回来。
        """
        with self._lock:
            # 0917：先 `_read()` 刷一遍 `_gsettings` —— 它是**唯一**不经过读就写的路径，
            # 不刷的话 `_write` 会拿一份空缓存把磁盘上的 `settings` 段（字号等）抹掉。
            self._read()
            return self._write([])

    # ---------------- 0917：悬浮便签里「删除便签」的双向一致 ----------------

    def delete_both(self, note_id: str, src_id: str = "") -> bool:
        """悬浮便签里点「删除便签」：删桌面记录 + 通知主界面删掉它对应的便签。

        老板要求：「悬浮便签中执行『删除便签』时，需同时关闭该悬浮便签，并删除主界面
        中对应的便签，保证两处状态一致。」

        两件事都做到才算完成（关窗由调用方 `_delete_note` 通过 `close_self` 触发）：
          ① 桌面便签 JSON 里这条记录（`note_id`）；
          ② 主界面那条（`src_id`）—— 🔴 **不能**在这里直接改主数据文件：主界面内存里
             有一份权威 DATA，从 Python 侧偷偷删掉，它下一次防抖落盘就写回来了
             （改文件 ≠ 改内存）。所以按本项目既定通路走**命令文件**
             （`del:<主界面便签id>`）：主界面 300ms 轮询取走后用自己那套删除逻辑删，
             两边状态才真正一致。
        独立便签（`src_id` 为空）只做 ①。
        返回主界面命令是否写出（`False` = 命令通道不可用，调用方据此提示）。
        """
        try:
            if note_id:
                self.delete_note(note_id)
        except Exception as e:
            _si_log("delete_both: 删桌面便签失败 %r" % (e,))
        if not src_id:
            return True
        ok = _write_pending_command("del:" + str(src_id))
        _si_log("delete_both: 通知主界面删除便签 %s → %s" % (src_id, "ok" if ok else "fail"))
        return ok

    def close_self(self, win) -> bool:
        """让 `FloatingWindowManager` 把 `win` 这个会话收掉（**只关窗口，不动数据**）。"""
        try:
            m = self.manager
            if m is None:
                return False
            return bool(m.close_by_window(win))
        except Exception as e:
            _si_log("close_self 失败: %r" % (e,))
            return False

    def broadcast_font(self, pt) -> int:
        """转发给 `FloatingWindowManager.broadcast_font`（字号全局统一用）。

        🔴 为什么要在 DesktopApi 上再包一层：会话对象只持有 **DesktopApi**（`self.api`），
           根本拿不到 manager —— 它调 `self.api.broadcast_font(...)` 时若这里没有这个方法，
           就会 `AttributeError` 被调用方的 try 吞掉，表现成「字号只改了当前这一条，
           别的便签没动静，且没有任何报错」（本项目已经栽过一次同类隐身 bug）。
        """
        try:
            m = self.manager
            if m is None:
                return 0
            return int(m.broadcast_font(pt))
        except Exception as e:
            _si_log("broadcast_font 失败: %r" % (e,))
            return 0

    def new_float_like_tray(self) -> bool:
        """**与托盘右键「新建桌面便签」完全同一条链路**地新建一条悬浮便签（0917b）。

        悬浮便签顶栏那个 `+` 走这里。0917b 老板报的 bug：`+` 原来直接
        `self.api.new_note()`（不带 `src_id`）→ 造出一条「主界面不认识、没有绑定」的
        孤儿便签 → **两个方向都同步不上**（铁律 4：没绑定的必然不通）。

        🔴 这里不另写一套逻辑，直接复用 `open_desktop_note()` —— 托盘右键与全局
           快捷键用的就是它。于是「`+` / 托盘 / 快捷键」三处共享同一条链路：
               写 `new_float` 命令文件 → 主界面 300ms 轮询取走 →
               JS `__trayNewFloatingNote()`：未分类组首建空便签 + 落盘 +
               `popout_note` 写 `src_id` 绑定 → 双向同步生效（且当前这个窗**原地不动**）。
           连「主界面没在跑时退回独立便签」的兜底行为也自然一致。

        ⚠️ 别把 `_new_note()`（会话内那个「造独立便签」的方法）改掉 ——
           它是 `FloatingWindowManager.new_local()` 的兜底实现，主界面不可用时还得靠它。
        """
        try:
            open_desktop_note()
            return True
        except Exception as e:
            _si_log("new_float_like_tray 失败: %r" % (e,))
            return False

    def hide(self) -> None:
        """仅隐藏弹窗，不退出应用（主程序继续在托盘运行）。"""
        try:
            if self.window is not None:
                self.window.hide()
        except Exception:
            pass

    def toggle_pin(self) -> dict:
        """切换当前便签窗口置顶。"""
        notes = self._read()
        pinned = False
        if notes:
            notes[-1]["pinned"] = not bool(notes[-1].get("pinned", False))
            pinned = notes[-1]["pinned"]
            self._write(notes)
        try:
            if self.window is not None:
                self.window.on_top = pinned
        except Exception:
            pass
        return {"pinned": pinned}


# ---------------------------------------------------------------------------
# 0917d P0-2：敏感凭据加密（Windows DPAPI）
# ---------------------------------------------------------------------------
# 背景：WebDAV 的账号密码原先**明文**写进 便签应用数据.json 的 settings 段。
#       任何人拿到这个文件（备份、网盘同步、U 盘拷贝）就直接拿到云盘密码。
# 方案：用 Windows 自带的 DPAPI（CryptProtectData）加密后落盘。
#       - 不需要用户另设主密码，体验不变；
#       - 密钥由系统按「当前 Windows 用户 + 当前机器」派生，不落在本项目里；
#       - 非 Windows 或 API 不可用时**降级为明文**，绝不因为加密组件挂掉而让用户存不下配置。

_DPAPI_PREFIX = "DPAPI:"


class _DATA_BLOB(ctypes.Structure):
    """Windows DPAPI 用的 DATA_BLOB 结构（CryptProtectData / CryptUnprotectData）。"""

    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_protect(data: bytes) -> bytes:
    """用当前 Windows 用户的 DPAPI 加密字节串；失败返回 b""（不抛异常）。"""
    if os.name != "nt" or not data:
        return b""
    try:
        buf = ctypes.create_string_buffer(data, len(data))
        in_blob = _DATA_BLOB(len(data), buf)
        out_blob = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        )
        if not ok:
            return b""
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return b""


def _dpapi_unprotect(data: bytes) -> bytes:
    """解密 _dpapi_protect 的产物；失败返回 b""（换用户/换机器时会走到这里）。"""
    if os.name != "nt" or not data:
        return b""
    try:
        buf = ctypes.create_string_buffer(data, len(data))
        in_blob = _DATA_BLOB(len(data), buf)
        out_blob = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        )
        if not ok:
            return b""
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return b""


# ---------------------------------------------------------------------------
# 主界面 JS 桥接接口
# ---------------------------------------------------------------------------
class Api:
    """暴露给主界面网页 JS 的桥接接口。"""

    def __init__(self, data_file: str, hotkey: GlobalHotkey) -> None:
        self.data_file = data_file
        self.hotkey = hotkey
        # 0915l：托盘「新建桌面便签」命令文件（主界面每 300ms 轮询来取，取走即删）。
        # 🔴 为什么不用 evaluate_js 通知主界面：winforms 后端里从**非 GUI 线程**调
        #    `evaluate_js` 会直接挂住不返回（0915l 真机实测：连 `1+1` 都回不来，40s 无响应）。
        #    托盘回调跑在 pystray 线程上 → 只能用「文件 + 轮询」这条本项目既定的通路。
        self.cmd_file = data_file + ".cmd"
        # 0917l：关窗/退出时请求主界面「立即落盘」用的标记文件。
        # 🔴 为什么另起一个文件而不是复用 cmd_file：cmd_file 是「取走即删」的
        #    待执行命令，若把 flush 也写进去会把还没被取走的 new_float 冲掉。
        self.flush_file = data_file + ".flush"
        self._show_gate = threading.Lock()   # 0917l：托盘连点时的重入闸门
        self._fallback_combo: str | None = None  # 设置页取消时恢复的快捷键
        self._save_lock = threading.Lock()
        self.quitting = False  # 托盘“退出”置位：允许真正关闭窗口
        # 0917：随「打开/关闭便签」快捷键下线，`_window_visible` 状态机（pywebview 的
        #       window.minimized/hidden 只是创建时的参数值，旧版靠它记录实时可见性）
        #       已整体删除 —— 它唯一的读取点就在被删掉的 `toggle_window()` 里，
        #       留着就是「只写不读」的死状态。隐藏主界面仍有入口：标题栏 × 与托盘菜单。

    # ---------------- 数据 ----------------
    def load_data(self) -> str:
        _log_once("load", "load_data 首次被调用 → JS 桥已真正可用")
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                return f.read()
        except (FileNotFoundError, OSError, UnicodeDecodeError):
            return ""

    def save_data(self, text: str) -> bool:
        _log_once("save", "save_data 首次被调用 → 写盘链路已打通")
        try:
            json.loads(text)  # 校验 JSON 合法性，避免写坏文件
        except Exception:
            return False
        try:
            with self._save_lock:
                # tmp 名加 pid：多实例并发时各写各的 tmp，不会互相截断；
                # os.replace 仍是原子替换，最终"最后写的那次"合法完整
                tmp = self.data_file + ".tmp.%d" % os.getpid()
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(tmp, self.data_file)
            return True
        except OSError as e:
            _si_log("save_data 写盘失败: %r" % (e,))
            return False

    # ---------------- 开机启动 ----------------
    def get_autostart(self) -> bool:
        return autostart_enabled()

    def set_autostart(self, on: bool) -> bool:
        return autostart_set(bool(on))

    # ---------------- 版本信息 ----------------
    def get_app_version(self) -> str:
        """返回应用版本号（设置页展示用）。"""
        return APP_VERSION

    # ---------------- 全局快捷键 ----------------
    def get_hotkey_status(self) -> dict:
        """返回当前活动快捷键及注册状态（供设置页打开时提示）。"""
        active = self.hotkey.active_combo
        return {
            "combo": active or DEFAULT_HOTKEY,
            "active": active is not None,
        }

    def begin_hotkey_session(self) -> dict:
        """设置页打开时调用：记录当前生效快捷键，作为“取消”时的恢复基准。"""
        self._fallback_combo = self.hotkey.active_combo or DEFAULT_HOTKEY
        return {"combo": self._fallback_combo}

    def try_hotkey(self, combo: str) -> dict:
        """
        预览注册（替换当前活动热键）。设置页每次捕获到新组合时调用。
        注册成功返回 ok=True；失败返回 ok=False + reason（红字提示）。
        """
        if not self._fallback_combo:
            self._fallback_combo = self.hotkey.active_combo or DEFAULT_HOTKEY
        ok, reason = self.hotkey.register(combo)
        return {"ok": ok, "reason": reason}

    def apply_hotkey(self, combo: str) -> dict:
        """保存设置时调用：确保 combo 处于注册生效状态，并作为新的取消基准。"""
        if self.hotkey.active_combo == combo:
            self._fallback_combo = combo
            return {"ok": True, "reason": ""}
        ok, reason = self.hotkey.register(combo)
        if ok:
            self._fallback_combo = combo
        return {"ok": ok, "reason": reason}

    def cancel_hotkey(self) -> dict:
        """取消设置：恢复进入设置页前的快捷键。"""
        target = self._fallback_combo or DEFAULT_HOTKEY
        ok, reason = self.hotkey.register(target)
        self._fallback_combo = None
        return {"ok": ok, "reason": reason}

    # ---------------- 剪贴板（图片右键菜单用，0915） ----------------
    # 为什么走 Python 桥而不是 navigator.clipboard：
    #   pywebview 用 file:// 加载本地 HTML → 不是「安全上下文」→ `navigator.clipboard`
    #   在这些环境里可能是 undefined（截图粘贴能走原生 paste 事件，但「写图片」不行）。
    #   Python 侧写 CF_DIB 与悬浮便签共用同一实现 → 两侧复制出的图完全等价。
    def copy_image(self, data_url: str) -> bool:
        """把正文图片（dataURL）放进系统剪贴板 → 可直接粘到微信 / Word / 画图。"""
        try:
            import clip_io
            return clip_io.copy_data_url(data_url)
        except Exception:
            return False

    def paste_clipboard(self):
        """读系统剪贴板：图片 → {kind:image,dataUrl,w,h}；文本 → {kind:text,text}；空 → None。"""
        try:
            import clip_io
            return clip_io.paste_payload()
        except Exception:
            return None

    # ---------------- 窗口（隐藏到托盘 / 恢复） ----------------
    def _main_window(self):
        return webview.windows[0]

    def move_window(self, dx: int, dy: int) -> bool:
        """顶栏自定义拖动：按增量移动主窗口（easy_drag=False 下 app-region 失效）。"""
        try:
            w = self._main_window()
            w.move(w.x + dx, w.y + dy)
            return True
        except Exception:
            return False

    def show_main_window(self) -> None:
        """托盘“显示主界面”：恢复并置顶。

        0917l 修复（老板报「托盘反复开/关 3~4 次后主界面卡死」）：
        原实现在**托盘线程**（pystray）里连做
            w.show(); w.restore(); w.on_top = True; w.on_top = False
        其中 `w.on_top` 是 pywebview 的**裸属性** —— winforms 后端 `set_on_top()`
        直接 `i.TopMost = on_top`，**没有 Invoke 编组到 GUI 线程**
        （见 pywebview/platforms/winforms.py 的 `def set_on_top`）。
        跨线程写 WinForms 属性会与 GUI 线程抢窗口状态；`TopMost` 还会同步给窗口
        所在线程派发 WM_WINDOWPOS* 消息，调用方要等它处理完 → 反复开关时容易
        把消息循环拖死。
        → 现在只保留 `show()` / `restore()`（pywebview 内部已用 Invoke 编组，安全），
          「置顶一下」改用**纯 Win32** `_bring_main_window_front()`
          （SetWindowPos/SetForegroundWindow 是线程安全的，且不碰 WinForms 状态）。
        另加**重入闸门**：连续双击托盘不会叠第二次阻塞式 Invoke。
        """
        if not self._show_gate.acquire(blocking=False):
            # 上一次 show 还在进行（托盘被连点）→ 直接忽略，别再叠一次
            return
        try:
            w = self._main_window()
            w.show()
            w.restore()
            _bring_main_window_front()
        except Exception as e:
            print("[api] show_main_window error:", e)
        finally:
            self._show_gate.release()

    def popout_note(self, title: str, content: str, note_id: str = "") -> bool:
        """主界面「弹出悬浮便签」：把当前便签标题 + 正文送到桌面悬浮便签窗口。

        返回 True = 悬浮窗确实弹出来了；False = 没弹出来（前端据此提示，不再假报成功）。
        `note_id` = 主界面便签 id：0915 起会写进桌面便签的 `src_id`，
        让两边**互为镜像实时同步**（不再是「一份拷贝，改动不回写」）。

        0915c Stage2：改走 FloatingWindowManager —— **每条便签各自一个悬浮窗**，
        同一 noteId 重复调用≠新建窗口，只更新内容并提到前台（deiconify + lift）。
        """
        try:
            if _float_manager is None:
                _si_log("popout_note: _float_manager 尚未初始化 → False")
                return False
            ok = bool(_float_manager.open(title or "", content or "", note_id or ""))
            # 0915f 取证日志：记下「传进来的 id」和「返回时到底建没建上绑定」。
            # 同步不通的根因基本都在这两个数上（id 为空 / 绑定没写进盘）。
            try:
                did = _float_manager.api.find_by_src(note_id or "")
            except Exception:
                did = ""
            _si_log("popout_note note_id=%r ok=%s bound=%r" % (note_id, ok, did))
            return ok
        except Exception as e:
            _si_log("popout_note 异常: %r" % (e,))
            print("[api] popout_note error:", e)
            return False

    def close_note_window(self, note_id: str) -> bool:
        """主界面**删除便签**时调用：关掉它对应的悬浮窗。

        注意：这里**不动主界面数据**（数据由前端自己删），只负责把浮窗收掉、
        并清掉桌面便签 JSON 里那条已经没有主人的记录（留着只会让 list_bound 每轮白扫）。
        """
        try:
            if _float_manager is None or not note_id:
                return False
            closed = _float_manager.close(note_id)     # 内部已等待 Tk 收尾，避免删了又被写回
            try:
                did = _float_manager.api.find_by_src(note_id)
                if did:
                    _float_manager.api.delete_note(did)
            except Exception:
                pass
            return bool(closed)
        except Exception as e:
            print("[api] close_note_window error:", e)
            return False

    def floating_note_ids(self) -> list:
        """当前正在悬浮的便签 id 列表（主界面可据此打「悬浮中」标记）。"""
        try:
            return _float_manager.floating_ids() if _float_manager else []
        except Exception:
            return []

    # ---------------- 双向同步的 JS 入口（0915g 补，0915 的头号漏网真因）----------------
    # 🔴 pywebview 的 `js_api=api` 暴露的是 **本类（Api）实例**，只有「这个对象上真实
    #    存在的 public 方法」才会挂给 JS。`list_bound` / `push_from_main` 0915 只写在
    #    `DesktopApi`（桌面便签数据）里，JS 端那两句
    #        if (typeof window.pywebview.api.list_bound  !== "function") return;
    #        if (typeof window.pywebview.api.push_from_main !== "function") return;
    #    便**每轮静默 return** —— 两个方向一次都没跑过。
    #    而「弹出悬浮便签」的 popout_note 在本类上 → 绑定照常建立、窗口照常弹出，
    #    看起来"功能正常"，所以文件级/桥级测试全绿也照不出这个问题。
    #    **教训：但凡给 JS 加桥方法，必须回到「js_api 挂的那个类」上做一次存在性核对。**

    def list_bound(self) -> dict:
        """`{主界面便签id: 悬浮便签正文}` —— 主界面每 300ms 拉一次（浮 → 主）。"""
        try:
            if _float_manager is None:
                return {}
            return _float_manager.api.list_bound() or {}
        except Exception as e:
            print("[api] list_bound error:", e)
            return {}

    def push_from_main(self, mapping) -> bool:
        """主界面改了正文 → 推给绑定的悬浮便签（主 → 浮）。`mapping={便签id: 正文}`。"""
        try:
            if _float_manager is None or not isinstance(mapping, dict):
                return False
            return bool(_float_manager.api.push_from_main(mapping))
        except Exception as e:
            print("[api] push_from_main error:", e)
            return False

    # ---------------- 托盘命令通道（0915l）----------------
    # 托盘右键「新建桌面便签」的完整链路：
    #   托盘线程写命令文件 → 主界面 300ms 轮询 take_pending_command() 取走 →
    #   JS 执行 __trayNewFloatingNote()（未分类建空便签 + popout_note 写 src_id 绑定）。
    # 这样托盘新建的便签**天然与主界面双向同步**，且**不弹主界面**。
    # 🔴 为什么绕这一圈：见 `Api.__init__` 里 cmd_file 的注释（evaluate_js 跨线程挂死）。

    def take_pending_command(self) -> str:
        """主界面轮询取托盘命令：**取走即删**（保证同一条命令只执行一次）。"""
        try:
            with self._save_lock:
                path = self.cmd_file
                if not path or not os.path.exists(path):
                    return ""
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        cmd = (f.read() or "").strip()
                except (OSError, UnicodeDecodeError):
                    cmd = ""
                try:
                    os.remove(path)
                except OSError:
                    pass
            if cmd:
                _TRAY_CMD_EVENT.set()     # 通知托盘看门狗：命令已被取走，不必兜底
                _si_log("take_pending_command: 主界面取走命令 %r" % cmd)
            return cmd
        except Exception as e:
            print("[api] take_pending_command error:", e)
            return ""

    # ---------------- 0917l：关窗/退出的「立即落盘」请求通道 ----------------
    # 替代原先 `on_closing` / `quit_app` 里的跨线程 `evaluate_js`（会永久阻塞，
    # 见上面 `Api.__init__` 的注释与铁律⑨）。语义与托盘命令同一条通路：
    #   Python 写标记文件 → 主界面 300ms 轮询 `flush_pending()` 取到 →
    #   真正落盘 → `flush_done()` 删标记。
    # 🔴 为什么「删标记」要单独一步：`quit_app` 靠**标记文件消失**来确认
    #    「JS 已经存完了」，若取走即删就变成「还没存就放行退出」→ 丢数据。

    def flush_pending(self) -> bool:
        """主界面轮询：是否有「立即落盘」请求？（只读，不删标记）"""
        try:
            return bool(self.flush_file) and os.path.isfile(self.flush_file)
        except OSError as e:
            _si_log("flush_pending 失败: %r" % (e,))
            return False

    def flush_done(self) -> bool:
        """主界面落盘完成后调用：删掉标记（`quit_app` 据此放行）。"""
        try:
            with self._save_lock:
                if os.path.isfile(self.flush_file):
                    os.remove(self.flush_file)
            return True
        except OSError as e:
            _si_log("flush_done 失败: %r" % (e,))
            return False

    # ---------------- 0917：开发者选项「清除所有数据」 ----------------

    def clear_all_data(self) -> dict:
        """清空主数据 + 桌面便签数据（开发者选项里的「清除所有数据」）。

        老板要求「完整实现其清除逻辑」。范围与顺序（前端 `clearAllData()` 与之对齐）：
          ① 先关掉**所有悬浮窗**（绑定的 + 独立的）—— 会话销毁时会补一次保存
             （`DesktopNoteWindow._cleanup()` 里的 `_save_now` / `_save_bounds`），
             顺序反了就会把刚清掉的数据又写回来；
          ② 清空桌面便签文件（`notes` → []）；
          ③ 清空主数据文件的**业务数据**（`groups` / `ungrouped` → []），
             但**保留 settings** —— 快捷键 / 开机启动 / 默认新建位置 / WebDAV 配置
             都在里面：清掉会连热键与开机启动一起毁掉，而它们与「便签数据」不是一回事；
          ④ 清掉可能残留的命令文件，免得下次启动执行一条过期命令。

        返回 `{"ok": bool, "reason": str}`（前端据此提示，异常不抛给 JS）。
        """
        try:
            closed = 0
            if _float_manager is not None:
                closed = _float_manager.close_all()
                try:
                    _float_manager.api.clear_all()
                except Exception as e:
                    _si_log("clear_all_data: 清空桌面便签文件失败 %r" % (e,))

            # 保留本机设置（读不到就当空）
            settings: dict = {}
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                if isinstance(obj, dict) and isinstance(obj.get("settings"), dict):
                    settings = obj["settings"]
            except (FileNotFoundError, OSError, ValueError):
                settings = {}

            empty = {"groups": [], "ungrouped": [], "settings": settings}
            with self._save_lock:
                tmp = self.data_file + ".tmp.%d" % os.getpid()
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(empty, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.data_file)

            _clear_pending_command()
            _si_log("clear_all_data: 已关闭 %d 个悬浮窗，主数据与桌面便签数据已清空" % closed)
            return {"ok": True}
        except Exception as e:
            _si_log("clear_all_data 失败: %r" % (e,))
            return {"ok": False, "reason": str(e)}

    # ---------------- 0917d P0-2：敏感凭据加密存储 ----------------

    def encrypt_secret(self, plain: str) -> str:
        """加密敏感字符串（WebDAV 密码等），落盘前调用。

        返回 `"DPAPI:" + base64`；加密不可用时**原样返回入参**（保功能优先）。
        空串 → 空串。
        ⚠️ DPAPI 绑定「当前 Windows 用户 + 当前机器」：换用户登录或重装系统后
           旧密文解不开，此时 decrypt_secret 返回空串，前端提示重输即可。
        """
        s = plain if isinstance(plain, str) else ""
        if not s:
            return ""
        try:
            raw = _dpapi_protect(s.encode("utf-8"))
            if raw:
                return _DPAPI_PREFIX + base64.b64encode(raw).decode("ascii")
            _si_log("encrypt_secret: DPAPI 不可用，退回明文存储")
        except Exception as e:
            _si_log("encrypt_secret 失败，退回明文存储: %r" % (e,))
        return s

    def decrypt_secret(self, stored: str) -> str:
        """还原 encrypt_secret 存下的值（供将来真正的云同步使用）。

        - 空串 → 空串
        - 非 `DPAPI:` 开头 → 视为**旧版本明文**，原样返回（老配置仍能读，向后兼容）
        - `DPAPI:` 开头但解不开（换机器 / 换用户）→ 返回空串（前端提示用户重输）
        """
        s = stored if isinstance(stored, str) else ""
        if not s:
            return ""
        if not s.startswith(_DPAPI_PREFIX):
            return s
        try:
            raw = base64.b64decode(s[len(_DPAPI_PREFIX):])
            out = _dpapi_unprotect(raw)
            if out:
                return out.decode("utf-8", errors="replace")
            _si_log("decrypt_secret: 解不开（可能换了 Windows 用户或重装系统），返回空串")
        except Exception as e:
            _si_log("decrypt_secret 失败: %r" % (e,))
        return ""

    # ---------------- 0917e WebDAV 云同步（备份 / 恢复 / 测试连接） ----------------
    # 设计：这三个是**同步**方法，校验配置后立即起 daemon 线程跑网络 I/O 并返回，
    #       网络结果通过命令文件 `webdav:ok/err/restored` 通知前端（复用托盘那条
    #       300ms 轮询通道，绝不跨线程 evaluate_js —— 见铁律②）。
    # 远端固定文件名 `便签应用数据.json`（与本地同名），目录取自 settings.webdav.dir。
    def _webdav_cfg(self) -> dict:
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                obj = json.load(f)
            w = (obj.get("settings") or {}).get("webdav") or {}
        except (FileNotFoundError, OSError, ValueError):
            return {}
        return w if isinstance(w, dict) else {}

    def _os_errmsg(self, e: Exception) -> str:
        """把常见文件 I/O 异常转成中文可读提示（权限不足 / 磁盘满等）。"""
        if isinstance(e, OSError):
            if e.errno in (13, 1):   # EACCES / EPERM
                return "权限不足"
            if e.errno == 28:        # ENOSPC
                return "磁盘空间不足"
        return (getattr(e, "strerror", None) or type(e).__name__)

    def _webdav_run(self, op: str) -> None:
        """后台线程：真正跑网络 I/O，结果写命令文件通知前端。"""
        try:
            w = self._webdav_cfg()
            pwd = self.decrypt_secret(w.get("pass") or "")
            if w.get("pass") and not pwd:
                _write_pending_command(
                    "webdav:err:密码解密失败（可能换了 Windows 用户/重装系统，请在设置里重新保存 WebDAV 配置）")
                return
            remote_dir = w.get("dir") or "/速记便签"
            remote = remote_dir.rstrip("/") + "/" + DATA_FILE_NAME
            cli = WebDavClient(w.get("url") or "", w.get("user") or "", pwd)

            if op == "test":
                cli.ensure_dir(remote_dir)
                _write_pending_command("webdav:ok:连接成功")
            elif op == "backup":
                text = self.load_data()
                if not text:
                    _write_pending_command("webdav:err:本地数据为空，无可备份内容")
                    return
                cli.ensure_dir(remote_dir)
                cli.upload(remote, text)
                _write_pending_command("webdav:ok:已备份到网盘（%d 字节）" % len(text.encode("utf-8")))
            elif op == "restore":
                text = cli.download(remote)
                try:
                    json.loads(text)
                except Exception:
                    _write_pending_command("webdav:err:远端文件不是合法 JSON，已取消恢复")
                    return
                # 🔴 恢复会覆盖本地数据：先备份当前文件到保险目录
                backup_dir = os.path.join(app_dir(), "backups")
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                    if os.path.exists(self.data_file):
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        shutil.copy2(self.data_file,
                                     os.path.join(backup_dir, "便签应用数据_恢复前备份_%s.json" % ts))
                except Exception as e:
                    _si_log("webdav_restore: 本地备份失败(继续恢复): %r" % (e,))
                if not self.save_data(text):
                    _write_pending_command("webdav:err:写入本地失败")
                    return
                _write_pending_command("webdav:restored:已从网盘恢复（本地旧数据已备份到 backups 目录）")
            else:
                _write_pending_command("webdav:err:未知操作 %s" % op)
        except Exception as e:
            _si_log("webdav_%s 失败: %r" % (op, e))
            _write_pending_command("webdav:err:%s" % (e,))

    def _webdav_start(self, op: str) -> dict:
        """校验配置后起线程；配置不全则同步返回错误（不启动线程）。"""
        w = self._webdav_cfg()
        if not (w.get("url") and w.get("user")):
            return {"ok": False, "reason": "未配置服务器地址与账号（请先在面板填写）"}
        threading.Thread(target=self._webdav_run, args=(op,), daemon=True).start()
        return {"ok": True, "started": True}

    def webdav_test(self) -> dict:
        """测试 WebDAV 连接（建目录探测）。结果经命令文件 webdav:ok/err 回传。"""
        return self._webdav_start("test")

    def webdav_backup(self) -> dict:
        """把本地便签数据上传到 WebDAV。结果经 webdav:ok/err 回传。"""
        return self._webdav_start("backup")

    def webdav_restore(self) -> dict:
        """从 WebDAV 下载并覆盖本地（覆盖前先备份到 backups/）。结果经
        webdav:restored/err 回传，前端收到 restored 后重建数据。"""
        return self._webdav_start("restore")

    # ---------------- 0917k 本地目录导出 / 导入 ----------------
    # 设计同 WebDAV：Api 方法是**同步**的，立即起 daemon 线程跑（文件夹对话框 +
    # 文件 I/O），结果经命令文件 webdav:ok/err/cancel/restored 通知前端；
    # 文件夹对话框用 ctypes SHBrowseForFolder（原生、线程安全，不依赖 Tk 线程）。
    # 导出：把本地「便签应用数据.json」写入用户选定目录（含 settings，即「配置 + 数据」）。
    # 导入：读取选定目录下同名文件，校验 JSON 合法后覆盖本地（覆盖前先备份到 backups/，
    #       与 webdav_restore 同一套保险逻辑）。
    def _pick_folder(self, title: str):
        """弹出系统文件夹选择对话框，返回选定目录路径或 None（取消 / 出错）。

        在任意线程都可安全调用：内部 CoInitializeEx(STA) 后 SHBrowseForFolder，结束时
        CoUninitialize。仅 Windows 有效（本软件只跑 Windows）。
        """
        try:
            ole32 = ctypes.windll.ole32
            shell32 = ctypes.windll.shell32
        except Exception as e:
            _si_log("_pick_folder 无法加载 shell32: %r" % (e,))
            return None
        try:
            ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
        except Exception:
            pass  # 已初始化则忽略（RPC_E_CHANGED_MODE 等）
        try:
            class _BROWSEINFO(ctypes.Structure):
                _fields_ = [
                    ("hwndOwner", ctypes.wintypes.HWND),
                    ("pidlRoot", ctypes.c_void_p),
                    ("pszDisplayName", ctypes.c_wchar_p),
                    ("lpszTitle", ctypes.c_wchar_p),
                    ("ulFlags", ctypes.c_uint),
                    ("lpfn", ctypes.c_void_p),
                    ("lParam", ctypes.c_void_p),
                    ("iImage", ctypes.c_int),
                ]
            display = ctypes.create_unicode_buffer(260)
            bi = _BROWSEINFO()
            bi.hwndOwner = None
            bi.pidlRoot = None
            bi.pszDisplayName = display
            bi.lpszTitle = title or "选择目录"
            bi.ulFlags = 0x00000001 | 0x00000040  # BIF_RETURNONLYFSDIRS | BIF_NEWDIALOG_STYLE
            pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
            if not pidl:
                return None
            path = ctypes.create_unicode_buffer(260)
            shell32.SHGetPathFromIDListW(pidl, path)
            try:
                ole32.CoTaskMemFree(pidl)
            except Exception:
                pass
            return path.value or None
        except Exception as e:
            _si_log("_pick_folder 失败: %r" % (e,))
            return None
        finally:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass

    def webdav_export_local(self) -> dict:
        """弹出文件夹选择对话框，把本地便签数据导出到用户指定目录。结果经命令文件回传。"""
        threading.Thread(target=self._local_export_run, daemon=True).start()
        return {"ok": True, "started": True}

    def webdav_import_local(self) -> dict:
        """弹出文件夹选择对话框，从用户指定目录导入便签数据。结果经命令文件回传。"""
        threading.Thread(target=self._local_import_run, daemon=True).start()
        return {"ok": True, "started": True}

    def _local_export_run(self) -> None:
        try:
            d = self._pick_folder("选择导出目录（便签数据将保存为 便签应用数据.json）")
            if not d:
                _write_pending_command("webdav:cancel:已取消导出")
                return
            text = self.load_data()
            if not text:
                _write_pending_command("webdav:err:本地数据为空，无可导出内容")
                return
            dst = os.path.join(d, DATA_FILE_NAME)
            try:
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError as e:
                _write_pending_command("webdav:err:写入失败（%s）：%s" % (self._os_errmsg(e), e))
                return
            _write_pending_command("webdav:ok:已导出到 %s（便签应用数据.json）" % d)
        except Exception as e:
            _si_log("_local_export_run 失败: %r" % (e,))
            _write_pending_command("webdav:err:%s" % (e,))

    def _local_import_run(self) -> None:
        try:
            d = self._pick_folder("选择包含 便签应用数据.json 的目录")
            if not d:
                _write_pending_command("webdav:cancel:已取消导入")
                return
            src = os.path.join(d, DATA_FILE_NAME)
            if not os.path.isfile(src):
                _write_pending_command("webdav:err:该目录下没有找到 便签应用数据.json")
                return
            try:
                with open(src, "r", encoding="utf-8") as f:
                    text = f.read()
            except OSError as e:
                _write_pending_command("webdav:err:读取失败（%s）：%s" % (self._os_errmsg(e), e))
                return
            try:
                json.loads(text)
            except Exception:
                _write_pending_command("webdav:err:文件不是合法 JSON，已取消导入")
                return
            # 🔴 覆盖本地前先备份当前数据到保险目录（与 webdav_restore 同逻辑）
            backup_dir = os.path.join(app_dir(), "backups")
            try:
                os.makedirs(backup_dir, exist_ok=True)
                if os.path.exists(self.data_file):
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    shutil.copy2(self.data_file,
                                 os.path.join(backup_dir, "便签应用数据_导入前备份_%s.json" % ts))
            except Exception as e:
                _si_log("_local_import_run: 本地备份失败(继续导入): %r" % (e,))
            if not self.save_data(text):
                _write_pending_command("webdav:err:写入本地失败")
                return
            _write_pending_command("webdav:restored:已从本地目录导入（本地旧数据已备份到 backups 目录）")
        except Exception as e:
            _si_log("_local_import_run 失败: %r" % (e,))
            _write_pending_command("webdav:err:%s" % (e,))

    def quit_app(self) -> None:
        """托盘“退出”：先落盘，再停托盘/热键/桌面便签，最后销毁窗口结束进程。"""
        if self.quitting:
            return
        self.quitting = True
        # 0917l：这里原来是跨线程 `self._main_window().evaluate_js(...)`。
        # 🔴 非 GUI 线程调 evaluate_js 会永久阻塞在 `semaphore.acquire()`
        #    （铁律⑨）→ 连托盘「退出」都会点不动（quit_app 永远走不到 destroy）。
        #    改走「标记文件 + 300ms 轮询」：写标记 → 等主界面存完并把标记删掉
        #    （`flush_done()`），最多等 1.5s；无论成功失败都继续收尾，绝不卡死。
        #    ⚠️ 只读态 / 桥没跑起来时没人来删标记 → 会等满上限，所以上限不能太长。
        try:
            _request_flush(self.flush_file)
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                if not os.path.isfile(self.flush_file):
                    break
                time.sleep(0.05)
        except Exception as e:
            _si_log("quit_app flush 等待失败(继续退出): %r" % (e,))
        try:
            self.hotkey.stop(wait=False)
        except Exception:
            pass
        try:
            stop_tray()
        except Exception:
            pass
        try:
            if _float_manager is not None:
                _float_manager.shutdown()   # 逐个销毁悬浮会话，最后停唯一的 Tk host
        except Exception:
            pass
        for w in list(webview.windows):
            try:
                w.destroy()
            except Exception:
                pass

    # ---------------- 自定义标题栏窗口控制 ----------------
    def minimize_window(self) -> None:
        """自定义标题栏“最小化”。"""
        try:
            self._main_window().minimize()
        except Exception as e:
            print("[api] minimize_window error:", e)

    def maximize_toggle(self) -> None:
        """自定义标题栏“最大化 / 还原”。"""
        try:
            w = self._main_window()
            w.maximized = not w.maximized
        except Exception as e:
            print("[api] maximize_toggle error:", e)

    def close_window(self) -> None:
        """自定义标题栏“关闭”：走原 closing 逻辑，隐藏到托盘不退出。"""
        try:
            self._main_window().destroy()
        except Exception as e:
            print("[api] close_window error:", e)


# ---------------------------------------------------------------------------
# 全局状态（供托盘回调使用）
# ---------------------------------------------------------------------------
_tray: Tray | None = None
# 0915c Stage2：**多悬浮窗管理器**（内部持唯一 FloatHost + per-note Toplevel 会话）
_float_manager: FloatingWindowManager | None = None


def stop_tray() -> None:
    global _tray
    if _tray is not None:
        _tray.stop()
        _tray = None


# ---- 0915l：托盘「新建桌面便签」命令通道（文件 + 轮询，**绝不 evaluate_js**）----
_TRAY_CMD_EVENT = threading.Event()   # 命令被主界面取走时置位（看门狗据此判断要不要兜底）
_cmd_file_path: str = ""              # 由 main() 拿 api.cmd_file 注册进来
_TRAY_FALLBACK_S = 3.0                # 看门狗等多久还没被取走就兜底（主界面 300ms 轮询，正常远快于此）


def _cmd_file() -> str:
    if _cmd_file_path:
        return _cmd_file_path
    return os.path.join(app_dir(), DATA_FILE_NAME + ".cmd")


def _write_pending_command(cmd: str) -> bool:
    """原子写命令文件（tmp + os.replace），主界面轮询取走。"""
    path = _cmd_file()
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(cmd)
        os.replace(tmp, path)
        return True
    except OSError as e:
        _si_log("write_pending_command 失败: %r" % (e,))
        return False


def _clear_pending_command() -> None:
    try:
        os.remove(_cmd_file())
    except OSError:
        pass


def _request_flush(path: str) -> bool:
    """请求主界面「立即落盘」：原子写一个标记文件，主界面 300ms 轮询取走。

    0917l：**替代**关窗/退出路径上的跨线程 `evaluate_js`。
    🔴 为什么必须换掉：winforms 后端里从非 GUI 线程调 `evaluate_js` 会永久阻塞在
       `edgechromium.py` 的 `semaphore.acquire()`（本项目 0915l 真机实测：连 `1+1`
       都回不来；0917l 复现 harness 里线程数随开关次数线性上涨即是此故）。关窗时
       窗口刚 hide，回调更难回来 → 每次关窗漏一个死线程，反复开关后消息循环被拖垮
       （老板 0917l 报「托盘反复开/关 3~4 次后主界面卡死」）。
    这里只做一次极小的文件写：**不开线程、不碰 evaluate_js**，任何线程调用都安全。
    """
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("1")
        os.replace(tmp, path)
        return True
    except OSError as e:
        _si_log("request_flush 失败: %r" % (e,))
        return False


def _tray_fallback_local(why: str) -> None:
    """主界面用不上时退回旧的「独立便签」：不同步，但点了至少得有反应。"""
    try:
        if _float_manager is not None:
            _float_manager.new_local()
            _si_log("tray_new_float: 兜底独立便签（%s，不与主界面同步）" % why)
    except Exception as e:
        print("[tray] fallback error:", e)


def _tray_cmd_watchdog(wait_s: float) -> None:
    """看门狗：等主界面把命令取走（正常 ≤300ms）。

    超时说明主界面没在跑（只读态 / 桥未就绪 / 程序刚起）→ 兜底弹独立便签，
    免得老板点了托盘什么都不发生。
    🔴 兜底前必须清掉残留命令：否则主界面稍后恢复时会再建一条 → 点一次变两个窗。
    """
    if _TRAY_CMD_EVENT.wait(wait_s):
        _si_log("tray_new_float: 主界面已取走命令（正在未分类建便签 + 弹悬浮窗）")
        return
    _clear_pending_command()
    _si_log("tray_new_float: %.1fs 内主界面未取走命令 → 兜底独立便签" % wait_s)
    _tray_fallback_local("主界面未响应")


def open_desktop_note() -> None:
    """「新建悬浮便签」的唯一后端入口 —— **托盘右键**与**全局快捷键**共用。

    在**主界面「未分类」组**建一条空便签并弹出它的悬浮窗。

    0915l（老板要求）：这样新建的便签必须和主界面**双向同步**，且**不弹主界面**。
    原先直接调 `DesktopApi.new_local()` 只能造一条「主界面不认识、没有 src_id」的
    独立便签 → 无论怎么改都同步不上（0915f 老板实测：桌面便签 JSON 里 70 条全无 src_id）。

    0917（老板要求）：工具栏那个「新建悬浮便签」按钮已删除；全局快捷键的语义也从
    「打开/关闭便签」改成了「新建悬浮便签」→ 与托盘**共用本函数**（见 `_hotkey_cb`）。

    链路：
        调用方（托盘线程 / 热键线程）写命令文件 → 主界面 300ms 轮询
        `take_pending_command()` 取走 → JS `__trayNewFloatingNote()`：
        未分类组首建空便签 → 立即落盘 → `popout_note` 写 src_id 绑定
        → 双向同步生效（主界面窗口不弹出）。

    🔴 为什么不用 evaluate_js 直接驱动 JS：winforms 后端里从**非 GUI 线程**调用
       `evaluate_js` 会直接挂住不返回（0915l 真机实测：连 `1+1` 都回不来）。
       托盘回调跑在 pystray 线程、热键回调跑在 hotkey 线程 → 都只能用
       「文件 + 轮询」这条本项目既定的通路。
    """
    _TRAY_CMD_EVENT.clear()
    if not _write_pending_command("new_float"):
        _tray_fallback_local("命令文件写入失败")
        return
    threading.Thread(target=_tray_cmd_watchdog, args=(_TRAY_FALLBACK_S,), daemon=True).start()


# ---------------------------------------------------------------------------
# 单实例保护
# ---------------------------------------------------------------------------
# 多开时每个进程各持一份内存 DATA，谁落盘晚谁覆盖 —— 表现为「在 A 窗口编辑的
# 内容被 B 窗口写回的旧数据冲掉」，看起来就是“数据没保存”。
_SINGLE_INSTANCE_MUTEX = None  # 必须持有引用：句柄被回收则锁失效


def _bring_main_window_front() -> None:
    """把主窗口唤起/置前 —— **纯 Win32，任何线程都能安全调**（0917l）。

    为什么不用 pywebview 的 `window.on_top`：winforms 后端把它实现成裸的
    `Form.TopMost = x`（没有 Invoke 到 GUI 线程）→ 从托盘线程写就是跨线程写
    WinForms 属性（0917l 卡死 bug 的成因之一）。
    这里只用 user32，不碰 pywebview / WinForms 的任何状态。
    """
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR]
        user32.FindWindowW.restype = ctypes.wintypes.HWND
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if not hwnd:
            return
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE：隐藏/最小化都能唤回
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _activate_existing_window() -> None:
    """把已在运行的主窗口唤到前台（第二个实例启动时用）。"""
    _bring_main_window_front()


def _si_log(msg: str) -> None:
    """单实例锁的诊断日志（写到 exe 同目录，定位打包态到底发生了什么）。"""
    try:
        import time
        with open(os.path.join(app_dir(), "_si_debug.log"), "a", encoding="utf-8") as f:
            f.write("%s.%03d pid=%d %s\n" % (
                time.strftime("%H:%M:%S"), int((time.time() % 1) * 1000), os.getpid(), msg))
    except Exception:
        pass


_logged_once: dict[str, bool] = {}


def _log_once(key: str, msg: str) -> None:
    """同一 key 只记一次，避免每次保存都写盘、拖慢交互。"""
    if _logged_once.get(key):
        return
    _logged_once[key] = True
    _si_log(msg)


def _try_acquire_single_instance() -> bool:
    """抢到单实例锁返回 True；已有实例在跑则唤起它并返回 False。"""
    global _SINGLE_INSTANCE_MUTEX
    _si_log("enter _try_acquire_single_instance")
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = wintypes.DWORD
        name = "Local\\SuJiBianQian_SingleInstance_v1"
        handle = kernel32.CreateMutexW(None, False, name)
        err = kernel32.GetLastError()   # 显式调，比 ctypes.get_last_error() 在打包态更稳
        _si_log("CreateMutexW handle=%s GetLastError=%d" % (handle, err))
        if not handle:
            _si_log("no handle → 放行")
            return True
        if err == 183:                   # ERROR_ALREADY_EXISTS
            _si_log("ALREADY_EXISTS → 唤起已有窗口 + 退出")
            _activate_existing_window()
            return False
        _SINGLE_INSTANCE_MUTEX = handle
        _si_log("acquired → 继续")
        return True
    except Exception as e:
        _si_log("exception %r → 放行" % (e,))
        return True


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> None:
    global _tray, _cmd_file_path
    _si_log("main() entered")
    # 已有实例在跑：唤起它的窗口后直接退出，避免两份内存数据互相覆盖
    if not _try_acquire_single_instance():
        _si_log("已有实例 → 本进程退出")
        return
    _si_log("单实例锁已获取，继续启动")
    # 0917n：是否由「开机自启」拉起（自启命令带 --startup 参数）
    startup_mode = "--startup" in sys.argv
    _si_log("startup_mode=%s" % startup_mode)
    # 0917n：已勾选开机自启 → 重写注册表命令带 --startup（存量用户升级后首次启动自动修正，
    #   否则旧命令无参数、自启仍会弹主窗，违背「仅常驻托盘、不弹主窗」需求）
    if autostart_enabled():
        try:
            autostart_set(True)
        except Exception:
            pass
    data_file = os.path.join(app_dir(), DATA_FILE_NAME)

    def _hotkey_cb() -> None:
        """全局快捷键命中（跑在 hotkey 线程）→ **新建一条悬浮便签**。

        0917（老板要求）：快捷键的语义从「打开/关闭便签」改成「新建悬浮便签」，
        功能逻辑随之改走「未分类建空便签 + 弹悬浮窗」那条路。

        🔴 为什么不在这里跨线程驱动前端 JS：hotkey 回调跑在 hotkey 线程，
           winforms 后端从**非 GUI 线程**执行 JS 会直接挂住不返回
           （0915l 真机实测：连 `1+1` 都回不来）。所以这里直接复用托盘那条
           已经验证过的「命令文件 + 轮询」通道（`open_desktop_note`）：
               写 `new_float` → 主界面 300ms 轮询取走 → `__trayNewFloatingNote()`
               → 未分类建空便签 + popout_note 写 src_id 绑定（不弹主界面窗口）。
           看门狗兜底：主界面没在跑（启动中 / 只读态）时退回独立便签，
           至少保证「按了有反应」。
        """
        try:
            open_desktop_note()
        except Exception as e:
            _si_log("hotkey_cb 新建悬浮便签失败: %r" % (e,))

    hotkey = GlobalHotkey(_hotkey_cb)
    api = Api(data_file, hotkey)
    # 0915l：把托盘命令文件路径注册给模块级（托盘回调写命令用），与主数据同目录
    _cmd_file_path = api.cmd_file

    # 启动时按数据文件里的设置注册快捷键（失败不阻塞启动，设置页会红字提示）
    initial_combo = DEFAULT_HOTKEY
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        saved = raw.get("settings", {}).get("hotkey", "")
        if saved:
            initial_combo = saved
    except (FileNotFoundError, OSError, ValueError):
        pass
    hotkey.register(initial_combo)

    html = resource_path("便签应用.html")
    window = webview.create_window(
        APP_TITLE,
        html,
        js_api=api,
        width=980,
        height=660,
        min_size=(860, 560),
        background_color="#f2f4f7",
        frameless=True,
        hidden=startup_mode,  # 0917n：开机自启(--startup)时不弹主窗，仅常驻托盘 + 恢复悬浮便签；普通双击仍弹主窗
        easy_drag=False,  # 修复：frameless 默认整窗可拖（任意位置按住左键拖动窗口），此处禁用，仅保留顶栏 .tb-drag 拖动
    )

    def on_closing() -> bool:
        """主窗口 [X]：立即隐藏到托盘（取消关闭，不退出）。

        0917l 修复（老板报「托盘反复开/关 3~4 次后主界面卡死」）：
        原实现在 GUI 线程里起一个后台线程调 `window.evaluate_js("__flushBeforeClose")`
        去触发落盘 —— 那正是本项目铁律⑨禁止的「非 GUI 线程 evaluate_js」；
        而此刻窗口**刚 hide**，WebView2 的脚本回调更容易不来 → 该线程**永久卡死**在
        `edgechromium.py:160 semaphore.acquire()`。0917l 复现 harness 实测：
        线程数随开关次数线性上涨（20 轮 → 泄漏 90 个死线程，全是这个位置），
        反复开关后 GUI 消息循环被拖垮，表现就是「卡死无响应」。
        → 改成写「落盘请求」标记文件，由主界面 300ms 轮询取走执行
          （与托盘命令同一条通路，见 `_request_flush`）。
        托盘“退出”置位 quitting 后返回 True 放行真正关闭。"""
        if api.quitting:
            return True
        try:
            window.hide()  # winforms hide 同线程直接执行，安全
        except Exception:
            pass
        # 只做一次极小的文件写：**不起线程、不碰 evaluate_js**（任何线程安全）
        _request_flush(api.flush_file)
        return False  # 取消关闭 → 缩到托盘

    # 0917：`minimized` / `restored` 两个事件回调已删除 —— 它们唯一的作用是维护
    #       `api._window_visible`，而那个状态随「打开/关闭便签」快捷键一起下线了
    #       （见 `Api.__init__` 的说明）。`closing`（关闭 → 缩到托盘）保持不变。
    window.events.closing += on_closing

    # 系统托盘 + 多悬浮便签（0915c Stage2：唯一 Tk host + per-note Toplevel）
    global _float_manager
    _desk_api = DesktopApi(os.path.join(app_dir(), DESKTOP_DATA_FILE_NAME))
    # 0917：反向注入 manager —— 悬浮便签里点「删除便签」时，会话要能请 manager
    #       把自己从注册表摘掉并销毁窗口（见 `DesktopApi.close_self`）。
    _float_manager = FloatingWindowManager(_desk_api)
    _desk_api.manager = _float_manager
    _float_manager.warmup()   # 预置一个隐藏会话：保持「启动后 Tk 侧已有悬浮窗」的既有行为

    # 0915d：恢复上次退出时仍在悬浮的窗口（位置尺寸一并还原）。
    # 放在主线程里做，但每个 open 都是「投递到 Tk 线程 + 等窗口就绪」，不会阻塞太久；
    # 失败不影响主界面启动（restore_all 内部整体 try 过）。
    try:
        n = _float_manager.restore_all()
        if n:
            print("[startup] 已恢复 %d 个悬浮便签窗口" % n)
    except Exception as e:
        print("[startup] restore_all error:", e)
    _tray = Tray(
        resource_path("icon.ico"),
        on_show=api.show_main_window,
        on_new_note=open_desktop_note,
        on_quit=api.quit_app,
    )
    _tray.start()

    _si_log("即将进入 webview.start()")
    webview.start(debug=False)
    _si_log("webview.start() 已返回（UI 退出）")

    # webview 退出后收尾
    stop_tray()
    try:
        hotkey.stop(wait=False)
    except Exception:
        pass


if __name__ == "__main__":
    main()
