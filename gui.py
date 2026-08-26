"""
VideoToText GUI v0.3 — 稳定版
两个核心场景：逐字稿 / 深度拆解
架构：模块级状态 + 独立 refreshable 分区（不用 ui.state，避开快照坑）
NiceGUI + Parchment 4.0 黑白风格
"""

import os
import sys
import json
import asyncio
import subprocess
from pathlib import Path
from nicegui import ui, app

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import video2text as v2t

# ============ 全局状态（可变容器，模块级） ============

VIEW = "home"  # home / transcript / deep / history
FILES = []  # [{name, path, size}]
PROCESSING = False
STEP_TEXT = ""
STEP_PCT = 0
RESULTS = []  # 处理结果列表
ENGINE = "doubao"
DEPTH = "standard"


# ============ 样式 ============

CSS = """
* { font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'PingFang SC', sans-serif; }
body { background: #0a0a0b; color: #e8e8ea; }
.q-card { background: #141416 !important; border: 1px solid #242426 !important; border-radius: 10px !important; box-shadow: none !important; }
.q-btn { border-radius: 6px !important; font-weight: 500 !important; text-transform: none !important; letter-spacing: 0 !important; }
.q-btn--unelevated { background: #fff !important; color: #0a0a0b !important; }
.q-btn--outline { border-color: #2a2a2d !important; color: #c8c8cc !important; }
.q-btn--flat { color: #c8c8cc !important; }
.text-h4 { font-weight: 600 !important; letter-spacing: -0.02em; }
.text-h6 { font-weight: 600 !important; letter-spacing: -0.01em; }
.text-subtitle2 { font-size: 13px !important; }
.q-separator { border-color: #1f1f22 !important; }
.q-uploader { background: #0f0f11 !important; border: 1px dashed #2a2a2d !important; border-radius: 10px !important; }
.q-linear-progress { border-radius: 2px !important; background: #1a1a1d !important; }
.q-linear-progress__bar { background: #fff !important; }
pre { background: #0d0d0f !important; padding: 16px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #2a2a2d; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #3a3a3d; }
.q-tab { font-weight: 500 !important; text-transform: none !important; letter-spacing: 0 !important; color: #6b6b70 !important; }
.q-tab--active { color: #fff !important; }
.q-tab-panels { background: transparent !important; padding: 0 !important; }
.q-field--dark .q-field__control { background: #0f0f11 !important; border-color: #242426 !important; }
.home-card { transition: all 0.15s ease; cursor: pointer; }
.home-card:hover { border-color: #3a3a3d !important; transform: translateY(-1px); }
.home-card:hover .home-card-icon { background: #fff !important; color: #0a0a0b !important; }
.home-card-icon { transition: all 0.15s ease; }
"""


# ============ 处理逻辑（不依赖 UI 组件） ============

def add_file(name: str, content: bytes):
    global FILES
    tmp = v2t.CACHE_DIR / name
    tmp.write_bytes(content)
    size_mb = tmp.stat().st_size / 1024 / 1024
    FILES.append({"name": name, "path": str(tmp), "size": size_mb})


def remove_file(i: int):
    global FILES
    if 0 <= i < len(FILES):
        FILES.pop(i)


def open_result(path: str):
    if path and Path(path).exists():
        subprocess.run(["open", "-R", str(path)])


async def do_transcribe():
    global PROCESSING, STEP_TEXT, STEP_PCT, RESULTS
    print("[do_transcribe] 被调用", flush=True)
    if not FILES:
        ui.notify("请先添加视频", type="warning")
        return
    PROCESSING = True
    RESULTS = []
    STEP_TEXT = "准备中..."
    STEP_PCT = 0
    results_area.refresh()
    try:
        total = len(FILES)
        for i, f in enumerate(FILES):
            STEP_TEXT = f"[{i+1}/{total}] {f['name']}"
            STEP_PCT = int(i / total * 100)
            status_area.refresh()
            result = await asyncio.to_thread(run_one, Path(f["path"]), "transcript", None, False)
            RESULTS.append(result)
            hist = app.storage.user.get("history", [])
            hist.insert(0, {"name": f["name"], "mode": "转写", "output": result["output_path"]})
            app.storage.user["history"] = hist[:50]
            results_area.refresh()
        STEP_PCT = 100
        STEP_TEXT = "完成"
        status_area.refresh()
        ui.notify(f"完成 {total} 个", type="positive")
    except Exception as ex:
        STEP_TEXT = f"失败: {ex}"
        status_area.refresh()
        ui.notify(f"失败: {ex}", type="negative")
    finally:
        PROCESSING = False
        status_area.refresh()


async def do_deep():
    global PROCESSING, STEP_TEXT, STEP_PCT, RESULTS, ENGINE, DEPTH
    if not FILES:
        ui.notify("请先添加视频", type="warning")
        return
    PROCESSING = True
    RESULTS = []
    STEP_TEXT = "准备中..."
    STEP_PCT = 0
    results_area.refresh()
    try:
        total = len(FILES)
        for i, f in enumerate(FILES):
            STEP_TEXT = f"[{i+1}/{total}] {f['name']}"
            STEP_PCT = int(i / total * 100)
            status_area.refresh()
            result = await asyncio.to_thread(run_one, Path(f["path"]), "deep", ENGINE, DEPTH == "deep")
            RESULTS.append(result)
            hist = app.storage.user.get("history", [])
            mode_label = f"拆解/{ENGINE}"
            hist.insert(0, {"name": f["name"], "mode": mode_label, "output": result["output_path"]})
            app.storage.user["history"] = hist[:50]
            results_area.refresh()
        STEP_PCT = 100
        STEP_TEXT = "完成"
        status_area.refresh()
        ui.notify(f"完成 {total} 个", type="positive")
    except Exception as ex:
        STEP_TEXT = f"失败: {ex}"
        status_area.refresh()
        ui.notify(f"失败: {ex}", type="negative")
    finally:
        PROCESSING = False
        status_area.refresh()


# ============ 动态分区（只刷新这些小块） ============

@ui.refreshable
def files_area():
    if not FILES:
        return
    with ui.column().classes("w-full gap-2"):
        for i, f in enumerate(FILES):
            with ui.row().classes("items-center justify-between w-full p-3 rounded bg-[#0f0f11]"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon("movie", size="sm").classes("opacity-40")
                    with ui.column().classes("gap-0"):
                        ui.label(f["name"]).classes("text-sm")
                        ui.label(f"{f['size']:.1f} MB").classes("text-xs opacity-40")
                ui.button(icon="close", on_click=lambda i=i: (remove_file(i), files_area.refresh())).props("flat size=sm dense").classes("opacity-40")


@ui.refreshable
def status_area():
    if not PROCESSING:
        return
    with ui.column().classes("w-full gap-2 mt-4"):
        ui.label(STEP_TEXT).classes("text-sm")
        ui.linear_progress(value=STEP_PCT / 100).props("inset")


@ui.refreshable
def results_area():
    if not RESULTS:
        return
    with ui.column().classes("w-full gap-3 mt-4"):
        ui.label("结果").classes("text-sm font-medium")
        for r in RESULTS:
            with ui.row().classes("items-center justify-between w-full p-3 rounded bg-[#0f0f11]"):
                with ui.column().classes("gap-0"):
                    ui.label(Path(r["file"]).name).classes("text-sm")
                    ui.label(f"{len(r.get('segments', []))} 段").classes("text-xs opacity-40")
                ui.button("在访达中显示", icon="folder_open", on_click=lambda r=r: open_result(r.get("output_path"))).props("flat size=sm")


def render_upload_area():
    async def on_upload(e):
        content = await e.file.read()
        add_file(e.file.name, content)
        files_area.refresh()
        ui.notify(f"已添加: {e.file.name}", type="info")

    with ui.card().classes("w-full p-6"):
        ui.label("添加视频").classes("text-sm font-medium mb-3")
        ui.upload(label="拖拽视频文件到这里，或点击选择", auto_upload=True, multiple=True, on_upload=on_upload).props("flat bordered no-thumbnails").classes("w-full")


# ============ 页面 ============

@ui.page("/")
def index():
    ui.add_css(CSS)

    def go(v):
        global VIEW
        VIEW = v
        page_content.refresh()

    # 顶栏（静态，不刷新）
    with ui.column().classes("w-full min-h-screen"):
        with ui.row().classes("w-full items-center justify-between px-6 py-4 border-b border-[#1a1a1d]"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("movie", size="sm").classes("opacity-60")
                ui.label("VideoToText").classes("text-sm font-medium")
            ui.button(icon="history", on_click=lambda: go("history")).props("flat size=sm dense")

        with ui.column().classes("flex-1 w-full max-w-3xl mx-auto px-6 py-8"):
            page_content()

        with ui.row().classes("w-full justify-center items-center gap-2 py-4 border-t border-[#1a1a1d]"):
            ui.label("v0.3").classes("text-xs opacity-20")
            ui.label("·").classes("text-xs opacity-10")
            ui.label("本地优先 · 数据不上传").classes("text-xs opacity-20")


@ui.refreshable
def page_content():
    # ===== 首页 =====
    if VIEW == "home":
        with ui.column().classes("w-full gap-8 mt-12"):
            with ui.column().classes("items-center w-full gap-2"):
                ui.label("VideoToText").classes("text-h4")
                ui.label("把视频变成可用的知识").classes("text-subtitle2 opacity-50")

            with ui.row().classes("justify-center gap-6 w-full mt-4"):
                with ui.card().classes("home-card w-72 p-6").on("click", lambda: (globals().update(VIEW="transcript"), page_content.refresh())):
                    with ui.column().classes("gap-4 w-full"):
                        ui.icon("description", size="sm").classes("home-card-icon")
                        ui.label("逐字稿").classes("text-h6")
                        ui.label("快速把视频转成文字。支持 SRT / TXT / Markdown。本地跑，不花钱。").classes("text-sm opacity-60 leading-6")
                        with ui.row().classes("items-center gap-2 mt-auto"):
                            ui.label("免费").classes("text-xs opacity-60")
                            ui.label("·").classes("text-xs opacity-30")
                            ui.label("本地 Whisper").classes("text-xs opacity-40")

                with ui.card().classes("home-card w-72 p-6").on("click", lambda: (globals().update(VIEW="deep"), page_content.refresh())):
                    with ui.column().classes("gap-4 w-full"):
                        ui.icon("analytics", size="sm").classes("home-card-icon")
                        ui.label("深度拆解").classes("text-h6")
                        ui.label("完整分析视频内容。结构、情绪、金句、行动项，沉淀成知识。").classes("text-sm opacity-60 leading-6")
                        with ui.row().classes("items-center gap-2 mt-auto flex-wrap"):
                            ui.label("3 种引擎").classes("text-xs opacity-60")
                            ui.label("·").classes("text-xs opacity-30")
                            ui.label("豆包 / 关键帧 / 本地").classes("text-xs opacity-40")

            with ui.row().classes("justify-center gap-4 w-full mt-2"):
                ui.button("历史记录", on_click=lambda: (globals().update(VIEW="history"), page_content.refresh())).props("flat outline size=sm")

    # ===== 子页面通用头部 =====
    if VIEW != "home":
        with ui.row().classes("items-center gap-2 w-full mb-4"):
            ui.button("← 返回", on_click=lambda: (globals().update(VIEW="home"), page_content.refresh())).props("flat size=sm dense").classes("p-0")

    # ===== 逐字稿页 =====
    if VIEW == "transcript":
        ui.label("逐字稿").classes("text-h6 mb-4")
        render_upload_area()
        files_area()
        with ui.card().classes("w-full p-6"):
            ui.label("导出设置").classes("text-sm font-medium mb-3")
            with ui.row().classes("gap-6 flex-wrap"):
                ui.switch("SRT 字幕", value=True)
                ui.switch("TXT 纯文本", value=True)
                ui.switch("带时间戳", value=True)
        ui.button("开始转写", icon="play_arrow", on_click=do_transcribe).props("unelevated").classes("px-8 py-3")
        status_area()
        results_area()

    # ===== 深度拆解页 =====
    if VIEW == "deep":
        ui.label("深度拆解").classes("text-h6 mb-4")
        render_upload_area()
        files_area()

        def set_engine(e):
            global ENGINE
            ENGINE = e.value

        def set_depth(e):
            global DEPTH
            DEPTH = e.value

        with ui.card().classes("w-full p-6"):
            ui.label("拆解引擎").classes("text-sm font-medium mb-4")
            ui.radio({
                "doubao": "豆包视频理解 — 质量最高，理解动态画面和动作",
                "frames": "关键帧 + VLM — 静态画面理解，便宜",
                "local": "完全本地 — 不花钱，本地模型跑",
            }, value=ENGINE, on_change=set_engine).props("inline label-color").classes("w-full")

            ui.separator().classes("my-4")
            ui.label("拆解深度").classes("text-sm font-medium mb-3")
            ui.toggle(["standard", "deep"], value=DEPTH, on_change=set_depth)
            ui.label("标准：摘要+章节+金句 ｜ 深度：+叙事+新概念+反常识").classes("text-xs opacity-40")

        with ui.expansion("高级选项", icon="settings").classes("w-full"):
            with ui.column().classes("gap-4 w-full"):
                ui.switch("说话人分离", value=False)
                ui.switch("导出到 Obsidian", value=False)

        ui.button("开始拆解", icon="play_arrow", on_click=do_deep).props("unelevated").classes("px-8 py-3")
        status_area()
        results_area()

    # ===== 历史页 =====
    if VIEW == "history":
        ui.label("历史记录").classes("text-h6 mb-1")
        ui.label("最近 50 条").classes("text-xs opacity-40 mb-4")
        hist = app.storage.user.get("history", [])
        if not hist:
            with ui.column().classes("items-center w-full py-16 gap-3"):
                ui.icon("history", size="lg").classes("opacity-20")
                ui.label("暂无历史记录").classes("text-sm opacity-40")
        else:
            with ui.column().classes("w-full gap-2"):
                for item in hist[:20]:
                    with ui.row().classes("items-center justify-between w-full p-3 rounded bg-[#0f0f11] hover:bg-[#141416] cursor-pointer transition-colors"):
                        with ui.column().classes("gap-0"):
                            ui.label(item.get("name", "")).classes("text-sm")
                            ui.label(item.get("mode", "")).classes("text-xs opacity-40")
                        ui.button("打开", icon="open_in_new", on_click=lambda item=item: open_result(item.get("output"))).props("flat size=sm")


# ============ 核心处理函数 ============

def run_one(video_path: Path, mode: str, engine: str = None, deep: bool = False) -> dict:
    """处理单个视频"""
    cache_key = v2t.file_hash(video_path)
    info = v2t.probe_video(video_path)

    segments = []
    frames_desc = []
    video_desc = None

    # 转写
    if info["has_audio"]:
        audio_path = v2t.extract_audio(video_path, cache_key)
        transcript = v2t.transcribe(audio_path, cache_key, v2t.DEFAULT_WHISPER_MODEL)
        segments = v2t.parse_segments(transcript)

    # 画面理解
    if mode == "deep":
        if engine == "doubao":
            video_desc = v2t.video_understanding_doubao(video_path, cache_key)
            if video_desc and "error" not in video_desc:
                frames_desc = []
                for i, sc in enumerate(video_desc.get("scenes", [])):
                    frames_desc.append({
                        "time": i * 5,
                        "description": sc.get("description", ""),
                        "source": "doubao"
                    })
        elif engine == "frames":
            frames = v2t.extract_keyframes(video_path, cache_key)
            frames_desc = v2t.describe_frames_vlm(frames, cache_key)

    # 摘要
    summary = {}
    if mode == "deep":
        doubao_data = video_desc if engine == "doubao" else None
        summary = v2t.summarize_with_llm(segments, info, frames_desc, deep=deep, video_desc=doubao_data)

    # 输出
    mode_suffix = mode
    if engine:
        mode_suffix += f"-{engine}"
    if deep:
        mode_suffix += "-deep"

    output_md = v2t.OUTPUT_DIR / f"{video_path.stem}_{mode_suffix}.md"
    v2t.write_markdown_output(video_path, info, segments, summary, frames_desc, output_md)

    return {
        "file": str(video_path),
        "mode": mode,
        "engine": engine,
        "info": info,
        "segments": segments,
        "frames": frames_desc,
        "summary": summary,
        "output_path": str(output_md),
    }


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="VideoToText",
        port=0,
        show=False,
        dark=True,
        native=False,
        window_size=(900, 750),
        reload=False,
        storage_secret="videotext-gui-secret",
    )
