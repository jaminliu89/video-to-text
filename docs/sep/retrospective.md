# SEP v1.0 试点复盘 — video-to-text

记录时间：2026-11-02 16:55（Asia/Shanghai）

## 范围

Prism 合同 + 试点仓 `jaminliu89/video-to-text` 步骤 #04–#09（#11 SkillHub 仓不可见，#12 推广待定）。

## 结果摘要

| 指标 | 观察 |
|---|---|
| 保护规则 | `main` 必需 CI `check`，`enforce_admins=true` |
| 关键 smoke | 2 路径（asr + distill），CI 每 PR 执行 |
| 小功能 | `cli.py smoke`（#08） |
| 回退 | revert PR 删除演练标记，无强推 |
| 打包 | CI dist/dmg + 一次 workflow_dispatch Release（`v0.6.0-sep-evidence`，证据标签） |
| 误报 | 未发现 smoke 假绿；Linux 不声称 MLX 可用 |
| 漏检 | GUI、storyboard 无专用单测；用户侧 DMG 安装未测 |
| 维护成本 | 文档 + 1 个 smoke 脚本 + PR 模板；Prism 侧结构门不跑产品测试 |

## 第二产品最小复制清单

1. `docs/sep/baseline.md` + 固定 baseline SHA  
2. `docs/feature-registry.yaml`  
3. `scripts/sep_smoke.py`（或等价）≥2 关键路径  
4. `.github/pull_request_template.md` + branch protection 绑定真实 job 名  
5. `docs/sep/step-09.md` 级别的 smoke / 打包 / 回退记录  
6. Prism `sep_evidence_gate.py check` 核对 PR JSON（可选）

## 推广决策

**建议**：在第二个产品仓重复 #04–#09 后再改 SkillHub 路由（#11 需仓库可见）。  
**不宣称**：SEP 已集团全面上线；Vibeguard 未接入。
