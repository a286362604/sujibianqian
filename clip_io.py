# -*- coding: utf-8 -*-
"""系统剪贴板读写（Windows）：图片 + 文本 —— 主界面与悬浮便签**共用**，行为一致。

为什么单独一个模块：图片右键菜单的「复制 / 剪切 / 粘贴 / 粘贴为纯文本」两侧都要用，
且两侧的剪贴板语义必须完全一样（在悬浮便签复制的图，粘到主界面要能插进去，反之亦然）。

实现要点：
· **写图片**：PIL 存 BMP → 去掉 14 字节 `BITMAPFILEHEADER`，剩下的就是 `CF_DIB`
  （Word / 微信 / QQ / 画图 都认这个格式）。纯 ctypes 调 Win32，**不依赖 pywin32**
  （打包体积 +0，且免去 32/64 位 COM 注册问题）。
· **读图片**：`PIL.ImageGrab.grabclipboard()` → `Image`（位图）/ `[路径]`（复制的文件）/ None。
· **读文本**：`CF_UNICODETEXT`。
· **编码规则**与主界面 / 悬浮便签逐条对齐：长边 ≤ IMG_MAX_EDGE(1400)、单张 ≤ IMG_MAX_BYTES(2MB)，
  超限先转 JPEG(q86) 再逐步等比缩小；文件来源且未超限时**保留原始字节**（不重编码、GIF 保动画）。

🔴 剪贴板是**全局独占**资源：别的进程开着剪贴板时 `OpenClipboard` 会失败 → 统一走 `_open()`
   重试（6 次 × 50ms ≈ 300ms）；并且**持有期间绝不做耗时操作**（否则会把桌面卡住）。
"""
from __future__ import annotations

import base64
import io
import mimetypes
import os
import time
from ctypes import wintypes

# ---- 剪贴板格式 / 内存标志 ----
CF_DIB = 8
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# ---- 图片规则（🔴 必须与 便签应用.html / desk_note_window.py 保持一致）----
IMG_MAX_EDGE = 1400
IMG_MAX_BYTES = 2 * 1024 * 1024
IMG_JPEG_Q = 86
IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:                       # 极简环境没有 Pillow → 图片相关功能整体降级
    Image = None
    _HAS_PIL = False

# 🔴 必须模块级导入：写进函数里 PyInstaller 静态分析扫不到 → 打出来的 exe 缺 ImageGrab
#    （读剪贴板图片静默失效）。build.spec 里另有 hiddenimports 双保险。
try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None

if os.name == "nt":
    import ctypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _HGLOBAL = getattr(wintypes, "HGLOBAL", wintypes.HANDLE)

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = _HGLOBAL
    _kernel32.GlobalLock.argtypes = [_HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [_HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [_HGLOBAL]
    _kernel32.GlobalFree.restype = _HGLOBAL
else:                                    # 非 Windows：本模块功能整体不可用（程式不会走到这）
    _user32 = _kernel32 = None


# ============================ 底层：内存 + 打开剪贴板 ============================

def _open(retries: int = 6, gap: float = 0.05) -> bool:
    """打开剪贴板（被别人占着时重试）。返回是否成功。"""
    if _user32 is None:
        return False
    for _ in range(max(1, retries)):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(gap)
    return False


def _write_block(fmt: int, data: bytes) -> bool:
    """把一段字节以指定剪贴板格式放进去（内部会 GlobalAlloc 一份副本）。"""
    if _user32 is None or not data:
        return False
    h = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        return False
    ptr = _kernel32.GlobalLock(h)
    if not ptr:
        _kernel32.GlobalFree(h)
        return False
    try:
        ctypes.memmove(ptr, data, len(data))
    finally:
        _kernel32.GlobalUnlock(h)
    if not _open():
        _kernel32.GlobalFree(h)
        return False
    try:
        _user32.EmptyClipboard()
        if not _user32.SetClipboardData(fmt, h):
            _kernel32.GlobalFree(h)     # 没交出去 → 自己释放；交出去就归系统，不能再 free
            return False
        return True
    except Exception:
        return False
    finally:
        _user32.CloseClipboard()


# ============================ 写：文本 / 图片 ============================

def copy_text(text: str) -> bool:
    """纯文本进剪贴板（`CF_UNICODETEXT`）。"""
    try:
        data = (str(text) + "\0").encode("utf-16-le")
    except Exception:
        return False
    return _write_block(CF_UNICODETEXT, data)


def copy_image(im) -> bool:
    """把 PIL 图放进剪贴板（`CF_DIB`）。返回是否成功。

    ATL/Word/微信 等都能直接粘出位图；透明像素会被拍平成白底（DIB 24bpp 的通用性最好，
    32bpp + alpha 在部分老程序里会显示成黑块）。
    """
    if _user32 is None or im is None or not _HAS_PIL:
        return False
    try:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "BMP")
        data = buf.getvalue()[14:]      # 去掉 BITMAPFILEHEADER → 就是 CF_DIB 需要的 DIB
    except Exception:
        return False
    return _write_block(CF_DIB, data)


def copy_data_url(url: str) -> bool:
    """把 dataURL（正文里内嵌的图片）放进剪贴板。"""
    im = data_url_to_pil(url)
    if im is None:
        return False
    return copy_image(im)


# ============================ 读：文本 / 图片 ============================

def read_text() -> str:
    """读剪贴板纯文本（`CF_UNICODETEXT`）；没有则返回空串。"""
    if _user32 is None:
        return ""
    try:
        if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        if not _open():
            return ""
        try:
            h = _user32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return ""
            ptr = _kernel32.GlobalLock(h)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr) or ""
            finally:
                _kernel32.GlobalUnlock(h)
        finally:
            _user32.CloseClipboard()
    except Exception:
        return ""


def read_image():
    """读剪贴板图片：`PIL.Image` / 图片文件路径列表 / None。"""
    if ImageGrab is None:
        return None
    try:
        return ImageGrab.grabclipboard()
    except Exception:
        return None


# ============================ dataURL / PIL 互转 ============================

def data_url_to_pil(url: str):
    """dataURL → PIL Image（失败返回 None）。"""
    if not _HAS_PIL or not url:
        return None
    try:
        head, _, b64 = str(url).partition(",")
        if not b64:
            return None
        raw = base64.b64decode(b64)
        im = Image.open(io.BytesIO(raw))
        im.load()                       # 强制解码（BytesIO 随后会被回收）
        return im.copy()
    except Exception:
        return None


def encode_pil(im, max_edge: int = IMG_MAX_EDGE, max_bytes: int = IMG_MAX_BYTES):
    """PIL 图 → (原始字节, mime)，按主界面/悬浮便签同款规则压缩。

    先无损 PNG；超 2MB → JPEG(q86)；仍超 → 每次缩 20% 再编码（下限 240px 保护）。
    """
    if im is None or not _HAS_PIL:
        return None
    cur = im
    nat_w, nat_h = cur.size
    if max(nat_w, nat_h) > max_edge:
        k = max_edge / float(max(nat_w, nat_h))
        cur = cur.resize((max(1, int(round(nat_w * k))), max(1, int(round(nat_h * k)))),
                         Image.LANCZOS)

    def _enc(img, fmt: str):
        buf = io.BytesIO()
        if fmt == "PNG":
            img.save(buf, "PNG")
            return buf.getvalue(), "image/png"
        img.convert("RGB").save(buf, "JPEG", quality=IMG_JPEG_Q)
        return buf.getvalue(), "image/jpeg"

    try:
        data, mime = _enc(cur, "PNG")
        if len(data) > max_bytes:
            data, mime = _enc(cur, "JPEG")
        while len(data) > max_bytes and max(cur.size) > 240:
            w, h = cur.size
            cur = cur.resize((max(1, int(w * 0.8)), max(1, int(h * 0.8))), Image.LANCZOS)
            data, mime = _enc(cur, "JPEG")
    except Exception:
        return None
    if len(data) > max_bytes:
        return None                     # 缩到 240px 还超限 → 放弃（与主界面「拒绝插入」一致）
    return data, mime


def pil_to_data_url(im, max_edge: int = IMG_MAX_EDGE) -> str:
    """PIL 图 → dataURL（按规则压缩）。失败返回空串。"""
    out = encode_pil(im, max_edge)
    if not out:
        return ""
    data, mime = out
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))


# ============================ 给主界面桥用的统一载荷 ============================

def paste_payload(max_edge: int = IMG_MAX_EDGE):
    """剪贴板 → 主界面 JS 能直接用的字典。

    · 图片位图   → {"kind": "image", "dataUrl": ..., "w":, "h":, "bytes":}
    · 复制的文件 → 其中图片文件按图片返回（与资源管理器「复制→粘贴」直觉一致）
    · 纯文本     → {"kind": "text", "text": ...}
    · 空/读不到  → None
    """
    data = read_image()
    if isinstance(data, list):
        paths = [p for p in data if isinstance(p, str) and os.path.isfile(p)]
        for p in paths:
            if os.path.splitext(p)[1].lower() not in IMG_EXTS:
                continue
            try:
                with open(p, "rb") as f:
                    raw = f.read()
                im = Image.open(io.BytesIO(raw))
                im.load()
            except Exception:
                continue
            nat_w, nat_h = im.size
            # 小图且未超限 → 原样保留（不重编码，GIF 还能保动画），与悬浮便签同规则
            if raw and max(nat_w, nat_h) <= max_edge and len(raw) <= IMG_MAX_BYTES:
                mime = mimetypes.guess_type(p)[0] or "image/png"
                return {"kind": "image",
                        "dataUrl": "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii")),
                        "w": nat_w, "h": nat_h, "bytes": len(raw)}
            url = pil_to_data_url(im, max_edge)
            if url:
                out = encode_pil(im, max_edge)
                return {"kind": "image", "dataUrl": url,
                        "w": nat_w, "h": nat_h, "bytes": (len(out[0]) if out else 0)}
    elif _HAS_PIL and isinstance(data, Image.Image):
        out = encode_pil(data, max_edge)
        if out:
            raw, mime = out
            return {"kind": "image",
                    "dataUrl": "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii")),
                    "w": data.size[0], "h": data.size[1], "bytes": len(raw)}

    txt = read_text()
    if txt:
        return {"kind": "text", "text": txt}
    return None
