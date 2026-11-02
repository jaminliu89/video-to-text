# SEP v1.0 试点 Baseline — video-to-text

状态：**#04 PASS 候选**（待 PR CI 与本文件合并 SHA 锁定）  
记录时间：2026-11-02 15:35（Asia/Shanghai）

## 选定理由

| 项 | 说明 |
|---|---|
| 仓库 | https://github.com/jaminliu89/video-to-text |
| Owner | `jaminliu89` |
| 默认分支 | `main` |
| Baseline commit | `d1bf5a7c908d1bd8b0dfeada6d24ded6c861989e` |
| 产品版本 | `0.6.0`（`VERSION`） |
| 边界 | 独立产品仓；Prism 仅编排与证据汇总，不在本仓外复制实现 |

本地优先的视频知识萃取器，具备 GUI/CLI、可离线单测、已有 GitHub Actions（`check` / `macos-mlx` / `dmg` / `dist`），适合 SEP 试点 #04–#09。

## 关键用户路径

| path_id | 入口 | 典型命令 / 模块 | 说明 |
|---|---|---|---|
| transcript | CLI / `video2text.py` | `python video2text.py <video>` | 逐字稿模式 |
| deep | CLI | `python video2text.py --mode video --deep <video>` | 深度拆解 |
| distill | CLI / `cli.py` | `python cli.py distill <folder>` | 文件夹蒸馏八阶段 |
| gui | GUI | `python gui.py` | NiceGUI 本地 Web UI |
| agent | Agent CLI | `python cli.py transcribe|storyboard|digest|batch|engines --json` | 外部 Agent 集成 |
| export | 导出 | `--obsidian` 等 flags | Obsidian Vault 写入 |

## 可复现运行（Linux，对齐 CI `check` job）

前置：Python 3.11+（CI 用 3.11）、`ffmpeg`、仓库根目录。

```bash
git clone https://github.com/jaminliu89/video-to-text.git
cd video-to-text
git checkout d1bf5a7c908d1bd8b0dfeada6d24ded6c861989e
python -m pip install --upgrade pip
pip install -r requirements.txt
sudo apt-get install -y ffmpeg   # Debian/Ubuntu

python -m py_compile video2text.py config.py cli.py gui.py v2t/*.py
python tests/test_distill_units.py
python tests/test_asr_units.py
python cli.py engines --json
python cli.py --help
```

## 本环境实测（2026-11-02）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `python tests/test_distill_units.py` | 0 | 通过 50 / 失败 0 |
| `python tests/test_asr_units.py` | 0 | 通过 52 项，失败 0 项 |
| `python -m py_compile …` | 0 | 与 CI 同组文件 |

环境：Ubuntu 24.04，Python 3.12.3，ffmpeg 已安装。未跑 GUI、未跑 macOS MLX job、未跑 DMG 打包。

## main 上 CI 快照（GitHub）

commit `d1bf5a7` 上最近检查均为 **success**：`check`、`macos-mlx`、`dmg`、`dist`（读取时间 2026-11-02 15:33 Asia/Shanghai）。

## 已知缺口 / 风险

| 项 | 状态 |
|---|---|
| `main` branch protection | **未配置**（API 404 Branch not protected）；#07 需补 PR 模板 + Ruleset |
| 云端 ASR / 豆包 / 飞书 | 需 API Key；本 baseline 未验证联网转写 |
| MLX Whisper | 仅 macOS-14 job 覆盖；Linux 基线不声称 MLX 可用 |
| E2E GUI / DMG | CI 有 job；本机 Linux 未跑窗口/DMG 断言 |
| `AGENTS.md` | 仓库尚无；#05/#07 可按 SEP 合同补 |

## 下一步（SEP 路线图）

- **#05**：`docs/feature-registry.yaml` + 契约索引，对照代码抽查。
- **#06**：固化 ≥2 条关键旧功能回归（在现有单测上扩展或标记 smoke）。
- **#07**：`.github/pull_request_template.md` + branch protection / 必需 `check`。
