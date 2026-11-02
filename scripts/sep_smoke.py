#!/usr/bin/env python3
"""SEP #06 — 关键旧功能最小 smoke（不联网、不加载重模型）。

两条必过业务路径：
  1) asr-transcribe：引擎注册表 + 未知引擎拒识 + CLI engines --json
  2) distill-pipeline：蒸馏单元断言入口（复用 tests/test_distill_units.py）

退出码：0 = 全部 PASS；非 0 = FAIL。不得把未运行标为通过。
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v2t import asr  # noqa: E402


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)


def path_asr() -> None:
    rows = asr.list_engines()
    names = {r["engine"] for r in rows}
    required = {"faster-whisper", "mlx-whisper", "qwen3-asr", "whisper", "sensevoice", "minutes"}
    missing = required - names
    if missing:
        raise AssertionError(f"引擎注册表缺失: {sorted(missing)}")
    if len(rows) != 6:
        raise AssertionError(f"期望 6 个引擎，得到 {len(rows)}: {sorted(names)}")

    is_apple = sys.platform == "darwin" and platform.machine() == "arm64"
    mlx = next(r for r in rows if r["engine"] == "mlx-whisper")
    if not is_apple and mlx["available"]:
        raise AssertionError("非 Apple Silicon 上 mlx-whisper 不应 available=True")

    fw = next(r for r in rows if r["engine"] == "faster-whisper")
    if not fw["available"]:
        raise AssertionError("Linux/CI 基线要求 faster-whisper available=True")

    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "probe.wav"
        # minimal RIFF header is not required — unknown engine fails before decode
        wav.write_bytes(b"")
        try:
            asr.transcribe(wav, "sep_smoke_unknown", "no-such-engine")
            raise AssertionError("未知引擎应抛 ValueError")
        except ValueError as e:
            if "no-such-engine" not in str(e):
                raise AssertionError(f"未知引擎错误信息不含引擎名: {e}") from e

    proc = run([sys.executable, "cli.py", "engines", "--json"])
    if proc.returncode != 0:
        raise AssertionError(f"cli.py engines --json failed: {proc.stderr}")
    payload = json.loads(proc.stdout)
    engines = payload.get("engines") or payload
    if not isinstance(engines, list) or len(engines) < 6:
        raise AssertionError(f"CLI engines JSON 异常: {payload!r}")


def path_distill() -> None:
    proc = run([sys.executable, "tests/test_distill_units.py"])
    if proc.returncode != 0:
        raise AssertionError(
            "distill unit smoke failed\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        )
    if "失败 0" not in proc.stdout and "失败 0" not in proc.stderr:
        # distill suite prints 通过 N / 失败 0
        raise AssertionError(
            "distill 输出未包含「失败 0」，拒绝冒充通过\n"
            f"tail:\n{(proc.stdout or proc.stderr)[-1500:]}"
        )


def main() -> int:
    results = []
    for name, fn in (
        ("asr-transcribe", path_asr),
        ("distill-pipeline", path_distill),
    ):
        try:
            fn()
            print(f"PASS  {name}")
            results.append((name, "PASS", ""))
        except Exception as e:  # noqa: BLE001 — smoke must surface any failure
            print(f"FAIL  {name}: {e}", file=sys.stderr)
            results.append((name, "FAIL", str(e)))

    failed = [r for r in results if r[1] != "PASS"]
    print("---")
    print(f"paths={len(results)} pass={len(results) - len(failed)} fail={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
