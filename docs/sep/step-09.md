# SEP #09 — 合并后 smoke、打包与恢复

记录时间：2026-11-02 16:15（Asia/Shanghai）  
产品：`jaminliu89/video-to-text`  
版本文件：`0.6.0`  
合并 SHA（#08 已在 main）：`96262bfb7914f336cda986febece1ae76e93e3bb`

## 状态

| 项 | 结果 |
|---|---|
| main 上 CI `check` | PASS — https://github.com/jaminliu89/video-to-text/actions/runs/41410680471/job/125162776920 |
| main 上 CI `macos-mlx` | PASS — 同 run `125162776522` |
| main 上 CI `dist`（源码包 job） | PASS — 同 run `125163108362` |
| main 上 CI `dmg`（macOS 安装包 job） | PASS — 同 run `125163108248` |
| 本机 smoke（该 SHA 工作树） | PASS — `python3 cli.py smoke --json` exit 0；`scripts/sep_smoke.py` exit 0 |
| 本机旧功能回归 | PASS — asr 52/0，distill 50/0 |
| GitHub Release（`release.yml` workflow_dispatch） | **PASS**（证据用，非产品发版授权）— [run 41416230636](https://github.com/jaminliu89/video-to-text/actions/runs/41416230636)；tag [`v0.6.0-sep-evidence`](https://github.com/jaminliu89/video-to-text/releases/tag/v0.6.0-sep-evidence) @ main `ee5df12` |
| 用户机器 DMG 安装 / 公证 smoke | **NOT_RUN**。未在实体 macOS 上双击安装验证；`release_authorized: false` |
| 数据库 / 对象存储副作用 | **NOT_APPLICABLE**。#08 只改 CLI 与文档，无迁移 |

`dist` / `dmg` job 成功只证明该 SHA 的打包流水线退出码为 0，不等于已发布、已签名或已在用户机器安装。

## 本机命令（SHA `96262bf`）

```bash
python3 cli.py smoke --json          # exit 0, status PASS
python3 scripts/sep_smoke.py         # exit 0, paths=2
python3 tests/test_asr_units.py      # exit 0, 52 pass
python3 tests/test_distill_units.py  # exit 0, 50 pass
```

环境：Ubuntu 24.04，Python 3.12.3，ffmpeg 与 `requirements.txt` 已安装。

## 代码回退演练

计划（共享 main，禁止强推）：

1. 本文件随 PR 进入 main。
2. 单独提交一次性标记文件 `docs/sep/DRILL_MARKER.txt`。
3. 用新 PR `git revert <marker-commit>` 删掉标记，保留本文件。
4. 回读 main：标记不存在，本文件仍在，`cli.py smoke` 仍为 0。

演练记录（2026-11-02 16:20 Asia/Shanghai）：

| 步骤 | SHA / PR |
|---|---|
| 证据 + 标记进入 main | [PR #12](https://github.com/jaminliu89/video-to-text/pull/12) merge `cca45e71d761c5c962c21267bbf1b5d4eeee44b5` |
| 标记提交 | `e585f5f736f6788b47032e3ea9a5615dfdab9944`（`docs/sep/DRILL_MARKER.txt`） |
| 回退提交 | `git revert e585f5f`（非 `-m`，该提交不是 merge commit） |

回退 PR 合并后：`docs/sep/DRILL_MARKER.txt` 必须不在 main；本文件保留；`python3 cli.py smoke --json` 退出码 0。没有数据库需要恢复。

## 回滚

产品行为回退：对引入问题的 merge commit 开 revert PR（merge commit 用 `git revert -m 1`）。  
外部副作用：本次无。已发出的 DMG 不因 Git revert 从用户磁盘消失。
