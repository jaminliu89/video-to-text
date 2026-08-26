#!/usr/bin/env python3
"""找 13 号的音频缓存并测 whisper 转写耗时"""
import hashlib, json, subprocess, time
from pathlib import Path

video = Path("/Volumes/视频素材/老白故事/3、老白的故事课——剧作理论与实战应用¥598/13、【实战】从头开始，写出一个故事.mp4")
print("视频存在:", video.exists())

h = hashlib.md5()
with open(video, "rb") as f:
    for chunk in iter(lambda: f.read(8192), b""):
        h.update(chunk)
key = h.hexdigest()[:12]
print("哈希:", key)

# 找对应音频
audio_files = list(Path("cache").glob(f"{key}_audio.wav"))
print("音频缓存:", [f.name for f in audio_files])
if not audio_files:
    print("没有音频缓存，结束")
    raise SystemExit(0)

audio = audio_files[0]
model_dir = Path.home() / ".cache" / "whisper"
model_file = model_dir / "ggml-small.bin"
print("模型存在:", model_file.exists())

# 计时跑 whisper-cli
t0 = time.time()
try:
    r = subprocess.run(
        ["whisper-cli", "-m", str(model_file), "-f", str(audio),
         "-oj", "-of", str(Path("cache") / f"{key}_small_test"),
         "-l", "zh"],
        capture_output=True, text=True, timeout=3600,
    )
    elapsed = time.time() - t0
    print(f"exit={r.returncode} 耗时={elapsed:.0f}s ({elapsed/60:.1f}min)")
    if r.returncode != 0:
        print("stderr:", r.stderr[-800:])
    else:
        # 找输出 json
        outs = sorted(Path("cache").glob(f"{key}_small_test*.json"))
        print("输出:", [f.name for f in outs])
except subprocess.TimeoutExpired:
    print(f"3600s 超时，已跑 {time.time()-t0:.0f}s")