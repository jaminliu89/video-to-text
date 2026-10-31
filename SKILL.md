---
name: video2text
description: 视频转结构化笔记工具。把课程、讲座、访谈、纪录片视频转成带时间戳的逐字稿、九宫格故事板、章节摘要；第三种模式「蒸馏」可对整个文件夹做去重、逐字稿合并、方法论抽象、产品架构与商业模式逆向。支持本地免费引擎（SenseVoice 语音识别）、关键帧画面理解、飞书妙记。供其他 Agent 通过 CLI 调用。
---

# video2text — 视频转结构化笔记

## 能力

| 命令 | 作用 | 输出 |
|------|------|------|
| `transcribe` | 转写视频音频为带时间戳的逐字稿 | JSON segments |
| `storyboard` | 抽帧拼成九宫格故事板 | 分页 JPG 图 |
| `digest` | 完整管线：转写 + 故事板 | 资产目录 |
| `distill` | **第三模式：整个文件夹蒸馏** | 认知包（5 份 md + json + 逐字稿） |
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

# 蒸馏整个文件夹（第三模式）
python3 cli.py distill ~/Movies/某门课/ --category 课程 --json

# 列出所有资产
python3 cli.py list --json
```

## 第三模式：蒸馏（distill）

给一个文件夹，产出"这批视频到底讲了什么"的完整认知包。固定八阶段：

```
S0 采集 → S1 去重 → S2 转写 → S3 合并 → S4 深读 → S5 综合 → S6 抽象 → S7 逆向 → S8 产出
```

| 阶段 | 做什么 | 关键判据 |
|---|---|---|
| S1 去重 | 三层：SHA-256 / 时长+画面 dHash / 逐字稿相似度 | 汉明 ≤6、Jaccard ≥0.8 |
| S3 合并 | 跨视频语句级去重 + 段落化 | 包含率 ≥85% 判重复 |
| S4 深读 | 单视频结构化：讲了什么/步骤/概念/硬数字/界面证据/坑 | 只基于材料，无证据留空 |
| S5 综合 | 主题图谱 + 知识单元合并 + 冲突 + 学习路径 | — |
| S6 抽象 | 方法论 L0 事实 → L1 规律 → L2 方法 → L3 心智模型 | 方法卡里出现产品名即失败 |
| S7 逆向 | 产品架构 + 商业模式 + 复刻路径（仅当涉及产品） | 规则信号 + LLM 判定 |

产出：

```
output/<分类>/<批次>/
  00_总览.md  01_逐字稿合并.md  02_方法论.md  03_产品逆向.md  04_证据索引.md
  dedupe_report.md  distill.json  transcripts/  _work/
```

常用参数：`--max-videos 3` 试跑、`--no-llm` 只去重转写、`--whisper-model small` 更准、
`--hotwords "错=对"` 修专名误听、`--concurrency 3` LLM 并发、`--fresh` 忽略缓存、`--name 批次名`。
方法规范见 `docs/distill-method.md`。

## 转写引擎选择

先跑 `python3 cli.py engines --json` 查这台机器上哪些引擎真能用（返回 `available` 与 `reason`）。

| 引擎 | 命令参数 | 稳态速度（122s 音频） | 质量 | 说明 |
|------|---------|------|------|------|
| **mlx-whisper**（Apple Silicon 推荐） | `--asr mlx-whisper --asr-model large-v3-turbo` | **5.3s（23x）** | ⭐⭐⭐⭐ | Metal GPU；`base` 更快，1.7s（72x） |
| faster-whisper（默认） | `--asr faster-whisper --asr-model base` | 14.3s（8.6x） | ⭐⭐⭐ | 跨平台，稳 |
| qwen3-asr | `--asr qwen3-asr --asr-model 0.6b` | 11.5s（10.6x） | ⭐⭐⭐⭐ | 断句标点最好；`flash` 走云端，零下载 |
| sensevoice | `--asr sensevoice` | — | ⭐⭐⭐⭐ | 标点好，需本地 funasr |
| minutes | `--asr minutes` | 云端 | ⭐⭐⭐⭐ | 飞书妙记，需 lark-cli |

**选型规则**：Apple Silicon → `mlx-whisper`；其他平台 → `faster-whisper`；
要断句标点好 → `qwen3-asr`。详细对比与复现方式见 `docs/asr-engines.md`。

> 引擎不是第一手段。专有名词被系统性听错时，先用 `--hotwords "错词=正词"`（零成本），
> 换模型是最后一步。

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
