# VideoToText — 本地优先的视频知识萃取器

> 把课程、讲座、纪录片视频转成可检索、可复用的结构化笔记。
> 支持三种引擎、三种模式，GUI + CLI 双模式。

---

## 界面预览

![VideoToText 主界面](screenshots/home.png)

浅色 Parchment 风格，干净克制。功能一目了然。

---

## 这是什么

你买了一堆课程、存了一堆讲座视频，从来没回头看过？

VideoToText 把视频转成**结构化文本**——不只是逐字稿，还有章节摘要、金句、行动项。
存到 Obsidian 里，以后想找什么直接搜，不用再拖进度条。

## 核心亮点

- **本地优先**：所有数据存在本地，API Key 也是你自己的，不上传任何数据到第三方服务器
- **三种转写引擎，按需切换**：
  - **SenseVoice（默认）** — 本地免费，中文准，长音频不重复字
  - Whisper.cpp — 本地免费，备用
  - 飞书妙记 — 免费额度，云端
- **九宫格故事板** — 把视频抽成 3x3 分页图，带时间戳，一张图知道视频讲什么
- **三种画面理解引擎**：豆包视频理解（质量最高）/ 关键帧+VLM（便宜）/ 完全本地
- **批量处理**：拖一整个文件夹进去，自动排队，处理完自动导出
- **蒸馏模式（第三模式）**：整个文件夹丢进去，自动去重、合并逐字稿、抽象方法论，涉及产品还能逆推出架构和商业模式
- **分类资产目录**：每个视频一个文件夹，笔记/转写/故事板分类存放
- **Agent CLI 接口**：别的 Agent（Codex/Claude Code/豆包）可通过 `cli.py --json` 调用
- **Obsidian 原生导出**：直接写入你的 Vault，跟笔记体系无缝衔接
- **缓存机制**：同一个视频不重复付费，结果本地缓存

---

## 三种模式

| 模式 | 输入 | 输出 | 适用场景 |
|------|------|------|---------|
| **逐字稿** | 单个/多个视频 | SRT / TXT / Markdown 带时间戳 | 字幕、速记、全文检索 |
| **深度拆解** | 单个/多个视频 | 摘要 + 章节 + 金句 + 行动项 + 原文引用 | 课程笔记、知识内化、内容创作素材 |
| **蒸馏** | **一个文件夹**（可含子目录） | 去重后的合并逐字稿 + 主题图谱 + 方法论 + 产品逆向 | 买来的一整套课、竞品教程合集、访谈合集 |

### 蒸馏模式做了什么

不是"转文字"，是把一堆散乱视频变成**一份可以拿去决策的认知包**。固定八阶段：

```
S0 采集 → S1 去重 → S2 转写 → S3 合并 → S4 深读 → S5 综合 → S6 抽象 → S7 逆向 → S8 产出
```

- **去重三层**：文件 SHA-256 → 时长+画面 dHash → 逐字稿相似度。同一门课的重录、切片、转码版都能识别
- **合并**：跨视频语句级去重，同一句话被 19 个视频讲过只保留一次，`dedupe_report.md` 里能看到每条视频被砍了多少
- **深读**：每个视频拆成 讲了什么 / 章节 / 可照做的步骤 / 术语 / 硬数字 / 界面线索 / 坑 / 主张
- **方法论**：强制四层——L0 事实 → L1 规律 → L2 方法 → L3 心智模型，**方法卡里出现产品名即判定失败**（那还是操作，不是方法）
- **产品逆向**：涉及产品时，从"能看到的功能"反推模块，从"反复强调的卖点"反推收费，从"必须教的步骤"反推摩擦，输出架构图 + 商业模式 + 复刻路径

方法论细节见 [`docs/distill-method.md`](docs/distill-method.md)。

---

## 快速开始

### 环境要求

- Python 3.10+
- ffmpeg（系统安装：`brew install ffmpeg` 或官网下载）
- （可选）whisper.cpp — 本地模式需要

### 安装

```bash
git clone https://github.com/jaminliu89/video-to-text.git
cd video-to-text
pip install -r requirements.txt
```

### 配置

方式一：复制 `.env.example` 为 `.env`，填入你的 API Key

```bash
cp .env.example .env
# 编辑 .env
```

方式二：启动后在 GUI 的「设置」页面配置（推荐，可视化）

### 启动 GUI

```bash
python gui.py
```

浏览器自动打开，开始用。

### 使用 CLI

```bash
# 逐字稿模式（音频转写，最便宜）
python video2text.py 视频路径.mp4

# 深度拆解 + 豆包视频理解
python video2text.py --mode video --deep 视频路径.mp4

# 批量处理整个文件夹 + 导出 Obsidian
python video2text.py --mode audio --deep --obsidian ~/Movies/课程/
```

### 蒸馏整个文件夹（第三模式）

```bash
# 一个文件夹进去，一份认知包出来（默认断点续跑）
python3 cli.py distill ~/Movies/某门课/ --category 课程 --json

# 先试跑 3 个视频看看效果
python3 cli.py distill ~/Movies/某门课/ --max-videos 3

# 不要 LLM，只要去重 + 逐字稿合并（不花钱，快）
python3 cli.py distill ~/Movies/某门课/ --no-llm

# 转写要更准（慢 3-5 倍）
python3 cli.py distill ~/Movies/某门课/ --whisper-model small

# 专有名词总被听错？给张纠错表，比换大模型便宜得多
python3 cli.py distill ~/Movies/某门课/ --hotwords "新约写作=星月写作,新约=星月"
```

产出：

```
output/课程/某门课/
  00_总览.md          # 一页看懂：数字、主题地图、知识单元、冗余、冲突、缺口、学习路径
  01_逐字稿合并.md     # 去重合并后的逐字稿，带 [V03 04:12] 锚点
  02_方法论.md        # 总方法 + 方法卡 + 心智模型 + 决策表 + 质量线
  03_产品逆向.md      # 定位 / 架构(mermaid) / 商业模式 / 复刻路径
  04_证据索引.md      # 硬数字表 + 每个视频的章节/步骤/界面线索/坑/原话
  dedupe_report.md    # 三层去重明细
  distill.json        # 全量结构化数据（给 Agent 用）
  transcripts/        # 单视频逐字稿 md/srt/txt
```

---

## 转写引擎对比

| 引擎 | 命令参数 | 大小 | 成本 | 中文质量 | 长音频重复字 |
|------|---------|------|------|---------|-------------|
| **whisper base（默认）** | `--asr whisper` | 141MB | 免费 | ⭐⭐⭐ | 无 |
| sensevoice（增强） | `--asr sensevoice` | 893MB | 免费 | ⭐⭐⭐⭐ | 无 |
| 飞书妙记 | `--asr minutes` | 云端 | 免费额度 | ⭐⭐⭐⭐ | 无 |

**默认模式**：whisper base（141MB），下得快、简体、错字少、时间戳细
**增强模式**：sensevoice（用户手动开启），标点好、流畅度高，但模型大

## Agent CLI 接口（给别的 Agent 调用）

```bash
# 转写
python3 cli.py transcribe video.mp4 --asr sensevoice --json

# 九宫格故事板
python3 cli.py storyboard video.mp4 --json

# 完整管线
python3 cli.py digest video.mp4 --category 课程 --json

# 批量
python3 cli.py batch ./input/ --category 课程 --json

# 蒸馏整个文件夹（第三模式）
python3 cli.py distill ./某门课/ --category 课程 --json

# 列出资产
python3 cli.py list --json
```

所有命令加 `--json`，结果输出到 stdout，日志走 stderr，可直接被 Agent 解析。

## 输出资产结构

```
output/
  <分类>/
    <视频名>/
      <视频名>.md          # 笔记
      <视频名>.json        # 结构化数据
      transcript.json      # 转写 segments
      storyboard_p01.jpg   # 九宫格故事板
      storyboard_index.json
```

---

## 配置说明

完整配置项见 `.env.example`。核心几项：

| 变量 | 说明 | 必填 |
|------|------|------|
| `ARK_API_KEY` | 火山方舟 API Key | 豆包模式需要 |
| `ARK_VIDEO_ENDPOINT` | 豆包视频模型 Endpoint ID | 豆包模式需要 |
| `SILICONFLOW_API_KEY` | 硅基流动 API Key | 关键帧模式需要 |
| `DISTILL_LLM_BASE` / `_KEY` / `_MODEL` | 蒸馏模式用的 LLM（任意 OpenAI 兼容端点，留空自动回落硅基流动/火山方舟） | 蒸馏模式可选 |
| `WHISPER_CLI` | whisper.cpp 可执行文件路径 | 本地模式需要 |
| `OBSIDIAN_VAULT` | Obsidian Vault 路径 | Obsidian 导出需要 |

所有配置也可以在 GUI「设置」页面修改，优先级更高。

---

## 项目结构

```
video-to-text/
├── gui.py              # NiceGUI 图形界面
├── video2text.py       # 核心逻辑 + CLI
├── cli.py              # Agent CLI（含 distill 第三模式）
├── config.py           # 统一配置管理
├── v2t/
│   ├── asr.py          # 转写引擎分发
│   ├── storyboard.py   # 九宫格故事板
│   ├── assets.py       # 资产目录
│   ├── ffmpeg.py       # ffmpeg/ffprobe 定位与探测
│   ├── distill.py      # 蒸馏管线（八阶段）
│   └── distill_prompts.py  # 蒸馏用的固定提示词与 schema
├── docs/
│   └── distill-method.md   # 蒸馏方法规范（改了方法就改这里）
├── requirements.txt    # Python 依赖
├── .env.example        # 配置模板
├── cache/              # 处理缓存（自动创建）
└── output/             # 输出目录（自动创建）
```

---

## 路线图

- [x] v0.1 — 音频转写 + CLI
- [x] v0.2 — 三种引擎 + 深度拆解
- [x] v0.3 — NiceGUI 界面 + 批量队列
- [x] v0.4 — 历史记录 + Obsidian 导出 + 缓存
- [x] v0.5 — 蒸馏模式（去重 / 合并 / 方法论 / 产品逆向）
- [ ] v0.6 — 说话人分离（diarization）
- [ ] v0.7 — 打包发布（macOS .app / Windows .exe）
- [ ] v0.8 — 插件系统（自定义输出模板）
- [ ] v1.0 — 稳定版 + 文档站

---

## 贡献

欢迎提 Issue 和 PR。

有 Bug 请附：
1. 操作系统和 Python 版本
2. 报错信息和复现步骤
3. 视频格式（如果是特定文件出问题）

---

## License

MIT
