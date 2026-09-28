# -*- coding: utf-8 -*-
"""
系统托盘：图标 + 右键菜单（显示主界面 / 新建桌面便签 / 退出）。
依赖 pystray + Pillow；业务回调由外部注入，本模块不包含任何业务逻辑。
"""
from __future__ import annotations

from typing import Callable

import pystray
from PIL import Image


class Tray:
    def __init__(
        self,
        icon_path: str,
        on_show: Callable[[], None],
        on_new_note: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._callbacks = {
            "show": on_show,
            "new_note": on_new_note,
            "quit": on_quit,
        }
        image = Image.open(icon_path)
        self._icon = pystray.Icon(
            "速记便签",
            image,
            "速记便签",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "显示主界面",
                    lambda _i, _it: self._safe("show"),
                    default=True,  # 双击托盘图标也触发
                ),
                pystray.MenuItem(
                    "新建桌面便签",
                    lambda _i, _it: self._safe("new_note"),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "退出",
                    lambda _i, _it: self._safe("quit"),
                ),
            ),
        )
        self._started = False

    def _safe(self, key: str) -> None:
        try:
            cb = self._callbacks.get(key)
            if cb:
                cb()
        except Exception:
            pass

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        # run_detached：在独立线程运行托盘消息循环，不阻塞主线程
        self._icon.run_detached()

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        try:
            self._icon.stop()
        except Exception:
            pass
