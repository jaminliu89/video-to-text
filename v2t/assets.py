"""
v2t/assets.py — 分类资产目录管理

把扁平的 output/*.md 改成分类目录结构：
  output/
    <分类>/
      <视频名>/
        <视频名>.md          # 笔记
        <视频名>.json        # 结构化数据
        transcript.json     # 转写 segments
        storyboard_p01.jpg  # 故事板
        _frames/            # 抽帧缓存
"""

import json
from pathlib import Path

import config as cfg

OUTPUT_DIR = cfg.OUTPUT_DIR


def get_asset_dir(video_path: Path, category: str = "未分类") -> Path:
    """获取某个视频的资产目录（自动创建）"""
    safe_name = video_path.stem.replace("/", "_").replace(" ", "_")
    asset_dir = OUTPUT_DIR / category / safe_name
    asset_dir.mkdir(parents=True, exist_ok=True)
    return asset_dir


def save_note(asset_dir: Path, video_path: Path, content: str) -> Path:
    """保存 markdown 笔记"""
    md_path = asset_dir / f"{video_path.stem}.md"
    md_path.write_text(content, encoding="utf-8")
    return md_path


def save_json(asset_dir: Path, video_path: Path, data: dict) -> Path:
    """保存结构化 JSON"""
    json_path = asset_dir / f"{video_path.stem}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def save_transcript(asset_dir: Path, segments: list) -> Path:
    """保存转写 segments"""
    t_path = asset_dir / "transcript.json"
    t_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    return t_path


def list_assets(category: str = None) -> list:
    """列出所有资产目录"""
    base = OUTPUT_DIR / category if category else OUTPUT_DIR
    if not base.exists():
        return []
    return sorted([p for p in base.iterdir() if p.is_dir()])


def get_asset_summary(asset_dir: Path) -> dict:
    """读取一个资产目录的摘要"""
    md_files = list(asset_dir.glob("*.md"))
    json_files = list(asset_dir.glob("*.json"))
    storyboards = sorted(asset_dir.glob("storyboard_p*.jpg"))

    return {
        "dir": str(asset_dir),
        "name": asset_dir.name,
        "md": str(md_files[0]) if md_files else None,
        "json": str(json_files[0]) if json_files else None,
        "storyboards": [str(p) for p in storyboards],
        "has_transcript": (asset_dir / "transcript.json").exists(),
    }
