---
name: video2text
description: 视频转结构化笔记工具。把课程、讲座、访谈、纪录片视频转成带时间戳的逐字稿、九宫格故事板、章节摘要。支持本地免费引擎（SenseVoice 语音识别）、关键帧画面理解、飞书妙记。供其他 Agent 通过 CLI 调用。
---

# video2text — 视频转结构化笔记

## 能力

| 命令 | 作用 | 输出 |
|------|------|------|
| `transcribe` | 转写视频音频为带时间戳的逐字稿 | JSON segments |
| `storyboard` | 抽帧拼成九宫格故事板 | 分页 JPG 图 |
| `digest` | 完整管线：转写 + 故事板 | 资产目录 |
| `batch` | 批量处理整个目录 | 汇总 JSON |
| `list` | 列出已处理的视频资产 | JSON 列表 |
| `info` | 读某个视频的资产摘要 | JSON |

## 快速调用

```bash
cd /Users/kimliu/Developer/video-to-text

# 转写（默认 sensevoice 本地引擎，免费、中文准）
python3 cli.py transcribe /path/to/video.mp4 --asr sensevoice --json

# 生成九宫格故事板
python3 cli.py storyboard /path/to/video.mp4 --json

# 完整管线（转写 + 故事板，存到"课程"分类）
python3 cli.py digest /path/to/video.mp4 --category 课程 --json

# 批量处理目录
python3 cli.py batch ~/Movies/课程/ --category 课程 --json

# 列出所有资产
python3 cli.py list --json
```

## 转写引擎选择

| 引擎 | 命令参数 | 大小 | 成本 | 质量 | 说明 |
|------|---------|------|------|------|------|
| whisper base（默认） | `--asr whisper` | 141MB | 免费 | ⭐⭐⭐ | 简体、错字少、时间戳细 |
| sensevoice（增强） | `--asr sensevoice` | 893MB | 免费 | ⭐⭐⭐⭐ | 标点好、流畅度高，需本地 funasr |
| minutes | `--asr minutes` | 云端 | 免费额度 | ⭐⭐⭐⭐ | 飞书妙记，需 lark-cli |

## 输出资产结构

```
output/
  <分类>/
    <视频名>/
      <视频名>.md          # 笔记
      <视频名>.json        # 结构化数据
      transcript.json      # 转写 segments
      storyboard_p01.jpg   # 故事板第1页
      storyboard_p02.jpg   # 故事板第2页
      storyboard_index.json
```

## 给 Agent 的提示

- 所有命令加 `--json`，结果输出到 stdout，日志走 stderr，可直接解析
- 转写缓存：同一个视频不重复转写，结果存在 `cache/`
- 故事板缓存：同一个视频不重复抽帧
- 首次运行 sensevoice 会下载模型（~900MB），之后秒级启动
- 需要 ffmpeg（系统已装）
