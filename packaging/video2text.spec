# -*- mode: python ; coding: utf-8 -*-
"""
packaging/video2text.spec — PyInstaller 打包配置（macOS .app）

同一个 spec 产出两种包，靠环境变量 V2T_VARIANT 选：

  V2T_VARIANT=browser（默认）
      产物 dist/VideoToText.app      启动本地服务 + 打开浏览器
      不含 pywebview / pyobjc，体积最小，这是被验证过最久的那条路

  V2T_VARIANT=native
      产物 dist/VideoToTextNative.app  启动本地服务 + 弹一个原生窗口（pywebview/Cocoa）
      多带 pywebview + pyobjc，大约多 20MB

为什么分成两个包而不是一个包两种模式：
  带 pywebview 就必然带 pyobjc（几十 MB、上百个 .so），而绝大多数人只是想在浏览器里用。
  拆开后"要不要窗口"这个选择发生在下载的时候，而不是让所有人替少数人付体积。
  代价是 CI 多打一次包（约 1.5 分钟），换来的是两个包各自的依赖图都能单独验证。

为什么是 one-dir 而不是 one-file：
  one-file 每次启动都要把 ~600MB 解到临时目录，冷启动 10s+；
  one-dir 直接跑，启动 2s。分发时用 DMG 装，用户感知不到目录结构。

排除大头：torch / transformers / qwen_asr / mlx 都不打进去
  —— qwen3-asr 的本地通道和 mlx-whisper 走 pip 另装，App 里只用 faster-whisper。
  这样包体积从 3G+ 降到 600M 左右。
"""

import os
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# ---------- 变体 ----------
_VARIANT = (os.environ.get("V2T_VARIANT") or "browser").strip().lower()
if _VARIANT not in ("browser", "native"):
    raise SystemExit(f"[spec] 未知变体 V2T_VARIANT={_VARIANT}（只支持 browser / native）")
_NATIVE = _VARIANT == "native"
_EXE_NAME = "VideoToTextNative" if _NATIVE else "VideoToText"
print(f"[spec] 变体：{_VARIANT}（产物 {_EXE_NAME}.app）")

# 版本号优先取 build_dmg.sh 传下来的 VERSION（打 tag 时以 tag 为准），
# 否则读仓库里的 VERSION 文件，避免 App 内版本和 Release tag 对不上
_ROOT = Path(SPECPATH).parent
_VERSION = (os.environ.get("VERSION") or (_ROOT / "VERSION").read_text(encoding="utf-8")).strip() or "0.0.0"
print(f"[spec] 打包版本：{_VERSION}")

# NiceGUI 官方推荐：collect_all 把静态资源、模板、子模块一次收齐
datas, binaries, hiddenimports = collect_all("nicegui")

# 变体标记文件：launcher.py 读它决定"默认开不开原生窗口"。
# 不写死在代码里，是因为同一个 launcher.py 要服务两个包；写在 Resources 里
# 还能被 verify_dmg.sh 直接断言"包名和内容是不是对得上"。
_FLAG_DIR = Path(tempfile.mkdtemp(prefix="v2t-native-flag-"))
(_FLAG_DIR / "NATIVE_DEFAULT").write_text("1\n" if _NATIVE else "0\n", encoding="utf-8")

# 本项目源码由 launcher 静态 import，PyInstaller 会自动分析依赖并打进 PYZ，
# 不需要（也不应该）再当数据文件塞一遍。
datas += [
    ("../VERSION", "."),
    ("../.env.example", "."),
    ("../docs", "docs"),
    (str(_FLAG_DIR / "NATIVE_DEFAULT"), "."),
]

hiddenimports += [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "engineio.async_drivers.asgi",
    "socketio",
    "aiofiles",
    "multipart",
    "python_multipart",
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "PIL.Image",
    "PIL._tkinter_finder",
]

# ---------- 原生窗口的额外依赖 ----------
# pywebview 的 macOS 后端是 Cocoa（pyobjc），而 pywebview 是"运行时挑后端"的：
# webview/guilib.py 用 importlib 动态 import webview.platforms.cocoa，
# 静态分析看不到这条边，不写进 hiddenimports 就会打出个"能启动但没有窗口"的包。
#
# pyobjc 的各个 framework 包内部还有大量 .so 子模块（AppKit._AppKit 等），
# 也是动态加载的，用 collect_submodules 一次收齐，别指望 modulegraph 猜。
_NATIVE_PACKAGES = ("objc", "Foundation", "AppKit", "WebKit", "PyObjCTools")
if _NATIVE:
    datas += collect_data_files("webview")   # webview/js、webview/lib 里的注入脚本
    hiddenimports += [
        "webview",
        "webview.platforms.cocoa",
        "webview.dom",
        "webview.menu",
        "webview.screen",
        "webview.util",
        "webview.window",
    ]
    for _pkg in _NATIVE_PACKAGES:
        hiddenimports += collect_submodules(_pkg)
    print(f"[spec] 原生窗口依赖：webview + pyobjc（{len(hiddenimports)} 个 hiddenimport）")

EXCLUDES = [
    # 三个引擎里 App 只用 faster-whisper，其余按需 pip 装
    "torch", "torchvision", "torchaudio",
    "transformers", "qwen_asr", "mlx", "mlx_whisper",
    "sentencepiece", "tokenizers", "accelerate", "librosa", "numba",
    # 常见肥依赖
    "matplotlib", "scipy", "pandas", "IPython", "notebook",
    "tkinter", "pytest", "setuptools._distutils",
]

if not _NATIVE:
    # 构建机上装了 pywebview（requirements.txt 里给 macOS 装了），而 nicegui 的
    # native_mode.py 顶层有一句 `import webview`（包在 try 里）。不显式排除的话，
    # modulegraph 会顺着这条边把 pywebview + 整个 pyobjc 拖进浏览器版，
    # 体积涨几十 MB —— 而且它根本用不上。
    EXCLUDES += [
        "webview", "bottle",
        "objc", "Foundation", "AppKit", "WebKit", "PyObjCTools", "Cocoa", "Quartz",
    ]

a = Analysis(
    ["launcher.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=_EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 双击不弹终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,       # 跟随构建机（arm64）
    codesign_identity=None, # 由 build_dmg.sh 统一 ad-hoc 签
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=_EXE_NAME,
)

app = BUNDLE(
    coll,
    name=f"{_EXE_NAME}.app",
    icon=None,
    bundle_identifier="com.video2text.native" if _NATIVE else "com.video2text.app",
    version=_VERSION,
    info_plist={
        "CFBundleName": _EXE_NAME,
        "CFBundleDisplayName": "VideoToText 窗口版" if _NATIVE else "VideoToText",
        "CFBundleShortVersionString": _VERSION,
        "CFBundleVersion": _VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "MIT License",
        # 需要在界面上打开浏览器/访问网络
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
    },
)
