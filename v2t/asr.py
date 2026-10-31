"""
v2t/asr.py — 转写引擎分发

支持四种后端：
  - faster-whisper: faster-whisper（CTranslate2，比 whisper.cpp 快 2-4 倍，默认）
  - whisper:        本地 whisper.cpp（旧逻辑保留）
  - sensevoice:     本地 SenseVoice-Small（增强模式，标点好）
  - minutes:        飞书妙记（免费额度，需 lark-cli）

统一接口：
  transcribe(audio_path, cache_key, engine) -> list[dict]
  返回 [{"start": float, "end": float, "text": str}, ...]
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import config as cfg

CACHE_DIR = cfg.CACHE_DIR

# sensevoice venv 路径（复用 sensevoice-local 的环境）
SENSEVOICE_VENV_PY = "/Users/kimliu/Projects/sensevoice-local/.venv/bin/python"
SENSEVOICE_WORKER = Path(__file__).parent / "workers" / "sensevoice_worker.py"


def transcribe(audio_path: Path, cache_key: str, engine: str = "faster-whisper",
               model_size: str = None) -> list:
    """统一转写入口，返回 segments 列表

    model_size 只对 faster-whisper 生效（tiny/base/small/medium/large-v3/large-v3-turbo），
    默认取 cfg.WHISPER_MODEL。不同模型分开缓存，换模型不会串结果。
    """
    model_size = model_size or cfg.WHISPER_MODEL
    suffix = f"{engine}-{model_size}" if engine == "faster-whisper" else engine
    cache_file = CACHE_DIR / f"{cache_key}_asr_{suffix}.json"
    if cache_file.exists():
        print(f"  ✓ 转写已缓存 ({suffix})")
        return json.loads(cache_file.read_text())

    if engine == "faster-whisper":
        segments = _transcribe_faster_whisper(audio_path, cache_key, model_size)
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


def _transcribe_sensevoice(audio_path: Path, cache_key: str) -> list:
    """调用 sensevoice_worker.py 子进程"""
    if not Path(SENSEVOICE_VENV_PY).exists():
        print(f"  ✗ sensevoice venv 不存在: {SENSEVOICE_VENV_PY}")
        print(f"    请先在 ~/Projects/sensevoice-local 建 venv 装 funasr")
        sys.exit(1)

    out_json = CACHE_DIR / f"{cache_key}_sensevoice_raw.json"
    print(f"  → SenseVoice 本地转写...", end=" ", flush=True)

    cmd = [
        SENSEVOICE_VENV_PY,
        str(SENSEVOICE_WORKER),
        str(audio_path),
        "--out", str(out_json),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

    if result.returncode != 0:
        print(f"✗")
        print(f"    stderr: {result.stderr[-500:]}")
        sys.exit(1)

    if not out_json.exists():
        print(f"✗ 转写输出不存在")
        sys.exit(1)

    segments = json.loads(out_json.read_text())
    total_chars = sum(len(s["text"]) for s in segments)
    print(f"✓ ({len(segments)} 段, {total_chars} 字)")
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
            print(f"  ✗ 找不到 whisper 模型")
            sys.exit(1)
        model_file = available[0]

    model_name = model_file.stem.replace("ggml-", "")
    output_prefix = CACHE_DIR / f"{cache_key}_whisper_{model_name}"

    print(f"  → Whisper.cpp 转写 ({model_name})...", end=" ", flush=True)
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
        print("✗ 找不到 whisper 输出")
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
    print(f"✓ ({len(segments)} 段, {total_chars} 字)")
    return segments


def _transcribe_minutes(audio_path: Path, cache_key: str) -> list:
    """飞书妙记（免费额度）— 调用 lark-cli"""
    out_json = CACHE_DIR / f"{cache_key}_minutes_raw.json"
    print(f"  → 飞书妙记转写...", end=" ", flush=True)

    # 1. 上传音频到飞书云空间
    up = subprocess.run(
        ["lark-cli", "drive", "+upload", "--file", str(audio_path), "--format", "json"],
        capture_output=True, text=True, timeout=120
    )
    if up.returncode != 0:
        print(f"✗ 上传失败: {up.stderr[-300:]}")
        return []

    up_data = json.loads(up.stdout)
    file_token = up_data.get("file_token", "")
    if not file_token:
        print(f"✗ 没拿到 file_token")
        return []

    # 2. 生成妙记
    mk = subprocess.run(
        ["lark-cli", "minutes", "+upload", "--file-token", file_token, "--format", "json"],
        capture_output=True, text=True, timeout=120
    )
    mk_data = json.loads(mk.stdout)
    minute_token = mk_data.get("minute_token", "")

    if not minute_token:
        print(f"✗ 没拿到 minute_token")
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
        print(f"  · 妙记处理中... ({attempt+1}/10)")
        import time; time.sleep(30)

    # 4. 解析 transcript.txt 成 segments（简单按行）
    transcript_dir = CACHE_DIR / f"minutes_{cache_key}"
    transcript_file = list(transcript_dir.glob("**/transcript.txt")) if transcript_dir.exists() else []
    if not transcript_file:
        print(f"✗ 没找到妙记产物")
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
    print(f"✓ ({len(segments)} 段, {total_chars} 字)")
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

    print(f"  → faster-whisper 转写 ({model_size})...", end=" ", flush=True)

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
    print(f"✓ ({len(segments)} 段, {total_chars} 字)")
    return segments
