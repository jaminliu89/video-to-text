"""Explicitly opt-in, evidence-only reasoning via an OpenAI-compatible API.

Local perception and raw media are never sent. This module transmits ONLY
selected ASR/OCR text on a user-approved reasoning job, not the video itself.
"""
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from v2t.workbench_service import STATE

CONFIG = STATE / "reasoning_provider.json"


def provider_info() -> dict:
    if not CONFIG.exists():
        return {"configured": False, "model": None, "transport": None}
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        host = urllib.parse.urlparse(cfg["base_url"]).hostname
        return {
            "configured": bool(cfg.get("base_url") and cfg.get("model")),
            "model": cfg.get("model"),
            "base_url": cfg.get("base_url"),
            "transport": "local" if host in ("127.0.0.1", "localhost", "::1") else "external",
            "status": "configured_not_verified",
        }
    except (ValueError, KeyError):
        return {"configured": False, "model": None, "transport": None}


def save_provider(base_url: str, model: str, api_key: str) -> dict:
    base_url, model = base_url.strip().rstrip("/"), model.strip()
    parsed = urllib.parse.urlparse(base_url)
    local_host = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if not base_url or not model or parsed.scheme not in ("http", "https"):
        raise ValueError("请填写完整的 API 地址和模型名称")
    if parsed.scheme != "https" and not local_host:
        raise ValueError("远端推理 API 必须使用 HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("不接受带用户名密码的 URL")
    if not api_key and CONFIG.exists():
        old = json.loads(CONFIG.read_text(encoding="utf-8"))
        # Reuse a key only for the exact same host/provider endpoint.
        if old.get("base_url") == base_url:
            api_key = old.get("api_key", "")
    if not local_host and not api_key:
        raise ValueError("远端 API 需要密钥")
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps({"base_url": base_url, "model": model,
                               "api_key": api_key}, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(CONFIG)
    return provider_info()


def _chat(system: str, user: str, max_tokens: int = 3500) -> str:
    if not CONFIG.is_file():
        raise RuntimeError("未配置推理 API")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    base = cfg["base_url"].rstrip("/")
    payload = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = "Bearer " + cfg["api_key"]
    req = urllib.request.Request(base + "/chat/completions", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            body = json.loads(res.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError) as exc:
        # Never log raw request payloads or provider credentials.
        raise RuntimeError(f"推理 API 请求失败：{type(exc).__name__}") from exc


def _source_lines(data: dict) -> list[str]:
    timeline = []
    for channel, label in (("segments", "ASR"), ("ocr_segments", "OCR")):
        for idx, item in enumerate(data.get(channel, []) or []):
            text = str(item.get("text") or "").strip()
            if text:
                t = float(item.get("start") or 0)
                timeline.append((t, f"[{label}-{idx+1:05} @ {t:.1f}s] {text}"))
    # Speech and visible text must share one chronological evidence timeline.
    timeline.sort(key=lambda x: x[0])
    return [text for _, text in timeline]


def generate(source_data: dict, media_title: str) -> dict:
    """Chunked writing. Retains the original evidence separately and cites line IDs."""
    info = provider_info()
    if not info.get("configured"):
        raise RuntimeError("推理 API 未配置")
    lines = _source_lines(source_data)
    if not lines:
        raise RuntimeError("没有可供推理的 ASR/OCR 文本证据")
    blocks, current, size = [], [], 0
    for line in lines:
        if current and size + len(line) > 6500:
            blocks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        blocks.append("\n".join(current))
    if len(blocks) > 60:
        raise RuntimeError("输入超过当前推理预算，请拆分任务；原始证据不会被裁剪")

    system = (
        "你是严谨的多模态视频证据分析员。只依据附带来源ID的文字证据。"
        "区分事实与推断，不要假装看到了没有提供的视频画面。"
        "不要创造不存在的引文、时间戳、镜头或人数。"
        "输出中文 Markdown，关键结论附 [ASR-00001] 或 [OCR-00001] 来源。"
    )
    chapters = []
    for i, block in enumerate(blocks, 1):
        prompt = (
            f"视频：{media_title}\n证据块 {i}/{len(blocks)}。\n"
            "请按事实顺序写成尽量完整的纪实章节，保留说话人原意、数字、术语、"
            "分歧与重要细节；每段附证据编号。遇到不确定性注明待核实。\n\n" + block
        )
        chapters.append(_chat(system, prompt, max_tokens=3200))
    # Do not summarize away chapters: preserve them verbatim in the final output.
    if len(chapters) > 1:
        brief = _chat(system,
                      "只用以下章节标题和摘要，写一段跨章节的结构导航。"
                      "不要取代原章节，也不要臆测未提到的画面：\n\n" +
                      "\n\n".join(ch[:750] for ch in chapters),
                      max_tokens=1300)
    else:
        brief = "单章节证据整理，无额外跨章节摘要。"
    doc = (
        f"# {media_title} · 证据驱动完整撰写\n\n"
        "## 说明\n\n本文件由用户授权的模型 API 基于本地提取的 ASR/OCR 文本生成；"
        "未向该 API 发送原视频。事实与推断应结合原始素材复核。\n\n"
        f"## 章节导航\n\n{brief}\n\n" +
        "\n\n".join(f"## 第 {i} 部分\n\n{ch}" for i, ch in enumerate(chapters, 1))
    )
    return {
        "analysis_markdown": doc,
        "evidence_lines": len(lines),
        "evidence_blocks": len(blocks),
        "provider": info.get("base_url"),
        "model": info.get("model"),
        "transport": info.get("transport"),
        "source_scope": "asr_ocr_text_only",
        "status": "DONE",
    }
