# -*- mode: python ; coding: utf-8 -*-
"""
packaging/video2text.spec — PyInstaller 打包配置（macOS .app）

产物：dist/VideoToText.app（one-dir 模式，启动快，不用每次解包）

为什么是 one-dir 而不是 one-file：
  one-file 每次启动都要把 ~600MB 解到临时目录，冷启动 10s+；
  one-dir 直接跑，启动 2s。分发时用 DMG 装，用户感知不到目录结构。

排除大头：torch / transformers / qwen_asr / mlx 都不打进去
  —— qwen3-asr 的本地通道和 mlx-whisper 走 pip 另装，App 里只用 faster-whisper。
  这样包体积从 3G+ 降到 600M 左右。
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 版本号优先取 build_dmg.sh 传下来的 VERSION（打 tag 时以 tag 为准），
# 否则读仓库里的 VERSION 文件，避免 App 内版本和 Release tag 对不上
_ROOT = Path(SPECPATH).parent
_VERSION = (os.environ.get("VERSION") or (_ROOT / "VERSION").read_text(encoding="utf-8")).strip() or "0.0.0"
print(f"[spec] 打包版本：{_VERSION}")

# NiceGUI 官方推荐：collect_all 把静态资源、模板、子模块一次收齐
datas, binaries, hiddenimports = collect_all("nicegui")

# 本项目源码由 launcher 静态 import，PyInstaller 会自动分析依赖并打进 PYZ，
# 不需要（也不应该）再当数据文件塞一遍。
datas += [
    ("../VERSION", "."),
    ("../.env.example", "."),
    ("../docs", "docs"),
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

EXCLUDES = [
    # 三个引擎里 App 只用 faster-whisper，其余按需 pip 装
    "torch", "torchvision", "torchaudio",
    "transformers", "qwen_asr", "mlx", "mlx_whisper",
    "sentencepiece", "tokenizers", "accelerate", "librosa", "numba",
    # 常见肥依赖
    "matplotlib", "scipy", "pandas", "IPython", "notebook",
    "tkinter", "pytest", "setuptools._distutils",
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
    name="VideoToText",
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
    name="VideoToText",
)

app = BUNDLE(
    coll,
    name="VideoToText.app",
    icon=None,
    bundle_identifier="com.video2text.app",
    version=_VERSION,
    info_plist={
        "CFBundleName": "VideoToText",
        "CFBundleDisplayName": "VideoToText",
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
