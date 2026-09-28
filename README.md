# 速记便签（SJBQ）

一款运行在 Windows 桌面上的**轻量级笔记 / 便签**应用。主界面采用 WebView2（HTML/CSS/JS）实现富文本编辑与标签分组管理；同时提供**独立悬浮便签小窗**（Tkinter 桌面窗口），可贴在桌面任意位置、置顶显示，适合随手记、临时备忘、边看边记。支持系统托盘常驻、全局快捷键、开机自启、WebDAV 云同步与本地备份。

> 当前版本：**2.1**。项目语言：中文（界面与文档均为简体中文）。目标平台：**Windows 10 / 11**（硬依赖 WebView2、系统托盘、全局热键、DPAPI 等 Windows 特性）。

---

## 目录

1. [项目概述](#1-项目概述)
2. [功能列表](#2-功能列表)
3. [环境要求](#3-环境要求)
4. [安装与运行](#4-安装与运行)
5. [使用说明](#5-使用说明)
6. [配置项](#6-配置项)
7. [命令行参数](#7-命令行参数)
8. [数据存储](#8-数据存储)
9. [目录结构](#9-目录结构)
10. [架构说明](#10-架构说明)
11. [安全设计](#11-安全设计)
12. [常见问题（FAQ）](#12-常见问题faq)
13. [开发指南（代码修改须知）](#13-开发指南代码修改须知)
14. [版本历史](#14-版本历史)
15. [许可证](#15-许可证)

---

## 1. 项目概述

### 1.1 定位

- **桌面便签工具**：不像重型笔记软件那样强调知识库，而是强调“快”——随手记、贴桌面、全局快捷键即写即存。
- **双形态**：
  - **主界面**（WebView2 窗口）：标签分组管理、富文本、搜索、云同步。
  - **悬浮便签**（Tkinter 桌面小窗）：脱离主界面的独立桌面贴纸，可置顶、拖拽、缩放。

### 1.2 核心特性

- 富文本便签（加粗、文字颜色、内嵌图片）。
- 标签（便签）按**分组**管理，支持新建/重命名/删除组、跨组拖拽。
- 全文搜索（标题 + 正文，不区分大小写）。
- 悬浮便签：独立桌面窗口，置顶、拖拽、缩放、删除。
- 系统托盘常驻：主窗口关闭 = 缩到托盘（不退出）；退出仅走托盘菜单。
- 全局快捷键：默认 `F8` 一键新建悬浮便签，可自定义并做冲突检测。
- 开机自启：仅常驻托盘并恢复上次悬浮便签，不弹主窗。
- WebDAV 云同步：支持坚果云 / 群晖等（Basic Auth）；密码用系统 DPAPI 加密后落盘。
- 本地备份：WebDAV 恢复前自动备份到 `backups/`；另支持纯本机“导出/导入本地目录”。
- 单实例运行：重复启动会唤起已有窗口而非开第二份。

### 1.3 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 主界面 UI | `pywebview` 6.2.1（WebView2 / winforms 后端）+ 原生 HTML/CSS/JS | 单文件 `便签应用.html`，无前端框架、无构建步骤 |
| 悬浮便签 UI | `Tkinter`（Python 标准库） | 独立线程 + 每便签一个 `Toplevel` 窗口 |
| 打包 | `PyInstaller` 6.20.0 | 单文件 exe（`console=False`，无控制台窗口） |
| 系统托盘 | `pystray` 0.19.5 | 图标 + 右键菜单 |
| 全局热键 | 标准库 `ctypes` 调 `RegisterHotKey` | 零额外依赖，原生冲突检测 |
| 剪贴板 | 标准库 `ctypes` 调 Win32 Clipboard | 图片/文本读写，不依赖 `pywin32` |
| WebDAV | 标准库 `urllib` / `base64` | 最小可用客户端，零第三方依赖 |
| 凭据加密 | Windows `DPAPI`（标准库 `ctypes` 调 `CryptProtectData`） | WebDAV 密码本机加密落盘 |

> **设计原则**：运行时**零第三方依赖**（Tkinter 来自标准库；WebView2 是系统组件）。`pywebview / pystray / Pillow / PyInstaller / pywin32` 仅用于**开发与打包**阶段。

---

## 2. 功能列表

### 2.1 主界面（WebView2 窗口）

| 功能 | 说明 |
|---|---|
| 分组管理 | 左侧标签树；支持「新建组 / 重命名组 / 删除组」；「未分类」为固定聚合组（不可改名/删除）。 |
| 便签管理 | 新建 / 重命名 / 删除便签；新建便签默认排到所属分组第一位。 |
| 跨组拖拽 | 可将便签拖入其他分组（拖入空白区归入「未分类」）。 |
| 富文本编辑 | `contenteditable` 正文，支持加粗、文字颜色等工具栏操作。 |
| 内嵌图片 | 支持**拖入 / 粘贴 / 点击调大小**；图片以 `dataURL` 内联进正文（长边 ≤ 1400px、单张 ≤ 2MB，超出自动压缩）。 |
| 剪贴板 | 复制 / 剪切 / 粘贴 / 粘贴为纯文本；支持从剪贴板粘贴图片（位图或图片文件）。 |
| 搜索 | 顶部搜索框，按标题 + 正文匹配，不区分大小写；搜索时只显示含匹配项的组。 |
| 设置面板 | 默认新建到、新建悬浮便签热键、开机自启、WebDAV 配置、清除所有数据、版本号。 |

### 2.2 悬浮便签（Tkinter 桌面小窗）

| 功能 | 说明 |
|---|---|
| 独立桌面窗 | 脱离主界面，可贴在桌面任意位置。 |
| 置顶 | 支持「钉住 / 取消钉住」（pin），置顶显示不被遮挡。 |
| 拖拽与缩放 | 标题栏拖动移动；边框拖拽缩放窗口。 |
| 编辑 | 与主界面同源的富文本编辑器。 |
| 删除 / 关闭 | 「×」为隐藏（不删数据）；菜单内「删除便签」才真删除。 |
| 全局字号 | 字号设置对**所有**悬浮便签统一生效。 |
| 位置恢复 | 关机前仍在悬浮的便签，下次启动（含开机自启）按原位置与尺寸恢复。 |

### 2.3 系统托盘（pystray）

- **显示主界面**（双击托盘图标或菜单默认项）。
- **新建桌面便签**（托盘右键）。
- **退出**（托盘右键；只有这里能真正退出程序，主窗口关闭只是缩到托盘）。

### 2.4 全局快捷键

- 默认 `F8`：在「未分类」新建一条便签并弹出其悬浮窗（**不弹主界面**）。
- 可在设置面板自定义组合键（支持 `Ctrl` / `Shift` / `Alt` + 字母 / 数字 / `F1`–`F24`）。
- 冲突检测：占用、Win 组合键、系统保留键（`Alt+F4`、`PrintScreen` 等）会被拦截并红字提示。

### 2.5 同步与备份

| 功能 | 说明 |
|---|---|
| WebDAV 备份 | 配置后点「备份到网盘」上传数据 JSON 到远端目录。 |
| WebDAV 恢复 | 点「从网盘恢复」下载覆盖本地；**恢复前自动备份当前数据到 `backups/`**。 |
| 本地导出 | 「导出到本地目录」：纯本机文件搬运，不依赖网盘。 |
| 本地导入 | 「从本地目录导入」：从本地目录读回数据。 |

> WebDAV 客户端仅实现 **Basic Auth**（覆盖坚果云 / 群晖等最常见场景）。未实现 Digest Auth：若服务器只接受 Digest 挑战会连不上。

---

## 3. 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | **Windows 10 / 11**（x64）。本项目硬依赖 WebView2、系统托盘、全局热键、DPAPI，无法在 macOS / Linux / Windows 7 上运行。 |
| WebView2 Runtime | Windows 11 自带；Windows 10 若缺省需安装 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)（Evergreen 版）。打包后的 exe 启动时会加载系统 WebView2。 |
| Python（开发/打包用） | 3.10 及以上（建议 3.10.x 或 3.11.x）。仅源码运行与打包时需要；**普通用户直接双击 exe 无需安装 Python**。 |
| 依赖（开发/打包） | 见 `config/requirements.txt`：pywebview==6.2.1、pystray==0.19.5、Pillow==12.2.0、PyInstaller==6.20.0、pywin32==312。 |
| 运行时第三方依赖 | **无**。Tkinter 来自 Python 标准库；WebView2 是系统组件。 |

---

## 4. 安装与运行

### 4.1 普通用户（使用已打包的 exe）

直接双击 `速记便签.exe` 即可。**无需安装 Python 或任何依赖**。首次运行会在「用户文档\速记便签\」下创建数据文件。

### 4.2 开发者模式（源码运行）

```bash
# 1) 准备 Python 3.10+ 虚拟环境（可选但推荐）
python -m venv .venv
.venv\Scripts\activate

# 2) 安装依赖（仅开发/打包需要）
pip install -r config/requirements.txt

# 3) 运行主程序（源码根目录 = 本 README 所在目录）
python main.py
```

也可双击 `run.bat`（仓库根目录的启动脚本）直接以源码模式运行。

### 4.3 打包为单文件 exe

```bash
# 在源码根目录执行（依赖见 4.2）
python -m PyInstaller --noconfirm --clean build.spec
# 产物：dist/速记便签.exe（单文件、无控制台窗口）
```

打包配置见 `build.spec`：
- `datas=[('便签应用.html', '.'), ('icon.ico', '.')]`：将 HTML 与图标打进 exe。
- `hiddenimports=['PIL','PIL.Image','PIL.ImageTk','PIL.ImageGrab']`：显式声明图片相关隐式依赖，避免打包后图片粘贴失效。
- `excludes`：排除 Qt/GTK 等多余 GUI 后端（Windows 实际用 WebView2，不必打进 Qt 套件，可省约 40MB 并加快冷启动）。
- `console=False`：无黑窗口；`icon=['icon.ico']`：exe 图标。

---

## 5. 使用说明

### 5.1 主界面布局

- **左侧**：分组 / 标签树（顶部固定「未分类」聚合组；下方为用户自建组与便签）。
- **顶部**：搜索框。
- **中间**：选中便签的标题输入 + 富文本正文（`contenteditable`）。
- **正文上方工具栏**：加粗、文字颜色（`A` 按钮）等。
- **右键**：在分组 / 便签 / 空白区右键，弹出「新建组 / 新建标签 / 重命名 / 删除」等菜单。

### 5.2 基本操作

- **新建便签**：右键分组 → 「新建标签」（或空白区右键）。
- **编辑**：在正文区直接输入；自动保存（无需手动保存）。
- **插入图片**：把图片文件拖进正文，或 `Ctrl+V` 粘贴剪贴板图片。
- **搜索**：在顶部搜索框输入关键词，实时过滤。
- **关闭主窗口**：点窗口「×」→ 缩到系统托盘（程序仍在运行）。
- **退出程序**：右键托盘图标 → 「退出」。

### 5.3 悬浮便签

- **新建**：托盘右键「新建桌面便签」，或按全局快捷键（默认 `F8`）。
- **移动 / 缩放**：拖标题栏移动；拖窗口边缘缩放。
- **置顶**：点击钉住按钮（pin）使其始终在最前。
- **关闭 vs 删除**：「×」仅隐藏（数据保留，可再次唤起）；菜单内「删除便签」才真正删除数据。
- **恢复**：程序下次启动会自动恢复关机前仍处于悬浮状态的便签（位置与尺寸一并还原）。

### 5.4 全局快捷键设置

1. 打开设置（主界面右上角或菜单进入设置面板）。
2. 在「新建悬浮便签」一栏点击「点击设置」。
3. 按下想要的组合键（如 `F8`、`Ctrl+Alt+N`）。
4. 若与系统保留键或其他程序冲突，会红字提示并要求更换。

### 5.5 开机自启

- 设置面板勾选「开机自启」。
- 原理：在注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写入值名 `便签应用`，命令为 `"<exe真实路径>" --startup`。
- 开机自启时：**仅常驻托盘 + 恢复悬浮便签，不弹主窗**；若无悬浮便签则完全静默。
- 路径用 `os.path.abspath(sys.argv[0])` 取真实 exe 路径（而非 PyInstaller 临时解压路径），因此**移动 exe 位置后下次启动会自动修正注册表项**。

### 5.6 WebDAV 同步

1. 设置面板进入 WebDAV 配置（或点「WebDAV」行）。
2. 填写：
   - **服务器地址**：如 `https://dav.jianguoyun.com/dav/`（坚果云）。
   - **用户名 / 密码**：Basic Auth 凭据；**密码本机用 DPAPI 加密后存储**，不以明文落盘。
   - **远端目录**：如 `/速记便签`。
3. 点「测试连接」确认可用。
4. 日常使用：「备份到网盘」上传；「从网盘恢复」下载（恢复前自动备份到本地 `backups/`）。
5. 不依赖网盘时，可用「导出到本地目录 / 从本地目录导入」做纯本机搬运。

---

## 6. 配置项

### 6.1 设置字段（持久化在 `便签应用数据.json` 的 `settings` 段）

| 字段名 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `hotkey` | 字符串 | `F8` | 全局快捷键组合（如 `F8`、`Ctrl+Alt+N`）。 |
| `default-new` | 字符串 | `ungrouped` | 新建便签的默认归属：`ungrouped` = 未分类；`last` = 上次使用的组。 |
| `font_pt`（悬浮便签） | 整数 | 由 `桌面便签数据.json` 的 `settings` 段管理 | 悬浮便签统一字号（全局生效）。 |

> 说明：开机自启（`autostart`）**不**存在 JSON 的 `settings` 段，而是由**注册表 Run 键**控制（见 5.5 / 7）。其读写函数为 `autostart_set(on)` / `autostart_enabled()`（`main.py` 内）。

### 6.2 开机自启（注册表）

- 路径：`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
- 值名：`便签应用`
- 值（示例）：`"C:\Path\To\速记便签.exe" --startup`
- 相关代码：`RUN_KEY_PATH`、`RUN_VALUE_NAME`、`_autostart_command()`、`autostart_set()`、`autostart_enabled()`（`main.py` 顶部与 `main()` 内）。

### 6.3 WebDAV 配置字段（持久化在 `settings` 段，密码单独加密）

| 字段 | 说明 |
|---|---|
| `webdav_url` | 服务器根地址（含末尾 `/dav/`）。 |
| `webdav_user` | 用户名。 |
| `webdav_pass`（加密） | 密码，经 DPAPI `CryptProtectData` 加密后的密文，存盘；读取时 `decrypt_secret()` 解密。 |
| `webdav_dir` | 远端目录（如 `/速记便签`）。 |

加密相关：`Api.encrypt_secret()` / `Api.decrypt_secret()`（`main.py`），底层走标准库 `ctypes` 调用 DPAPI。

### 6.4 快捷键语义约束

- 支持修饰键：`Ctrl` / `Shift` / `Alt` / `Win`（Win 组合键被禁止，会与系统冲突）。
- 主键：字母 `A`–`Z`、数字 `0`–`9`、`F1`–`F24`。
- 系统保留键（如 `Alt+F4`、`PrintScreen`）会被 `is_system_reserved()` 拒绝。
- 已被其他程序占用的组合，注册时 `RegisterHotKey` 返回 1409，会提示更换。
- 实现见 `hotkey.py`（`GlobalHotkey`、`parse_combo`、`is_system_reserved`）。

---

## 7. 命令行参数

| 参数 | 作用 |
|---|---|
| （无参数） | 普通启动：弹出主界面窗口。 |
| `--startup` | 开机自启模式：由注册表 Run 键拉起时使用。仅常驻系统托盘、不弹主窗；若上次有悬浮便签则按原位置恢复，否则静默。 |

> `main()` 中 `startup_mode = "--startup" in sys.argv` 据此决定 `webview.create_window(..., hidden=startup_mode)`。

---

## 8. 数据存储

### 8.1 数据目录

所有用户数据位于：

```
%USERPROFILE%\Documents\速记便签\
```

即「用户文档目录」下的「速记便签」子目录（中文 Windows 实际路径如 `C:\Users\用户名\Documents\速记便签\`）。
路径通过 Windows Shell 已知文件夹 API（`SHGetKnownFolderPath`）动态解析，回退 `~/Documents`，再回退程序目录，避免硬编码。

首次运行会把旧版本（exe 同目录）的数据自动迁移到此目录（防丢）。

### 8.2 文件清单

| 文件 / 目录 | 说明 |
|---|---|
| `便签应用数据.json` | 主界面数据：分组、便签、图片（内联 dataURL）、`settings` 段。 |
| `桌面便签数据.json` | 悬浮便签数据：`notes` 列表 + `settings` 段；每条便签可能含 `src_id` 与主界面便签绑定。 |
| `backups/` | WebDAV「从网盘恢复」前自动备份的本地副本。 |
| 命令 / flush 文件（同目录，带固定后缀） | 进程内「写命令文件 + 主界面 300ms 轮询」通道的临时文件（跨线程驱动前端用，详见 10.3）。 |

### 8.3 JSON 结构示例

`便签应用数据.json`（主界面）近似结构：

```json
{
  "groups": [
    { "id": "g1", "name": "工作", "notes": ["n1", "n2"] }
  ],
  "notes": {
    "n1": { "id": "n1", "title": "会议要点", "html": "<p>...</p>", "group": "g1", "updated": 1695000000 }
  },
  "settings": { "hotkey": "F8", "default-new": "ungrouped" }
}
```

`桌面便签数据.json`（悬浮便签）近似结构：

```json
{
  "notes": [
    { "id": "d1", "content": "<p>随手记…</p>", "pinned": true, "src_id": "n1", "bounds": [120,110,320,220] }
  ],
  "settings": { "font_pt": 14 }
}
```

> 实际字段以代码为准（见 `main.py` 的 `DesktopApi` 与 `Api` 读写逻辑），上例为便于理解的**简化示意**，不保证与线上完全一致。

### 8.4 写盘安全

- 采用**原子写**：先写临时文件，再 `os.replace` 覆盖，避免半截文件损坏。
- 悬浮便签的「读-改-写」方法（`load` / `new_note` / `save_note` / `delete_note` / `clear_all` 等）统一 `with self._lock` 整体加锁，防止双线程互相覆盖。

---

## 9. 目录结构

本仓库（发布根目录）刻意保持**扁平布局**，因为 `build.spec` 写死了 `Analysis(['main.py'], datas=[('便签应用.html','.'),('icon.ico','.')])`，扁平布局下打包无需改动配置。

```
速记便签/                      ← 仓库根（= 源码根 = 打包工作目录）
├── main.py                 主程序入口（1833 行）
│                             · 常量：APP_TITLE/APP_VERSION/DATA_FILE_NAME/DESKTOP_DATA_FILE_NAME/
│                               DEFAULT_HOTKEY/RUN_KEY_PATH/RUN_VALUE_NAME
│                             · class DesktopApi：悬浮便签 JS 桥 + 桌面便签数据读写
│                             · class Api：主界面 JS 桥（webview.create_window(js_api=) 挂的就是它）
│                             · 开机自启注册表逻辑、DPAPI 凭据加密、WebDAV 备份/恢复、命令轮询通道
│                             · main()：单实例锁 → 建窗口 → 起托盘/热键 → webview.start()
├── desk_note_window.py      悬浮便签本体（Tkinter，5894 行）
│                             · class FloatHost（单 Tk root / 单线程 / 单 mainloop）
│                             · class DesktopNoteWindow（每便签一个 Toplevel：编辑器/工具条/拖拽缩放/删除）
├── float_manager.py         悬浮窗会话管理器（346 行）
│                             · class FloatingWindowManager：noteId → 会话映射、去重激活、全局字号广播、
│                               统一收尾、restore_all() 重启恢复
├── tray.py                  系统托盘（73 行）
│                             · class Tray：图标 + 右键菜单（显示主界面/新建桌面便签/退出），业务回调注入
├── hotkey.py                全局快捷键（240 行）
│                             · RegisterHotKey 封装、组合键解析、冲突检测、GlobalHotkey 类
├── clip_io.py               剪贴板图片/文本读写（310 行）
│                             · 纯 ctypes 调 Win32；主界面与悬浮便签共用；dataURL/PIL 互转
├── webdav_sync.py           WebDAV 客户端（82 行）
│                             · WebDavClient：Basic Auth + MKCOL/PUT/GET/PROPFIND；零第三方依赖
├── 便签应用.html            主界面（6378 行）
│                             · 单文件 HTML/CSS/JS，原生无框架；富文本编辑器 + 设置面板 + 搜索 + 分组
├── build.spec               PyInstaller 打包配置（50 行）
├── icon.ico                 应用图标（托盘 + exe）
├── run.bat                  源码模式启动脚本
├── 说明.md                  模块级说明（本仓库各文件职责速查）
├── config/
│   ├── requirements.txt     开发/打包依赖清单
│   └── 说明.md              配置目录说明
└── （其他）                 tests/、docs/、scripts/、assets/、logs/ 等按交付结构组织
```

---

## 10. 架构说明

### 10.1 双 UI 引擎

- **主界面**：`pywebview` 创建 WebView2 窗口，加载本地 `便签应用.html`。UI 与逻辑全在 HTML/JS 内；Python 侧通过 `js_api=` 暴露的 `Api` 类供 JS 调用（读写数据、调系统能力）。
- **悬浮便签**：`Tkinter`（标准库）在独立线程跑一个 `FloatHost`（单 `Tk` root + `mainloop`），每个悬浮便签是一个 `Toplevel`。由 `FloatingWindowManager` 管理 `noteId → 会话` 映射。

### 10.2 两个独立 JSON + 绑定

- 主界面数据：`便签应用数据.json`。
- 悬浮便签数据：`桌面便签数据.json`。
- 二者靠悬浮便签里的 `src_id` 字段建立**一一绑定**：有 `src_id` 的悬浮便签与主界面对应便签互为镜像（双向同步）；无 `src_id` 的是独立桌面便签（老行为，不自动冒出）。

### 10.3 跨线程安全：命令文件 + 轮询

- **铁律**：绝不从非 GUI 线程调用 `evaluate_js`（winforms 后端会挂死不返回）。
- 跨线程驱动前端（托盘命令、全局热键、窗口关闭落盘）一律走「**写命令文件 → 主界面 300ms 轮询取走执行**」通道（`open_desktop_note()`、`_request_flush()`、`take_pending_command()` 等）。

### 10.4 单实例

- 启动时尝试获取命名 Mutex（`_try_acquire_single_instance`，`Local\` 前缀）。已有实例在跑则唤起其窗口并退出，避免两份内存数据互相覆盖。进程退出时 OS 自动释放 Mutex。

---

## 11. 安全设计

| 风险 | 措施 |
|---|---|
| WebDAV 密码泄露 | 经 Windows **DPAPI**（`CryptProtectData`）加密后以密文落盘；读取时解密到内存，不以明文存储。 |
| 富文本 XSS | 外部 HTML 进 DOM 前必须过 `sanitizeNoteHtml()`（剥离 `<img onerror=…>` 等可执行属性）；`innerHTML` 会执行事件属性，而 `window.pywebview.api` 对页内任意 JS 可见，故必须消毒。 |
| 数据文件损坏 | 原子写盘（tmp + `os.replace`）；悬浮便签读写整体加锁。 |
| 剪贴板独占 | 打开剪贴板失败自动重试（6 次 × 50ms）；持有期间不做耗时操作，避免卡住桌面。 |

---

## 12. 常见问题（FAQ）

**Q1：开机自启没生效？**
- 检查注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 是否存在值名 `便签应用`，且指向**真实 exe 路径**（不是临时目录）。
- 若曾用旧版（路径指向 PyInstaller 临时解压目录），升级后首次正常启动会自动修正（见 5.5）。
- 确认没有被安全软件 / 组策略拦截自启项。

**Q2：数据在哪里？换电脑怎么迁移？**
- 默认在 `%USERPROFILE%\Documents\速记便签\`。迁移时把该目录整体拷贝到新电脑同名位置即可；也可用 WebDAV 备份/恢复或本地导出/导入。

**Q3：WebDAV 连不上？**
- 本客户端仅支持 **Basic Auth**。坚果云 / 群晖均支持；若服务器只给 Digest 挑战会失败（后续可扩展）。
- 确认地址以 `/dav/`（坚果云）结尾、用户名密码正确、目录存在或有创建权限。

**Q4：为什么不能直接开两个实例？**
- 设计为单实例（见 10.4），重复启动会唤起已有窗口。如需多开，需改 `_try_acquire_single_instance` 逻辑。

**Q5：图片粘贴 / 插图失效？**
- 打包后若图片功能异常，通常是 Pillow 隐式依赖未打进包。已通过 `build.spec` 的 `hiddenimports=['PIL','PIL.Image','PIL.ImageTk','PIL.ImageGrab']` 规避。源码模式请确认 `Pillow` 已安装。

**Q6：全局快捷键没反应 / 提示冲突？**
- 被其他程序占用：换一个组合键。
- 用了 Win 组合键或系统保留键（`Alt+F4`、`PrintScreen`）：这些被主动禁止，请换普通组合键。
- 设置页会红字提示具体原因。

**Q7：主界面卡死 / 无响应？**
- 历史上「关闭主窗口」曾因在非 GUI 线程调 `evaluate_js` 导致死线程累积而卡死（已修复为命令文件通道）。若仍异常，检查是否误改了跨线程调用逻辑（见 13 铁律②）。

**Q8：悬浮便签位置错乱 / 重叠？**
- 新建时做错位摆位；但若便签已存过 `bounds`，会按保存位置恢复（不再错位）。异常可清 `桌面便签数据.json` 中对应 `bounds` 后重试。

---

## 13. 开发指南（代码修改须知）

> 本章为**给后续维护者 / AI 工具**的硬约束，违反会导致静默失效或死锁。修改代码前务必逐条对照。

1. **`js_api=` 只挂 `Api` 类**（`main.py` 的 `class Api`），不是 `DesktopApi`。给主界面 JS 新加方法必须加在 `Api` 里；加到 `DesktopApi` 上，JS 端 `typeof` 会不是 function 而**静默失效**（项目踩过两次）。
2. **绝不跨线程 `evaluate_js`**。winforms 后端会挂死不返回。跨线程驱动前端一律走「命令文件 + 主界面 300ms 轮询」（见 10.3）。
3. **`DesktopApi` 凡是「读-改-写」的方法必须整体 `with self._lock`**（`load` / `new_note` / `save_note` / `delete_note` / `clear_all` …）。只在 `_read`/`_write` 内部加锁挡不住跨调用竞态。
4. **外部 HTML 进 DOM 前必须过 `sanitizeNoteHtml`**（见 `便签应用.html`）。`innerHTML` 会执行 `<img onerror=…>`，而 `window.pywebview.api` 对页内任意 JS 可见。
5. **扁平布局约定**：新增源码文件直接放仓库根（与 `main.py` 同级），不要新建子目录——`build.spec` 的 `datas` 与 `Analysis(['main.py'])` 不感知子目录。若必须改目录结构，同步改 `build.spec`。
6. **改打包相关**：图片功能依赖 Pillow 隐式导入，新增图片处理请在 `build.spec` 的 `hiddenimports` 同步声明，否则打包后失效。
7. **版本号单一来源**：改版本号只改 `main.py` 的 `APP_VERSION` 常量 + 本 README 的版本历史，保持一致。
8. **开机自启路径**：`_autostart_command()` 打包态必须用 `os.path.abspath(sys.argv[0])`（真实 exe 路径），绝不可用 `sys.executable`（PyInstaller 临时目录，退出即失效）。
9. **数据位置**：用户数据走 `app_dir()`（用户文档\速记便签\），不要把数据写到 exe 同目录（便携性 / 权限问题）。
10. **测试 / 验证**：仓库含 `_verify_embed_*.py`、`_regress_*.py` 等验证脚本（开发目录），改动核心逻辑后应跑回归，确认 0 MISSING 且行为符合预期。

---

## 14. 版本历史

| 版本 | 关键变更 |
|---|---|
| 2.1 | 设置页展示版本号；修复开机自启路径（`sys.argv[0]` 替代 `sys.executable`，彻底解决「关机前退出后开机不自启」）。 |
| 2.0 | 开机自启逻辑重构：仅常驻托盘、恢复悬浮便签、静默；悬浮便签位置持久化与重启恢复；WebDAV 同步（备份/恢复 + 本地导出/导入）；数据迁移到用户文档目录。 |
| 1.0 | 初始桌面便签功能（主界面 + 悬浮便签 + 系统托盘 + 全局热键）。 |

> 更细的开发日志见仓库历史提交记录与内部 `说明.md`。

---

## 15. 许可证

本项目**尚未声明开源许可证**。如需公开发布，请在仓库根补充 `LICENSE` 文件并明确授权范围（当前代码可直接阅读与修改，但默认不授予再分发或商用权利，直至明确授权）。
