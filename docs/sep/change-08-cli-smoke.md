# SEP #08 — 小功能：CLI `smoke` 子命令

| 项 | 值 |
|---|---|
| change_id | PR（合并后填写） |
| feature_ids | `cli-agent`, `asr-transcribe`, `distill-pipeline` |
| 需求 | Agent / CI 可通过 `python cli.py smoke` 跑 SEP #06 关键路径，可选 `--json` |
| 验收 | 退出码与 `scripts/sep_smoke.py` 一致；`--json` 含 `status`/`exit_code`；旧 smoke 与 asr/distill 单测仍 PASS |

## 影响分析

| 模块 | 影响 |
|---|---|
| `cli.py` | 新增 `cmd_smoke` + `smoke` subparser |
| `scripts/sep_smoke.py` | 被动态 import，行为不变 |
| `tests/*` | 无强制改动；回归跑既有单测 + smoke |
| GUI / 打包 | 无 |

风险：**low**。回滚：revert PR。`release_authorized: false`。
