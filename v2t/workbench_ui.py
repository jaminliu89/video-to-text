"""DRE Media Workbench: a real product surface over the existing video2text engine.

Launch: python workbench.py
This is deliberately a separate entry point while the legacy GUI/DMG baseline
remains protected. Media analysis is executed by v2t.workbench_service.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException
from fastapi.responses import FileResponse
from nicegui import app, ui
from pydantic import BaseModel

from v2t import workbench_service as svc
from v2t import workbench_reasoning as reasoning

svc.initialize_schema_once()
TOKEN_FILE = svc.STATE / "api_token"
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(36), encoding="utf-8")
    TOKEN_FILE.chmod(0o600)
API_TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()


def authorize(authorization: str | None):
    if not authorization or not secrets.compare_digest(authorization, f"Bearer {API_TOKEN}"):
        raise HTTPException(status_code=401, detail="Token required")


class ImportPayload(BaseModel):
    path: str


class JobPayload(BaseModel):
    media_id: str
    kind: str = "transcribe"
    engine: str = "auto"


@app.get("/api/v1/capabilities")
def api_capabilities(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return svc.capabilities()


@app.get("/api/v1/media")
def api_media(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return {"media": svc.list_media()}


@app.post("/api/v1/media")
def api_import(payload: ImportPayload, authorization: str | None = Header(default=None)):
    authorize(authorization)
    allowed = [Path(x).expanduser().resolve() for x in os.environ.get("V2T_AGENT_ALLOWED_ROOTS", "").split(os.pathsep) if x.strip()]
    if not allowed:
        raise HTTPException(status_code=403, detail="请先设置 V2T_AGENT_ALLOWED_ROOTS，MCP 不能默认读取任意本地目录")
    try:
        requested = Path(payload.path).expanduser().resolve(strict=True)
        if not any(requested.is_relative_to(root) for root in allowed):
            raise HTTPException(status_code=403, detail="路径不在 Agent 授权范围内")
        return svc.import_media(str(requested))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/jobs")
def api_job_create(payload: JobPayload, authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        return svc.submit_job(payload.media_id, payload.kind, payload.engine)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/jobs")
def api_jobs(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return {"jobs": svc.list_jobs()}


@app.get("/api/v1/jobs/{job_id}")
def api_job_get(job_id: str, authorization: str | None = Header(default=None)):
    authorize(authorization)
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Status requests must not stuff an entire long transcript into Agent context.
    job.pop("result", None)
    job["result_available"] = job["state"] == "done"
    return job


@app.get("/api/v1/jobs/{job_id}/result")
def api_job_result(job_id: str, offset: int = 0, limit: int = 50,
                   channel: str = "segments", authorization: str | None = Header(default=None)):
    authorize(authorization)
    job = svc.get_job(job_id)
    if not job or job["state"] != "done":
        raise HTTPException(status_code=404, detail="Finished job not found")
    if channel not in ("segments", "ocr_segments"):
        raise HTTPException(status_code=400, detail="Supported channels: segments, ocr_segments")
    data = _display_result(job) or {}
    values = data.get(channel, [])
    if not isinstance(values, list):
        values = []
    offset, limit = max(0, offset), max(1, min(limit, 200))
    return {
        "job_id": job_id, "channel": channel,
        "offset": offset, "limit": limit, "total": len(values),
        "items": values[offset:offset+limit],
        "has_more": offset + limit < len(values),
    }


@app.post("/api/v1/jobs/{job_id}/cancel")
def api_job_cancel(job_id: str, authorization: str | None = Header(default=None)):
    authorize(authorization)
    job = svc.cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/workbench/media/{media_id}")
def media_stream(media_id: str, token: str = ""):
    if not secrets.compare_digest(token, API_TOKEN):
        raise HTTPException(status_code=401, detail="Token required")
    item = svc.get_media(media_id)
    if not item or item["kind"] != "video":
        raise HTTPException(status_code=404, detail="Video not registered")
    path = Path(item["source"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video missing")
    return FileResponse(path)


CSS = """
:root {
  --ink:#172629; --secondary:#627175; --canvas:#f4f5f2;
  --line:#e2e7e4; --mint:#0c806d; --mintlight:#e7f4ef;
}
body { background:var(--canvas); color:var(--ink); font-family:
  -apple-system,BlinkMacSystemFont,'PingFang SC','Noto Sans CJK SC',sans-serif; }
.q-page-container { padding:0!important; }
.v2t-shell { min-height:100vh; width:100%; align-items:stretch; flex-wrap:nowrap!important; gap:0!important; }
.v2t-sidebar { width:242px; min-width:242px; min-height:100vh;
  position:sticky; top:0; align-self:flex-start; height:100vh;
  background:#152a2d; color:#eef5f2; padding:23px 15px; }
.v2t-brand { font-size:18px; font-weight:750; letter-spacing:-.6px; color:#fff; }
.v2t-brand-desc { font-size:11px; letter-spacing:1.5px; color:#8fa9a6; margin-top:-3px; }
.v2t-nav { margin:25px 0 10px; gap:5px; }
.v2t-nav-btn { justify-content:flex-start!important; width:100%!important; padding:10px 12px!important;
  border-radius:10px!important; text-align:left!important; font-weight:500; color:#a9c0bc!important; }
.v2t-nav-active { color:#fff!important; background:#27504b!important; }
.v2t-privacy { padding:13px; background:#213d3c; border:1px solid #335453; border-radius:14px; margin-top:auto; }
.v2t-main { min-width:0; flex:1; padding:24px 34px 38px; gap:20px; }
.v2t-top { width:100%; display:flex; align-items:center; justify-content:space-between; }
.v2t-h1 { font-size:28px; font-weight:760; letter-spacing:-1.1px; line-height:1.3; }
.v2t-sub { color:var(--secondary); font-size:13px; margin-top:5px; }
.v2t-card { border:1px solid var(--line); background:#fff; border-radius:17px; box-shadow:0 3px 15px #0a292909; }
.v2t-card-pad { padding:18px; }
.v2t-label { font-size:11px; letter-spacing:1.1px; text-transform:uppercase; color:#8a9799; font-weight:700; }
.v2t-stat { font-size:20px; font-weight:700; color:var(--ink); }
.v2t-chip { padding:5px 9px; border-radius:8px; background:var(--mintlight);
  color:#087263; font-size:11px; font-weight:650; }
.v2t-muted { font-size:12px; color:var(--secondary); line-height:1.6; }
.v2t-btn-primary { background:var(--mint)!important; color:white!important; border-radius:10px!important; }
.v2t-btn-soft { background:#edf4f0!important; color:#216c5e!important; border-radius:10px!important; }
.v2t-media-row { border-bottom:1px solid #ecf0ee; padding:12px 5px; cursor:pointer; }
.v2t-media-row:hover { background:#f6faf8; border-radius:9px; }
.v2t-workspace { display:grid; grid-template-columns:minmax(190px,.8fr) minmax(350px,1.7fr) minmax(250px,1.05fr); gap:16px; width:100%; }
.v2t-screen { background:#0e171a; border-radius:13px; min-height:240px; overflow:hidden; }
.v2t-screen video { width:100%; max-height:340px; border-radius:13px; }
.v2t-evidence-row { padding:11px 10px; border-left:2px solid #c5ddd3; margin-bottom:7px;
   background:#f8faf8; border-radius:0 9px 9px 0; cursor:pointer; }
.v2t-evidence-row:hover { border-color:#0c806d; background:#eef6f2; }
.v2t-dashed { border:1.5px dashed #bdd0c6; border-radius:15px; background:#fafdfb; padding:30px 24px; }
.v2t-empty { color:#7a8e8a; text-align:center; }
.v2t-task { border-bottom:1px solid #edf0ee; padding:10px 0; }
.v2t-pill { padding:4px 8px; border-radius:7px; font-size:10px; font-weight:700; }
.v2t-done { background:#e2f5e9; color:#147a49; }
.v2t-running { background:#e9efff; color:#4261b2; }
.v2t-error { background:#fff0eb; color:#a85839; }
.v2t-queued { background:#f3f3f0; color:#667373; }
.v2t-section { font-size:15px; font-weight:730; }
.v2t-overview { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:15px; }
.q-field--outlined .q-field__control { border-radius:10px; }
.q-btn { text-transform:none; }
@media (max-width:1100px) {
  .v2t-sidebar { width:190px; min-width:190px; }
  .v2t-main { padding:20px; }
  .v2t-workspace { grid-template-columns:1fr 1.5fr; }
  .v2t-workspace > :last-child { grid-column:1/-1; }
}
@media (max-width:690px) {
  .v2t-shell { flex-direction:column!important; }
  .v2t-sidebar { position:relative; width:100%; height:auto; min-height:0; }
  .v2t-nav { flex-direction:row!important; flex-wrap:wrap; margin:12px 0; }
  .v2t-nav-btn { width:auto!important; }
  .v2t-workspace, .v2t-overview { display:flex; flex-direction:column; }
}
"""


def _friendly_state(state):
    return {
        "done": "完成", "queued": "排队中", "running": "处理中",
        "error": "失败", "interrupted": "已中断", "cancelled": "已取消",
    }.get(state, state)


def _display_result(job):
    if not job or not job.get("result"):
        return None
    try:
        return json.loads(job["result"])
    except (ValueError, TypeError):
        return None


def _human_size(value):
    if value is None:
        return "—"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def _export_job(job: dict, fmt: str) -> Path:
    """Write a durable, non-truncated artifact for the active user to download."""
    data = _display_result(job)
    if data is None:
        raise ValueError("任务尚未产生结果")
    output = svc.STATE / "exports"
    output.mkdir(parents=True, exist_ok=True)
    ext = "json" if fmt == "json" else "md"
    file = output / f"{job['id']}.{ext}"
    if fmt == "json":
        content = json.dumps(data, ensure_ascii=False, indent=2)
    elif data.get("analysis_markdown"):
        content = data["analysis_markdown"]
    else:
        lines = [
            "# DRE Media Workbench · 视频证据文档",
            "",
            f"- 任务：{job['id']}",
            f"- 类型：{job['kind']}",
            f"- 引擎：{job['engine']}",
            f"- 状态：{job['state']}",
            "",
        ]
        segments = data.get("segments") or []
        if segments:
            lines.extend(["## 原始语音转写", ""])
            for s in segments:
                t = int(float(s.get("start", 0)))
                lines.append(f"[{t//60:02}:{t%60:02}] {s.get('text','')}")
            lines.append("")
        ocr = data.get("ocr_segments") or []
        if ocr:
            lines.extend(["## 画面文字（采样 OCR）", ""])
            for s in ocr:
                t = int(float(s.get("start", 0)))
                lines.append(f"[{t//60:02}:{t%60:02}] {s.get('text','')}")
            lines.append("")
        if data.get("analysis_status"):
            lines.append(f"> AI 推理状态：{data['analysis_status']}（原始事实不可由推理覆盖）")
        if not segments and not ocr:
            lines.extend(["## 结构化结果", "", "~~~json",
                          json.dumps(data, ensure_ascii=False, indent=2), "~~~"])
        content = "\n".join(lines)
    file.write_text(content, encoding="utf-8")
    return file


@ui.page("/")
def workbench():
    ui.add_head_html(f"<style>{CSS}</style>")
    state = {"page": "studio", "selected": None, "engine": "auto", "filter": ""}
    nav_buttons = {}
    items = svc.list_media()
    if items:
        state["selected"] = items[0]["id"]

    def go(page):
        state["page"] = page
        for name, button in nav_buttons.items():
            button.classes(add="v2t-nav-active" if name == page else None,
                           remove="v2t-nav-active" if name != page else None)
        render.refresh()

    def pick(media_id):
        state["selected"] = media_id
        state["page"] = "studio"
        render.refresh()

    def import_path(path):
        try:
            asset = svc.import_media(path.strip())
            state["selected"] = asset["id"]
            state["page"] = "studio"
            ui.notify(f"已加入媒体库：{asset['title']}", type="positive")
            render.refresh()
            return True
        except Exception as exc:
            ui.notify(str(exc), type="negative")
            return False

    def start(kind):
        try:
            job = svc.submit_job(state["selected"], kind, state["engine"])
            ui.notify(f"任务已提交：{job['id']}", type="positive")
            job_list.refresh()
        except Exception as exc:
            ui.notify(str(exc), type="negative")

    with ui.row().classes("v2t-shell"):
        with ui.column().classes("v2t-sidebar"):
            with ui.row().classes("items-center no-wrap").style("gap:11px"):
                ui.icon("auto_awesome_mosaic", size="26px").style("color:#94d5c1")
                with ui.column().style("gap:0"):
                    ui.label("DRE Media").classes("v2t-brand")
                    ui.label("INTELLIGENCE WORKBENCH").classes("v2t-brand-desc")

            with ui.column().classes("v2t-nav"):
                for page, label, icon in (
                    ("studio", "分析工作台", "space_dashboard"),
                    ("library", "媒体项目库", "video_library"),
                    ("tasks", "任务与交付", "fact_check"),
                    ("capability", "能力中心", "hub"),
                ):
                    btn = ui.button(label, icon=icon, on_click=lambda p=page: go(p)).props("flat no-caps align=left")
                    btn.classes("v2t-nav-btn" + (" v2t-nav-active" if page == state["page"] else ""))
                    nav_buttons[page] = btn
            ui.space()
            with ui.column().classes("v2t-privacy").style("gap:6px"):
                with ui.row().classes("items-center").style("gap:6px"):
                    ui.icon("verified_user", size="16px").style("color:#9fdec9")
                    ui.label("本地优先").style("font-size:12px;font-weight:650")
                ui.label("媒体分析默认不会发送至云端。API/MCP 需令牌授权。").style("font-size:11px;color:#aac2bd;line-height:1.5")
            ui.label("WORKBENCH · BETA").style("font-size:10px;letter-spacing:1.6px;color:#789593;margin:12px 5px")

        with ui.column().classes("v2t-main"):
            @ui.refreshable
            def job_list():
                selected = state["selected"]
                rows = svc.list_jobs(selected if state["page"] == "studio" else None)
                if not rows:
                    ui.label("尚无分析任务").classes("v2t-muted")
                    return
                for job in rows[:10]:
                    with ui.row().classes("w-full items-center justify-between v2t-task"):
                        with ui.column().style("gap:2px;min-width:0"):
                            ui.label({"transcribe":"语音转写","storyboard":"镜头故事板","digest":"本地证据汇总","distill":"知识蒸馏","ocr":"画面文字 OCR","reason":"API 深度推理"}.get(job["kind"],job["kind"])).style("font-size:12px;font-weight:600")
                            ui.label(job["id"][:10]+" · "+job["engine"]).classes("v2t-muted")
                        with ui.column().classes("items-end").style("gap:5px"):
                            css = "v2t-done" if job["state"]=="done" else "v2t-running" if job["state"]=="running" else "v2t-error" if job["state"] in ("error","interrupted") else "v2t-queued"
                            ui.label(_friendly_state(job["state"])).classes("v2t-pill "+css)
                            if job["state"] in ("error", "interrupted"):
                                ui.button("重试", on_click=lambda j=job["id"]: retry(j)).props("flat dense size=xs")
                            elif job["state"] == "queued":
                                ui.button("取消", on_click=lambda j=job["id"]: cancel(j)).props("flat dense size=xs")

            def retry(job_id):
                try:
                    svc.retry_job(job_id)
                    job_list.refresh()
                except Exception as exc:
                    ui.notify(str(exc), type="negative")

            def cancel(job_id):
                svc.cancel_job(job_id)
                job_list.refresh()

            @ui.refreshable
            def evidence():
                asset = svc.get_media(state["selected"]) if state["selected"] else None
                if not asset:
                    ui.label("导入视频后，转写结果会在这里逐条出现。").classes("v2t-muted")
                    return
                latest = next((j for j in svc.list_jobs(asset["id"]) if j["kind"] in ("transcribe", "digest") and j["state"] == "done"), None)
                data = _display_result(latest) if latest else None
                if data and isinstance(data.get("segments"), list):
                    with ui.scroll_area().style("height:400px;width:100%"):
                        for segment in data["segments"][:2500]:
                            ts = float(segment.get("start") or 0)
                            with ui.column().classes("v2t-evidence-row").style("gap:4px;width:100%").on("click", lambda _,t=ts: video_seek(t)):
                                ui.label(f"{int(ts//60):02}:{int(ts%60):02} · ASR").style("font-size:10px;color:#12816d;font-weight:700")
                                ui.label(segment.get("text") or "").style("font-size:12px;line-height:1.65;white-space:normal")
                elif latest:
                    ui.label("分析已完成。请查看任务结果文件。").classes("v2t-muted")
                    ui.code(json.dumps(data, ensure_ascii=False, indent=2)[:1600]).classes("text-xs")
                else:
                    ui.label("请选择「开始转写」，生成带时间戳的语音证据。").classes("v2t-muted")
                ocr_job = next((j for j in svc.list_jobs(asset["id"]) if j["kind"] in ("ocr", "digest") and j["state"] == "done"), None)
                ocr_data = _display_result(ocr_job) if ocr_job else None
                if ocr_data and ocr_data.get("ocr_segments"):
                    ui.separator()
                    ui.label("画面文字 / Apple Vision").classes("v2t-section")
                    with ui.scroll_area().style("height:230px;width:100%"):
                        for segment in ocr_data["ocr_segments"][:800]:
                            ts = float(segment.get("start") or 0)
                            with ui.column().classes("v2t-evidence-row").style("gap:4px;width:100%").on("click", lambda _,t=ts: video_seek(t)):
                                ui.label(f"{int(ts//60):02}:{int(ts%60):02} · OCR").style("font-size:10px;color:#12816d;font-weight:700")
                                ui.label(segment.get("text") or "").style("font-size:12px;line-height:1.65;white-space:normal")

            video_holder = {"el": None}

            def video_seek(seconds):
                if video_holder["el"] is not None:
                    video_holder["el"].seek(seconds)

            @ui.refreshable
            def render():
                with ui.row().classes("v2t-top"):
                    with ui.column().style("gap:0"):
                        ui.label({"studio":"分析工作台","library":"媒体项目库","tasks":"任务与交付","capability":"能力中心"}[state["page"]]).classes("v2t-h1")
                        ui.label({"studio":"从视频到证据，再到可复用的知识资产。","library":"统一管理你的本地视频与批量项目。","tasks":"追踪每一个真实执行的任务和结果。","capability":"本地模型、HTTP API 与 Agent 能力共享。"}[state["page"]]).classes("v2t-sub")
                    with ui.row().classes("items-center").style("gap:8px"):
                        ui.label("● 仅本机访问").classes("v2t-chip")
                        ui.button("导入媒体", icon="add", on_click=show_import).classes("v2t-btn-primary").props("no-caps unelevated")

                if state["page"] == "library":
                    show_library()
                elif state["page"] == "tasks":
                    with ui.row().classes("w-full").style("gap:15px;align-items:start"):
                        with ui.column().classes("v2t-card v2t-card-pad").style("flex:1"):
                            ui.label("所有任务").classes("v2t-section")
                            job_list()
                elif state["page"] == "capability":
                    show_capabilities()
                else:
                    show_studio()

            def show_import():
                with ui.dialog() as d, ui.card().style("width:580px;max-width:96vw;padding:25px;border-radius:18px"):
                    ui.label("导入本地视频或项目文件夹").classes("v2t-section")
                    ui.label("输入 Mac 上的绝对路径；分析在本机执行，不会自动上传。").classes("v2t-muted")
                    entry = ui.input(label="本地文件 / 文件夹路径", placeholder="/Users/.../Movies/video.mp4").props("outlined").classes("w-full")
                    with ui.row().classes("justify-end w-full"):
                        ui.button("取消", on_click=d.close).props("flat")
                        ui.button("加入媒体库", on_click=lambda: d.close() if import_path(entry.value or "") else None).classes("v2t-btn-primary")
                d.open()

            def show_library():
                media = svc.list_media()
                with ui.column().classes("v2t-card v2t-card-pad w-full").style("gap:7px"):
                    ui.label(f"{len(media)} 个本地资产").classes("v2t-section")
                    if not media:
                        show_empty()
                    for item in media:
                        with ui.row().classes("items-center justify-between w-full v2t-media-row").on("click", lambda _,m=item["id"]: pick(m)):
                            with ui.row().classes("items-center").style("gap:12px"):
                                ui.icon("folder_open" if item["kind"] == "folder" else "movie", size="22px").style("color:#178873")
                                with ui.column().style("gap:2px"):
                                    ui.label(item["title"]).style("font-size:13px;font-weight:680")
                                    ui.label(item["source"]).classes("v2t-muted").style("max-width:65vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")
                            ui.icon("chevron_right").style("color:#9aaea5")

            def show_empty():
                with ui.column().classes("v2t-dashed items-center w-full").style("gap:11px"):
                    ui.icon("video_library", size="48px").style("color:#5da18c")
                    ui.label("从第一个视频开始").style("font-size:18px;font-weight:730")
                    ui.label("导入一个视频或课程文件夹，形成可持续积累的媒体资产。").classes("v2t-muted")
                    ui.button("选择本地媒体", icon="add", on_click=show_import).classes("v2t-btn-primary")

            def show_reason_dialog(source_job_id):
                info = reasoning.provider_info()
                if not info.get("configured"):
                    ui.notify("请先在能力中心配置 OpenAI 兼容推理 API", type="warning")
                    go("capability")
                    return
                with ui.dialog() as dialog, ui.card().style("width:580px;max-width:96vw;padding:24px;border-radius:18px"):
                    ui.label("增强推理 · 数据外发确认").classes("v2t-section")
                    ui.label(f"目标模型：{info.get('model')}").style("font-size:13px;font-weight:650")
                    ui.label(f"服务地址：{info.get('base_url')}").classes("v2t-muted")
                    ui.label("只发送该视频本地提取的 ASR/OCR 文字证据；不会发送视频原片。"
                             "生成内容会保留来源标记，原始转写不会被覆盖。").classes("v2t-muted")
                    agree = ui.checkbox("我确认将上述文字证据发送至该模型服务", value=False)
                    with ui.row().classes("justify-end w-full"):
                        ui.button("取消", on_click=dialog.close).props("flat")
                        def approved():
                            try:
                                svc.submit_reasoning(state["selected"], source_job_id, consent=agree.value)
                                dialog.close()
                                job_list.refresh()
                                ui.notify("已提交增强推理任务", type="positive")
                            except Exception as exc:
                                ui.notify(str(exc), type="negative")
                        ui.button("授权并执行", on_click=approved).classes("v2t-btn-primary")
                dialog.open()

            def show_studio():
                media = svc.get_media(state["selected"]) if state["selected"] else None
                if not media:
                    show_empty()
                    return
                jobs = svc.list_jobs(media["id"])
                with ui.row().classes("v2t-card v2t-card-pad w-full items-center justify-between").style("gap:12px"):
                    with ui.column().style("gap:3px;min-width:0"):
                        ui.label("当前媒体 / ACTIVE PROJECT").classes("v2t-label")
                        ui.label(media["title"]).style("font-size:17px;font-weight:760;max-width:65vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")
                        ui.label(("文件夹 · " if media["kind"] == "folder" else _human_size(media["size"])+" · ")+media["source"]).classes("v2t-muted")
                    with ui.row().classes("items-center").style("gap:7px"):
                        ui.label("本地执行").classes("v2t-chip")
                        ui.button("切换媒体", icon="swap_horiz", on_click=lambda: go("library")).props("flat no-caps")

                with ui.row().classes("v2t-overview w-full"):
                    for caption, value, icon in (
                        ("已运行任务", str(len(jobs)), "receipt_long"),
                        ("已完成", str(sum(j["state"]=="done" for j in jobs)), "task_alt"),
                        ("待处理", str(sum(j["state"] in ("queued","running") for j in jobs)), "schedule"),
                    ):
                        with ui.row().classes("v2t-card v2t-card-pad items-center").style("gap:14px"):
                            ui.icon(icon, size="25px").style("color:#6d9e91")
                            with ui.column().style("gap:0"):
                                ui.label(caption).classes("v2t-label")
                                ui.label(value).classes("v2t-stat")

                with ui.row().classes("w-full items-center").style("gap:9px;flex-wrap:wrap"):
                    if media["kind"] == "video":
                        ui.button("开始转写", icon="record_voice_over", on_click=lambda: start("transcribe")).classes("v2t-btn-primary").props("no-caps")
                        ui.button("镜头故事板", icon="view_module", on_click=lambda: start("storyboard")).classes("v2t-btn-soft").props("no-caps")
                        ui.button("画面文字 OCR", icon="text_snippet", on_click=lambda: start("ocr")).classes("v2t-btn-soft").props("no-caps")
                        ui.button("汇总证据", icon="description", on_click=lambda: start("digest")).classes("v2t-btn-soft").props("no-caps").tooltip("本地 ASR、OCR 和镜头证据汇总")
                        latest_digest = next((j for j in jobs if j["kind"] == "digest" and j["state"] == "done"), None)
                        if latest_digest:
                            ui.button("API 深度推理", icon="psychology", on_click=lambda j=latest_digest["id"]: show_reason_dialog(j)).classes("v2t-btn-soft").props("no-caps")

                    else:
                        ui.button("蒸馏整个文件夹", icon="auto_awesome", on_click=lambda: start("distill")).classes("v2t-btn-primary").props("no-caps")
                    ui.select(options={"auto":"自动选择","mlx-whisper":"MLX Whisper","faster-whisper":"faster-whisper","qwen3-asr":"Qwen3-ASR 本地","sensevoice":"SenseVoice"},
                              value=state["engine"], on_change=lambda e: state.update(engine=e.value)).props("dense outlined").style("width:195px")
                    ui.button(icon="refresh", on_click=lambda: (job_list.refresh(), evidence.refresh())).props("flat round").tooltip("刷新任务与证据")

                with ui.element("div").classes("v2t-workspace"):
                    with ui.column().classes("v2t-card v2t-card-pad").style("gap:13px;min-width:0"):
                        ui.label("01 / 时间轴").classes("v2t-label")
                        ui.label("分析任务").classes("v2t-section")
                        job_list()
                    with ui.column().classes("v2t-card v2t-card-pad").style("gap:13px;min-width:0"):
                        ui.label("02 / 媒体预览").classes("v2t-label")
                        if media["kind"] == "video":
                            with ui.column().classes("v2t-screen w-full"):
                                video_holder["el"] = ui.video(f"/workbench/media/{media['id']}?token={API_TOKEN}").classes("w-full")
                        else:
                            with ui.column().classes("v2t-screen w-full items-center justify-center").style("color:#a8c5ba"):
                                ui.icon("folder_copy", size="42px")
                                ui.label("文件夹项目 · 批量蒸馏")
                        ui.label("原始素材保留在本机。点击右侧证据可跳转视频时间。").classes("v2t-muted")
                        ui.separator()
                        ui.label("03 / 交付成果").classes("v2t-label")
                        latest_done = next((j for j in jobs if j["state"] == "done"), None)
                        if latest_done:
                            result = _display_result(latest_done)
                            ui.label("最近完成："+latest_done["kind"]).style("font-size:12px;font-weight:650")
                            if result:
                                text = json.dumps(result, ensure_ascii=False, indent=2)
                                with ui.scroll_area().style("height:230px;width:100%;background:#f8faf8;border-radius:9px;padding:9px"):
                                    ui.label(text[:10000]).style("font:11px/1.6 ui-monospace,monospace;white-space:pre-wrap;word-break:break-word")
                                with ui.row().style("gap:8px;flex-wrap:wrap"):
                                    ui.button("下载全文 Markdown", icon="download", on_click=lambda j=latest_done: ui.download(_export_job(j, "md"))).classes("v2t-btn-soft").props("no-caps")
                                    ui.button("下载 JSON", icon="data_object", on_click=lambda j=latest_done: ui.download(_export_job(j, "json"))).props("flat no-caps")
                                    ui.button("复制 JSON 结果", icon="content_copy", on_click=lambda t=text: ui.run_javascript("navigator.clipboard.writeText("+json.dumps(t)+")")).props("flat no-caps")
                        else:
                            ui.label("完成一次真实分析后，这里展示结果。").classes("v2t-muted")
                    with ui.column().classes("v2t-card v2t-card-pad").style("gap:13px;min-width:0"):
                        ui.label("04 / 内容证据").classes("v2t-label")
                        ui.label("原始转写 · 点击定位").classes("v2t-section")
                        evidence()
                        ui.separator()
                        ui.label("OCR 以抽帧方式识别，可能遗漏短暂文字；视觉大模型尚未接通，未识别的信息不作猜测。").classes("v2t-muted")

            def show_capabilities():
                caps = svc.capabilities()
                with ui.row().classes("w-full").style("gap:16px;align-items:stretch;flex-wrap:wrap"):
                    with ui.column().classes("v2t-card v2t-card-pad").style("flex:1;min-width:300px;gap:10px"):
                        ui.label("本地模型状态").classes("v2t-section")
                        for entry in caps["engines"]:
                            with ui.row().classes("w-full items-center justify-between v2t-media-row"):
                                with ui.column().style("gap:1px"):
                                    ui.label(entry["engine"]).style("font-weight:630;font-size:13px")
                                    ui.label(entry.get("reason") or "自动检测").classes("v2t-muted")
                                ui.label("可用" if entry.get("available") else "不可用").classes("v2t-pill "+("v2t-done" if entry.get("available") else "v2t-queued"))
                    with ui.column().classes("v2t-card v2t-card-pad").style("flex:1;min-width:300px;gap:10px"):
                        ui.label("增强推理模型").classes("v2t-section")
                        pinfo = reasoning.provider_info()
                        ui.label("为本地识别结果选择一个 OpenAI 兼容推理 API。只在你对具体视频授权后才会发送文字。").classes("v2t-muted")
                        base = ui.input("API Base URL", value=pinfo.get("base_url") or "",
                                        placeholder="https://provider.example/v1").props("outlined dense").classes("w-full")
                        model_name = ui.input("模型 ID", value=pinfo.get("model") or "",
                                              placeholder="model-name").props("outlined dense").classes("w-full")
                        secret = ui.input("API Key（同一端点留空则保留旧密钥）", password=True,
                                          password_toggle_button=True).props("outlined dense").classes("w-full")
                        def save_api():
                            try:
                                saved = reasoning.save_provider(base.value or "", model_name.value or "", secret.value or "")
                                ui.notify("配置已保存在本机（尚未验证连通性）", type="positive")
                            except Exception as exc:
                                ui.notify(str(exc), type="negative")
                        ui.button("保存推理 API", icon="save", on_click=save_api).classes("v2t-btn-soft")
                        ui.separator()
                        ui.label("Agent / API 接入").classes("v2t-section")
                        ui.label("同一条执行队列支持 Web 和带令牌的 REST API。MCP 可使用可选桥接器，不复制模型实现。").classes("v2t-muted")
                        ui.label("地址：http://127.0.0.1:8765/api/v1").style("font-size:12px")
                        ui.label("本地 API 令牌").classes("v2t-label")
                        ui.input(password=True, password_toggle_button=True, value=API_TOKEN).props("outlined readonly dense").classes("w-full")
                        ui.button("复制令牌", icon="content_copy", on_click=lambda: ui.run_javascript("navigator.clipboard.writeText("+json.dumps(API_TOKEN)+")")).classes("v2t-btn-soft")
                        ui.separator()
                        for c in caps["abilities"]:
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(c["name"]).style("font-size:12px")
                                ui.label(c["status"]).classes("v2t-muted")

            render()
            ui.timer(3.0, lambda: job_list.refresh() if state["page"] in ("studio","tasks") else None)


def run():
    svc.initialize_schema_once()
    svc.start_worker()
    ui.run(host="127.0.0.1", port=int(os.environ.get("V2T_WORKBENCH_PORT", "8765")),
           title="DRE Media Workbench", favicon="🎬", reload=False, show=True)


if __name__ == "__main__":
    run()
