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
import re
import shutil
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
KINDS = {"transcribe", "storyboard", "digest", "distill", "ocr"}
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
        CREATE TABLE IF NOT EXISTS reasoning_approvals (
            job_id TEXT PRIMARY KEY,
            source_job_id TEXT NOT NULL,
            media_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            approved_at TEXT NOT NULL
        );
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
        raise ValueError("文件夹仅支持知识蒸馏；单视频支持转写、OCR、故事板及证据汇总")
    engine = "none" if kind in ("ocr", "storyboard") else resolve_engine(engine)
    job_id = uuid.uuid4().hex[:20]
    with _lock, _db() as con:
        con.execute(
            "INSERT INTO jobs(id,media_id,kind,engine,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (job_id, media_id, kind, engine, "queued", now(), now()),
        )
    start_worker()
    return get_job(job_id)


def submit_reasoning(media_id: str, source_job_id: str, consent: bool = False) -> dict:
    """User-initiated opt-in job. Generic Agent submit_job cannot create these."""
    if not consent:
        raise PermissionError("必须明确确认文字证据传给推理 API")
    from v2t.workbench_reasoning import provider_info
    if not provider_info().get("configured"):
        raise ValueError("请先在能力中心配置推理 API")
    source = get_job(source_job_id)
    if not source or source["media_id"] != media_id or source["kind"] != "digest" or source["state"] != "done":
        raise ValueError("必须先完成该视频的本地证据汇总")
    job_id = uuid.uuid4().hex[:20]
    with _lock, _db() as con:
        con.execute(
            "INSERT INTO jobs(id,media_id,kind,engine,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (job_id, media_id, "reason", "explicit-api", "queued", now(), now()),
        )
        con.execute(
            "INSERT INTO reasoning_approvals(job_id,source_job_id,media_id,scope,approved_at) VALUES(?,?,?,?,?)",
            (job_id, source_job_id, media_id, "asr_ocr_text_only", now()),
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
            {"name": "Apple Vision OCR", "status": "available" if sys.platform == "darwin" and shutil.which("swiftc") else "unavailable"},
            {"name": "VLM scene analysis", "status": "not_integrated"},
            {"name": "Evidence-only reasoning API", "status": "explicit_opt_in"},
            {"name": "MCP", "status": "optional_adapter"},
        ],
    }


def _staged_input(media: dict) -> str:
    path = Path(media["source"])
    if media["kind"] == "folder" and not path.is_dir():
        raise FileNotFoundError(path)
    if media["kind"] == "video" and not path.is_file():
        raise FileNotFoundError(path)
    # CLI cache keys now include resolved file identity. Avoid needless symlinks.
    return str(path)


def _cli(kind: str, source: str, engine: str, media_id: str = "") -> dict:
    cmd = [sys.executable, str(ROOT / "cli.py"), kind, source]
    if media_id:
        cmd += ["--category", "dre-" + media_id]
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


def _ocr_video(source: str, media_id: str) -> dict:
    """Native Apple Vision OCR at adaptive FPS. Frames retain actual ffmpeg PTS where available.

    OCR sampling is not exhaustive of transient text; expose sampling metadata.
    """
    if sys.platform != "darwin":
        raise RuntimeError("Apple Vision OCR 仅支持 macOS")
    compiler = shutil.which("swiftc")
    if not compiler:
        raise RuntimeError("缺少 swiftc：请安装 Xcode Command Line Tools")
    from v2t import ffmpeg as ff
    swift_file = ROOT / "native" / "apple_vision" / "ocr.swift"
    binary = STATE / "dre-vision-ocr"
    if not binary.exists() or binary.stat().st_mtime < swift_file.stat().st_mtime:
        compile_result = subprocess.run(
            [compiler, "-O", str(swift_file), "-o", str(binary)],
            capture_output=True, text=True, timeout=240,
        )
        if compile_result.returncode:
            raise RuntimeError("Apple Vision 构建失败：" + compile_result.stderr[-1000:])
    media_path = Path(source)
    duration = float(ff.probe(media_path).get("duration") or 0.0)
    if duration <= 0:
        raise RuntimeError("无法读取视频时长，OCR 不执行")
    # Up to 1200 frames: ~1 FPS for videos under 20 minutes.
    step = max(1.0, duration / 1200.0)
    frame_dir = STATE / "ocr_frames" / media_id
    frame_dir.mkdir(parents=True, exist_ok=True)
    signature = f"{media_id}-{duration:.3f}-{step:.4f}"
    manifest = frame_dir / "manifest.json"
    images = sorted(frame_dir.glob("frame_*.jpg"))
    times = []
    if manifest.exists():
        try:
            old = json.loads(manifest.read_text())
            if old.get("signature") == signature and len(old.get("times", [])) == len(images):
                times = old["times"]
        except (ValueError, OSError):
            pass
    if not times:
        for img in images:
            img.unlink()
        cmd = [
            "ffmpeg", "-hide_banner", "-y", "-i", str(media_path),
            "-vf", f"fps=1/{step:.5f},scale=960:-2,showinfo",
            "-q:v", "4", str(frame_dir / "frame_%06d.jpg"),
        ]
        proc = ff.run(cmd, timeout=6 * 3600)
        if proc.returncode:
            raise RuntimeError("视频抽帧失败：" + proc.stderr[-900:])
        images = sorted(frame_dir.glob("frame_*.jpg"))
        times = [float(m.group(1)) for line in proc.stderr.splitlines()
                 if (m := re.search(r"\bpts_time:\s*([0-9.eE+-]+)", line))]
        pts_source = "video_pts" if len(times) == len(images) else "estimated"
        if len(times) != len(images):
            times = [i * step for i in range(len(images))]
        manifest.write_text(json.dumps({"signature": signature, "times": times,
                                         "pts_source": pts_source}), encoding="utf-8")
    else:
        pts_source = json.loads(manifest.read_text()).get("pts_source", "estimated")
    if not images:
        raise RuntimeError("没有抽取到任何视频帧")
    observations = []
    for idx, image in enumerate(images):
        proc = subprocess.run([str(binary), str(image)], capture_output=True, text=True, timeout=90)
        if proc.returncode:
            observations.append({"time": times[idx], "error": proc.stderr[-280:], "items": []})
            continue
        try:
            items = json.loads(proc.stdout)["items"]
        except (KeyError, ValueError):
            items = []
        observations.append({
            "time": round(times[idx], 3),
            "items": [x for x in items if x.get("text", "").strip()],
        })
    # Preserve all frame-level evidence; merge identical text only for the overview.
    segments = []
    for obs in observations:
        content = " | ".join(item["text"] for item in obs["items"])
        if not content:
            continue
        t = obs["time"]
        if segments and segments[-1]["text"] == content and t - segments[-1]["end"] <= step * 1.6:
            segments[-1]["end"] = round(t + step, 3)
        else:
            segments.append({"start": t, "end": round(min(duration, t + step), 3),
                             "text": content, "frame_index": len(segments)})
    return {
        "ocr_segments": segments,
        "frame_observations": observations,
        "frame_count": len(images),
        "sample_interval_seconds": round(step, 4),
        "timestamp_source": pts_source,
        "coverage": "sampled_not_exhaustive",
        "engine": "apple-vision-native",
    }


def _run(job: dict) -> dict:
    media = get_media(job["media_id"])
    if not media:
        raise ValueError("媒体被删除")
    if job["kind"] == "reason":
        with _db() as con:
            approval = con.execute(
                "SELECT * FROM reasoning_approvals WHERE job_id=?", (job["id"],)
            ).fetchone()
        if not approval or approval["media_id"] != media["id"] or approval["scope"] != "asr_ocr_text_only":
            raise PermissionError("找不到有效的数据外发授权")
        src_job = get_job(approval["source_job_id"])
        if not src_job or src_job["state"] != "done" or src_job["media_id"] != media["id"]:
            raise RuntimeError("原始证据任务不可用")
        from v2t.workbench_reasoning import generate
        return generate(json.loads(src_job["result"]), media["title"])
    source = _staged_input(media)
    if job["kind"] == "ocr":
        return _ocr_video(source, media["id"])
    if job["kind"] == "digest":
        # Legacy digest invokes cloud summarization based on on-disk .env.
        # Preserve local-only privacy by composing only explicitly local abilities.
        transcript = _cli("transcribe", source, job["engine"], media["id"])
        shots = _cli("storyboard", source, job["engine"], media["id"])
        ocr, ocr_status = {}, "UNAVAILABLE"
        if sys.platform == "darwin" and shutil.which("swiftc"):
            try:
                ocr = _ocr_video(source, media["id"])
                ocr_status = "DONE"
            except Exception as exc:
                ocr_status = "ERROR: " + str(exc)[:180]
        return {
            "segments": transcript.get("segments", []),
            "storyboard": shots,
            "ocr_segments": ocr.get("ocr_segments", []),
            "ocr_status": ocr_status,
            "analysis_status": "NOT_INFERRED",
            "note": "本地 ASR / OCR / 故事板证据汇总；没有进行云端 LLM 推理",
        }
    return _cli(job["kind"], source, job["engine"], media["id"])


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
