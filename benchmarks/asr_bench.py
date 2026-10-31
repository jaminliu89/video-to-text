#!/usr/bin/env python
"""
benchmarks/asr_bench.py — 转写引擎横向基准

同一段音频喂给多个引擎，测三件事：
  1. 速度：耗时 / RTF（实时率）/ 每字耗时
  2. 内存：峰值 RSS（每个引擎独立子进程，互不污染）
  3. 质量：两两 CER（字错率）+ 与"共识文本"的 CER + 关键术语命中数

为什么用 CER 而不是"感觉"：
  CER = 编辑距离 / 参考长度，中文 ASR 的标准指标。没有人工标注时，
  用"共识"当参考——哪个引擎离所有引擎的平均距离最近，哪个最不像异类。
  术语命中（--terms）比 CER 更贴近业务：专有名词错一个字，下游全废。

用法:
  # 单条音频跑全部可用引擎
  python3 benchmarks/asr_bench.py --audio cache/xxx_audio.wav \
      --engines faster-whisper:base,faster-whisper:large-v3-turbo,mlx-whisper:large-v3-turbo \
      --terms "星月写作,提示词,对标书" --out benchmarks/results.md

  # 从视频现抽音频
  python3 benchmarks/asr_bench.py --video a.mp4 --seconds 120 --engines mlx-whisper:large-v3-turbo
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------- 文本归一 / CER

PUNCT = set("，。！？；：、,.!?;:\"'“”‘’（）()《》<>[]【】—–-…·~` \t\n\r")


def norm(text: str) -> str:
    """去掉标点和空白，只留内容字（中文 ASR 对比的标准做法）"""
    out = []
    for ch in text or "":
        if ch in PUNCT:
            continue
        if "\uFF01" <= ch <= "\uFF5E":  # 全角 → 半角
            ch = chr(ord(ch) - 0xFEE0)
        out.append(ch.lower())
    return "".join(out)


def edit_distance(a: str, b: str) -> int:
    """Levenshtein（滚动数组，O(min(n,m)) 空间）"""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    ref_n = norm(ref)
    if not ref_n:
        return 0.0
    return edit_distance(ref_n, norm(hyp)) / len(ref_n)


# ---------------------------------------------------------------- 单引擎 worker

def run_engine(engine: str, model: str, audio: Path, repeat: int = 1) -> dict:
    """在子进程里跑一个引擎（隔离内存与崩溃），返回 metrics + 文本

    repeat > 1 时同一进程里连跑多次：第一次含模型加载/编译（冷启动），
    后面是稳态。两个数都要看——冷启动决定「跑一次」的成本，
    稳态决定「跑一批」的成本。
    """
    code = f"""
import json, resource, sys, time
sys.path.insert(0, {str(ROOT)!r})
from pathlib import Path
from v2t import asr
times = []
segs = []
for i in range({repeat}):
    t0 = time.time()
    segs = asr.transcribe(Path({str(audio)!r}), "bench_{engine}_{model}_r%d" % i,
                          {engine!r}, {model!r})
    times.append(time.time() - t0)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
if sys.platform == "darwin":
    rss = rss / 1024.0 / 1024.0  # bytes -> MB
else:
    rss = rss / 1024.0           # KB -> MB
print("__RESULT__" + json.dumps({{
    "engine": {engine!r}, "model": {model!r}, "times": times,
    "elapsed": min(times), "elapsed_cold": times[0],
    "rss_mb": round(rss, 1), "segments": len(segs),
    "text": "".join(s["text"] for s in segs),
}}, ensure_ascii=False))
"""
    t0 = time.time()
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    wall = time.time() - t0
    for line in (proc.stdout or "").splitlines():
        if line.startswith("__RESULT__"):
            d = json.loads(line[len("__RESULT__"):])
            d["wall"] = wall
            d["ok"] = True
            d.setdefault("elapsed_cold", d.get("elapsed", 0.0))
            return d
    return {
        "engine": engine, "model": model, "ok": False, "wall": wall,
        "error": ((proc.stderr or "") + (proc.stdout or ""))[-600:],
        "text": "", "elapsed": 0.0, "elapsed_cold": 0.0, "rss_mb": 0.0, "segments": 0,
    }


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 16000)
    except Exception:
        return 0.0


# ---------------------------------------------------------------- 报告

def build_report(rows: list, duration: float, terms: list, audio: str) -> str:
    ok = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]

    # 两两 CER
    cer_matrix = {}
    for r in ok:
        for o in ok:
            if r is o:
                continue
            cer_matrix[(r["engine"] + ":" + r["model"], o["engine"] + ":" + o["model"])] = \
                cer(r["text"], o["text"])

    # 共识：离其他引擎平均 CER 最小的那个
    consensus_key, best = None, 9e9
    for r in ok:
        k = r["engine"] + ":" + r["model"]
        others = [v for (a, _), v in cer_matrix.items() if a == k]
        if others:
            avg = sum(others) / len(others)
            r["avg_cer"] = avg
            if avg < best:
                best, consensus_key = avg, k
        else:
            r["avg_cer"] = 0.0
    consensus = next((r for r in ok if r["engine"] + ":" + r["model"] == consensus_key), None)

    L = []
    L.append("# ASR 引擎基准\n")
    L.append(f"- 音频：`{Path(audio).name}`（{duration:.1f}s）")
    L.append(f"- 时间：{time.strftime('%Y-%m-%d %H:%M')}")
    L.append(f"- 机器：{sys.platform} {os.uname().machine if hasattr(os, 'uname') else ''}")
    L.append("")

    L.append("## 速度与内存\n")
    L.append("| 引擎 | 模型 | 稳态耗时 | 冷启动 | 倍速 | 峰值内存 | 段数 | 字数 |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for r in sorted(ok, key=lambda x: x["elapsed"]):
        rtf = r["elapsed"] / duration if duration else 0
        L.append(f"| {r['engine']} | {r['model']} | {r['elapsed']:.1f}s | "
                 f"{r.get('elapsed_cold', r['elapsed']):.1f}s | {1/rtf:.1f}x | "
                 f"{r['rss_mb']:.0f} MB | {r['segments']} | {len(norm(r['text']))} |")
    L.append("")

    if consensus:
        L.append("## 质量（CER，越低越好）\n")
        L.append(f"共识文本取自 `{consensus_key}`（离所有引擎平均距离最近）。\n")
        L.append("| 引擎 | 模型 | 与共识 CER | 平均两两 CER |")
        L.append("|---|---|---:|---:|")
        for r in sorted(ok, key=lambda x: x.get("avg_cer", 0)):
            c = cer(consensus["text"], r["text"]) if r is not consensus else 0.0
            L.append(f"| {r['engine']} | {r['model']} | {c*100:.2f}% | {r.get('avg_cer',0)*100:.2f}% |")
        L.append("")

    if terms:
        L.append("## 关键术语命中（业务准确度）\n")
        L.append("| 引擎 | 模型 | " + " | ".join(terms) + " | 合计 |")
        L.append("|---|---|" + "---:|" * len(terms) + "---:|")
        for r in ok:
            counts = [r["text"].count(t) for t in terms]
            L.append(f"| {r['engine']} | {r['model']} | " +
                     " | ".join(str(c) for c in counts) + f" | {sum(counts)} |")
        L.append("")

    if bad:
        L.append("## 未能运行\n")
        for r in bad:
            first = (r.get("error") or "").strip().splitlines()
            L.append(f"- `{r['engine']}:{r['model']}` — {first[-1] if first else '未知错误'}")
        L.append("")

    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", help="wav 音频路径")
    ap.add_argument("--video", help="视频路径（会现抽 16k wav）")
    ap.add_argument("--seconds", type=float, default=0, help="只取前 N 秒（0=全部）")
    ap.add_argument("--engines", default="faster-whisper:base,mlx-whisper:large-v3-turbo,qwen3-asr:0.6b",
                    help="逗号分隔，格式 engine:model")
    ap.add_argument("--terms", default="", help="关键术语，逗号分隔（统计命中次数）")
    ap.add_argument("--repeat", type=int, default=1,
                    help="每个引擎跑几次（>1 时第一次算冷启动，其余取稳态最小值）")
    ap.add_argument("--out", default="", help="markdown 报告输出路径")
    ap.add_argument("--json", default="", help="原始结果 JSON 输出路径")
    args = ap.parse_args()

    audio = Path(args.audio).expanduser() if args.audio else None
    if args.video:
        from v2t import ffmpeg as ff
        tmp = Path(tempfile.mkdtemp(prefix="asrbench_")) / "clip.wav"
        src = Path(args.video).expanduser()
        cmd = ["ffmpeg", "-y"]
        if args.seconds:
            cmd += ["-t", str(args.seconds)]
        cmd += ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(tmp)]
        ff.run(cmd)
        audio = tmp
    if not audio or not audio.exists():
        print("需要 --audio 或 --video", file=sys.stderr)
        return 2

    duration = wav_seconds(audio)
    if args.seconds:
        duration = min(duration, args.seconds) if duration else args.seconds

    specs = []
    for item in args.engines.split(","):
        item = item.strip()
        if not item:
            continue
        engine, _, model = item.partition(":")
        specs.append((engine, model or ""))

    rows = []
    for engine, model in specs:
        print(f"→ {engine}:{model or '(默认)'} ...", file=sys.stderr, flush=True)
        row = run_engine(engine, model, audio, max(1, args.repeat))
        if row["ok"]:
            print(f"   ✓ 稳态 {row['elapsed']:.1f}s / 冷启动 {row['elapsed_cold']:.1f}s, "
                  f"{len(norm(row['text']))} 字, {row['rss_mb']:.0f} MB", file=sys.stderr)
        else:
            print(f"   ✗ 失败：{(row.get('error') or '').strip().splitlines()[-1][:160]}",
                  file=sys.stderr)
        rows.append(row)

    terms = [t.strip() for t in args.terms.split(",") if t.strip()]
    report = build_report(rows, duration, terms, str(audio))
    print(report)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n报告已写入 {args.out}", file=sys.stderr)
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"audio": str(audio), "duration": duration, "rows": rows},
            ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
