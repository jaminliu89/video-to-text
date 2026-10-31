#!/usr/bin/env python
"""
cli.py — video2text 的 Agent 调用入口

给别的 Agent（Codex / Claude Code / 豆包）用的命令行接口。
所有命令支持 --json：结果输出到 stdout（JSON），日志走 stderr。

用法:
  # 转写（默认 sensevoice 本地引擎）
  python cli.py transcribe video.mp4 --asr sensevoice --json

  # 生成九宫格故事板
  python cli.py storyboard video.mp4 --json

  # 完整管线：转写 + 故事板 + 摘要
  python cli.py digest video.mp4 --deep --category 课程 --json

  # 批量处理目录
  python cli.py batch ./input/ --category 课程 --json

  # 蒸馏整个文件夹（第三模式：去重 + 合并 + 方法论 + 产品逆向）
  python cli.py distill ~/Movies/某门课/ --category 课程 --json

  # 列出资产
  python cli.py list --category 课程 --json

  # 读取某个资产
  python cli.py info output/课程/视频名 --json
"""

import argparse
import json
import sys
from pathlib import Path

# 让 import 能找到项目根
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from v2t import asr, storyboard, assets
from v2t import ffmpeg as ff


ASR_ENGINES = ["faster-whisper", "mlx-whisper", "qwen3-asr",
               "whisper", "sensevoice", "minutes"]


def out_json(data, as_json: bool):
    """统一输出"""
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        # 人类可读
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"  {k}: {v}")
        elif isinstance(data, list):
            for item in data:
                print(f"  - {item}")
        else:
            print(data)


def cmd_transcribe(args):
    """转写视频音频"""
    video_path = Path(args.input).expanduser().resolve()
    if not video_path.exists():
        out_json({"error": f"找不到: {video_path}"}, args.json); sys.exit(1)

    cache_key = video_path.stem
    audio_path = cfg.CACHE_DIR / f"{cache_key}_audio.wav"
    if not audio_path.exists():
        ff.extract_audio(video_path, audio_path)

    segments = asr.transcribe(audio_path, cache_key, args.asr,
                              model_size=getattr(args, "asr_model", None))

    # 保存到资产目录
    asset_dir = assets.get_asset_dir(video_path, args.category)
    assets.save_transcript(asset_dir, segments)

    out_json({
        "video": str(video_path),
        "engine": args.asr,
        "segments_count": len(segments),
        "total_chars": sum(len(s["text"]) for s in segments),
        "segments": segments,
        "asset_dir": str(asset_dir),
    }, args.json)


def cmd_storyboard(args):
    """生成九宫格故事板"""
    video_path = Path(args.input).expanduser().resolve()
    if not video_path.exists():
        out_json({"error": f"找不到: {video_path}"}, args.json); sys.exit(1)

    asset_dir = assets.get_asset_dir(video_path, args.category)
    result = storyboard.build_storyboard(video_path, asset_dir, max_frames=args.max_frames)

    out_json({
        "video": str(video_path),
        "total_frames": len(result["index"]),
        "pages": [str(p) for p in result["pages"]],
        "asset_dir": str(asset_dir),
    }, args.json)


def cmd_digest(args):
    """完整管线：转写 + 故事板 + LLM 摘要 + md 笔记"""
    video_path = Path(args.input).expanduser().resolve()
    if not video_path.exists():
        out_json({"error": f"找不到: {video_path}"}, args.json); sys.exit(1)

    asset_dir = assets.get_asset_dir(video_path, args.category)

    # 0. 拿视频信息
    from video2text import probe_video, summarize_with_llm, write_markdown_output
    video_info = probe_video(video_path)

    # 1. 转写
    cache_key = video_path.stem
    audio_path = cfg.CACHE_DIR / f"{cache_key}_audio.wav"
    if not audio_path.exists():
        ff.extract_audio(video_path, audio_path)

    segments = asr.transcribe(audio_path, cache_key, args.asr,
                              model_size=getattr(args, "asr_model", None))
    assets.save_transcript(asset_dir, segments)

    # 2. 故事板
    sb_result = storyboard.build_storyboard(video_path, asset_dir, max_frames=args.max_frames)

    # 3. LLM 摘要（需要 SILICONFLOW_API_KEY）
    summary = summarize_with_llm(segments, video_info, deep=args.deep)

    # 4. 写 md 笔记
    md_path = asset_dir / f"{video_path.stem}.md"
    write_markdown_output(video_path, video_info, segments, summary, [], md_path)

    # 5. 组装结果
    result = {
        "video": str(video_path),
        "asset_dir": str(asset_dir),
        "md_path": str(md_path),
        "transcript": {
            "engine": args.asr,
            "segments_count": len(segments),
            "total_chars": sum(len(s["text"]) for s in segments),
        },
        "storyboard": {
            "total_frames": len(sb_result["index"]),
            "pages": [str(p) for p in sb_result["pages"]],
        },
        "summary": {
            "has_summary": "error" not in summary,
            "one_liner": summary.get("one_liner", ""),
            "core_points_count": len(summary.get("core_points", [])),
        },
    }
    out_json(result, args.json)


def cmd_batch(args):
    """批量处理目录"""
    input_dir = Path(args.input).expanduser().resolve()
    if not input_dir.is_dir():
        out_json({"error": f"不是目录: {input_dir}"}, args.json); sys.exit(1)

    video_exts = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
    videos = sorted([
        p for p in input_dir.iterdir()
        if p.suffix.lower() in video_exts and p.stat().st_size > 1024*1024
    ])

    if not videos:
        out_json({"error": f"目录里没有视频: {input_dir}"}, args.json); sys.exit(1)

    results = []
    for i, v in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}] {v.name}", file=sys.stderr)
        try:
            args_clone = argparse.Namespace(**vars(args))
            args_clone.input = str(v)
            cmd_digest(args_clone)
            results.append({"video": v.name, "status": "ok"})
        except Exception as e:
            results.append({"video": v.name, "status": "fail", "error": str(e)})

    out_json({
        "total": len(videos),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
        "results": results,
    }, args.json)


def cmd_list(args):
    """列出资产"""
    asset_dirs = assets.list_assets(args.category)
    summaries = [assets.get_asset_summary(d) for d in asset_dirs]
    out_json({"count": len(summaries), "assets": summaries}, args.json)


def cmd_distill(args):
    """第三模式：蒸馏整个文件夹

    固定八阶段：采集 → 去重 → 转写 → 合并 → 深读 → 综合 → 方法论 → 产品逆向 → 产出
    进度日志走 stderr，最终结果走 stdout（--json 时是 JSON）。
    """
    from v2t import distill

    folder = Path(args.input).expanduser().resolve()
    if not folder.is_dir():
        out_json({"error": f"不是目录: {folder}"}, args.json); sys.exit(1)

    def log(msg=""):
        print(msg, file=sys.stderr, flush=True)

    try:
        result = distill.run_distill(
            folder=folder,
            category=args.category,
            batch=args.name,
            asr_engine=args.asr,
            whisper_model=args.asr_model,
            use_llm=not args.no_llm,
            max_videos=args.max_videos,
            resume=not args.fresh,
            concurrency=args.concurrency,
            hotwords=args.hotwords,
            log=log,
        )
    except Exception as e:
        out_json({"error": str(e)}, args.json); sys.exit(1)

    out_json(result, args.json)


def cmd_engines(args):
    """列出转写引擎及可用性（装了什么、还缺什么）"""
    rows = asr.list_engines()
    if args.json:
        out_json({"engines": rows}, True)
        return
    print(f"{'引擎':<16}{'可用':<6}{'默认模型':<18}{'说明'}")
    print("-" * 78)
    for r in rows:
        ok = "✓" if r["available"] else "✗"
        note = r["reason"] or ("Metal GPU" if r["gpu"] else (r.get("channel") or ""))
        print(f"{r['engine']:<16}{ok:<6}{r['default_model']:<18}{note}")


def cmd_info(args):
    """读取某个资产"""
    asset_dir = Path(args.input).expanduser().resolve()
    if not asset_dir.is_dir():
        out_json({"error": f"不是目录: {asset_dir}"}, args.json); sys.exit(1)
    out_json(assets.get_asset_summary(asset_dir), args.json)


def main():
    parser = argparse.ArgumentParser(description="video2text Agent CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # 公共参数
    def add_common(p):
        p.add_argument("--asr", default="faster-whisper", choices=ASR_ENGINES,
                       help="转写引擎（默认 faster-whisper；Apple Silicon 用 mlx-whisper 快 5-8 倍）")
        p.add_argument("--asr-model", default=None,
                       help="引擎对应的模型：faster/mlx 用 base/small/large-v3-turbo，qwen3 用 0.6b/1.7b/flash")
        p.add_argument("--category", default="未分类", help="资产分类目录")
        p.add_argument("--max-frames", type=int, default=24, help="故事板最大帧数")
        p.add_argument("--json", action="store_true", help="JSON 输出到 stdout")

    p_trans = sub.add_parser("transcribe", help="转写视频音频")
    p_trans.add_argument("input", help="视频文件路径")
    add_common(p_trans)
    p_trans.set_defaults(func=cmd_transcribe)

    p_sb = sub.add_parser("storyboard", help="生成九宫格故事板")
    p_sb.add_argument("input", help="视频文件路径")
    add_common(p_sb)
    p_sb.set_defaults(func=cmd_storyboard)

    p_dig = sub.add_parser("digest", help="完整管线：转写+故事板")
    p_dig.add_argument("input", help="视频文件路径")
    p_dig.add_argument("--deep", action="store_true", help="深度模式")
    add_common(p_dig)
    p_dig.set_defaults(func=cmd_digest)

    p_batch = sub.add_parser("batch", help="批量处理目录")
    p_batch.add_argument("input", help="目录路径")
    add_common(p_batch)
    p_batch.set_defaults(func=cmd_batch)

    p_distill = sub.add_parser(
        "distill",
        help="第三模式：蒸馏整个文件夹（去重 + 合并 + 方法论 + 产品逆向）",
    )
    p_distill.add_argument("input", help="文件夹路径（可含子目录）")
    p_distill.add_argument("--asr", default="faster-whisper", choices=ASR_ENGINES,
                           help="转写引擎")
    p_distill.add_argument("--asr-model", "--whisper-model", dest="asr_model", default=None,
                           help="模型：faster/mlx 用 tiny/base/small/medium/large-v3/large-v3-turbo；"
                                "qwen3-asr 用 0.6b/1.7b/flash（默认取各引擎的 config 默认值）")
    p_distill.add_argument("--category", default="未分类", help="资产分类目录")
    p_distill.add_argument("--name", default=None, help="批次名（默认用文件夹名）")
    p_distill.add_argument("--max-videos", type=int, default=None, help="只跑前 N 个视频（试跑用）")
    p_distill.add_argument("--no-llm", action="store_true", help="跳过 LLM，只做去重+转写+合并")
    p_distill.add_argument("--concurrency", type=int, default=3,
                           help="LLM 并发数（网络 IO，默认 3）")
    p_distill.add_argument("--hotwords", default="",
                           help='热词纠正表，如 "新约写作=星月写作,新约=星月"（修 ASR 专名误听）')
    p_distill.add_argument("--fresh", action="store_true", help="忽略缓存，全部重跑")
    p_distill.add_argument("--json", action="store_true", help="JSON 输出到 stdout")
    p_distill.set_defaults(func=cmd_distill)

    p_list = sub.add_parser("list", help="列出资产")
    p_list.add_argument("--category", default=None, help="按分类筛选")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_engines = sub.add_parser("engines", help="列出转写引擎及可用性")
    p_engines.add_argument("--json", action="store_true")
    p_engines.set_defaults(func=cmd_engines)

    p_info = sub.add_parser("info", help="读取资产摘要")
    p_info.add_argument("input", help="资产目录路径")
    p_info.add_argument("--json", action="store_true")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
