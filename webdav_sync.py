# -*- coding: utf-8 -*-
"""速记便签 WebDAV 同步客户端（标准库实现，零第三方依赖）。

单独成文件以便单元测试直接 import —— main.py 本身依赖 pywebview 等重组件，
不便在测试里整体加载。本模块只用到标准库 urllib / base64，可独立运行。

覆盖坚果云 / 群晖等最常见场景（均支持 Basic Auth）。
⚠️ 未实现 Digest Auth：若服务器只给 Digest 挑战会连不上，届时再加。
"""
from __future__ import annotations

import base64
import urllib.error
import urllib.parse
import urllib.request


class WebDavError(Exception):
    """WebDAV 操作失败（连接 / 认证 / 路径 / 传输）。"""


class WebDavClient:
    """最小可用 WebDAV 客户端：Basic Auth + MKCOL / PUT / GET / PROPFIND。"""

    def __init__(self, base_url: str, user: str, password: str) -> None:
        self.base = (base_url or "").rstrip("/") + "/"
        self.user = user or ""
        self.password = password or ""

    def _url(self, path: str) -> str:
        # 逐段 URL 编码：支持中文目录 / 文件名（坚果云 / 群晖通用）
        seg = [urllib.parse.quote(s, safe="") for s in path.strip("/").split("/") if s]
        return self.base + "/".join(seg)

    def _request(self, method: str, path: str, data=None, extra=None):
        url = self._url(path)
        headers = {"User-Agent": "SJBQ-WebDAV/1.0", "Connection": "keep-alive"}
        if self.user or self.password:
            token = base64.b64encode(("%s:%s" % (self.user, self.password)).encode("utf-8")).decode("ascii")
            headers["Authorization"] = "Basic " + token
        if extra:
            headers.update(extra)
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read(), resp.status, dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.read(), e.code, dict(e.headers)

    def ensure_dir(self, dir_path: str) -> None:
        """逐级 MKCOL 创建远程目录；已存在（405/409）视为成功。"""
        parts = [p for p in dir_path.strip("/").split("/") if p]
        cur = ""
        for seg in parts:
            cur = seg if not cur else cur + "/" + seg
            body = (b'<?xml version="1.0" encoding="utf-8"?>'
                    b'<d:mkcol xmlns:d="DAV:"><d:set><d:prop>'
                    b'<d:resourcetype><d:collection/></d:resourcetype>'
                    b'</d:prop></d:set></d:mkcol>')
            _, status, _ = self._request(
                "MKCOL", cur + "/", data=body,
                extra={"Content-Type": "application/xml; charset=utf-8"},
            )
            # 201 新建；405/409 目录已存在（坚果云/群晖对存在的集合返回这两者之一）
            if status >= 400 and status not in (405, 409):
                raise WebDavError("创建远程目录失败 %s（HTTP %d）" % (cur, status))

    def exists(self, path: str) -> bool:
        _, status, _ = self._request("PROPFIND", path, extra={"Depth": "0"})
        return status in (207, 200)

    def upload(self, path: str, text: str) -> None:
        self._request(
            "PUT", path, data=text.encode("utf-8"),
            extra={"Content-Type": "application/json; charset=utf-8"},
        )

    def download(self, path: str) -> str:
        data, status, _ = self._request("GET", path)
        if status != 200:
            raise WebDavError("下载失败（HTTP %d）" % status)
        return data.decode("utf-8", errors="replace")
