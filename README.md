# VideoToText — 本地优先的视频知识萃取器

> 把课程、讲座、纪录片视频转成可检索、可复用的结构化笔记。
> 支持三种引擎、两种模式，GUI + CLI 双模式。

---

## 这是什么

你买了一堆课程、存了一堆讲座视频，从来没回头看过？

VideoToText 把视频转成**结构化文本**——不只是逐字稿，还有章节摘要、金句、行动项。
存到 Obsidian 里，以后想找什么直接搜，不用再拖进度条。

## 核心亮点

- **本地优先**：所有数据存在本地，API Key 也是你自己的，不上传任何数据到第三方服务器
- **三种引擎，按需切换**
  - 豆包视频理解 — 质量最高，能理解动态画面和人物关系
  - 关键帧 + VLM — 便宜，静态画面理解，适合 PPT 类视频
  - 完全本地 — 不花钱，whisper.cpp 本地跑
- **批量处理**：拖一整个文件夹进去，自动排队，处理完自动导出
- **GUI + CLI 双模式**：日常用图形界面，自动化用命令行
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

## 引擎对比

| 引擎 | 质量 | 速度 | 成本（1小时视频） | 能否看懂画面 |
|------|------|------|------------------|-------------|
| 豆包视频理解 | ⭐⭐⭐⭐⭐ | 中 | ¥2-5 | ✅ 动态画面 |
| 关键帧 + VLM | ⭐⭐⭐ | 快 | ¥0.5-2 | ⚠️ 静态画面 |
| 本地 Whisper | ⭐⭐ | 慢（看机器） | 免费 | ❌ 只有声音 |

**推荐**：
- PPT/网课类 → 关键帧模式，便宜够用
- 纪录片/故事类 → 豆包视频理解，能看懂画面
- 敏感内容 / 不想花钱 → 本地模式

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
