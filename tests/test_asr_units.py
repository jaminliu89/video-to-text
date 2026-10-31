#!/usr/bin/env python
"""
tests/test_asr_units.py — 转写层单测（不联网、不加载模型）

覆盖：
  - 引擎注册表（list_engines）字段完整、平台判定正确
  - 未知引擎要明确报错，不能静默返回空
  - 缓存键区分引擎与模型（换模型不串结果）
  - 无时间戳时的按字数分配时间（_segments_from_text）
  - wav 分片逻辑（短音频不分片）
  - 基准脚本的文本归一与 CER 计算

跑法：python3 tests/test_asr_units.py
"""

import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v2t import asr  # noqa: E402

sys.path.insert(0, str(ROOT / "benchmarks"))
import asr_bench  # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} — {detail}")
        print(f"  ✗ {name}  {detail}")


def make_wav(path: Path, seconds: float, rate: int = 16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


# ------------------------------------------------------------------ 测试

def test_engine_registry():
    rows = asr.list_engines()
    names = [r["engine"] for r in rows]
    check("注册表含六个引擎", len(rows) == 6, str(names))
    for need in ("faster-whisper", "mlx-whisper", "qwen3-asr"):
        check(f"含 {need}", need in names)

    keys = {"engine", "label", "available", "reason", "models", "default_model", "gpu"}
    for r in rows:
        check(f"{r['engine']} 字段完整", keys <= set(r), str(keys - set(r)))
        check(f"{r['engine']} available 是布尔", isinstance(r["available"], bool))
        check(f"{r['engine']} models 非空", len(r["models"]) > 0)
        # 不可用必须给出可操作的说明
        if not r["available"]:
            check(f"{r['engine']} 不可用时有原因", bool(r["reason"]), "reason 为空")

    import platform
    is_apple = sys.platform == "darwin" and platform.machine() == "arm64"
    mlx = next(r for r in rows if r["engine"] == "mlx-whisper")
    if not is_apple:
        check("非 Apple Silicon 上 mlx 不可用", mlx["available"] is False)
        check("提示 Apple Silicon", "Apple Silicon" in mlx["reason"], mlx["reason"])

    qwen = next(r for r in rows if r["engine"] == "qwen3-asr")
    check("qwen3 模型列表含 0.6b/1.7b/flash",
          {"0.6b", "1.7b", "flash"} <= set(qwen["models"]), str(qwen["models"]))


def test_unknown_engine():
    with tempfile.TemporaryDirectory() as d:
        wav = make_wav(Path(d) / "a.wav", 0.2)
        try:
            asr.transcribe(wav, "unit_unknown_engine", "no-such-engine")
            check("未知引擎抛错", False, "没有抛异常")
        except ValueError as e:
            check("未知引擎抛 ValueError", "no-such-engine" in str(e), str(e))


def test_cache_key_separation():
    """缓存文件名必须带引擎+模型，否则换模型会拿到旧结果"""
    import config as cfg
    f1 = cfg.CACHE_DIR / "unitkey_asr_faster-whisper-base.json"
    f2 = cfg.CACHE_DIR / "unitkey_asr_mlx-whisper-base.json"
    for f in (f1, f2):
        f.write_text("[]")
    try:
        a = asr.transcribe(Path("whatever.wav"), "unitkey", "faster-whisper", "base")
        b = asr.transcribe(Path("whatever.wav"), "unitkey", "mlx-whisper", "base")
        check("不同引擎命中各自缓存", a == [] and b == [], f"{a} {b}")
    finally:
        for f in (f1, f2):
            f.unlink(missing_ok=True)


def test_segments_from_text():
    text = ("今天讲三件事。第一是提示词的结构，第二是对标书的用法。"
            "第三是去 AI 味的具体手段，比如把长句拆短、把书面语换成口语。")
    segs = asr._segments_from_text(text, 10.0, 70.0)
    check("切出多段", len(segs) >= 2, str(len(segs)))
    check("起点对齐", abs(segs[0]["start"] - 10.0) < 1e-6, str(segs[0]))
    check("终点对齐", abs(segs[-1]["end"] - 70.0) < 1e-3, str(segs[-1]))
    check("时间单调不回退",
          all(segs[i]["end"] <= segs[i + 1]["start"] + 1e-6 for i in range(len(segs) - 1)))
    joined = "".join(s["text"] for s in segs).replace(" ", "")
    check("内容不丢字", asr_bench.norm(joined) == asr_bench.norm(text), joined[:40])
    check("空文本返回空", asr._segments_from_text("", 0, 10) == [])
    check("纯标点返回空", asr._segments_from_text("。。。", 0, 10) == [])


def test_split_wav():
    with tempfile.TemporaryDirectory() as d:
        short = make_wav(Path(d) / "short.wav", 1.0)
        parts = asr._split_wav(short, chunk_sec=240)
        check("短音频不分片", parts == [(short, 0.0)], str(parts))

        long = make_wav(Path(d) / "long.wav", 6.0)
        parts = asr._split_wav(long, chunk_sec=2.0)
        check("长音频切 3 片", len(parts) == 3, str(len(parts)))
        check("分片起点递增", [round(p[1], 1) for p in parts] == [0.0, 2.0, 4.0],
              str([p[1] for p in parts]))
        check("分片存在", all(p[0].exists() for p in parts))


def test_bench_text_metrics():
    check("归一化去标点", asr_bench.norm("你好，世界！") == "你好世界")
    check("归一化全角转半角", asr_bench.norm("ＡＢＣ") == "abc")
    check("相同文本 CER=0", asr_bench.cer("你好世界", "你好世界") == 0.0)
    check("全错 CER=1", abs(asr_bench.cer("abcd", "wxyz") - 1.0) < 1e-9)
    check("半错 CER≈0.5", abs(asr_bench.cer("abcd", "abzz") - 0.5) < 1e-9)
    check("空参考不炸", asr_bench.cer("", "x") == 0.0)
    # 标点差异不该算错
    check("标点不影响 CER", asr_bench.cer("你好，世界", "你好世界。") == 0.0)


def test_wav_duration():
    with tempfile.TemporaryDirectory() as d:
        w = make_wav(Path(d) / "d.wav", 2.5)
        check("时长读取", abs(asr._wav_duration(w) - 2.5) < 0.05, str(asr._wav_duration(w)))
        check("坏文件返回 0", asr._wav_duration(Path(d) / "nope.wav") == 0.0)


def main():
    tests = [
        ("引擎注册表", test_engine_registry),
        ("未知引擎", test_unknown_engine),
        ("缓存键隔离", test_cache_key_separation),
        ("无时间戳切分", test_segments_from_text),
        ("wav 分片", test_split_wav),
        ("基准文本指标", test_bench_text_metrics),
        ("wav 时长", test_wav_duration),
    ]
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            fn()
        except Exception as e:
            global FAIL
            FAIL += 1
            FAILURES.append(f"{name} 异常 — {type(e).__name__}: {e}")
            print(f"  ✗ 异常 {type(e).__name__}: {e}")

    print(f"\n{'=' * 46}\n通过 {PASS} 项，失败 {FAIL} 项")
    if FAILURES:
        print("失败项：")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
