#!/usr/bin/env python3
"""
video2text.py — 视频转结构化文本（最省钱方案）

三种模式:
  audio   纯音频转写（免费，本地 whisper.cpp）
  frames  关键帧 + VLM 画面理解（硅基流动 Qwen3-VL，极便宜）
  video   完整视频理解（豆包视频/火山方舟，质量最高，需配置）

用法:
  # 单视频
  python3 video2text.py video.mp4
  python3 video2text.py video.mp4 --mode frames
  python3 video2text.py video.mp4 --deep
  python3 video2text.py video.mp4 --no-llm

  # 批量处理（目录）
  python3 video2text.py ./input/ --mode audio
  python3 video2text.py ./input/ --mode frames --deep

  # Obsidian 导出
  python3 video2text.py video.mp4 --obsidian
  python3 video2text.py ./input/ --obsidian --folder "01_内容创作/视频笔记"

  # 说话人分离
  python3 video2text.py video.mp4 --diarize
"""

import os
import sys
import json
import subprocess
import hashlib
import argparse
import base64
import urllib.request
import shutil
from pathlib import Path
from datetime import timedelta, datetime

import config as cfg  # 统一配置管理

BASE_DIR = cfg.BASE_DIR
CACHE_DIR = cfg.CACHE_DIR
OUTPUT_DIR = cfg.OUTPUT_DIR

# whisper.cpp
WHISPER_CLI = cfg.WHISPER_CLI
DEFAULT_WHISPER_MODEL = cfg.WHISPER_MODEL

# 硅基流动（LLM + VLM）
SILICONFLOW_API_KEY = cfg.SILICONFLOW_API_KEY
SILICONFLOW_BASE = cfg.SILICONFLOW_BASE
LLM_MODEL = cfg.LLM_MODEL
VLM_MODEL = cfg.VLM_MODEL

# 火山方舟（豆包视频理解）
ARK_API_KEY = cfg.ARK_API_KEY
ARK_BASE = cfg.ARK_BASE
VIDEO_MODEL_ENDPOINT = cfg.ARK_VIDEO_ENDPOINT

# Obsidian
OBSIDIAN_VAULT = cfg.OBSIDIAN_VAULT
DEFAULT_OBSIDIAN_FOLDER = cfg.DEFAULT_OBSIDIAN_FOLDER

# 支持的视频格式
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".m4v", ".wmv"}

# ============ 工具函数 ============

def file_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def fmt_time(seconds: float) -> str:
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    m, s = divmod(total_seconds, 60)
    return f"{m:02d}:{s:02d}"

def fmt_time_hms(seconds: float) -> str:
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def run_cmd(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    timeout = kwargs.pop("timeout", 120)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)
    if result.returncode != 0:
        print(f"  ✗ 命令失败: {' '.join(cmd[:3])}...")
        print(f"    stderr: {result.stderr[-500:]}")
        sys.exit(1)
    return result

def encode_image_base64(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def parse_json_response(content: str) -> dict:
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        content = content[start:end+1]
    return json.loads(content)

def siliconflow_chat(messages: list, model: str = None, max_tokens: int = 4000, temperature: float = 0.3, timeout: int = 180) -> str:
    """调用硅基流动 Chat Completions"""
    if not SILICONFLOW_API_KEY:
        raise RuntimeError("没有 SILICONFLOW_API_KEY")
    model = model or LLM_MODEL
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{SILICONFLOW_BASE}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

# ============ Step 0: 视频信息 ============

def probe_video(video_path: Path) -> dict:
    result = run_cmd([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(video_path)
    ])
    info = json.loads(result.stdout)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    
    duration = float(fmt.get("duration", 0))
    size = int(fmt.get("size", 0))
    
    video_stream = next((s for s in streams if s["codec_type"] == "video"), None)
    audio_stream = next((s for s in streams if s["codec_type"] == "audio"), None)
    
    return {
        "duration": duration,
        "size": size,
        "width": int(video_stream.get("width", 0)) if video_stream else 0,
        "height": int(video_stream.get("height", 0)) if video_stream else 0,
        "has_audio": audio_stream is not None,
        "format": fmt.get("format_name", ""),
    }

# ============ Step 1: 抽音频 ============

def extract_audio(video_path: Path, cache_key: str) -> Path:
    audio_path = CACHE_DIR / f"{cache_key}_audio.wav"
    if audio_path.exists():
        print(f"  ✓ 音频已缓存")
        return audio_path
    
    print(f"  → 抽音频...", end=" ", flush=True)
    run_cmd([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(audio_path)
    ])
    size_mb = audio_path.stat().st_size / 1024 / 1024
    print(f"✓ ({size_mb:.1f} MB)")
    return audio_path

# ============ Step 2: ASR 转写 ============

def transcribe(audio_path: Path, cache_key: str, model: str) -> dict:
    result_path = CACHE_DIR / f"{cache_key}_{model}_transcript.json"
    if result_path.exists():
        print(f"  ✓ 转写已缓存")
        return json.loads(result_path.read_text())
    
    # 找模型文件
    model_file = WHISPER_MODEL_DIR / f"ggml-{model}.bin"
    if not model_file.exists():
        available = [f for f in WHISPER_MODEL_DIR.glob("ggml-*.bin") if ".en." not in f.name]
        if not available:
            available = sorted(WHISPER_MODEL_DIR.glob("ggml-*.bin"))
        if not available:
            print(f"  ✗ 找不到任何 ggml 模型")
            sys.exit(1)
        priority = {"small": 0, "base": 1, "tiny": 2, "medium": 3, "large": 4}
        available.sort(key=lambda f: priority.get(f.stem.replace("ggml-", ""), 9))
        model_file = available[0]
        print(f"  ⚠ 用 {model_file.name} 替代")
    
    model_name = model_file.stem.replace("ggml-", "")
    print(f"  → 转写 ({model_name})...", end=" ", flush=True)
    
    output_prefix = CACHE_DIR / f"{cache_key}_{model_name}"
    
    run_cmd([
        WHISPER_CLI,
        "-m", str(model_file),
        "-f", str(audio_path),
        "-oj",
        "-of", str(output_prefix),
        "-l", "zh",
    ])
    
    json_files = sorted(CACHE_DIR.glob(f"{cache_key}_{model_name}*.json"))
    if not json_files:
        print("✗ 找不到输出")
        sys.exit(1)
    
    transcript = json.loads(json_files[-1].read_text())
    result_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2))
    for f in json_files:
        if f != result_path:
            f.unlink(missing_ok=True)
    
    segs = transcript.get("transcription", []) or transcript.get("segments", [])
    print(f"✓ ({len(segs)} 段)")
    return transcript

def parse_segments(transcript: dict) -> list:
    segs = transcript.get("transcription", [])
    if not segs:
        segs = transcript.get("segments", [])
    
    result = []
    for s in segs:
        start = s.get("t0", s.get("start", 0))
        end = s.get("t1", s.get("end", 0))
        text = s.get("text", s.get("content", "")).strip()
        if isinstance(start, int) and start > 1000:
            start = start / 1000.0
            end = end / 1000.0
        if text:
            result.append({"start": float(start), "end": float(end), "text": text})
    
    return result

# ============ Step 2.5: 说话人分离 ============

def diarize_segments(segments: list, cache_key: str, model: str) -> list:
    """用 LLM 做说话人分离。
    
    思路：给模型逐字稿 + 时间戳，让它根据内容、语气、话题切换
    判断哪些段是同一个人说的。对于 2-3 人的对话场景准确率够用。
    这是最省钱的方案，成本约 0.001-0.005 元。
    """
    result_path = CACHE_DIR / f"{cache_key}_{model}_diarized.json"
    if result_path.exists():
        print(f"  ✓ 说话人分离已缓存")
        return json.loads(result_path.read_text())
    
    if not SILICONFLOW_API_KEY:
        print("  ⚠ 没有 API Key，跳过说话人分离")
        for s in segments:
            s["speaker"] = "未知"
        return segments
    
    print(f"  → 说话人分离...", end=" ", flush=True)
    
    # 组装逐字稿
    transcript_text = "\n".join(
        f"[{fmt_time(s['start'])}-{fmt_time(s['end'])}] {s['text']}"
        for s in segments
    )
    
    # 太长就截断（保留头尾）
    if len(transcript_text) > 20000:
        transcript_text = transcript_text[:12000] + "\n...[省略]...\n" + transcript_text[-8000:]
    
    prompt = f"""以下是一段视频的语音转写，带时间戳。请判断有几个人在说话，
并给每一段标注说话人（用"说话人A""说话人B""说话人C"等）。
只输出 JSON 数组，每个元素是 {{ "index": 序号, "speaker": "说话人X" }}，
序号从 0 开始，和输入顺序对应。

转写：
{transcript_text}

只输出 JSON 数组。"""
    
    try:
        content = siliconflow_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.1,
            timeout=120,
        )
        
        # 解析 JSON（容错：可能包在 markdown 代码块里，可能是 dict 或 array）
        import re
        # 先找第一个 [ 或 {
        arr_match = re.search(r'\[\s*\{', content)
        obj_match = re.search(r'\{', content)
        
        if arr_match and (not obj_match or arr_match.start() < obj_match.start()):
            # 数组开头
            start = arr_match.start()
            end = content.rfind(']')
            if end > start:
                result = json.loads(content[start:end+1])
            else:
                result = []
        elif obj_match:
            result = parse_json_response(content)
            if isinstance(result, dict) and any(k in result for k in ["speakers", "segments", "results"]):
                key = next(k for k in ["speakers", "segments", "results"] if k in result)
                result = result[key]
            else:
                result = []
        else:
            result = []
        
        # 结果可能是 list of dict 或 list of string
        speakers_list = []
        for item in result:
            if isinstance(item, dict):
                spk = item.get("speaker", item.get("spk", item.get("说话人", "未知")))
                speakers_list.append(spk)
            elif isinstance(item, str):
                speakers_list.append(item)
            else:
                speakers_list.append("未知")
        
        # 应用到 segments
        for i, s in enumerate(segments):
            s["speaker"] = speakers_list[i] if i < len(speakers_list) else "未知"
        
        result_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
        speakers = set(s.get("speaker", "未知") for s in segments)
        print(f"✓ ({len(speakers)} 人)")
        return segments
    except Exception as e:
        print(f"✗ ({e})")
        for s in segments:
            s["speaker"] = "未知"
        return segments

# ============ Step 3: 关键帧 + VLM 画面理解 ============

def extract_keyframes(video_path: Path, cache_key: str, max_frames: int = 20) -> list:
    frames_dir = CACHE_DIR / f"{cache_key}_frames"
    index_file = frames_dir / "_index.json"
    
    if index_file.exists():
        frames = json.loads(index_file.read_text())
        print(f"  ✓ 关键帧已缓存 ({len(frames)} 帧)")
        return frames
    
    frames_dir.mkdir(exist_ok=True)
    print(f"  → 提取关键帧...", end=" ", flush=True)
    
    # 均匀抽帧 + 按时间戳对齐（简单可靠）
    duration = float(ffprobe_duration(video_path))
    interval = max(1.0, duration / max_frames)
    pattern = str(frames_dir / "frame_%04d.jpg")
    
    run_cmd([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"fps=1/{interval},scale=640:-1",
        "-q:v", "3",
        pattern
    ], timeout=300)
    
    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    frames = []
    for i, f in enumerate(frame_files):
        t = i * interval
        frames.append({"path": str(f), "time": round(t, 2)})
    
    index_file.write_text(json.dumps(frames, indent=2))
    print(f"✓ ({len(frames)} 帧)")
    return frames

def ffprobe_duration(video_path: Path) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def describe_frames_vlm(frames: list, cache_key: str) -> list:
    result_path = CACHE_DIR / f"{cache_key}_vlm_frames.json"
    if result_path.exists():
        print(f"  ✓ 画面描述已缓存")
        return json.loads(result_path.read_text())
    
    if not SILICONFLOW_API_KEY:
        print("  ⚠ 没有 SILICONFLOW_API_KEY，跳过 VLM")
        return []
    
    print(f"  → VLM 画面理解 ({len(frames)} 帧)...", end=" ", flush=True)
    
    described = []
    batch_size = 4
    
    for i in range(0, len(frames), batch_size):
        batch = frames[i:i+batch_size]
        
        content = [
            {"type": "text", "text": "请简洁描述每一张图的主要内容（场景、人物、物体、文字）。每张图用一行中文描述，不超过30字。按图片顺序编号输出：1. xxx\\n2. xxx"}
        ]
        
        for fr in batch:
            b64 = encode_image_base64(Path(fr["path"]))
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            })
        
        body = json.dumps({
            "model": VLM_MODEL,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 2000,
            "temperature": 0.2,
        }).encode("utf-8")
        
        req = urllib.request.Request(
            f"{SILICONFLOW_BASE}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
            }
        )
        
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
                text = data["choices"][0]["message"]["content"]
                lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
                for j, fr in enumerate(batch):
                    desc = lines[j] if j < len(lines) else ""
                    if desc and desc[0].isdigit() and "." in desc[:3]:
                        desc = desc[desc.find(".")+1:].strip()
                    described.append({
                        "time": fr["time"],
                        "path": fr["path"],
                        "description": desc
                    })
        except Exception as e:
            print(f"\n    ✗ 批次 {i//batch_size} 失败: {e}")
            for fr in batch:
                described.append({
                    "time": fr["time"],
                    "path": fr["path"],
                    "description": "[VLM 失败]"
                })
    
    result_path.write_text(json.dumps(described, ensure_ascii=False, indent=2))
    print(f"✓")
    return described

# ============ Step 3.5: 完整视频理解（豆包/火山方舟） ============

def video_understanding_doubao(video_path: Path, cache_key: str) -> dict:
    """用豆包视频理解模型做完整的视频内容分析。
    
    优势: 理解动态内容、动作、时序关系，比关键帧+VLM质量高
    成本: 约 ¥0.05-0.2/分钟（取决于视频长度和复杂度）
    """
    result_path = CACHE_DIR / f"{cache_key}_doubao_video.json"
    if result_path.exists():
        print(f"  ✓ 视频理解已缓存")
        return json.loads(result_path.read_text())
    
    if not ARK_API_KEY or not VIDEO_MODEL_ENDPOINT:
        print("  ⚠ 豆包视频理解未配置（需要 ARK_API_KEY + endpoint）")
        return {"error": "not_configured"}
    
    print(f"  → 豆包视频理解...", end=" ", flush=True)
    
    file_size_mb = video_path.stat().st_size / 1024 / 1024
    
    # 超过 50MB 先压缩
    video_to_send = video_path
    if file_size_mb > 50:
        compressed_path = CACHE_DIR / f"{cache_key}_compressed.mp4"
        if not compressed_path.exists():
            subprocess.run([
                "ffmpeg", "-y", "-i", str(video_path),
                "-b:v", "1M", "-s", "640x360", "-r", "15",
                str(compressed_path)
            ], capture_output=True, timeout=300)
        video_to_send = compressed_path
    
    with open(video_to_send, "rb") as f:
        video_b64 = base64.b64encode(f.read()).decode("utf-8")
    
    prompt = """请详细分析这段视频的内容，输出 JSON 格式：
{
  "summary": "视频整体内容一句话总结",
  "scenes": [
    {"time": "大致时间点", "description": "场景描述", "key_elements": ["关键元素列表"]}
  ],
  "visual_highlights": ["3-5个画面亮点/重要镜头"],
  "text_detected": ["视频中出现的文字/OCR"],
  "actions": ["主要动作/事件"],
  "emotion_mood": "整体情绪氛围"
}
只输出 JSON。"""
    
    body = json.dumps({
        "model": VIDEO_MODEL_ENDPOINT,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_video",
                        "video_url": f"data:video/mp4;base64,{video_b64}"
                    },
                    {
                        "type": "input_text",
                        "text": prompt
                    }
                ]
            }
        ],
        "max_output_tokens": 4000,
    }).encode("utf-8")
    
    req = urllib.request.Request(
        f"{ARK_BASE}/responses",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ARK_API_KEY}",
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
            
            # 从 responses 格式提取文本
            text = ""
            for item in data.get("output", []):
                if item.get("content"):
                    for c in item["content"]:
                        if c.get("text"):
                            text += c["text"]
            
            result = parse_json_response(text)
            result["usage"] = data.get("usage", {})
            
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print("✓")
            return result
    except Exception as e:
        print(f"✗ ({e})")
        return {"error": str(e)}

# ============ Step 4: LLM 摘要 ============

def summarize_with_llm(segments: list, video_info: dict, frames_desc: list = None, deep: bool = False, video_desc: dict = None) -> dict:
    if not SILICONFLOW_API_KEY:
        print("  ⚠ 没有 SILICONFLOW_API_KEY，跳过 LLM 摘要")
        return {"error": "no_api_key"}
    
    has_speakers = any("speaker" in s for s in segments)
    
    transcript_lines = []
    for s in segments:
        prefix = f"[{fmt_time(s['start'])}]"
        if has_speakers and s.get("speaker"):
            prefix += f" {s['speaker']}:"
        transcript_lines.append(f"{prefix} {s['text']}")
    transcript_text = "\n".join(transcript_lines)
    
    frames_text = ""
    if frames_desc:
        frames_text = "\n\n关键画面（按时间顺序）：\n"
        for f in frames_desc:
            frames_text += f"[{fmt_time(f['time'])}] {f['description']}\n"
    
    # 豆包视频理解的额外信息
    video_extra_text = ""
    if video_desc and "error" not in video_desc:
        parts = []
        if video_desc.get("emotion_mood"):
            parts.append(f"情绪氛围: {video_desc['emotion_mood']}")
        if video_desc.get("text_detected"):
            parts.append(f"画面文字: {', '.join(video_desc['text_detected'])}")
        if video_desc.get("actions"):
            parts.append(f"主要动作: {', '.join(video_desc['actions'][:5])}")
        if parts:
            video_extra_text = "\n\n视频细节：\n" + "\n".join(f"- {p}" for p in parts)
    
    if len(transcript_text) > 40000:
        transcript_text = transcript_text[:20000] + "\n...[中间省略]...\n" + transcript_text[-15000:]
    
    if deep:
        prompt = f"""你是资深内容分析师。请深度拆解这个视频。

视频时长：{fmt_time_hms(video_info['duration'])}
分辨率：{video_info['width']}x{video_info['height']}
{frames_text}{video_extra_text}

语音逐字稿：
{transcript_text}

输出 JSON，包含：
1. "one_liner": 一句话总结（50字以内）
2. "core_points": 核心观点（3-7条）
3. "chapters": 章节划分（每章: title, start_time, end_time, summary）
4. "key_quotes": 金句（5-10条，带时间戳，字符串数组）
5. "visual_highlights": 画面亮点（3-5个重要画面/场景）
6. "narrative": 叙事分析（人物/冲突/结构/情绪/价值观，dict格式）
7. "action_items": 行动项（如果有）
8. "new_concepts": 新概念/新方法（如果有，数组，每项含概念+解释）
9. "counter_intuitive": 反常识观点（如果有）

只输出 JSON。"""
    else:
        prompt = f"""请把这个视频整理成结构化文本。

视频时长：{fmt_time_hms(video_info['duration'])}
{frames_text}{video_extra_text}

语音逐字稿：
{transcript_text}

输出 JSON，包含：
1. "one_liner": 一句话总结（50字以内）
2. "core_points": 核心观点（3-5条）
3. "chapters": 章节划分（每章: title, start_time, end_time, summary）
4. "key_quotes": 金句/重要句子（3-5条，带时间戳，字符串数组）
5. "action_items": 行动项（如果有）

只输出 JSON。"""
    
    print(f"  → LLM 结构化摘要...", end=" ", flush=True)
    try:
        content = siliconflow_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.3,
            timeout=180,
        )
        result = parse_json_response(content)
        print("✓")
        return result
    except Exception as e:
        print(f"✗ ({e})")
        return {"error": str(e)}

# ============ 输出 Markdown ============

def write_markdown_output(
    video_path: Path,
    video_info: dict,
    segments: list,
    summary: dict,
    frames_desc: list,
    output_path: Path,
):
    has_speakers = any("speaker" in s for s in segments)
    has_summary = "error" not in summary
    
    lines = []
    lines.append(f"# {video_path.stem}")
    lines.append("")
    
    # YAML frontmatter for Obsidian
    lines.insert(0, "---")
    lines.insert(1, f"来源: 视频")
    lines.insert(2, f"时长: {fmt_time_hms(video_info['duration'])}")
    lines.insert(3, f"日期: {datetime.now().strftime('%Y-%m-%d')}")
    lines.insert(4, f"分辨率: {video_info['width']}x{video_info['height']}")
    lines.insert(5, f"文件大小: {video_info['size'] / 1024 / 1024:.1f} MB")
    lines.insert(6, f"文件名: {video_path.name}")
    lines.insert(7, "---")
    lines.insert(8, "")
    
    # 一句话总结
    if has_summary:
        lines.append("> " + summary.get("one_liner", ""))
        lines.append("")
    
    # 核心观点
    if has_summary and summary.get("core_points"):
        lines.append("## 核心观点")
        lines.append("")
        for i, pt in enumerate(summary["core_points"], 1):
            lines.append(f"{i}. {pt}")
        lines.append("")
    
    # 画面亮点
    if has_summary and summary.get("visual_highlights"):
        lines.append("## 画面亮点")
        lines.append("")
        for v in summary["visual_highlights"]:
            lines.append(f"- {v}")
        lines.append("")
    
    # 关键帧
    if frames_desc:
        lines.append("## 关键画面")
        lines.append("")
        for f in frames_desc:
            lines.append(f"- [{fmt_time(f['time'])}] {f.get('description', '')}")
        lines.append("")
    
    # 章节
    if has_summary and summary.get("chapters"):
        lines.append("## 章节")
        lines.append("")
        for ch in summary["chapters"]:
            st = ch.get("start_time", "")
            et = ch.get("end_time", "")
            lines.append(f"### {st} - {et} | {ch.get('title', '')}")
            lines.append("")
            lines.append(ch.get("summary", ""))
            lines.append("")
    
    # 金句
    if has_summary and summary.get("key_quotes"):
        lines.append("## 金句")
        lines.append("")
        for q in summary["key_quotes"]:
            lines.append(f"- {q}")
        lines.append("")
    
    # 行动项
    if has_summary and summary.get("action_items"):
        lines.append("## 行动项")
        lines.append("")
        for item in summary["action_items"]:
            lines.append(f"- [ ] {item}")
        lines.append("")
    
    # 叙事分析
    if has_summary and summary.get("narrative"):
        lines.append("## 叙事分析")
        lines.append("")
        narr = summary["narrative"]
        if isinstance(narr, dict):
            for k, v in narr.items():
                lines.append(f"**{k}**: {v}")
                lines.append("")
        else:
            lines.append(str(narr))
            lines.append("")
    
    # 新概念
    if has_summary and summary.get("new_concepts"):
        lines.append("## 新概念")
        lines.append("")
        for c in summary["new_concepts"]:
            if isinstance(c, dict):
                name = c.get('概念', c.get('name', c.get('concept', '')))
                desc = c.get('解释', c.get('desc', c.get('description', '')))
                lines.append(f"### {name}")
                lines.append(desc)
            else:
                lines.append(f"- {c}")
            lines.append("")
    
    # 反常识
    if has_summary and summary.get("counter_intuitive"):
        lines.append("## 反常识")
        lines.append("")
        for c in summary["counter_intuitive"]:
            lines.append(f"- {c}")
        lines.append("")
    
    # 逐字稿
    lines.append("## 逐字稿")
    lines.append("")
    for s in segments:
        prefix = f"[{fmt_time(s['start'])}]"
        if has_speakers and s.get("speaker"):
            prefix += f" **{s['speaker']}**:"
        lines.append(f"{prefix} {s['text']}")
    lines.append("")
    
    output_path.write_text("\n".join(lines), encoding="utf-8")

# ============ Obsidian 导出 ============

def export_to_obsidian(md_path: Path, folder: str) -> Path:
    """导出到 Obsidian vault"""
    if not OBSIDIAN_VAULT.exists():
        print(f"  ⚠ 找不到 Obsidian vault: {OBSIDIAN_VAULT}")
        return None
    
    target_dir = OBSIDIAN_VAULT / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    
    target = target_dir / md_path.name
    shutil.copy2(md_path, target)
    print(f"  ✓ 导出到 Obsidian: {folder}/{md_path.name}")
    return target

# ============ 单视频处理 ============

def process_single(video_path: Path, args) -> tuple:
    """处理单个视频，返回 (md_path, json_path)"""
    cache_key = file_hash(video_path)
    
    mode_suffix = args.mode
    if args.deep:
        mode_suffix += "-deep"
    if args.diarize:
        mode_suffix += "-diarized"
    
    output_md = OUTPUT_DIR / f"{video_path.stem}_{mode_suffix}.md"
    output_json = OUTPUT_DIR / f"{video_path.stem}_{mode_suffix}.json"
    
    # 如果输出已存在，跳过
    if output_md.exists() and not args.force:
        print(f"  ✓ 已处理，跳过: {video_path.name}")
        return output_md, output_json
    
    info = probe_video(video_path)
    print(f"  时长: {fmt_time_hms(info['duration'])} | "
          f"分辨率: {info['width']}x{info['height']} | "
          f"大小: {info['size']/1024/1024:.1f} MB")
    
    has_audio = info["has_audio"]
    segments = []
    
    # 音频 + 转写
    if has_audio and args.mode in ("audio", "frames", "video"):
        audio_path = extract_audio(video_path, cache_key)
        transcript = transcribe(audio_path, cache_key, args.model)
        segments = parse_segments(transcript)
        total_chars = sum(len(s["text"]) for s in segments)
        print(f"  → {len(segments)} 段，{total_chars} 字")
        
        # 说话人分离
        if args.diarize:
            segments = diarize_segments(segments, cache_key, args.model)
    else:
        print("  ⚠ 无音轨，跳过转写")
    
    # 画面理解
    frames_desc = []
    if args.mode == "frames":
        frames = extract_keyframes(video_path, cache_key, args.max_frames)
        frames_desc = describe_frames_vlm(frames, cache_key)
    elif args.mode == "video":
        doubao_result = video_understanding_doubao(video_path, cache_key)
        # 把豆包结果转换成 frames_desc 格式，复用后面的摘要逻辑
        if "error" not in doubao_result:
            frames_desc = []
            for i, sc in enumerate(doubao_result.get("scenes", [])):
                frames_desc.append({
                    "time": i * 5,  # 豆包场景时间是大致的，这里估算
                    "description": sc.get("description", ""),
                    "source": "doubao"
                })
            # 额外存一下豆包完整结果
            video_understanding_result = doubao_result
        else:
            video_understanding_result = doubao_result
            frames_desc = []
    
    # LLM 摘要
    summary = {}
    doubao_desc = locals().get("video_understanding_result", None)
    if not args.no_llm and (segments or frames_desc):
        summary = summarize_with_llm(segments, info, frames_desc, deep=args.deep, video_desc=doubao_desc)
    
    # 输出
    write_markdown_output(video_path, info, segments, summary, frames_desc, output_md)
    output_json.write_text(json.dumps({
        "video": str(video_path),
        "info": info,
        "mode": args.mode,
        "segments": segments,
        "frames": frames_desc,
        "summary": summary,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return output_md, output_json

# ============ 批量处理 ============

def find_videos(input_path: Path) -> list:
    """找到目录下所有视频文件"""
    videos = []
    for ext in sorted(VIDEO_EXTENSIONS):
        videos.extend(sorted(input_path.glob(f"*{ext}")))
        videos.extend(sorted(input_path.glob(f"*{ext.upper()}")))
    # 去重
    return list(dict.fromkeys(videos))

def process_batch(input_dir: Path, args) -> list:
    """批量处理目录下的所有视频"""
    videos = find_videos(input_dir)
    if not videos:
        print(f"✗ 目录里找不到视频文件: {input_dir}")
        print(f"  支持格式: {', '.join(sorted(VIDEO_EXTENSIONS))}")
        return []
    
    print(f"\n📦 批量处理: {len(videos)} 个视频")
    
    results = []
    for i, video in enumerate(videos, 1):
        print(f"\n--- [{i}/{len(videos)}] {video.name} ---")
        try:
            md_path, json_path = process_single(video, args)
            results.append((video, md_path, json_path, "ok"))
            
            # Obsidian 导出
            if args.obsidian:
                export_to_obsidian(md_path, args.obsidian_folder)
                
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            results.append((video, None, None, str(e)))
    
    # 总结
    ok = sum(1 for r in results if r[3] == "ok")
    fail = len(results) - ok
    print(f"\n📊 批量完成: {ok} 成功, {fail} 失败")
    
    return results

# ============ 主入口 ============

def main():
    parser = argparse.ArgumentParser(description="视频转结构化文本")
    parser.add_argument("input", help="视频文件或目录路径")
    parser.add_argument("--mode", choices=["audio", "frames", "video"], default="audio",
                        help="模式: audio(默认)/frames/video")
    parser.add_argument("--model", default=DEFAULT_WHISPER_MODEL, help="whisper 模型")
    parser.add_argument("--deep", action="store_true", help="深度叙事拆解")
    parser.add_argument("--no-llm", action="store_true", help="只转写，不用LLM")
    parser.add_argument("--diarize", action="store_true", help="说话人分离")
    parser.add_argument("--max-frames", type=int, default=20, help="关键帧最大数量")
    parser.add_argument("--lang", default="zh", help="语言")
    parser.add_argument("--force", action="store_true", help="强制重新处理，不使用缓存")
    
    # Obsidian
    parser.add_argument("--obsidian", action="store_true", help="导出到 Obsidian")
    parser.add_argument("--obsidian-folder", default=DEFAULT_OBSIDIAN_FOLDER,
                        help=f"Obsidian 目录 (默认: {DEFAULT_OBSIDIAN_FOLDER})")
    
    args = parser.parse_args()
    
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"✗ 找不到: {input_path}")
        sys.exit(1)
    
    # 判断是文件还是目录
    if input_path.is_file():
        print(f"\n🎬 {input_path.name}")
        md_path, json_path = process_single(input_path, args)
        print(f"\n📝 输出")
        print(f"  ✓ {md_path}")
        print(f"  ✓ {json_path}")
        
        if args.obsidian:
            export_to_obsidian(md_path, args.obsidian_folder)
        
        print(f"\n✅ 完成")
    elif input_path.is_dir():
        process_batch(input_path, args)
    else:
        print(f"✗ 不是文件也不是目录: {input_path}")
        sys.exit(1)

if __name__ == "__main__":
    main()
