"""Offline contract tests for DRE Workbench.

Run with: python tests/test_workbench_service.py
No real ASR inference, cloud account or running web server required.
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v2t import workbench_service as w

with tempfile.TemporaryDirectory(prefix="dre-workbench-") as tmp:
    base = Path(tmp)
    w.STATE = base / "state"
    w.STAGING = w.STATE / "imports"
    w.DB = w.STATE / "test.sqlite3"
    w._initialized = False
    w.initialize_schema_once()

    path = base / "sample.mp4"
    path.write_bytes(b"fake-media-for-service-tests")
    from cli import _media_cache_key
    sibling = base / "other"
    sibling.mkdir()
    (sibling / "sample.mp4").write_bytes(b"different-video-same-filename")
    assert _media_cache_key(path) != _media_cache_key(sibling / "sample.mp4")
    media = w.import_media(str(path))
    assert media["kind"] == "video"
    assert w.import_media(str(path))["id"] == media["id"]
    assert len(w.list_media()) == 1
    assert w.get_media(media["id"])["source"] == str(path)

    (base / "invalid.txt").write_text("not media")
    try:
        w.import_media(str(base / "invalid.txt"))
        raise AssertionError("txt should not be accepted")
    except ValueError:
        pass

    old_resolve, old_start = w.resolve_engine, w.start_worker
    w.resolve_engine = lambda engine: "faster-whisper"
    w.start_worker = lambda: None
    try:
        job = w.submit_job(media["id"], "transcribe")
        assert job["state"] == "queued"
        assert job["engine"] == "faster-whisper"
        assert len(w.list_jobs(media["id"])) == 1
        assert w.cancel_job(job["id"])["state"] == "cancelled"
        retried = w.retry_job(job["id"])
        assert retried["id"] != job["id"] and retried["state"] == "queued"
        try:
            w.submit_job(media["id"], "distill")
            raise AssertionError("folder distill should reject file")
        except ValueError:
            pass
    finally:
        w.resolve_engine, w.start_worker = old_resolve, old_start

    # Failing forward: do not accidentally execute legacy remote digest.
    calls = []
    old_run = w.subprocess.run
    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if "transcribe" in cmd:
            body = {"segments":[{"start":0, "end":1, "text":"你好"}]}
        else:
            body = {"pages":[], "total_frames":0}
        return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")
    w.subprocess.run = fake_run
    try:
        result = w._run({"media_id": media["id"], "kind":"digest", "engine":"faster-whisper"})
    finally:
        w.subprocess.run = old_run
    assert result["analysis_status"] == "NOT_INFERRED"
    assert len(calls) == 2
    assert all("digest" not in command for command, _ in calls)
    assert "transcribe" in calls[0][0] and "storyboard" in calls[1][0]
    assert all("--json" in command for command, _ in calls)

    with w._db() as con:
        con.execute("UPDATE jobs SET state='running' WHERE id=?", (retried["id"],))
    w._initialized = False
    w.initialize_schema_once()
    assert w.get_job(retried["id"])["state"] == "interrupted"

print("DRE workbench service: PASS (media identity, queue, privacy, restart)")
