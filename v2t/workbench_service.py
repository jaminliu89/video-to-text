"""DRE Workbench shared execution service.

A deliberately small single-machine task engine. The existing CLI remains the
source of truth for media analysis; UI/API/MCP submit identical jobs here.
No cloud provider is selected implicitly: distillation defaults to --no-llm.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("VIDEOTOTEXT_HOME", str(Path.home() / "Library" / "Application Support" / "VideoToText"))).expanduser()
STATE = HOME / "workbench"
STAGING = STATE / "imports"
DB = STATE / "workbench.sqlite3"
SUPPORTED = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts"}
KINDS = {"transcribe", "storyboard", "digest", "distill"}
_lock = threading.RLock()
_worker: threading.Thread | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _db():
    STATE.mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=15000")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def initialize() -> None:
    with _lock, _db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS media (
            id TEXT PRIMARY KEY, title TEXT NOT NULL,
            source TEXT NOT NULL, kind TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, media_id TEXT NOT NULL,
            kind TEXT NOT NULL, engine TEXT NOT NULL,
            state TEXT NOT NULL, result TEXT, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(media_id) REFERENCES media(id)
        );
        CREATE INDEX IF NOT EXISTS jobs_by_media ON jobs(media_id, created_at DESC);
        """)
        con.execute("UPDATE jobs SET state='interrupted', updated_at=? WHERE state='running'", (now(),))


def _obj(row):
    return dict(row) if row is not None else None


def list_media() -> list[dict]:
    initialize_schema_once()
    with _db() as con:
        return [dict(x) for x in con.execute("SELECT * FROM media ORDER BY created_at DESC LIMIT 300")]


def get_media(media_id: str) -> dict | None:
    initialize_schema_once()
    with _db() as con:
        return _obj(con.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone())


def import_media(source: str) -> dict:
    """Only user-requested, existing local files/folders can be registered."""
    initialize_schema_once()
    path = Path(source).expanduser().resolve(strict=True)
    if not (path.is_dir() or (path.is_file() and path.suffix.lower() in SUPPORTED)):
        raise ValueError("请选择视频文件或包含视频的文件夹")
    if path.is_dir() and not any(p.suffix.lower() in SUPPORTED for p in path.rglob("*") if p.is_file()):
        raise ValueError("文件夹里没有支持的视频")
    stat = path.stat()
    ident = hashlib.sha256(f"{path}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()[:20]
    kind = "folder" if path.is_dir() else "video"
    with _lock, _db() as con:
        con.execute(
            "INSERT OR IGNORE INTO media(id,title,source,kind,size,created_at) VALUES(?,?,?,?,?,?)",
            (ident, path.name, str(path), kind, stat.st_size if kind == "video" else 0, now()),
        )
    return get_media(ident)


def list_jobs(media_id: str | None = None) -> list[dict]:
    initialize_schema_once()
    with _db() as con:
        if media_id:
            rows = con.execute("SELECT * FROM jobs WHERE media_id=? ORDER BY created_at DESC LIMIT 80", (media_id,))
        else:
            rows = con.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 120")
        return [dict(x) for x in rows]


def get_job(job_id: str) -> dict | None:
    initialize_schema_once()
    with _db() as con:
        return _obj(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def submit_job(media_id: str, kind: str, engine: str = "auto") -> dict:
    initialize_schema_once()
    media = get_media(media_id)
    if not media:
        raise ValueError("未知媒体资产")
    if kind not in KINDS:
        raise ValueError(f"不支持的任务: {kind}")
    if (media["kind"] == "folder") != (kind == "distill"):
        raise ValueError("文件夹仅支持知识蒸馏；单视频支持转写、故事板及解读")
    engine = resolve_engine(engine)
    job_id = uuid.uuid4().hex[:20]
    with _lock, _db() as con:
        con.execute(
            "INSERT INTO jobs(id,media_id,kind,engine,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (job_id, media_id, kind, engine, "queued", now(), now()),
        )
    start_worker()
    return get_job(job_id)


def resolve_engine(engine: str) -> str:
    from v2t import asr
    entries = {e["engine"]: e for e in asr.list_engines()}
    if engine == "auto":
        for name in ("mlx-whisper", "qwen3-asr", "faster-whisper", "sensevoice"):
            if entries.get(name, {}).get("available"):
                return name
        raise RuntimeError("未找到可用的本地 ASR 引擎")
    if not entries.get(engine, {}).get("available"):
        raise ValueError(f"ASR 引擎不可用: {engine}")
    if engine == "minutes":
        raise ValueError("当前工作台不允许自动上传音频到云端")
    if engine == "qwen3-asr":
        # The legacy adapter auto-falls back to cloud if qwen-asr is absent.
        from v2t.asr import _has_module
        if not _has_module("qwen_asr"):
            raise ValueError("Qwen3 本地依赖未安装；禁止静默切换云端")
    return engine


def capabilities() -> dict:
    from v2t import asr
    engines = asr.list_engines()
    return {
        "product": "DRE Media Workbench",
        "api_version": "v1",
        "engines": engines,
        "abilities": [
            {"name": "ASR", "status": "available" if any(e.get("available") and e.get("engine") not in ("minutes",) for e in engines) else "unavailable"},
            {"name": "Storyboard", "status": "available"},
            {"name": "Batch distillation", "status": "available"},
            {"name": "Apple Vision OCR", "status": "not_integrated"},
            {"name": "VLM scene analysis", "status": "not_integrated"},
            {"name": "MCP", "status": "optional_adapter"},
        ],
    }


def _staged_input(media: dict) -> str:
    if media["kind"] == "folder":
        return media["source"]
    path = Path(media["source"])
    if not path.is_file():
        raise FileNotFoundError(path)
    link = STAGING / f"{media['id']}{path.suffix.lower()}"
    if link.is_symlink() and link.resolve() != path.resolve():
        link.unlink()
    if not link.exists():
        link.symlink_to(path)
    return str(link)


def _cli(kind: str, source: str, engine: str) -> dict:
    cmd = [sys.executable, str(ROOT / "cli.py"), kind, source]
    if kind != "storyboard":
        cmd += ["--asr", engine]
    if engine == "qwen3-asr":
        # Explicitly choose a local weight. A model='flash' fallback uploads data.
        cmd += ["--asr-model", "0.6b"]
    if kind == "distill":
        cmd += ["--no-llm"]  # Never call an LLM configured in config.py/.env.
    cmd += ["--json"]
    env = os.environ.copy()
    for key in ("DASHSCOPE_API_KEY", "SILICONFLOW_API_KEY", "ARK_API_KEY", "DISTILL_LLM_KEY"):
        env.pop(key, None)
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=6 * 3600)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout or "任务失败")[-1600:])
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI 没有返回合法 JSON: {proc.stdout[-400:]}") from exc


def _run(job: dict) -> dict:
    media = get_media(job["media_id"])
    if not media:
        raise ValueError("媒体被删除")
    source = _staged_input(media)
    if job["kind"] == "digest":
        # Legacy digest invokes cloud summarization based on on-disk .env.
        # Preserve local-only privacy by composing local ASR + storyboard instead.
        transcript = _cli("transcribe", source, job["engine"])
        shots = _cli("storyboard", source, job["engine"])
        return {
            "segments": transcript.get("segments", []),
            "storyboard": shots,
            "analysis_status": "NOT_INFERRED",
            "note": "仅包含本地 ASR 和镜头故事板，未调用 LLM 进行解读",
        }
    return _cli(job["kind"], source, job["engine"])


def _worker_loop() -> None:
    global _worker
    while True:
        with _lock, _db() as con:
            row = con.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at ASC LIMIT 1").fetchone()
            if row is None:
                _worker = None
                return
            job = dict(row)
            con.execute("UPDATE jobs SET state='running',updated_at=? WHERE id=?", (now(), job["id"]))
        try:
            data = _run(job)
            state, result, error = "done", json.dumps(data, ensure_ascii=False), None
        except Exception as exc:
            state, result, error = "error", None, str(exc)[-2000:]
        with _lock, _db() as con:
            # Respect a cancel request: do not overwrite the cancelled state.
            con.execute(
                "UPDATE jobs SET state=?, result=?, error=?, updated_at=? WHERE id=? AND state='running'",
                (state, result, error, now(), job["id"]),
            )


def start_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="dre-media-jobs", daemon=True)
            _worker.start()


def cancel_job(job_id: str) -> dict | None:
    with _lock, _db() as con:
        con.execute(
            "UPDATE jobs SET state='cancelled', updated_at=? WHERE id=? AND state='queued'",
            (now(), job_id),
        )
    return get_job(job_id)


def retry_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job or job["state"] not in ("error", "interrupted", "cancelled"):
        raise ValueError("该任务目前不能重新提交")
    return submit_job(job["media_id"], job["kind"], job["engine"])


_initialized = False

def initialize_schema_once():
    global _initialized
    with _lock:
        if not _initialized:
            initialize()
            _initialized = True
