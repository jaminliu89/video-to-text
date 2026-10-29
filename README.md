# VideoToText — 本地优先的视频知识萃取器

> 把课程、讲座、纪录片视频转成可检索、可复用的结构化笔记。
> 支持三种引擎、两种模式，GUI + CLI 双模式。

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
- **分类资产目录**：每个视频一个文件夹，笔记/转写/故事板分类存放
- **Agent CLI 接口**：别的 Agent（Codex/Claude Code/豆包）可通过 `cli.py --json` 调用
- **Obsidian 原生导出**：直接写入你的 Vault，跟笔记体系无缝衔接
- **缓存机制**：同一个视频不重复付费，结果本地缓存

---

## 两种模式

| 模式 | 输出 | 适用场景 |
|------|------|---------|
| **逐字稿** | SRT / TXT / Markdown 带时间戳 | 字幕、速记、全文检索 |
| **深度拆解** | 摘要 + 章节 + 金句 + 行动项 + 原文引用 | 课程笔记、知识内化、内容创作素材 |

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
| `WHISPER_CLI` | whisper.cpp 可执行文件路径 | 本地模式需要 |
| `OBSIDIAN_VAULT` | Obsidian Vault 路径 | Obsidian 导出需要 |

所有配置也可以在 GUI「设置」页面修改，优先级更高。

---

## 项目结构

```
video-to-text/
├── gui.py              # NiceGUI 图形界面
├── video2text.py       # 核心逻辑 + CLI
├── config.py           # 统一配置管理
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
- [ ] v0.5 — 说话人分离（diarization）
- [ ] v0.6 — 打包发布（macOS .app / Windows .exe）
- [ ] v0.7 — 插件系统（自定义输出模板）
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
