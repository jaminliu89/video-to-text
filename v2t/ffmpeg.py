"""
v2t/ffmpeg.py — ffmpeg / ffprobe 定位与探测

为什么要单独一个模块：
  非交互式 shell（IDE 内置终端、CI、Agent 子进程、cron）常常拿不到
  Homebrew 的 PATH，导致 shutil.which("ffmpeg") 返回 None，
  而 subprocess 直接调 "ffmpeg" 会抛 FileNotFoundError。
  这里做一次统一解析：环境变量 > PATH > 常见安装目录，并缓存结果。

对外接口：
  ffmpeg()  -> str      ffmpeg 可执行文件路径
  ffprobe() -> str      ffprobe 可执行文件路径
  run(cmd, **kw)        subprocess 封装（返回 CompletedProcess）
  probe(path) -> dict   视频元信息（时长/宽高/大小/有无音轨）
"""

import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

# 常见安装位置（macOS Homebrew ARM / Intel、Linuxbrew、Windows 常见路径）
_CANDIDATE_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/snap/bin",
    str(Path.home() / "bin"),
]


@lru_cache(maxsize=None)
def _resolve(name: str) -> str:
    """解析可执行文件路径：环境变量 > PATH > 候选目录 > 裸名字"""
    env_key = f"{name.upper()}_BIN"
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        return env_val

    found = shutil.which(name)
    if found:
        return found

    for d in _CANDIDATE_DIRS:
        p = Path(d) / name
        if p.exists() and os.access(p, os.X_OK):
            return str(p)

    # 实在找不到就返回裸名字，让 subprocess 报出可读的错误
    return name


def ffmpeg() -> str:
    return _resolve("ffmpeg")


def ffprobe() -> str:
    return _resolve("ffprobe")


def ensure_available() -> None:
    """启动前检查，给出人类可读的安装提示"""
    missing = [n for n, p in (("ffmpeg", ffmpeg()), ("ffprobe", ffprobe()))
               if not Path(p).exists() and shutil.which(p) is None]
    if missing:
        raise RuntimeError(
            f"找不到 {' / '.join(missing)}。请先安装：\n"
            f"  macOS:  brew install ffmpeg\n"
            f"  Ubuntu: sudo apt install ffmpeg\n"
            f"也可以用环境变量 FFMPEG_BIN / FFPROBE_BIN 指定绝对路径。"
        )


def run(cmd: list, timeout: int = 1800, check: bool = False) -> subprocess.CompletedProcess:
    """subprocess.run 封装：把 argv[0] 换成解析后的绝对路径"""
    argv = list(cmd)
    if argv and argv[0] in ("ffmpeg", "ffprobe"):
        argv[0] = ffmpeg() if argv[0] == "ffmpeg" else ffprobe()
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout, check=check)


def probe(path: Path) -> dict:
    """读取视频元信息。失败时返回全 0 的安全默认值，不抛异常。"""
    try:
        r = run([
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ], timeout=60)
        info = json.loads(r.stdout or "{}")
    except Exception:
        return {"duration": 0.0, "size": 0, "width": 0, "height": 0,
                "has_audio": False, "format": ""}

    fmt = info.get("format", {}) or {}
    streams = info.get("streams", []) or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    try:
        size = int(fmt.get("size", 0) or 0)
    except (TypeError, ValueError):
        size = 0

    return {
        "duration": duration,
        "size": size or (path.stat().st_size if path.exists() else 0),
        "width": int((v or {}).get("width", 0) or 0),
        "height": int((v or {}).get("height", 0) or 0),
        "has_audio": a is not None,
        "format": fmt.get("format_name", "") or "",
    }


def _ensure_dir(p: Path) -> Path:
    """某些网络盘/沙箱文件系统上 mkdir(exist_ok=True) 仍会抛 EEXIST"""
    p = Path(p)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        if not p.is_dir():
            raise
    return p


def extract_audio(video_path: Path, out_wav: Path, timeout: int = 3600) -> Path:
    """抽 16k 单声道 wav（ASR 统一输入）"""
    _ensure_dir(out_wav.parent)
    r = run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(out_wav),
    ], timeout=timeout)
    if not out_wav.exists():
        raise RuntimeError(f"抽音频失败：{r.stderr[-400:]}")
    return out_wav


def grab_frame(video_path: Path, ts: float, out_jpg: Path, width: int = 320) -> Path | None:
    """在指定时间点抓一帧（用于画面指纹 / 去重）"""
    _ensure_dir(out_jpg.parent)
    r = run([
        "ffmpeg", "-y", "-ss", f"{max(0.0, ts):.3f}", "-i", str(video_path),
        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4",
        str(out_jpg),
    ], timeout=120)
    return out_jpg if out_jpg.exists() else None


def main(argv=None):
    """自检：python -m v2t.ffmpeg"""
    print(f"ffmpeg : {ffmpeg()}")
    print(f"ffprobe: {ffprobe()}")
    try:
        ensure_available()
        print("✓ 可用")
    except RuntimeError as e:
        print(f"✗ {e}")
        return 1
    if argv:
        print(json.dumps(probe(Path(argv[0])), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
