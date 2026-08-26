#!/usr/bin/env python3
"""验证转写超时修复：直接跑 13 的转写"""
import sys
sys.path.insert(0, ".")
import video2text as v2t
from pathlib import Path

audio = Path("cache/4df4cc647c1e_audio.wav")
t = v2t.transcribe(audio, "4df4cc647c1e", "small")
segs = t.get("transcription") or t.get("segments") or []
print(f"转写成功, 段数: {len(segs)}")