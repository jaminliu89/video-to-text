"""Optional Model Context Protocol v2 adapter for the running workbench.

Install: pip install 'mcp>=2,<3'
Run: python -m v2t.workbench_mcp
All media work goes through the same authenticated localhost HTTP gateway.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server import MCPServer

from v2t.workbench_service import STATE

mcp = MCPServer("DRE Media Workbench")
BASE = os.getenv("V2T_WORKBENCH_API_URL", "http://127.0.0.1:8765/api/v1").rstrip("/")
TOKEN_PATH = STATE / "api_token"


def _call(method: str, route: str, payload: dict | None = None) -> dict:
    if not TOKEN_PATH.is_file():
        raise RuntimeError("请先启动本地 Workbench：python workbench.py")
    token = TOKEN_PATH.read_text().strip()
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + route, data=body, method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Workbench API {exc.code}: {exc.read().decode()[:300]}") from exc


@mcp.tool()
def local_capabilities() -> dict:
    """Discover ASR engines, implemented abilities and their real statuses."""
    return _call("GET", "/capabilities")


@mcp.tool()
def local_media_list() -> dict:
    """List registered local media assets and their IDs."""
    return _call("GET", "/media")


@mcp.tool()
def local_media_import(path: str) -> dict:
    """Import a local path. Requires agent-allowed roots configured by the user."""
    return _call("POST", "/media", {"path": path})


@mcp.tool()
def local_media_job(media_id: str, kind: str = "transcribe", engine: str = "auto") -> dict:
    """Queue ASR, storyboard, digest or folder distillation; return job_id immediately."""
    return _call("POST", "/jobs", {"media_id": media_id, "kind": kind, "engine": engine})


@mcp.tool()
def local_media_jobs() -> dict:
    """List recent jobs. The model never needs to see full transcripts automatically."""
    return _call("GET", "/jobs")


@mcp.tool()
def local_media_job_status(job_id: str) -> dict:
    """Check status and access results of a previously submitted media job."""
    return _call("GET", "/jobs/" + job_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
