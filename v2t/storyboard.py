"""
v2t/storyboard.py — 九宫格故事板抽帧

把视频抽成 hybrid 关键帧（均匀 + 场景切换检测），拼成 3x3 九宫格分页图，
每格带时间戳标签。Agent 或人看一张图就能知道视频讲什么。

输出：
  <output_dir>/storyboard_p01.jpg  (每页 9 帧)
  <output_dir>/storyboard_index.json  (帧清单 + 时间戳)
"""

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def extract_scene_frames(video_path: Path, frames_dir: Path, scene_threshold: float = 0.30) -> list:
    """用 ffmpeg 场景切换检测抽帧，返回帧文件列表（按时间排序）"""
    frames_dir.mkdir(parents=True, exist_ok=True)

    # 场景切换检测抽帧
    pattern = str(frames_dir / "scene_%04d.jpg")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"select='gt(scene,{scene_threshold})',scale=640:-1",
        "-vsync", "vfr",
        "-q:v", "3",
        pattern,
    ], capture_output=True, timeout=300)

    return sorted(frames_dir.glob("scene_*.jpg"))


def get_video_duration(video_path: Path) -> float:
    """拿视频时长（秒）"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def extract_uniform_frames(video_path: Path, frames_dir: Path, max_frames: int = 24) -> list:
    """均匀抽帧"""
    duration = get_video_duration(video_path)
    if duration <= 0:
        return []

    interval = duration / max_frames
    pattern = str(frames_dir / "uni_%04d.jpg")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"fps=1/{interval},scale=640:-1",
        "-q:v", "3",
        pattern,
    ], capture_output=True, timeout=300)

    return sorted(frames_dir.glob("uni_*.jpg"))


def hybrid_frames(video_path: Path, frames_dir: Path, max_frames: int = 24,
                  scene_threshold: float = 0.30) -> list:
    """混合抽帧：均匀 + 场景切换，去重后按时间排序

    返回 [{"path": Path, "time": float}, ...]
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    duration = get_video_duration(video_path)

    # 1. 均匀抽帧
    uniform = extract_uniform_frames(video_path, frames_dir, max_frames)

    # 2. 场景切换抽帧
    scene = extract_scene_frames(video_path, frames_dir, scene_threshold)

    # 3. 合并：均匀帧为基础，场景帧补充（如果和均匀帧时间太接近就跳过）
    all_frames = []
    used_times = []

    for i, f in enumerate(uniform):
        t = (i + 0.5) * duration / max_frames
        all_frames.append({"path": f, "time": round(t, 2)})
        used_times.append(t)

    for f in scene:
        # 从文件名拿不到精确时间，用文件顺序估算
        idx = int(f.stem.split("_")[1]) - 1
        t = idx * duration / max(1, len(scene))
        # 如果和已有帧时间太接近（<2秒），跳过
        if any(abs(t - ut) < 2.0 for ut in used_times):
            continue
        all_frames.append({"path": f, "time": round(t, 2)})
        used_times.append(t)

    # 按时间排序
    all_frames.sort(key=lambda x: x["time"])
    return all_frames


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def make_storyboard(frames: list, output_path: Path, cols: int = 3, rows: int = 3):
    """把帧拼成 cols x rows 的九宫格图，每格带时间戳标签"""
    if not frames:
        return None

    # 统一帧尺寸
    cell_w, cell_h = 640, 360  # 16:9
    label_h = 30  # 底部时间戳标签高度

    # 一页 cols*rows 帧
    pages = [frames[i:i+cols*rows] for i in range(0, len(frames), cols*rows)]

    page_files = []
    for page_idx, page_frames in enumerate(pages, 1):
        canvas_w = cols * cell_w
        canvas_h = rows * (cell_h + label_h)
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        draw = ImageDraw.Draw(canvas)

        # 尝试加载字体
        try:
            font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 18)
        except Exception:
            font = ImageFont.load_default()

        for i, frame in enumerate(page_frames):
            row = i // cols
            col = i % cols
            x = col * cell_w
            y = row * (cell_h + label_h)

            # 贴帧
            try:
                img = Image.open(frame["path"]).convert("RGB")
                img = img.resize((cell_w, cell_h))
                canvas.paste(img, (x, y))
            except Exception:
                draw.rectangle([x, y, x+cell_w, y+cell_h], fill="#eee")

            # 时间戳标签
            label = fmt_time(frame["time"])
            draw.rectangle([x, y+cell_h, x+cell_w, y+cell_h+label_h], fill="black")
            draw.text((x+8, y+cell_h+6), label, fill="yellow", font=font)

        page_path = output_path.parent / f"{output_path.stem}_p{page_idx:02d}.jpg"
        canvas.save(page_path, "JPEG", quality=85)
        page_files.append(page_path)
        print(f"  ✓ 故事板: {page_path.name} ({len(page_frames)} 帧)")

    return page_files


def build_storyboard(video_path: Path, output_dir: Path, max_frames: int = 24) -> dict:
    """完整故事板管线：抽帧 + 拼图 + 索引

    返回 {"pages": [Path...], "index": [{"path", "time"}, ...]}
    """
    frames_dir = output_dir / "_frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    index_file = output_dir / "storyboard_index.json"
    if index_file.exists():
        print(f"  ✓ 故事板已缓存")
        data = json.loads(index_file.read_text())
        return {"pages": [output_dir / p for p in data.get("page_names", [])],
                "index": data.get("frames", [])}

    print(f"  → 抽关键帧 (hybrid, {max_frames} 帧)...", end=" ", flush=True)
    frames = hybrid_frames(video_path, frames_dir, max_frames)
    print(f"✓ {len(frames)} 帧")

    storyboard_path = output_dir / "storyboard.jpg"
    pages = make_storyboard(frames, storyboard_path)

    index_data = {
        "video": str(video_path),
        "total_frames": len(frames),
        "frames": [{"time": f["time"], "path": str(f["path"])} for f in frames],
        "page_names": [p.name for p in (pages or [])],
    }
    index_file.write_text(json.dumps(index_data, ensure_ascii=False, indent=2))

    return {"pages": pages or [], "index": frames}
