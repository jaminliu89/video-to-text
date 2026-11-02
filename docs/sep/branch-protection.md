# SEP #07 — PR 模板与分支保护

| 项 | 值 |
|---|---|
| PR 模板 | `.github/pull_request_template.md` |
| 目标分支 | `main` |
| 计划必需检查 | `check`（GitHub Actions job 名，含 `scripts/sep_smoke.py`） |

## 启用步骤（仓库 owner）

Classic branch protection（本仓 API 当前返回未保护）：

```bash
gh api -X PUT repos/jaminliu89/video-to-text/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["check"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
```

启用后必须再读：

```bash
gh api repos/jaminliu89/video-to-text/branches/main/protection
```

若 API 拒绝或 Ruleset 未出现，标 **BLOCKED**，不得绕过直推 `main`。

## 实读结果（2026-11-02 15:56 Asia/Shanghai）

`PUT` + `GET` 均成功：

| 字段 | 值 |
|---|---|
| `required_status_checks.contexts` | `["check"]` |
| `required_status_checks.strict` | `true` |
| `enforce_admins` | `true` |
| `allow_force_pushes` | `false` |
| `allow_deletions` | `false` |
| `required_conversation_resolution` | `true` |
| `required_approving_review_count` | `0` |

Rulesets API 仍可能为空；本仓使用 **classic branch protection**，与 Prism 治理合同一致——以实读保护配置为准，不以文档自称代替。
