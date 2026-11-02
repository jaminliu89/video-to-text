## 变更摘要

<!-- 一句话说明动机与范围 -->

## SEP 证据（v1.0）

```yaml
sep_version: "1.0"
change_id: "PR-"
feature_ids: []
base_sha: ""
head_sha: ""
affected_modules: []
affected_contracts: []
tests:
  - command: "python scripts/sep_smoke.py"
    result: "PASS|FAIL|BLOCKED|NOT_RUN"
    evidence: ""
  - command: "python tests/test_asr_units.py"
    result: "PASS|FAIL|BLOCKED|NOT_RUN"
    evidence: ""
  - command: "python tests/test_distill_units.py"
    result: "PASS|FAIL|BLOCKED|NOT_RUN"
    evidence: ""
risk: "low|medium|high|unknown"
migration_plan: ""
rollback_plan: "revert PR on protected main"
open_gaps: []
release_authorized: false
```

## 影响分析

- 调用方 / 公共 CLI：
- 旧功能回归：是否跑过 `scripts/sep_smoke.py`：

## 检查清单

- [ ] 未提交 secrets / `.env` / 私有媒体
- [ ] CI `check`（含 SEP smoke）在最新 head 上为绿
- [ ] 未把未运行测试写成 PASS
