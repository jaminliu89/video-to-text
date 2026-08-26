"""
VideoToText GUI v0.4 — 可用版
P0 全功能：批量队列 / 历史记录 / 结果浏览 / Obsidian 导出
架构：模块级状态 + 独立 refreshable 分区
NiceGUI + Parchment 4.0 浅色黑白风格
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
import config as cfg

# ============ 全局状态 ============

VIEW = "home"  # home / transcript / deep / history / settings
CURRENT_RESULT = None  # 当前查看的结果详情

# 批量队列
QUEUE = []  # [{name, path, size, status: pending/running/done/error, progress: 0-100, result, error}]
QUEUE_RUNNING = False
TOTAL_PROGRESS = 0

# 引擎和深度
ENGINE = "doubao"
DEPTH = "standard"


def scan_output_dir() -> list[dict]:
    """扫 output 目录，生成历史记录列表（按修改时间倒序）"""
    items = []
    for md_file in sorted(v2t.OUTPUT_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        name = md_file.stem  # 文件名（带模式后缀）
        # 从文件名解析：原名_模式_引擎_深度
        parts = name.rsplit("_", 1)
        if len(parts) < 2:
            continue
        base_name = parts[0]
        mode_str = parts[1]

        # 解析模式
        mode_label = ""
        if mode_str.startswith("transcript"):
            mode_label = "逐字稿"
        elif mode_str.startswith("audio"):
            mode_label = "逐字稿"
        elif mode_str.startswith("deep"):
            mode_label = "深度拆解"
            if "doubao" in mode_str:
                mode_label += " / 豆包"
            elif "frames" in mode_str:
                mode_label += " / 关键帧"
            elif "local" in mode_str:
                mode_label += " / 本地"

        size = md_file.stat().st_size
        mtime = md_file.stat().st_mtime

        items.append({
            "name": base_name + ".mp4",
            "mode": mode_label,
            "output": str(md_file),
            "size_kb": round(size / 1024, 1),
            "mtime": mtime,
        })
    return items[:50]


def read_result_preview(md_path: str) -> dict:
    """读取结果 md 文件，提取摘要和逐字稿预览"""
    path = Path(md_path)
    if not path.exists():
        return {}
    text = path.read_text()
    lines = text.split("\n")

    # 找摘要段
    summary = []
    transcript = []
    in_summary = False
    in_transcript = False

    for line in lines[:100]:  # 只读前 100 行
        if line.startswith("# ") and "逐字稿" not in line and "转写" not in line:
            in_summary = True
            continue
        if line.startswith("## 逐字稿") or line.startswith("## 转写") or line.startswith("## 完整逐字稿"):
            in_summary = False
            in_transcript = True
            continue
        if line.startswith("## "):
            if in_transcript:
                in_transcript = False
            continue
        if in_summary and line.strip():
            summary.append(line)
        if in_transcript and line.strip():
            transcript.append(line)

    return {
        "full_text": text,
        "summary": "\n".join(summary[:20]),
        "transcript": "\n".join(transcript[:30]),
        "has_summary": bool(summary),
        "has_transcript": bool(transcript),
    }


# ============ 样式 ============

CSS = """
* { font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'PingFang SC', sans-serif; }
.material-icons, .q-icon, i[class*="material-icons"] {
  font-family: 'Material Icons' !important;
  font-weight: normal;
  font-style: normal;
  font-size: 24px;
  line-height: 1;
  letter-spacing: normal;
  text-transform: none;
  display: inline-block;
  white-space: nowrap;
  word-wrap: normal;
  direction: ltr;
  -webkit-font-feature-settings: 'liga';
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  -moz-osx-font-smoothing: grayscale;
  font-feature-settings: 'liga';
}
body { background: #faf8f5; color: #1a1a1a; }
.q-card { background: #ffffff !important; border: 1px solid #e5e3df !important; border-radius: 10px !important; box-shadow: none !important; }
.q-btn { border-radius: 6px !important; font-weight: 500 !important; text-transform: none !important; letter-spacing: 0 !important; }
.q-btn--flat { color: #5a5a5a !important; }
.q-btn--flat:hover { color: #1a1a1a !important; background: rgba(26,26,26,0.05) !important; }
.q-btn--flat .q-icon { color: inherit !important; }
.q-btn--outline { border-color: #d5d3cf !important; color: #4a4a4a !important; }
.q-btn--outline:hover { border-color: #1a1a1a !important; color: #1a1a1a !important; }
.q-btn--unelevated { background: #1a1a1a !important; color: #ffffff !important; }
.q-btn--unelevated:hover { background: #333 !important; }
.q-btn--unelevated .q-icon { color: #ffffff !important; }
.q-btn .q-icon { color: inherit !important; }
.text-h4 { font-weight: 600 !important; letter-spacing: -0.02em; color: #1a1a1a !important; }
.text-h6 { font-weight: 600 !important; letter-spacing: -0.01em; color: #1a1a1a !important; }
.text-subtitle2 { font-size: 13px !important; color: #6a6a6a !important; }
.q-separator { border-color: #e8e6e2 !important; }
.q-uploader { background: #f7f5f1 !important; border: 1px dashed #d5d3cf !important; border-radius: 10px !important; color: #1a1a1a !important; }
.q-linear-progress { border-radius: 2px !important; background: #edebe7 !important; }
.q-linear-progress__bar { background: #1a1a1a !important; }
pre { background: #f7f5f1 !important; padding: 16px; border-radius: 6px; overflow-x: auto; font-size: 12px; color: #2a2a2a !important; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d5d3cf; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #c5c3bf; }
.q-tab { font-weight: 500 !important; text-transform: none !important; letter-spacing: 0 !important; color: #8a8a8a !important; }
.q-tab--active { color: #1a1a1a !important; }
.q-tab-panels { background: transparent !important; padding: 0 !important; }
.q-field .q-field__control { background: #f7f5f1 !important; border-color: #e5e3df !important; color: #1a1a1a !important; }
.home-card { transition: all 0.15s ease; cursor: pointer; }
.home-card:hover { border-color: #c5c3bf !important; transform: translateY(-1px); }
.home-card:hover .home-card-icon { background: #1a1a1a !important; color: #ffffff !important; }
.home-card-icon { transition: all 0.15s ease; background: #f0eee9 !important; color: #1a1a1a !important; }

.q-toggle__inner--active .q-toggle__track { background: #1a1a1a !important; }
.q-toggle__inner--active .q-toggle__thumb { background: #ffffff !important; }
.q-toggle__track { background: #d5d3cf !important; }

.q-radio__inner--active .q-radio__icon { color: #1a1a1a !important; }
.q-radio .q-icon { color: #8a8a8a !important; }
.q-radio__icon { color: #b5b3af !important; }

.q-btn-toggle .q-btn { background: transparent !important; color: #6a6a6a !important; border-color: #d5d3cf !important; }
.q-btn-toggle .q-btn--active { background: #1a1a1a !important; color: #fff !important; }

.q-uploader__header, .q-uploader__list .q-item { color: #2a2a2a !important; }
.q-expansion-item__icon { color: #6a6a6a !important; }

/* Dialog */
.q-dialog .q-card { background: #ffffff !important; }

/* 队列状态色 */
.status-pending { color: #8a8a8a !important; }
.status-running { color: #1a1a1a !important; }
.status-done { color: #2a7a2a !important; }
.status-error { color: #a02020 !important; }
"""


# ============ 文件上传 ============

UPLOAD_TMP_FILES = []  # 上传的文件列表（未入队）


def add_upload_file(name: str, content: bytes):
    """添加上传的文件到待处理列表"""
    tmp = v2t.CACHE_DIR / name
    tmp.write_bytes(content)
    size_mb = tmp.stat().st_size / 1024 / 1024
    UPLOAD_TMP_FILES.append({"name": name, "path": str(tmp), "size": size_mb})


def add_queue_files(mode: str, engine: str = None, deep: bool = False):
    """把待上传文件加入处理队列"""
    global QUEUE
    for f in UPLOAD_TMP_FILES:
        QUEUE.append({
            "name": f["name"],
            "path": f["path"],
            "size": f["size"],
            "mode": mode,
            "engine": engine,
            "deep": deep,
            "status": "pending",
            "progress": 0,
            "result": None,
            "error": None,
        })
    UPLOAD_TMP_FILES.clear()
    queue_area.refresh()
    if not QUEUE_RUNNING:
        asyncio.create_task(run_queue())


# ============ 批量队列 ============

async def run_queue():
    """顺序处理队列里的所有任务"""
    global QUEUE_RUNNING, TOTAL_PROGRESS
    QUEUE_RUNNING = True
    total = len(QUEUE)

    for i, item in enumerate(QUEUE):
        if item["status"] in ("done", "error"):
            continue

        item["status"] = "running"
        item["progress"] = 5
        queue_area.refresh()

        try:
            result = await asyncio.to_thread(
                process_single_video,
                Path(item["path"]),
                mode=item["mode"],
                engine=item["engine"],
                deep=item["deep"],
            )
            item["status"] = "done"
            item["progress"] = 100
            item["result"] = result
            # 写历史
            hist = app.storage.user.get("history", [])
            hist.insert(0, {"name": item["name"], "mode": item_mode_label(item), "output": str(result["output_path"])})
            app.storage.user["history"] = hist[:100]
        except Exception as e:
            item["status"] = "error"
            item["error"] = str(e)

        TOTAL_PROGRESS = int((i + 1) / total * 100)
        queue_area.refresh()
        history_area.refresh()

    QUEUE_RUNNING = False
    queue_area.refresh()


def item_mode_label(item: dict) -> str:
    if item["mode"] == "transcript":
        return "逐字稿"
    if item["mode"] == "deep":
        engine_label = {"doubao": "豆包", "frames": "关键帧", "local": "本地"}.get(item["engine"], item["engine"])
        return f"深度拆解 / {engine_label}"
    return item["mode"]


def clear_queue_done():
    """清除已完成的任务"""
    global QUEUE
    QUEUE = [q for q in QUEUE if q["status"] not in ("done", "error")]
    queue_area.refresh()


def clear_queue_all():
    """清空队列"""
    global QUEUE, QUEUE_RUNNING
    if QUEUE_RUNNING:
        return
    QUEUE = []
    queue_area.refresh()


# ============ 各 refreshable 分区 ============

@ui.refreshable
def queue_area():
    """队列进度面板"""
    if not QUEUE:
        return

    total = len(QUEUE)
    done = sum(1 for q in QUEUE if q["status"] == "done")
    running = sum(1 for q in QUEUE if q["status"] == "running")

    with ui.card().classes("w-full p-5 mt-4"):
        with ui.row().classes("items-center justify-between w-full mb-3"):
            ui.label(f"处理队列（{done}/{total}）").classes("text-sm font-medium")
            with ui.row().classes("gap-2"):
                ui.button("清除已完成", on_click=clear_queue_done).props("flat size=sm dense")
                if not QUEUE_RUNNING:
                    ui.button("清空", on_click=clear_queue_all).props("flat size=sm dense")

        ui.linear_progress(value=TOTAL_PROGRESS / 100).props("inset").classes("mb-3")

        with ui.column().classes("w-full gap-2"):
            for item in QUEUE:
                with ui.row().classes("items-center justify-between w-full py-2"):
                    with ui.row().classes("items-center gap-3 flex-1 min-w-0"):
                        status_icon = {"pending": "schedule", "running": "play_arrow", "done": "check_circle", "error": "error"}.get(item["status"], "schedule")
                        ui.icon(status_icon, size="sm").classes(f"status-{item['status']} flex-shrink-0")
                        with ui.column().classes("gap-0 flex-1 min-w-0"):
                            ui.label(item["name"]).classes("text-sm truncate")
                            ui.label(item_mode_label(item)).classes("text-xs opacity-40")
                    if item["status"] == "running":
                        ui.label(f"{item['progress']}%").classes("text-xs opacity-60 w-10 text-right")
                    elif item["status"] == "done":
                        ui.button("查看", icon="visibility", on_click=lambda item=item: view_result(item["result"]["output_path"])).props("flat size=sm dense")
                    elif item["status"] == "error":
                        ui.label(item.get("error", "失败")[:20]).classes("text-xs status-error")


@ui.refreshable
def files_upload_area():
    """待上传文件列表"""
    if not UPLOAD_TMP_FILES:
        return
    with ui.column().classes("w-full gap-2 mt-3"):
        for i, f in enumerate(UPLOAD_TMP_FILES):
            with ui.row().classes("items-center justify-between w-full p-3 rounded bg-[#f7f5f1]"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon("movie", size="sm").classes("opacity-40")
                    with ui.column().classes("gap-0"):
                        ui.label(f["name"]).classes("text-sm")
                        ui.label(f"{f['size']:.1f} MB").classes("text-xs opacity-40")
                ui.button(icon="close", on_click=lambda i=i: (UPLOAD_TMP_FILES.pop(i), files_upload_area.refresh())).props("flat size=sm dense").classes("opacity-40")


@ui.refreshable
def history_area():
    """历史记录（从 output 目录扫）"""
    items = scan_output_dir()
    if not items:
        with ui.column().classes("items-center w-full py-16 gap-3"):
            ui.icon("history", size="lg").classes("opacity-20")
            ui.label("暂无记录").classes("text-sm opacity-40")
        return

    with ui.column().classes("w-full gap-2"):
        for item in items[:30]:
            with ui.row().classes("items-center justify-between w-full p-3 rounded bg-[#f7f5f1] hover:bg-[#f0eee9] cursor-pointer transition-colors"):
                with ui.column().classes("gap-0"):
                    ui.label(item["name"]).classes("text-sm")
                    ui.label(item["mode"]).classes("text-xs opacity-40")
                with ui.row().classes("gap-1"):
                    ui.button("查看", icon="visibility", on_click=lambda item=item: view_result(item["output"])).props("flat size=sm dense")
                    ui.button("打开", icon="folder_open", on_click=lambda item=item: open_result(item["output"])).props("flat size=sm dense")


# ============ 结果详情 ============

result_dialog = None


def view_result(md_path: str):
    """打开结果详情对话框"""
    global CURRENT_RESULT, result_dialog
    CURRENT_RESULT = md_path
    if result_dialog:
        result_dialog.delete()
    with ui.dialog(value=True) as result_dialog:
        with ui.card().classes("w-full max-w-2xl"):
            with ui.row().classes("items-center justify-between w-full mb-4"):
                ui.label(Path(md_path).name.replace("_", " ")).classes("text-h6")
                ui.button(icon="close", on_click=result_dialog.close).props("flat size=sm dense")

            data = read_result_preview(md_path)

            tabs = ["全文"]
            if data.get("has_summary"):
                tabs.insert(0, "摘要")
            if data.get("has_transcript"):
                tabs.insert(1 if data.get("has_summary") else 0, "逐字稿")

            with ui.tabs() as tab:
                for t in tabs:
                    ui.tab(t)

            with ui.tab_panels(tab, value=tabs[0]).classes("w-full"):
                for t in tabs:
                    with ui.tab_panel(t).classes("w-full"):
                        if t == "摘要":
                            ui.label(data.get("summary", "")).classes("text-sm leading-6").style("white-space: pre-wrap;")
                        elif t == "逐字稿":
                            with ui.scroll_area().classes("w-full h-80"):
                                ui.label(data.get("transcript", "")).classes("text-sm leading-6").style("white-space: pre-wrap;")
                        else:  # 全文
                            with ui.scroll_area().classes("w-full h-96"):
                                ui.label(data.get("full_text", "")).classes("text-sm leading-6").style("white-space: pre-wrap;")

            with ui.row().classes("justify-end gap-2 mt-4 pt-4 border-t border-[#e8e6e2]"):
                ui.button("在访达中显示", icon="folder_open", on_click=lambda: open_result(md_path)).props("flat size=sm")
                ui.button("导出到 Obsidian", icon="book", on_click=lambda: export_to_obsidian(md_path)).props("outline size=sm")


def export_to_obsidian(md_path: str):
    """导出到 Obsidian"""
    src = Path(md_path)
    if not src.exists():
        ui.notify("文件不存在", type="negative")
        return

    vault = cfg.OBSIDIAN_VAULT
    if not vault.exists():
        ui.notify(f"找不到 Obsidian vault: {vault}", type="negative")
        return

    target_dir = vault / cfg.DEFAULT_OBSIDIAN_FOLDER
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / src.name

    # 复制文件
    import shutil
    shutil.copy2(src, target)
    ui.notify(f"已导出到 Obsidian：{cfg.DEFAULT_OBSIDIAN_FOLDER}", type="positive")


# ============ 工具函数 ============

def open_result(path: str):
    if path and Path(path).exists():
        subprocess.run(["open", "-R", str(path)])


# ============ 页面 ============

@ui.page("/")
def index():
    ui.add_css(CSS)
    ui.add_head_html('<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">')
    ui.colors(
        primary="#1a1a1a",
        secondary="#6a6a6a",
        accent="#3a3a3a",
        info="#5a5a5a",
        positive="#2a7a2a",
        negative="#a02020",
        warning="#8a6a20",
    )

    # 从 storage 加载配置
    _saved_cfg = app.storage.user.get("config", {})
    if _saved_cfg:
        cfg.set_gui_config(_saved_cfg)
        import importlib
        importlib.reload(v2t)

    def go(v):
        global VIEW
        VIEW = v
        page_content.refresh()

    # 顶栏
    with ui.column().classes("w-full min-h-screen"):
        with ui.row().classes("w-full items-center justify-between px-6 py-4 border-b border-[#e5e3df]"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("movie", size="sm").classes("opacity-60")
                ui.label("VideoToText").classes("text-sm font-medium")
            with ui.row().classes("items-center gap-1"):
                ui.button(icon="history", on_click=lambda: go("history")).props("flat size=sm dense")
                ui.button(icon="settings", on_click=lambda: go("settings")).props("flat size=sm dense")

        with ui.column().classes("flex-1 w-full max-w-3xl mx-auto px-6 py-8"):
            page_content()

        with ui.row().classes("w-full justify-center items-center gap-2 py-4 border-t border-[#e5e3df]"):
            ui.label("v0.4").classes("text-xs opacity-40")
            ui.label("·").classes("text-xs opacity-20")
            ui.label("本地优先 · 数据不上传").classes("text-xs opacity-40")


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
                ui.button("历史记录", icon="history", on_click=lambda: (globals().update(VIEW="history"), page_content.refresh())).props("flat outline size=sm")

    # ===== 子页面通用头部 =====
    if VIEW != "home":
        with ui.row().classes("items-center gap-2 w-full mb-4"):
            ui.button("返回", icon="arrow_back", on_click=lambda: (globals().update(VIEW="home"), page_content.refresh())).props("flat size=sm dense").classes("p-0")

    # ===== 逐字稿页 =====
    if VIEW == "transcript":
        ui.label("逐字稿").classes("text-h6 mb-4")

        # 上传区
        with ui.card().classes("w-full p-6"):
            ui.label("添加视频").classes("text-sm font-medium mb-3")
            async def on_upload_transcript(e):
                content = await e.file.read()
                add_upload_file(e.file.name, content)
                files_upload_area.refresh()
            ui.upload(label="拖拽视频文件或文件夹到这里，或点击选择", auto_upload=True, multiple=True, on_upload=on_upload_transcript).props("flat bordered no-thumbnails").classes("w-full")

        files_upload_area()

        # 批量设置
        if UPLOAD_TMP_FILES:
            with ui.card().classes("w-full p-6"):
                ui.label("导出设置").classes("text-sm font-medium mb-3")
                with ui.row().classes("gap-6 flex-wrap"):
                    ui.switch("SRT 字幕", value=True)
                    ui.switch("TXT 纯文本", value=True)
                    ui.switch("带时间戳", value=True)

            ui.button(f"开始转写（{len(UPLOAD_TMP_FILES)} 个）", icon="play_arrow", on_click=lambda: start_batch("transcript")).props("unelevated").classes("px-8 py-3 mt-2")

        queue_area()
        history_area()

    # ===== 深度拆解页 =====
    if VIEW == "deep":
        ui.label("深度拆解").classes("text-h6 mb-4")

        # 上传区
        with ui.card().classes("w-full p-6"):
            ui.label("添加视频").classes("text-sm font-medium mb-3")
            async def on_upload_deep(e):
                content = await e.file.read()
                add_upload_file(e.file.name, content)
                files_upload_area.refresh()
            ui.upload(label="拖拽视频文件或文件夹到这里，或点击选择", auto_upload=True, multiple=True, on_upload=on_upload_deep).props("flat bordered no-thumbnails").classes("w-full")

        files_upload_area()

        if UPLOAD_TMP_FILES:
            with ui.card().classes("w-full p-6"):
                ui.label("拆解引擎").classes("text-sm font-medium mb-4")

                def set_engine(e):
                    global ENGINE
                    ENGINE = e.value
                ui.radio({
                    "doubao": "豆包视频理解 — 质量最高，理解动态画面和动作",
                    "frames": "关键帧 + VLM — 静态画面理解，便宜",
                    "local": "完全本地 — 不花钱，本地模型跑",
                }, value=ENGINE, on_change=set_engine).props("inline label-color").classes("w-full")

                ui.separator().classes("my-4")
                ui.label("拆解深度").classes("text-sm font-medium mb-3")

                def set_depth(e):
                    global DEPTH
                    DEPTH = e.value
                ui.toggle(["standard", "deep"], value=DEPTH, on_change=set_depth)
                ui.label("标准：摘要+章节+金句 ｜ 深度：+叙事+新概念+反常识").classes("text-xs opacity-40")

            with ui.expansion("高级选项", icon="settings").classes("w-full"):
                with ui.column().classes("gap-4 w-full"):
                    ui.switch("说话人分离", value=False)
                    ui.switch("导出到 Obsidian", value=False)

            ui.button(f"开始拆解（{len(UPLOAD_TMP_FILES)} 个）", icon="play_arrow", on_click=lambda: start_batch("deep")).props("unelevated").classes("px-8 py-3 mt-2")

        queue_area()
        history_area()

    # ===== 历史页 =====
    if VIEW == "history":
        ui.label("历史记录").classes("text-h6 mb-1")
        ui.label(f"共 {len(scan_output_dir())} 条").classes("text-xs opacity-40 mb-4")
        history_area()

    # ===== 设置页 =====
    if VIEW == "settings":
        ui.label("设置").classes("text-h6 mb-1")
        ui.label("配置保存到本地，不上传").classes("text-xs opacity-40 mb-4")

        def save_config():
            saved = {}
            for section in cfg.CONFIG_FIELDS:
                for item in section["items"]:
                    key = item["key"]
                    val = input_refs[key].value
                    if val:
                        saved[key] = val
            app.storage.user["config"] = saved
            cfg.set_gui_config(saved)
            import importlib
            importlib.reload(v2t)
            ui.notify("已保存，立即生效", type="positive")

        input_refs = {}
        current_cfg = app.storage.user.get("config", {})

        for section in cfg.CONFIG_FIELDS:
            with ui.card().classes("w-full p-5 mb-4"):
                ui.label(section["section"]).classes("text-sm font-medium mb-4")
                with ui.column().classes("w-full gap-4"):
                    for item in section["items"]:
                        key = item["key"]
                        val = current_cfg.get(key, "") or cfg._get(key, item["default"])
                        placeholder = "••••••••" if item["type"] == "password" and val else ""
                        inp = ui.input(
                            label=item["label"],
                            value=val if item["type"] != "password" else "",
                            password=item["type"] == "password",
                            password_toggle_button=item["type"] == "password",
                        ).props("outlined dense").classes("w-full")
                        if placeholder:
                            inp.props(f'placeholder="{placeholder}"')
                        input_refs[key] = inp

        ui.button("保存设置", icon="save", on_click=save_config).props("unelevated").classes("px-8 py-3")


# ============ 批量启动 ============

def start_batch(mode: str):
    """启动批量处理"""
    engine = ENGINE if mode == "deep" else None
    deep = DEPTH == "deep"
    add_queue_files(mode, engine, deep)
    ui.notify(f"已加入 {len([q for q in QUEUE if q['status'] == 'pending'])} 个任务到队列", type="info")


# ============ 启动 ============



# ============ 单个视频处理 ============

def process_single_video(video_path: Path, mode: str, engine: str = None, deep: bool = False) -> dict:
    """处理单个视频，返回结果字典（兼容 GUI 显示）"""
    cache_key = v2t.file_hash(video_path)
    info = v2t.probe_video(video_path)

    segments = []
    frames_desc = []
    video_desc = None

    # 转写
    if info["has_audio"]:
        audio_path = v2t.extract_audio(video_path, cache_key)
        transcript = v2t.transcribe(audio_path, cache_key, cfg.WHISPER_MODEL)
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
    output_json = v2t.OUTPUT_DIR / f"{video_path.stem}_{mode_suffix}.json"
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
        dark=False,
        native=False,
        window_size=(900, 750),
        reload=False,
        storage_secret="videotext-gui-secret",
    )
