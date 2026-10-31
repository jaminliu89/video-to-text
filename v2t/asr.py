"""
v2t/asr.py — 转写引擎分发

支持六种后端：
  - faster-whisper: CTranslate2（CPU 通用，跨平台，默认）
  - mlx-whisper:    Apple Silicon Metal（同模型快 5-8 倍，仅 macOS arm64）
  - qwen3-asr:      Qwen3-ASR（0.6B/1.7B，中文最强；本地 qwen-asr 或 DashScope API）
  - whisper:        本地 whisper.cpp（旧逻辑保留）
  - sensevoice:     本地 SenseVoice-Small（增强模式，标点好）
  - minutes:        飞书妙记（免费额度，需 lark-cli）

统一接口：
  transcribe(audio_path, cache_key, engine) -> list[dict]
  返回 [{"start": float, "end": float, "text": str}, ...]

引擎可用性用 `list_engines()` 查询（CLI: `python3 cli.py engines`）。
"""

import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import config as cfg

CACHE_DIR = cfg.CACHE_DIR


def _log(msg: str = "", end: str = "\n") -> None:
    """进度一律走 stderr —— stdout 留给 --json 的结构化结果

    Agent 调用方是按 stdout 解析 JSON 的，混进一行"✓ 转写已缓存"就会解析失败。
    """
    print(msg, file=sys.stderr, end=end, flush=True)

# sensevoice venv 路径（复用 sensevoice-local 的环境）
SENSEVOICE_VENV_PY = "/Users/kimliu/Projects/sensevoice-local/.venv/bin/python"
SENSEVOICE_WORKER = Path(__file__).parent / "workers" / "sensevoice_worker.py"

# mlx-whisper 的 HF 仓库名（同一份权重，MLX 量化/半精度格式）
MLX_WHISPER_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}

# Qwen3-ASR 本地权重（0.6B 约 1.2G，1.7B 约 3.5G）
QWEN3_ASR_MODELS = {
    "0.6b": "Qwen/Qwen3-ASR-0.6B",
    "1.7b": "Qwen/Qwen3-ASR-1.7B",
}

ENGINE_LABELS = {
    "faster-whisper": "faster-whisper（CPU 通用）",
    "mlx-whisper": "mlx-whisper（Apple Metal）",
    "qwen3-asr": "Qwen3-ASR（中文最强）",
    "whisper": "whisper.cpp（旧）",
    "sensevoice": "SenseVoice（标点好）",
    "minutes": "飞书妙记（云端）",
}


def transcribe(audio_path: Path, cache_key: str, engine: str = "faster-whisper",
               model_size: str = None) -> list:
    """统一转写入口，返回 segments 列表

    model_size 语义按引擎而定：
      - faster-whisper: tiny/base/small/medium/large-v3/large-v3-turbo，默认 cfg.WHISPER_MODEL
      - mlx-whisper:    同上（映射到 mlx-community 仓库），默认 cfg.MLX_WHISPER_MODEL
      - qwen3-asr:      0.6b/1.7b（本地）或 flash（DashScope API），默认 cfg.QWEN3_ASR_MODEL

    缓存键带引擎 + 模型，换模型/换引擎不会串结果。
    """
    if engine == "faster-whisper":
        model_size = model_size or cfg.WHISPER_MODEL
    elif engine == "mlx-whisper":
        model_size = model_size or cfg.MLX_WHISPER_MODEL
    elif engine == "qwen3-asr":
        model_size = model_size or cfg.QWEN3_ASR_MODEL

    suffix = f"{engine}-{model_size}" if model_size else engine
    cache_file = CACHE_DIR / f"{cache_key}_asr_{suffix}.json"
    if cache_file.exists():
        _log(f"  ✓ 转写已缓存 ({suffix})")
        return json.loads(cache_file.read_text())

    if engine == "faster-whisper":
        segments = _transcribe_faster_whisper(audio_path, cache_key, model_size)
    elif engine == "mlx-whisper":
        segments = _transcribe_mlx_whisper(audio_path, cache_key, model_size)
    elif engine == "qwen3-asr":
        segments = _transcribe_qwen3_asr(audio_path, cache_key, model_size)
    elif engine == "whisper":
        segments = _transcribe_whisper(audio_path, cache_key)
    elif engine == "sensevoice":
        segments = _transcribe_sensevoice(audio_path, cache_key)
    elif engine == "minutes":
        segments = _transcribe_minutes(audio_path, cache_key)
    else:
        raise ValueError(f"未知转写引擎: {engine}")

    cache_file.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
    return segments


def _has_module(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def list_engines() -> list:
    """列出所有引擎及其可用性（GUI 下拉 / CLI 自检用）"""
    is_apple = sys.platform == "darwin" and platform.machine() == "arm64"
    out = []

    out.append({
        "engine": "faster-whisper",
        "label": ENGINE_LABELS["faster-whisper"],
        "available": _has_module("faster_whisper"),
        "reason": "" if _has_module("faster_whisper") else "pip install faster-whisper",
        "models": ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
        "default_model": cfg.WHISPER_MODEL,
        "gpu": False,
    })

    mlx_ok = is_apple and _has_module("mlx_whisper")
    out.append({
        "engine": "mlx-whisper",
        "label": ENGINE_LABELS["mlx-whisper"],
        "available": mlx_ok,
        "reason": "" if mlx_ok else (
            "仅 macOS Apple Silicon 支持；pip install mlx-whisper"
            if not is_apple else "pip install mlx-whisper"
        ),
        "models": list(MLX_WHISPER_REPOS),
        "default_model": cfg.MLX_WHISPER_MODEL,
        "gpu": True,
    })

    qwen_local = _has_module("qwen_asr")
    qwen_api = bool(cfg.DASHSCOPE_API_KEY)
    out.append({
        "engine": "qwen3-asr",
        "label": ENGINE_LABELS["qwen3-asr"],
        "available": qwen_local or qwen_api,
        "reason": "" if (qwen_local or qwen_api) else
                  "pip install qwen-asr，或配 DASHSCOPE_API_KEY 走云端",
        "models": list(QWEN3_ASR_MODELS) + ["flash"],
        "default_model": cfg.QWEN3_ASR_MODEL,
        "gpu": False,   # 本地跑也不一定是 GPU（CUDA/MPS/CPU 自适应）
        "channel": "local" if qwen_local else ("api" if qwen_api else ""),
    })

    sv_ok = Path(SENSEVOICE_VENV_PY).exists()
    out.append({
        "engine": "sensevoice",
        "label": ENGINE_LABELS["sensevoice"],
        "available": sv_ok,
        "reason": "" if sv_ok else f"缺 venv: {SENSEVOICE_VENV_PY}",
        "models": ["sensevoice-small"],
        "default_model": "sensevoice-small",
        "gpu": False,
    })

    w_ok = shutil.which(cfg.WHISPER_CLI) is not None
    out.append({
        "engine": "whisper",
        "label": ENGINE_LABELS["whisper"],
        "available": w_ok,
        "reason": "" if w_ok else f"找不到 {cfg.WHISPER_CLI}",
        "models": ["tiny", "base", "small", "medium", "large"],
        "default_model": cfg.WHISPER_MODEL,
        "gpu": False,
    })

    m_ok = shutil.which("lark-cli") is not None
    out.append({
        "engine": "minutes",
        "label": ENGINE_LABELS["minutes"],
        "available": m_ok,
        "reason": "" if m_ok else "需要 lark-cli 并登录飞书",
        "models": ["feishu-minutes"],
        "default_model": "feishu-minutes",
        "gpu": False,
    })
    return out



def _transcribe_sensevoice(audio_path: Path, cache_key: str) -> list:
    """调用 sensevoice_worker.py 子进程"""
    if not Path(SENSEVOICE_VENV_PY).exists():
        _log(f"  ✗ sensevoice venv 不存在: {SENSEVOICE_VENV_PY}")
        _log(f"    请先在 ~/Projects/sensevoice-local 建 venv 装 funasr")
        sys.exit(1)

    out_json = CACHE_DIR / f"{cache_key}_sensevoice_raw.json"
    _log(f"  → SenseVoice 本地转写...", end=" ", flush=True)

    cmd = [
        SENSEVOICE_VENV_PY,
        str(SENSEVOICE_WORKER),
        str(audio_path),
        "--out", str(out_json),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

    if result.returncode != 0:
        _log(f"✗")
        _log(f"    stderr: {result.stderr[-500:]}")
        sys.exit(1)

    if not out_json.exists():
        _log(f"✗ 转写输出不存在")
        sys.exit(1)

    segments = json.loads(out_json.read_text())
    total_chars = sum(len(s["text"]) for s in segments)
    _log(f"✓ ({len(segments)} 段, {total_chars} 字)")
    return segments


def _transcribe_whisper(audio_path: Path, cache_key: str) -> list:
    """旧 whisper.cpp 逻辑（保留兼容）"""
    whisper_cli = cfg.WHISPER_CLI
    whisper_model_dir = cfg.WHISPER_MODEL_DIR
    model = cfg.WHISPER_MODEL

    model_file = whisper_model_dir / f"ggml-{model}.bin"
    if not model_file.exists():
        available = sorted(whisper_model_dir.glob("ggml-*.bin"))
        if not available:
            _log(f"  ✗ 找不到 whisper 模型")
            sys.exit(1)
        model_file = available[0]

    model_name = model_file.stem.replace("ggml-", "")
    output_prefix = CACHE_DIR / f"{cache_key}_whisper_{model_name}"

    _log(f"  → Whisper.cpp 转写 ({model_name})...", end=" ", flush=True)
    subprocess.run([
        whisper_cli,
        "-m", str(model_file),
        "-f", str(audio_path),
        "-oj",
        "-of", str(output_prefix),
        "-l", "zh",
    ], check=True, timeout=1800)

    json_files = sorted(CACHE_DIR.glob(f"{cache_key}_whisper_{model_name}*.json"))
    if not json_files:
        _log("✗ 找不到 whisper 输出")
        sys.exit(1)

    transcript = json.loads(json_files[-1].read_text())
    segs = transcript.get("transcription", []) or transcript.get("segments", [])

    segments = []
    for s in segs:
        start = s.get("t0", s.get("start", 0))
        end = s.get("t1", s.get("end", 0))
        text = s.get("text", s.get("content", "")).strip()
        if isinstance(start, int) and start > 1000:
            start = start / 1000.0
            end = end / 1000.0
        if text:
            segments.append({"start": float(start), "end": float(end), "text": text})

    total_chars = sum(len(s["text"]) for s in segments)
    _log(f"✓ ({len(segments)} 段, {total_chars} 字)")
    return segments


def _transcribe_minutes(audio_path: Path, cache_key: str) -> list:
    """飞书妙记（免费额度）— 调用 lark-cli"""
    out_json = CACHE_DIR / f"{cache_key}_minutes_raw.json"
    _log(f"  → 飞书妙记转写...", end=" ", flush=True)

    # 1. 上传音频到飞书云空间
    up = subprocess.run(
        ["lark-cli", "drive", "+upload", "--file", str(audio_path), "--format", "json"],
        capture_output=True, text=True, timeout=120
    )
    if up.returncode != 0:
        _log(f"✗ 上传失败: {up.stderr[-300:]}")
        return []

    up_data = json.loads(up.stdout)
    file_token = up_data.get("file_token", "")
    if not file_token:
        _log(f"✗ 没拿到 file_token")
        return []

    # 2. 生成妙记
    mk = subprocess.run(
        ["lark-cli", "minutes", "+upload", "--file-token", file_token, "--format", "json"],
        capture_output=True, text=True, timeout=120
    )
    mk_data = json.loads(mk.stdout)
    minute_token = mk_data.get("minute_token", "")

    if not minute_token:
        _log(f"✗ 没拿到 minute_token")
        return []

    # 3. 轮询读取产物（妙记处理需要时间）
    for attempt in range(10):
        notes = subprocess.run(
            ["lark-cli", "vc", "+notes", "--minute-tokens", minute_token,
             "--output-dir", str(CACHE_DIR / f"minutes_{cache_key}"), "--format", "json"],
            capture_output=True, text=True, timeout=120
        )
        if notes.returncode == 0 and "minute not ready" not in notes.stdout:
            break
        _log(f"  · 妙记处理中... ({attempt+1}/10)")
        import time; time.sleep(30)

    # 4. 解析 transcript.txt 成 segments（简单按行）
    transcript_dir = CACHE_DIR / f"minutes_{cache_key}"
    transcript_file = list(transcript_dir.glob("**/transcript.txt")) if transcript_dir.exists() else []
    if not transcript_file:
        _log(f"✗ 没找到妙记产物")
        return []

    segments = []
    for i, line in enumerate(transcript_file[0].read_text().splitlines()):
        line = line.strip()
        if line:
            segments.append({
                "start": round(i * 3.0, 2),  # 粗略时间戳（妙记 transcript.txt 不带时间戳）
                "end": round((i + 1) * 3.0, 2),
                "text": line,
            })

    total_chars = sum(len(s["text"]) for s in segments)
    _log(f"✓ ({len(segments)} 段, {total_chars} 字)")
    return segments


def _read_wav_mono(audio_path: Path):
    """读 wav 成 16k 单声道 float32 numpy 数组

    优先用标准库 wave（零依赖）；scipy 只作为兜底。
    之前这里直接 import scipy，而 requirements.txt 里并没有 scipy，
    导致默认引擎在干净环境里直接崩 —— 属于隐性依赖，这里去掉。
    """
    import numpy as np

    try:
        import wave
        with wave.open(str(audio_path), "rb") as w:
            ch = w.getnchannels()
            sw = w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw == 2:
            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sw == 4:
            data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:  # 8-bit 无符号
            data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0
        if ch > 1:
            data = data.reshape(-1, ch).mean(axis=1)
        return data
    except Exception:
        from scipy.io import wavfile  # 兜底（未安装时才会走到这里）
        _, data = wavfile.read(str(audio_path))
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        else:
            data = data.astype(np.float32)
        if data.ndim > 1:
            data = data.mean(axis=1)
        return data


def _transcribe_faster_whisper(audio_path: Path, cache_key: str, model_size: str = "base") -> list:
    """faster-whisper（CTranslate2 后端，比 whisper.cpp 快 2-4 倍）"""
    from faster_whisper import WhisperModel

    _log(f"  → faster-whisper 转写 ({model_size})...", end=" ", flush=True)

    audio_np = _read_wav_mono(audio_path)

    # Mac 上用 CPU（CTranslate2 不支持 MPS），int8 量化省内存
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments_iter, info = model.transcribe(
        audio_np,
        language="zh",
        beam_size=5,
        vad_filter=True,  # 内置 VAD，减少重复幻觉
    )

    segments = []
    for seg in segments_iter:
        text = seg.text.strip()
        if text:
            segments.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": text,
            })

    total_chars = sum(len(s["text"]) for s in segments)
    _log(f"✓ ({len(segments)} 段, {total_chars} 字)")
    return segments


# Qwen3-ASR 权重缓存（同一进程内批量转写时只加载一次）
_QWEN_MODEL_CACHE: dict = {}


def _is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _transcribe_mlx_whisper(audio_path: Path, cache_key: str,
                            model_size: str = "large-v3-turbo") -> list:
    """mlx-whisper —— 同一份 Whisper 权重跑在 Apple Metal 上

    和 faster-whisper 的区别只在执行后端：CTranslate2 int8 CPU vs MLX fp16 GPU。
    权重一样，所以文本质量基本一致，差的是速度（M 系列实测 5-8 倍）。

    注意：mlx_whisper.transcribe 传文件路径时会自己 fork ffmpeg 解码，
    非交互 shell 里常常找不到 ffmpeg。这里直接喂 numpy 数组，绕开这个问题。
    """
    if not _is_apple_silicon():
        raise RuntimeError(
            f"mlx-whisper 只支持 macOS Apple Silicon（当前 {sys.platform}/{platform.machine()}）。"
            " 非 Mac 环境请用 faster-whisper。"
        )
    import time

    import mlx_whisper

    repo = MLX_WHISPER_REPOS.get(model_size, model_size)  # 也允许直接传 HF 仓库名
    _log(f"  → mlx-whisper 转写 ({model_size}, Metal)...", end=" ", flush=True)

    audio_np = _read_wav_mono(audio_path)
    t0 = time.time()
    result = mlx_whisper.transcribe(
        audio_np,
        path_or_hf_repo=repo,
        language="zh",
        word_timestamps=False,
        condition_on_previous_text=False,  # 中文长音频下更少串词/复读
    )

    segments = []
    for seg in result.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if text:
            segments.append({
                "start": round(float(seg.get("start", 0.0)), 2),
                "end": round(float(seg.get("end", 0.0)), 2),
                "text": text,
            })

    total_chars = sum(len(s["text"]) for s in segments)
    _log(f"✓ ({len(segments)} 段, {total_chars} 字, {time.time() - t0:.1f}s)")
    return segments


# ---------- Qwen3-ASR ----------

def _wav_duration(path: Path) -> float:
    try:
        import wave
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 16000)
    except Exception:
        return 0.0


def _split_wav(path: Path, chunk_sec: float = 240.0) -> list:
    """切成若干 wav 分片（Qwen3-ASR 单次识别上限 5 分钟，API 也有体积限制）

    返回 [(分片路径, 起始秒), ...]；不足一片时返回原文件。
    """
    from v2t import ffmpeg as ff

    dur = _wav_duration(path)
    if dur <= chunk_sec:
        return [(path, 0.0)]

    out_dir = Path(tempfile.mkdtemp(prefix="qwen3asr_"))
    parts = []
    start = 0.0
    idx = 0
    while start < dur:
        part = out_dir / f"part{idx:03d}.wav"
        ff.run([
            "ffmpeg", "-y",
            "-ss", f"{start:.2f}", "-t", f"{chunk_sec:.2f}",
            "-i", str(path), "-ac", "1", "-ar", "16000", str(part),
        ])
        if part.exists() and part.stat().st_size > 1024:
            parts.append((part, start))
        start += chunk_sec
        idx += 1
    return parts or [(path, 0.0)]


def _segments_from_text(text: str, start: float, end: float) -> list:
    """没有时间戳时：按标点切句，再按字数比例把时长分给每句

    比"每 3 秒一行"靠谱得多：句长和语速大致成正比。
    """
    import re

    text = (text or "").strip()
    if not text:
        return []
    pieces = [p.strip() for p in re.split(r"(?<=[。！？；!?;])\s*|\n+", text) if p.strip()]
    # 只剩标点的片段（"。。。"）不算内容
    pieces = [p for p in pieces if re.search(r"\w", p)]
    if not pieces:
        return []
    # 太碎的句子（"好。"这种）并到下一句，避免一句三四个字
    merged, buf = [], ""
    for p in pieces:
        buf += p
        if len(buf) >= 12:
            merged.append(buf)
            buf = ""
    if buf:
        merged.append(buf)

    total = sum(len(p) for p in merged) or 1
    span = max(0.0, end - start)
    segs, cursor = [], start
    for p in merged:
        share = span * len(p) / total
        segs.append({"start": round(cursor, 2), "end": round(cursor + share, 2), "text": p})
        cursor += share
    return segs


def _transcribe_qwen3_asr(audio_path: Path, cache_key: str, model: str = "0.6b") -> list:
    """Qwen3-ASR —— 中文识别第一梯队

    两条通道，自动选：
      1) 本地 qwen-asr 包（需 pip install qwen-asr + 下载权重）
      2) DashScope 云端 qwen3-asr-flash（需 DASHSCOPE_API_KEY，按量计费）

    model: 0.6b / 1.7b（本地） / flash（强制走云端）
    """
    use_api = model == "flash" or not _has_module("qwen_asr")
    if use_api:
        return _transcribe_qwen3_asr_api(audio_path, cache_key, model)
    return _transcribe_qwen3_asr_local(audio_path, cache_key, model)


def _transcribe_qwen3_asr_local(audio_path: Path, cache_key: str, model: str = "0.6b") -> list:
    import time

    import torch
    from qwen_asr import Qwen3ASRModel

    repo = QWEN3_ASR_MODELS.get(model, model)
    if torch.cuda.is_available():
        device, dtype = "cuda:0", torch.bfloat16
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device, dtype = "mps", torch.float16
    else:
        device, dtype = "cpu", torch.float32

    _log(f"  → Qwen3-ASR 本地转写 ({model}, {device})...", end=" ", flush=True)
    t0 = time.time()

    # 权重只加载一次：批量跑 20 个视频时，重复 from_pretrained 会白等 20s×20
    key = (repo, device, cfg.QWEN3_ASR_ALIGN)
    engine = _QWEN_MODEL_CACHE.get(key)
    if engine is None:
        kwargs = {"max_new_tokens": 1024}
        if cfg.QWEN3_ASR_ALIGN:
            # 强制对齐模型能给到字级时间戳，代价是多下载 ~1.2G
            kwargs["forced_aligner"] = "Qwen/Qwen3-ForcedAligner-0.6B"
            kwargs["forced_aligner_kwargs"] = {"dtype": dtype, "device_map": device}
        engine = Qwen3ASRModel.from_pretrained(repo, dtype=dtype, device_map=device, **kwargs)
        _QWEN_MODEL_CACHE[key] = engine
        _log(f"[加载 {time.time() - t0:.0f}s] ", end="", flush=True)

    segments = []
    for part, offset in _split_wav(audio_path):
        dur = _wav_duration(part)
        res = engine.transcribe(
            audio=str(part),
            language="Chinese",
            return_time_stamps=bool(cfg.QWEN3_ASR_ALIGN),
        )
        item = res[0] if isinstance(res, (list, tuple)) and res else res
        text = getattr(item, "text", "") or ""
        stamps = getattr(item, "time_stamps", None) if cfg.QWEN3_ASR_ALIGN else None
        if stamps:
            for st in stamps:
                segments.append({
                    "start": round(offset + float(st.start_time), 2),
                    "end": round(offset + float(st.end_time), 2),
                    "text": (st.text or "").strip(),
                })
        else:
            segments.extend(_segments_from_text(text, offset, offset + dur))

    total_chars = sum(len(s["text"]) for s in segments)
    _log(f"✓ ({len(segments)} 段, {total_chars} 字, {time.time() - t0:.1f}s)")
    return segments


def _transcribe_qwen3_asr_api(audio_path: Path, cache_key: str, model: str = "flash") -> list:
    """DashScope 云端 qwen3-asr-flash（OpenAI 兼容协议）"""
    import time
    import urllib.request

    key = cfg.DASHSCOPE_API_KEY
    if not key:
        raise RuntimeError(
            "qwen3-asr 云端通道需要 DASHSCOPE_API_KEY。"
            " 本地跑请 pip install qwen-asr 并把 --asr-model 设为 0.6b / 1.7b。"
        )

    _log(f"  → Qwen3-ASR 云端转写 (qwen3-asr-flash)...", end=" ", flush=True)
    t0 = time.time()

    segments = []
    for part, offset in _split_wav(audio_path, chunk_sec=180.0):
        dur = _wav_duration(part)
        b64 = base64.b64encode(part.read_bytes()).decode()
        payload = {
            "model": "qwen3-asr-flash",
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {"data": f"data:audio/wav;base64,{b64}"},
                }],
            }],
            "stream": False,
            "asr_options": {"language": "zh", "enable_lid": False, "enable_itn": False},
        }
        req = urllib.request.Request(
            f"{cfg.DASHSCOPE_BASE.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            detail = ""
            try:
                detail = e.read().decode()[:300]
            except Exception:
                pass
            raise RuntimeError(f"DashScope 转写失败: {type(e).__name__} {e} {detail}")

        text = ""
        try:
            text = data["choices"][0]["message"]["content"]
            if isinstance(text, list):  # 少数情况下是分段结构
                text = "".join(x.get("text", "") for x in text)
        except Exception:
            text = ""
        segments.extend(_segments_from_text(text, offset, offset + dur))

    total_chars = sum(len(s["text"]) for s in segments)
    _log(f"✓ ({len(segments)} 段, {total_chars} 字, {time.time() - t0:.1f}s)")
    return segments
