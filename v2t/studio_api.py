"""DRE Studio browser API, built on existing NiceGUI/FastAPI runtime.

Adds actual browser upload, reviewed evidence, document edits and session-safe
media streaming while keeping the existing MCP /api/v1 contract intact.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import urllib.parse
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from nicegui import app
from v2t import workbench_service as svc
from v2t import workbench_reasoning as reasoning

WEB = Path(__file__).resolve().parent.parent / "webui"
COOKIE = "dre_studio"
SESSION = secrets.token_urlsafe(40)
PORT = int(os.environ.get("V2T_WORKBENCH_PORT", "8765"))
MAX_UPLOAD = int(os.environ.get("V2T_MAX_UPLOAD_GB", "12")) * 1024**3

app.mount("/studio-assets", StaticFiles(directory=WEB), name="studio-assets")


def auth(request: Request, write: bool = False):
    if not secrets.compare_digest(request.cookies.get(COOKIE, ""), SESSION):
        raise HTTPException(status_code=401, detail="会话失效，请刷新工作台")
    if write:
        origin = request.headers.get("origin", "")
        if origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            raise HTTPException(status_code=403, detail="禁止跨站写入")
        if request.headers.get("x-dre-ui") != "1":
            raise HTTPException(status_code=403, detail="缺少本地 UI 授权")


def job_summary(job: dict) -> dict:
    return {k:v for k,v in job.items() if k != "result"} | {
        "result_available": job.get("state") == "done" and bool(job.get("result"))
    }


def require_result(job_id: str) -> tuple[dict, dict]:
    job = svc.get_job(job_id)
    if not job or job["state"] != "done":
        raise HTTPException(status_code=404, detail="任务未完成")
    try:
        return job, json.loads(job.get("result") or "{}")
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="结果数据无法解析")


def ensure_tables():
    with svc._db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS evidence_edits (
          media_id TEXT NOT NULL, job_id TEXT NOT NULL,
          channel TEXT NOT NULL, item_index INTEGER NOT NULL,
          corrected_text TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY(job_id, channel, item_index)
        );
        CREATE TABLE IF NOT EXISTS document_edits (
          job_id TEXT PRIMARY KEY, content TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """)


def edits(job_id: str) -> dict:
    ensure_tables()
    with svc._db() as db:
        rows = db.execute(
            "SELECT channel,item_index,corrected_text FROM evidence_edits WHERE job_id=?",
            (job_id,),
        ).fetchall()
    return {f"{r['channel']}:{r['item_index']}":r["corrected_text"] for r in rows}


def reviewed(job_id: str, data: dict) -> dict:
    overlay = edits(job_id)
    data = dict(data)
    for channel in ("segments","ocr_segments"):
        data[channel] = [
            dict(row, text=overlay.get(f"{channel}:{i}", row.get("text","")))
            for i,row in enumerate(data.get(channel, []) or [])
        ]
    return data


def saved_document(job_id: str, data: dict) -> str:
    ensure_tables()
    with svc._db() as db:
        row = db.execute("SELECT content FROM document_edits WHERE job_id=?", (job_id,)).fetchone()
    return row["content"] if row else str(data.get("analysis_markdown") or "")


@app.get("/")
def root_redirect():
    return RedirectResponse("/studio", status_code=307)


@app.get("/studio", response_class=HTMLResponse)
def studio():
    r = HTMLResponse((WEB/"index.html").read_text(encoding="utf-8"))
    r.set_cookie(COOKIE, SESSION, httponly=True, samesite="strict", secure=False,
                 path="/", max_age=28800)
    r.headers["Cache-Control"] = "no-store"
    r.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; "
        "media-src 'self' blob:; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'"
    )
    return r


@app.get("/ui-api/bootstrap")
def bootstrap(request: Request):
    auth(request)
    return {"product":"DRE Media Studio","mode":"local_first",
            "capabilities":svc.capabilities(),"provider":reasoning.provider_info()}


@app.get("/ui-api/library")
def library(request: Request):
    auth(request)
    jobs = svc.list_jobs()
    recent = {}
    for job in jobs:
        recent.setdefault(job["media_id"], job_summary(job))
    return {"media":[dict(item,latest_job=recent.get(item["id"])) for item in svc.list_media()]}


@app.post("/ui-api/import/path")
async def import_path(request: Request):
    auth(request,write=True)
    body = await request.json()
    try:
        return svc.import_media(str(body.get("path","")))
    except (ValueError,OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/ui-api/upload")
async def upload(request: Request):
    auth(request,write=True)
    raw_name = urllib.parse.unquote(request.headers.get("x-file-name",""))
    ext = Path(Path(raw_name).name).suffix.lower()
    if ext not in svc.SUPPORTED:
        raise HTTPException(status_code=400,detail="请选择支持的视频格式")
    folder = svc.STATE/"uploads"
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/(secrets.token_hex(16)+".part")
    size,sha = 0,hashlib.sha256()
    try:
        with path.open("wb") as dest:
            async for chunk in request.stream():
                size += len(chunk)
                if size>MAX_UPLOAD:
                    raise HTTPException(status_code=413,detail="文件超出容量限制")
                sha.update(chunk)
                dest.write(chunk)
        if not size:
            raise HTTPException(status_code=400,detail="无法导入空文件")
        final = folder/(sha.hexdigest()+ext)
        if final.exists(): path.unlink()
        else: path.replace(final)
        return svc.import_media(str(final))
    finally:
        path.unlink(missing_ok=True)


@app.get("/ui-api/media/{media_id}/stream")
def media_stream(media_id: str,request: Request):
    auth(request)
    item = svc.get_media(media_id)
    if not item or item["kind"]!="video":
        raise HTTPException(status_code=404,detail="视频不存在")
    path = Path(item["source"])
    if not path.is_file():
        raise HTTPException(status_code=404,detail="源文件已经移动")
    return FileResponse(path,content_disposition_type="inline")


@app.get("/ui-api/media/{media_id}/thumbnail")
def thumbnail(media_id: str,request: Request):
    auth(request)
    item = svc.get_media(media_id)
    if not item or item["kind"]!="video":
        raise HTTPException(status_code=404,detail="素材不存在")
    from v2t import ffmpeg as ff
    image = svc.STATE/"thumbnails"/(media_id+".jpg")
    if not image.exists():
        ff.grab_frame(Path(item["source"]),0.5,image,width=480)
    if not image.is_file():
        raise HTTPException(status_code=404,detail="没有可用的缩略图")
    return FileResponse(image,media_type="image/jpeg")


@app.get("/ui-api/jobs")
def jobs(request: Request,media_id: str|None=None):
    auth(request)
    return {"jobs":[job_summary(j) for j in svc.list_jobs(media_id)]}


@app.post("/ui-api/jobs")
async def start_job(request: Request):
    auth(request,write=True)
    body = await request.json()
    try:
        return job_summary(svc.submit_job(body.get("media_id",""),
            body.get("kind","transcribe"),body.get("engine","auto")))
    except (RuntimeError,ValueError) as exc:
        raise HTTPException(status_code=400,detail=str(exc))


@app.get("/ui-api/jobs/{job_id}/result")
def result(job_id: str,request: Request):
    auth(request)
    job,data = require_result(job_id)
    data = reviewed(job_id,data)
    if job["kind"]=="reason":
        data["analysis_markdown"]=saved_document(job_id,data)
    return {"job":job_summary(job),"data":data,"edits":edits(job_id)}


@app.post("/ui-api/jobs/{job_id}/cancel")
def cancel(job_id: str,request: Request):
    auth(request,write=True)
    job=svc.cancel_job(job_id)
    if not job: raise HTTPException(status_code=404,detail="任务不存在")
    return job_summary(job)


@app.post("/ui-api/jobs/{job_id}/retry")
def retry(job_id: str,request: Request):
    auth(request,write=True)
    try: return job_summary(svc.retry_job(job_id))
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))


@app.put("/ui-api/jobs/{job_id}/evidence")
async def correct(job_id: str,request: Request):
    auth(request,write=True)
    job,data = require_result(job_id)
    body=await request.json()
    channel=body.get("channel")
    try: index=int(body.get("index",-1))
    except (TypeError,ValueError): raise HTTPException(status_code=400,detail="无效证据序号")
    rows=data.get(channel,[]) if channel in ("segments","ocr_segments") else []
    if not 0<=index<len(rows): raise HTTPException(status_code=400,detail="找不到证据")
    content=body.get("text")
    if not isinstance(content,str) or len(content)>10000:
        raise HTTPException(status_code=400,detail="无效文字")
    ensure_tables()
    with svc._db() as db:
        db.execute("""INSERT INTO evidence_edits
          (media_id,job_id,channel,item_index,corrected_text,updated_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(job_id,channel,item_index)
          DO UPDATE SET corrected_text=excluded.corrected_text,
          updated_at=excluded.updated_at""",
          (job["media_id"],job_id,channel,index,content,svc.now()))
    return {"ok":True}


@app.put("/ui-api/jobs/{job_id}/document")
async def document_save(job_id: str,request: Request):
    auth(request,write=True)
    job,_=require_result(job_id)
    if job["kind"]!="reason":
        raise HTTPException(status_code=400,detail="这不是可编辑的推理文稿")
    body=await request.json()
    content=body.get("content")
    if not isinstance(content,str) or len(content)>2000000:
        raise HTTPException(status_code=400,detail="文稿容量超限")
    ensure_tables()
    with svc._db() as db:
        db.execute("""INSERT INTO document_edits(job_id,content,updated_at)
          VALUES(?,?,?) ON CONFLICT(job_id)
          DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at""",
          (job_id,content,svc.now()))
    return {"ok":True}


@app.get("/ui-api/provider")
def provider(request: Request):
    auth(request)
    return reasoning.provider_info()


@app.post("/ui-api/provider")
async def provider_save(request: Request):
    auth(request,write=True)
    body=await request.json()
    try: return reasoning.save_provider(str(body.get("base_url","")),
              str(body.get("model","")),str(body.get("api_key","")))
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))


@app.get("/ui-api/reason/preview")
def reason_preview(source_job_id: str,request: Request):
    auth(request)
    job,data=require_result(source_job_id)
    if job["kind"]!="digest":
        raise HTTPException(status_code=400,detail="请先完成本地证据汇总")
    from v2t.workbench_reasoning import _source_lines
    lines=_source_lines(reviewed(source_job_id,data))
    return {"provider":reasoning.provider_info(),"segments":len(lines),
            "characters":sum(len(x) for x in lines),
            "scope":"仅 ASR/OCR 文字，不包含原视频及画面"}


@app.post("/ui-api/reason")
async def reason(request: Request):
    auth(request,write=True)
    body=await request.json()
    try:
        return job_summary(svc.submit_reasoning(
          str(body.get("media_id","")),str(body.get("source_job_id","")),
          consent=body.get("consent") is True))
    except (PermissionError,ValueError) as exc:
        raise HTTPException(status_code=400,detail=str(exc))


def markdown(job: dict,data: dict) -> str:
    if job["kind"]=="reason":
        return saved_document(job["id"],data)
    lines=["# DRE 媒体证据记录","",f"- 任务：{job['id']}",
           f"- 引擎：{job['engine']}",""]
    for channel,title in (("segments","逐字稿"),("ocr_segments","画面文字（抽帧 OCR）")):
        rows=data.get(channel) or []
        if not rows: continue
        lines.extend(["## "+title,""])
        for item in rows:
            s=int(float(item.get("start",0)))
            lines.append(f"[{s//3600:02}:{s//60%60:02}:{s%60:02}] {item.get('text','')}")
        lines.append("")
    if not data.get("segments") and not data.get("ocr_segments"):
        lines.extend(["## 结构化结果",json.dumps(data,ensure_ascii=False,indent=2)])
    return "\n".join(lines)


@app.get("/ui-api/jobs/{job_id}/export")
def export(job_id: str,request: Request,format: str="md"):
    auth(request)
    job,data=require_result(job_id)
    data=reviewed(job_id,data)
    if format=="json":
        body=json.dumps(data,ensure_ascii=False,indent=2)
        mime,ext="application/json","json"
    elif format=="md":
        body=markdown(job,data)
        mime,ext="text/markdown","md"
    elif format=="txt":
        body="\n".join(i.get("text","") for i in data.get("segments",[]))
        mime,ext="text/plain","txt"
    elif format=="srt":
        def stamp(s):
            n=int(round(max(0,float(s))*1000))
            return f"{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}"
        body="\n".join(f"{i}\n{stamp(x.get('start',0))} --> {stamp(x.get('end',0))}\n{x.get('text','')}\n"
                       for i,x in enumerate(data.get("segments",[]),1))
        mime,ext="application/x-subrip","srt"
    else:
        raise HTTPException(status_code=400,detail="无效格式")
    return Response(body,media_type=mime+"; charset=utf-8",headers={
        "Content-Disposition":f'attachment; filename="dre-{job_id}.{ext}"',
        "Cache-Control":"no-store"
    })
