#!/usr/bin/env python
"""
sensevoice_worker.py — SenseVoice 本地转写 worker（子进程调用）

用 sensevoice-local 的 venv 跑：
  /Users/kimliu/Projects/sensevoice-local/.venv/bin/python sensevoice_worker.py <wav路径>

输出：JSON segments 到 stdout
  [{"start": 0.0, "end": 2.3, "text": "..."}, ...]

设计：
  - VAD（silero-vad）先把音频切成句段，避免长音频重复幻觉
  - 每段单独转写，累加时间戳
  - MPS 加速（Apple Silicon）
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess
from scipy.io import wavfile
from silero_vad import load_silero_vad, VADIterator

SAMPLE_RATE = 16000
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


def load_model():
    """懒加载 SenseVoice 模型（只一次）"""
    log("加载 SenseVoice-Small ...")
    t0 = time.time()
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        trust_remote_code=True,
        device=DEVICE,
        disable_update=True,
    )
    log(f"模型加载完成 {time.time()-t0:.1f}s")
    return model


def log(msg: str):
    """日志走 stderr，不污染 stdout 的 JSON 输出"""
    print(f"[sensevoice] {msg}", file=sys.stderr, flush=True)


def read_wav_16k_mono(wav_path: Path) -> np.ndarray:
    """读 wav，转 float32 mono 16k"""
    sr, data = wavfile.read(str(wav_path))
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483648.0
    elif data.dtype == np.float32:
        pass
    else:
        data = data.astype(np.float32) / 32768.0

    # 多声道转 mono
    if data.ndim > 1:
        data = data.mean(axis=1)

    # 重采样（如果不是 16k）
    if sr != SAMPLE_RATE:
        # 简单线性插值重采样（够用）
        duration = len(data) / sr
        new_len = int(duration * SAMPLE_RATE)
        if new_len > 0:
            old_idx = np.linspace(0, len(data) - 1, len(data))
            new_idx = np.linspace(0, len(data) - 1, new_len)
            data = np.interp(new_idx, old_idx, data)
        log(f"重采样 {sr} -> {SAMPLE_RATE}")

    return data


def vad_split(audio: np.ndarray, vad_model) -> list:
    """用 silero-vad 把音频切成句段 [(start_sec, end_sec, np_array), ...]"""
    vad_iter = VADIterator(
        vad_model,
        sampling_rate=SAMPLE_RATE,
        threshold=0.5,
        min_silence_duration_ms=300,  # 300ms 停顿就切段，粒度更细
        speech_pad_ms=100,
    )

    chunks = []
    chunk_size = 512  # 32ms @ 16k
    buffer = audio.copy()
    in_speech = False
    speech_start = 0
    speech_buffer = np.zeros(0, dtype=np.float32)

    for i in range(0, len(buffer), chunk_size):
        chunk = buffer[i:i+chunk_size]
        if len(chunk) < chunk_size:
            # 最后一片不足，补零
            chunk = np.pad(chunk, (0, chunk_size - len(chunk)))

        speech_dict = vad_iter(chunk, return_seconds=False)

        if in_speech:
            speech_buffer = np.concatenate([speech_buffer, chunk])

        if speech_dict is not None:
            if 'start' in speech_dict:
                in_speech = True
                speech_start = i
                speech_buffer = chunk.copy()
            elif 'end' in speech_dict:
                in_speech = False
                if len(speech_buffer) > SAMPLE_RATE * 0.3:  # 至少 300ms
                    start_sec = speech_start / SAMPLE_RATE
                    end_sec = (i + chunk_size) / SAMPLE_RATE
                    chunks.append((start_sec, end_sec, speech_buffer.copy()))
                speech_buffer = np.zeros(0, dtype=np.float32)

    # 收尾：最后一段可能没被 VAD end 触发
    if in_speech and len(speech_buffer) > SAMPLE_RATE * 0.5:
        start_sec = speech_start / SAMPLE_RATE
        end_sec = len(audio) / SAMPLE_RATE
        chunks.append((start_sec, end_sec, speech_buffer.copy()))

    return chunks


def transcribe_chunk(model, audio: np.ndarray) -> str:
    """转写一段音频"""
    res = model.generate(
        input=audio,
        cache={},
        language="zh",
        use_itn=True,
        batch_size_s=60,
        disable_pbar=True,
    )
    if res and len(res) > 0:
        raw = res[0].get("text", "")
        return rich_transcription_postprocess(raw)
    return ""


def transcribe_file(model, wav_path: Path, vad_model) -> list:
    """转写整个 wav 文件，返回 segments"""
    log(f"读音频: {wav_path.name}")
    audio = read_wav_16k_mono(wav_path)
    log(f"时长: {len(audio)/SAMPLE_RATE:.1f}s")

    log("VAD 分段...")
    chunks = vad_split(audio, vad_model)
    log(f"切成 {len(chunks)} 段")

    segments = []
    for start_sec, end_sec, chunk_audio in chunks:
        text = transcribe_chunk(model, chunk_audio)
        if text.strip():
            segments.append({
                "start": round(start_sec, 2),
                "end": round(end_sec, 2),
                "text": text.strip(),
            })

    log(f"转写完成: {len(segments)} 段, {sum(len(s['text']) for s in segments)} 字")
    return segments


def main():
    parser = argparse.ArgumentParser(description="SenseVoice 本地转写 worker")
    parser.add_argument("wav", help="wav 文件路径（16kHz mono 最佳）")
    parser.add_argument("--out", help="输出 JSON 文件（默认 stdout）")
    args = parser.parse_args()

    wav_path = Path(args.wav)
    if not wav_path.exists():
        print(f"✗ 找不到: {wav_path}", file=sys.stderr)
        sys.exit(1)

    model = load_model()
    vad_model = load_silero_vad()

    segments = transcribe_file(model, wav_path, vad_model)

    out_text = json.dumps(segments, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out_text, encoding="utf-8")
        log(f"写入: {args.out}")
    else:
        print(out_text)


if __name__ == "__main__":
    main()
